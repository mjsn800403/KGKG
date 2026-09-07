"""Answer-level evaluation through the REAL production chat pipeline.

    python manage.py run_answer_eval --budget 600 --dry-run
    python manage.py run_answer_eval --budget 600

COSTS MONEY: every in-scope/out-of-scope question is one Metis call, and each
no-RAG baseline question is another. `--budget` is a hard ceiling on total
calls; the run stops cleanly when it is reached. `--dry-run` prints the plan
and makes zero calls.

A short-lived auth token is minted for an existing AI-eligible account and
revoked at the end. No account is created and no password is touched.
"""
import json
import os
import random
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand

from api.rag import config, store
from api.models import PortalUser, AuthToken
from api.access import user_ai_eligible
from api.evalsuite import goldset, answer_eval, stats


def _env_from(path, keys):
    out = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() in keys:
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


class Command(BaseCommand):
    help = "Hallucination / unsupported-answer / no-RAG-baseline measurement."

    def add_arguments(self, p):
        p.add_argument("--budget", type=int, default=600,
                       help="hard ceiling on total paid LLM calls")
        p.add_argument("--n-inscope", type=int, default=200)
        p.add_argument("--n-oos", type=int, default=52)
        p.add_argument("--n-wrong", type=int, default=60)
        p.add_argument("--n-norag", type=int, default=150)
        p.add_argument("--seed", type=int, default=1373)
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--sleep", type=float, default=0.4,
                       help="pause between paid calls (be polite to the API)")
        p.add_argument("--out", default="")

    def handle(self, *a, **o):
        gold_dir = Path(config.INDEX_DB).parent / "eval" / "gold"
        rng = random.Random(o["seed"])

        fa = goldset.read_jsonl(gold_dir / "known_item_fa.jsonl")
        real = goldset.read_jsonl(gold_dir / "real_user.jsonl")
        oos = goldset.read_jsonl(gold_dir / "out_of_scope.jsonl")
        wrong = goldset.read_jsonl(gold_dir / "wrong_vehicle.jsonl")

        # In-scope mix: mostly synthetic known-item questions (we know the right
        # page) plus every real logged user question we have (realistic phrasing).
        rng.shuffle(fa)
        real_ok = [r for r in real if r.get("car")]
        inscope = ([{"query": r["query"], "car": r["car"], "brand": "Toyota",
                     "kind": "known_item_fa", "expected_blob_ids": r["expected_blob_ids"]}
                    for r in fa[:max(0, o["n_inscope"] - len(real_ok))]] +
                   [{"query": r["query"], "car": r["car"],
                     "brand": r.get("brand") or "Toyota", "kind": "real_user"}
                    for r in real_ok])
        rng.shuffle(inscope)
        inscope = inscope[:o["n_inscope"]]
        oos = oos[:o["n_oos"]]
        wrong = wrong[:o["n_wrong"]]
        # PAIRED baseline: the no-RAG condition gets the SAME questions as the
        # RAG condition, so the two columns are directly comparable rather than
        # being two different samples.
        norag_pool = inscope[:o["n_norag"]]

        plan = {"in_scope": len(inscope), "out_of_scope": len(oos),
                "wrong_vehicle": len(wrong), "no_rag_baseline": len(norag_pool)}
        plan["total_paid_calls"] = sum(plan.values())
        self.stdout.write(json.dumps(plan, indent=2))
        if plan["total_paid_calls"] > o["budget"]:
            self.stdout.write(self.style.WARNING(
                f"plan exceeds budget {o['budget']}; will stop at the ceiling"))
        if o["dry_run"]:
            self.stdout.write(self.style.SUCCESS("dry run — no calls made"))
            return

        env = _env_from("/opt/KGKG/kg_frontend/.env.production",
                        {"METIS_API_KEY", "METIS_BOT_ID"})
        api_key, bot_id = env.get("METIS_API_KEY"), env.get("METIS_BOT_ID")
        if not api_key or not bot_id:
            self.stderr.write("Metis not configured; aborting.")
            return

        user = next((u for u in PortalUser.objects.select_related("company").all()
                     if user_ai_eligible(u) and u.active), None)
        if user is None:
            self.stderr.write("No AI-eligible account to run as; aborting.")
            return
        tok = AuthToken.issue(user)
        self.stdout.write(f"minted eval token for '{user.username}' (revoked at end)")
        index = store.get_index_ro()      # to recover the real grounding text

        spent = [0]
        budget = o["budget"]

        def can_spend():
            return spent[0] < budget

        results = {"ts": datetime.now().strftime("%Y%m%d_%H%M%S"),
                   "plan": plan, "budget": budget, "ran_as": user.username}
        rows = defaultdict(list)
        try:
            for label, items in (("in_scope", inscope), ("out_of_scope", oos),
                                 ("wrong_vehicle", wrong)):
                self.stdout.write(self.style.WARNING(f"\n== {label} ({len(items)})"))
                for i, q in enumerate(items, 1):
                    if not can_spend():
                        self.stdout.write("  budget reached; stopping")
                        break
                    t0 = time.monotonic()
                    try:
                        resp = answer_eval.ask_production(
                            q["query"], q.get("car"), q.get("brand") or "Toyota",
                            tok.key)
                        spent[0] += 1
                    except Exception as ex:
                        rows[label].append({"query": q["query"],
                                            "error": str(ex)[:200]})
                        continue
                    sc = answer_eval.score_answer(resp, index=index,
                                                  question=q["query"])
                    sc.update({"query": q["query"], "car": q.get("car"),
                               "kind": q.get("kind") or q.get("category"),
                               "latency_ms": round((time.monotonic() - t0) * 1000)})
                    rows[label].append(sc)
                    if i % 20 == 0:
                        self.stdout.write(f"    {label}: {i}/{len(items)} "
                                          f"(spent {spent[0]})")
                    time.sleep(o["sleep"])

            self.stdout.write(self.style.WARNING(
                f"\n== no_rag_baseline ({len(norag_pool)})"))
            for i, q in enumerate(norag_pool, 1):
                if not can_spend():
                    self.stdout.write("  budget reached; stopping")
                    break
                try:
                    txt = answer_eval.ask_no_rag(q["query"], api_key, bot_id)
                    spent[0] += 1
                except Exception as ex:
                    rows["no_rag"].append({"query": q["query"], "error": str(ex)[:200]})
                    continue
                rows["no_rag"].append({
                    "query": q["query"], "reply": txt,
                    "reply_chars": len(txt),
                    "n_numbers": len(answer_eval.numbers_in(txt)),
                    "n_buttons": len(answer_eval.BUTTON_RE.findall(txt)),
                    "refused": _looks_refusal(txt),
                })
                if i % 20 == 0:
                    self.stdout.write(f"    no_rag: {i}/{len(norag_pool)} "
                                      f"(spent {spent[0]})")
                time.sleep(o["sleep"])
        finally:
            AuthToken.objects.filter(pk=tok.pk).delete()
            self.stdout.write("eval token revoked")

        results["spent_calls"] = spent[0]
        results["raw"] = {k: v for k, v in rows.items()}
        results["summary"] = _summarise(rows)
        out_dir = Path(o["out"]) if o["out"] else (
            Path(config.INDEX_DB).parent / "eval" / "runs" /
            f"answer_{results['ts']}")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "answer_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(json.dumps(results["summary"], ensure_ascii=False, indent=2))
        self.stdout.write(self.style.SUCCESS(f"-> {out_dir/'answer_results.json'}"))


