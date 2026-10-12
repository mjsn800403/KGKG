"""Run the offline evaluation suite: every system, every gold set, real numbers.

    python manage.py run_evalsuite                     # everything
    python manage.py run_evalsuite --sets known_item_fa --systems hybrid
    python manage.py run_evalsuite --limit 25          # quick smoke run

Makes ZERO external/LLM calls and never writes to product data. Results land in
Database_warehouse/_rag/eval/runs/<timestamp>/.
"""
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand

from api.rag import config, store, embed, glossary, evalmetrics, diag
from api.evalsuite import goldset, baselines, stats

KS = (1, 3, 5, 10)
RETRIEVAL_SETS = ("known_item_en", "known_item_fa")


def _is_retrieval_set(name):
    """Known-item sets, including per-vehicle subsets like
    known_item_en_gr86 and technician-authored known_item_fa_human.
    Without this an unrecognised --sets name matches NO branch in handle()
    and is silently dropped from results.json instead of erroring."""
    return name in RETRIEVAL_SETS or name.startswith(("known_item_en", "known_item_fa"))


def _embed_for(query, use_glossary):
    q = query
    if use_glossary:
        eng, _ = glossary.expand(query)
        if eng:
            q = f"{query} {eng}"
    return embed.encode([q], is_query=True)[0]