_REFUSAL_MARKERS = (
    "اطلاعاتی", "یافت نشد", "نمی‌توانم", "نمیتوانم", "در دسترس نیست",
    "مرتبط نیست", "خارج از", "پیدا نکردم", "موجود نیست", "متأسفانه",
)


def _looks_refusal(text):
    t = (text or "").strip()
    return any(m in t for m in _REFUSAL_MARKERS)


def _summarise(rows):
    def agg(label):
        rs = [r for r in rows.get(label, []) if "error" not in r]
        if not rs:
            return {"n": 0}
        n = len(rs)
        llm = [r for r in rs if r.get("llm_used")]
        halluc = sum(1 for r in rs if r.get("stripped_links", 0) > 0)
        badlink = sum(1 for r in rs if r.get("links_not_in_sources", 0) > 0)
        with_nums = [r for r in rs if r.get("n_numbers", 0) > 0]
        num_bad = sum(1 for r in with_nums if r.get("n_unsupported_numbers", 0) > 0)
        tot_nums = sum(r.get("n_numbers", 0) for r in rs)
        tot_unsup = sum(r.get("n_unsupported_numbers", 0) for r in rs)
        grounded = sum(1 for r in rs if r.get("grounded"))
        return {
            "n": n,
            "llm_answers": len(llm),
            "fallback_no_llm_rate": stats.wilson_ci(n - len(llm), n),
            "grounded_rate": stats.wilson_ci(grounded, n),
            "link_hallucination_rate": stats.wilson_ci(halluc, n),
            "links_surviving_gate_not_in_sources": badlink,
            "answers_with_numbers": len(with_nums),
            "answers_with_unsupported_number": stats.wilson_ci(
                num_bad, len(with_nums)) if with_nums else {"n": 0},
            "numeric_claims_total": tot_nums,
            "numeric_claims_unsupported": tot_unsup,
            "numeric_unsupported_share": (round(tot_unsup / tot_nums, 4)
                                          if tot_nums else None),
            "median_latency_ms": sorted(r.get("latency_ms", 0)
                                        for r in rs)[n // 2],
        }

    out = {k: agg(k) for k in ("in_scope", "out_of_scope", "wrong_vehicle")}
    nr = [r for r in rows.get("no_rag", []) if "error" not in r]
    if nr:
        out["no_rag"] = {
            "n": len(nr),
            "refusal_rate": stats.wilson_ci(sum(1 for r in nr if r["refused"]),
                                            len(nr)),
            "answers_with_numeric_claims": sum(1 for r in nr if r["n_numbers"] > 0),
            "numeric_claims_total": sum(r["n_numbers"] for r in nr),
            "answers_with_link_buttons": sum(1 for r in nr if r["n_buttons"] > 0),
            "median_reply_chars": sorted(r["reply_chars"] for r in nr)[len(nr) // 2],
        }
    return out