class Command(BaseCommand):
    help = "Offline evaluation: retrieval metrics, refusal, diagnosis, baselines."

    def add_arguments(self, p):
        p.add_argument("--sets", default="")
        p.add_argument("--systems", default="")
        p.add_argument("--limit", type=int, default=0)
        p.add_argument("--out", default="")

    # ------------------------------------------------------------ retrieval
    def _run_retrieval(self, gold_dir, name, systems, limit):
        rows = goldset.read_jsonl(gold_dir / f"{name}.jsonl")
        if limit:
            rows = rows[:limit]
        index = store.get_index_ro()
        per_sys = {s: defaultdict(list) for s in systems}
        lat = {s: [] for s in systems}
        details = []

        for i, row in enumerate(rows, 1):
            rel = set(row.get("expected_blob_ids") or [])
            if not rel:
                continue
            # embed once per glossary-mode and share across systems that need it
            qvec = {True: None, False: None}
            for s in systems:
                spec = baselines.SYSTEMS[s]
                if spec["dense"] and qvec[spec["glossary"]] is None:
                    qvec[spec["glossary"]] = _embed_for(row["query"], spec["glossary"])
            rec = {"query": row["query"], "car": row["car"],
                   "component": row.get("component"), "action": row.get("action"),
                   "n_relevant": len(rel), "systems": {}}
            for s in systems:
                spec = baselines.SYSTEMS[s]
                t0 = time.monotonic()
                try:
                    out = spec["fn"](index, row["query"], row["car"],
                                     k=baselines.TOPK,
                                     qvec=qvec[spec["glossary"]] if spec["dense"] else None,
                                     use_glossary=spec["glossary"])
                except Exception as ex:      # never let one query kill the run
                    rec["systems"][s] = {"error": str(ex)[:200]}
                    continue
                dt = (time.monotonic() - t0) * 1000.0
                lat[s].append(dt)
                if spec["full"]:
                    ranked = [h["blob_id"] for h in out["hits"]]
                    grounded = bool(out.get("grounded"))
                    band = (out.get("confidence_band") or {}).get("band")
                    top_url = out["hits"][0]["app_url"] if out["hits"] else None
                    cited_car = out["hits"][0]["car_stem"] if out["hits"] else None
                else:
                    ranked, grounded, band, top_url, cited_car = out, None, None, None, None
                m = {}
                for k in KS:
                    m[f"P@{k}"] = evalmetrics.precision_at_k(ranked, rel, k)
                    m[f"R@{k}"] = evalmetrics.recall_at_k(ranked, rel, k)
                    m[f"nDCG@{k}"] = evalmetrics.ndcg_at_k(ranked, rel, k)
                    m[f"Hit@{k}"] = evalmetrics.hit_at_k(ranked, rel, k)
                m["MRR"] = evalmetrics.mrr(ranked, rel)
                for key, v in m.items():
                    per_sys[s][key].append(v)
                if grounded is not None:
                    per_sys[s]["grounded"].append(1 if grounded else 0)
                rec["systems"][s] = {**{k: round(v, 4) for k, v in m.items()},
                                     "latency_ms": round(dt),
                                     "grounded": grounded, "band": band,
                                     "top_app_url": top_url, "cited_car": cited_car,
                                     "top5": ranked[:5]}
            details.append(rec)
            if i % 25 == 0:
                self.stdout.write(f"    {name}: {i}/{len(rows)}")

        agg = {}
        for s in systems:
            agg[s] = {k: stats.bootstrap_ci(v) for k, v in per_sys[s].items()}
            agg[s]["latency_ms"] = {
                "p50": evalmetrics.percentile(lat[s], 50),
                "p90": evalmetrics.percentile(lat[s], 90),
                "p99": evalmetrics.percentile(lat[s], 99),
            }
        # paired significance vs the production pipeline
        sig = {}
        if "hybrid" in systems:
            for s in systems:
                if s == "hybrid":
                    continue
                sig[f"hybrid_vs_{s}"] = {
                    m: stats.paired_bootstrap(per_sys["hybrid"][m], per_sys[s][m])
                    for m in ("nDCG@5", "Hit@1", "MRR", "R@10")
                    if per_sys["hybrid"].get(m) and per_sys[s].get(m)
                }
        return {"n": len(details), "aggregates": agg, "significance": sig,
                "per_query": details}

    # ------------------------------------------------------------- refusal
    def _run_refusal(self, gold_dir, name, limit):
        rows = goldset.read_jsonl(gold_dir / f"{name}.jsonl")
        if limit:
            rows = rows[:limit]
        index = store.get_index_ro()
        by_cat = defaultdict(lambda: {"n": 0, "ok": 0})
        details, lat = [], []
        # For wrong_vehicle rows the component is verifiably absent from the
        # scoped car, so citing that car is the error mode; refusing, or citing
        # the vehicle that actually has the page, are both acceptable.
        attribution = {"n": 0, "claimed_scoped_vehicle": 0,
                       "attributed_other_vehicle": 0, "refused": 0}
        for row in rows:
            t0 = time.monotonic()
            try:
                res = baselines.run_hybrid(index, row["query"], row["car"])
            except Exception as ex:
                details.append({"query": row["query"], "error": str(ex)[:200]})
                continue
            dt = (time.monotonic() - t0) * 1000.0
            lat.append(dt)
            grounded = bool(res.get("grounded"))
            band = (res.get("confidence_band") or {}).get("band")
            cat = row.get("category", "out_of_scope")
            cited_car = res["hits"][0]["car_stem"] if res.get("hits") else None
            if cat == "wrong_vehicle":
                attribution["n"] += 1
                if not grounded:
                    attribution["refused"] += 1
                elif cited_car == row["car"]:
                    attribution["claimed_scoped_vehicle"] += 1   # the error mode
                else:
                    attribution["attributed_other_vehicle"] += 1
                ok = (not grounded) or (cited_car != row["car"])
            else:
                ok = (not grounded)
            by_cat[cat]["n"] += 1
            by_cat[cat]["ok"] += 1 if ok else 0
            details.append({"query": row["query"], "category": cat,
                            "car": row["car"], "grounded": grounded, "band": band,
                            "cited_car": cited_car, "refused_ok": ok,
                            "top_similarity": res.get("top_similarity"),
                            "latency_ms": round(dt)})
        out = {"by_category": {c: stats.wilson_ci(v["ok"], v["n"])
                               for c, v in by_cat.items()},
               "overall": stats.wilson_ci(sum(v["ok"] for v in by_cat.values()),
                                          sum(v["n"] for v in by_cat.values())),
               "latency_ms": {"p50": evalmetrics.percentile(lat, 50),
                              "p90": evalmetrics.percentile(lat, 90)},
               "per_query": details}
        if attribution["n"]:
            out["vehicle_attribution"] = attribution
        return out

    # ----------------------------------------------------------- diagnosis
    def _run_diagnosis(self, gold_dir, limit):
        rows = goldset.read_jsonl(gold_dir / "diagnosis.jsonl")
        if limit:
            rows = rows[:limit]
        by_cond = defaultdict(lambda: defaultdict(list))
        details, lat = [], []
        for i, row in enumerate(rows, 1):
            t0 = time.monotonic()
            try:
                res = diag.diagnose(row["query"], car_stem=row["car"])
            except Exception as ex:
                details.append({"query": row["query"], "error": str(ex)[:200]})
                continue
            dt = (time.monotonic() - t0) * 1000.0
            lat.append(dt)
            cond = row["condition"]
            codes = [c.get("code") for c in (res.get("candidates") or [])]
            urls = [p.get("app_url") for p in (res.get("procedures") or [])]
            if cond in ("dtc_code", "dtc_name"):
                gold = set(row.get("expected_codes") or [])
                ranked = codes
            else:
                gold = set(row.get("expected_app_urls") or [])
                ranked = urls
            hit1 = evalmetrics.hit_at_k(ranked, gold, 1)
            hit3 = evalmetrics.hit_at_k(ranked, gold, 3)
            hit5 = evalmetrics.hit_at_k(ranked, gold, 5)
            mrr = evalmetrics.mrr(ranked, gold)
            by_cond[cond]["Hit@1"].append(hit1)
            by_cond[cond]["Hit@3"].append(hit3)
            by_cond[cond]["Hit@5"].append(hit5)
            by_cond[cond]["MRR"].append(mrr)
            # a bare trouble code must be routed to the DTC lookup path
            if cond == "dtc_code":
                by_cond[cond]["intent_ok"].append(
                    1 if res.get("intent") == "dtc" else 0)
            details.append({"query": row["query"], "condition": cond,
                            "car": row["car"], "intent": res.get("intent"),
                            "gold": sorted(gold)[:3], "ranked": ranked[:5],
                            "Hit@1": hit1, "Hit@3": hit3, "MRR": round(mrr, 4),
                            "latency_ms": round(dt)})
            if i % 25 == 0:
                self.stdout.write(f"    diagnosis: {i}/{len(rows)}")
        agg = {c: {m: stats.bootstrap_ci(v) for m, v in d.items()}
               for c, d in by_cond.items()}
        return {"n": len(details), "by_condition": agg,
                "latency_ms": {"p50": evalmetrics.percentile(lat, 50),
                               "p90": evalmetrics.percentile(lat, 90)},
                "per_query": details}

    # ---------------------------------------------------------- real users
    def _run_real_users(self, gold_dir, limit):
        """Real logged Persian queries. No relevance labels exist for these, so
        only label-free properties are reported (grounding rate, confidence
        distribution, latency). They are the sample frame for expert review."""
        rows = goldset.read_jsonl(gold_dir / "real_user.jsonl")
        if limit:
            rows = rows[:limit]
        index = store.get_index_ro()
        bands, grounded, lat, details = defaultdict(int), [], [], []
        cars = set(goldset.indexed_cars(index))
        for row in rows:
            car = row.get("car") if row.get("car") in cars else None
            if car is None:
                continue
            t0 = time.monotonic()
            try:
                # k=None -> the adaptive depth production actually serves, so
                # this latency is the real user-facing number (the retrieval
                # sets above run at k=20 to score @10, which is deeper).
                res = baselines.run_hybrid(index, row["query"], car, k=None)
            except Exception as ex:
                details.append({"query": row["query"], "error": str(ex)[:200]})
                continue
            dt = (time.monotonic() - t0) * 1000.0
            lat.append(dt)
            g = bool(res.get("grounded"))
            grounded.append(1 if g else 0)
            bands[(res.get("confidence_band") or {}).get("band")] += 1
            details.append({"query": row["query"], "car": car, "grounded": g,
                            "band": (res.get("confidence_band") or {}).get("band"),
                            "top_similarity": res.get("top_similarity"),
                            "n_hits": res.get("count"),
                            "top_app_url": res["hits"][0]["app_url"] if res.get("hits") else None,
                            "top_title": res["hits"][0]["title"] if res.get("hits") else None,
                            "latency_ms": round(dt)})
        return {"n": len(details),
                "grounded_rate": stats.wilson_ci(sum(grounded), len(grounded)),
                "confidence_bands": dict(bands),
                "latency_ms": {"p50": evalmetrics.percentile(lat, 50),
                               "p90": evalmetrics.percentile(lat, 90),
                               "p99": evalmetrics.percentile(lat, 99)},
                "per_query": details}

    # ------------------------------------------------------------- driver
    def handle(self, *a, **o):
        gold_dir = Path(config.INDEX_DB).parent / "eval" / "gold"
        if not gold_dir.exists():
            self.stderr.write("No gold sets. Run: manage.py build_goldset")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(o["out"]) if o["out"] else (
            Path(config.INDEX_DB).parent / "eval" / "runs" / ts)
        out_dir.mkdir(parents=True, exist_ok=True)

        systems = [s for s in (o["systems"].split(",") if o["systems"]
                               else list(baselines.SYSTEMS)) if s]
        want = [s for s in (o["sets"].split(",") if o["sets"] else
                            ["known_item_en", "known_item_fa", "out_of_scope",
                             "wrong_vehicle", "diagnosis", "real_user"]) if s]
        limit = o["limit"]
        results = {"ts": ts, "systems": systems, "sets": want,
                   "k_values": list(KS), "embed_model": config.EMBED_MODEL,
                   "index_db": str(config.INDEX_DB)}

        for name in want:
            self.stdout.write(self.style.WARNING(f"\n== {name}"))
            t0 = time.monotonic()
            if _is_retrieval_set(name):
                sys_for_set = systems
                if name == "known_item_en" and "hybrid_ng" in sys_for_set:
                    # The terminology layer only fires on Persian input, so on
                    # the English set hybrid_ng is identical to hybrid by
                    # construction (verified: same scores). Skipping it saves a
                    # full pipeline run per query rather than measuring a tie.
                    sys_for_set = [s for s in sys_for_set if s != "hybrid_ng"]
                    self.stdout.write("   (skipping hybrid_ng: no-op on English)")
                results[name] = self._run_retrieval(gold_dir, name, sys_for_set, limit)
            elif name in ("out_of_scope", "wrong_vehicle"):
                results[name] = self._run_refusal(gold_dir, name, limit)
            elif name == "diagnosis":
                results[name] = self._run_diagnosis(gold_dir, limit)
            elif name == "real_user":
                results[name] = self._run_real_users(gold_dir, limit)
            self.stdout.write(f"   done in {time.monotonic() - t0:.1f}s")

        (out_dir / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

        # compact console summary
        for name in want:
            r = results.get(name) or {}
            self.stdout.write(self.style.SUCCESS(f"\n### {name}  (n={r.get('n', '-')})"))
            if _is_retrieval_set(name):
                self.stdout.write(f"  {'system':<11}{'nDCG@5':>9}{'Hit@1':>9}"
                                  f"{'R@10':>9}{'MRR':>9}{'p50ms':>8}")
                for s in systems:
                    a = r["aggregates"].get(s, {})
                    def g(m):
                        v = a.get(m) or {}
                        return f"{v.get('mean'):.3f}" if v.get("mean") is not None else "  -  "
                    lat = (a.get("latency_ms") or {}).get("p50")
                    self.stdout.write(
                        f"  {s:<11}{g('nDCG@5'):>9}{g('Hit@1'):>9}{g('R@10'):>9}"
                        f"{g('MRR'):>9}{(round(lat) if lat else '-'):>8}")
            elif name in ("out_of_scope", "wrong_vehicle"):
                for c, v in (r.get("by_category") or {}).items():
                    self.stdout.write(f"  {c:<22} correct-refusal {v['rate']} "
                                      f"[{v['lo']}, {v['hi']}] n={v['n']}")
                if r.get("vehicle_attribution"):
                    self.stdout.write(f"  attribution: {r['vehicle_attribution']}")
            elif name == "diagnosis":
                for c, m in (r.get("by_condition") or {}).items():
                    self.stdout.write(
                        f"  {c:<12} Hit@1={m['Hit@1']['mean']} "
                        f"Hit@3={m['Hit@3']['mean']} MRR={m['MRR']['mean']} n={m['Hit@1']['n']}")
            elif name == "real_user":
                self.stdout.write(f"  grounded={r.get('grounded_rate')}")
                self.stdout.write(f"  bands={r.get('confidence_bands')}")
                self.stdout.write(f"  latency={r.get('latency_ms')}")
        self.stdout.write(self.style.SUCCESS(f"\n-> {out_dir / 'results.json'}"))
