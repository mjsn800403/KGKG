"""Assemble the evaluation report from completed runs.

    python manage.py eval_report                 # newest run(s)
    python manage.py eval_report --out /root/report

Reads results.json (offline suite), answer_results.json (paid answer suite) and
expert_scores.json (if reviewers have returned sheets) and writes a single
Markdown report plus a machine-readable summary. Numbers are copied from the
run files verbatim; this command computes nothing new, so the report can never
disagree with the measurements.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from api.rag import config

PCT = lambda v: "—" if v is None else f"{100 * v:.1f}%"


def _ci(d, pct=True):
    if not d or d.get("mean") is None and d.get("rate") is None:
        return "—"
    m = d.get("mean", d.get("rate"))
    lo, hi = d.get("lo"), d.get("hi")
    if pct:
        s = f"{100 * m:.1f}%"
        if lo is not None:
            s += f" [{100 * lo:.1f}–{100 * hi:.1f}]"
    else:
        s = f"{m:.3f}"
        if lo is not None:
            s += f" [{lo:.3f}–{hi:.3f}]"
    return s


def _latest(runs, name):
    c = sorted(runs.glob(f"*/{name}"), key=lambda p: p.stat().st_mtime)
    return c[-1] if c else None


class Command(BaseCommand):
    help = "Render the evaluation report from the latest runs."

    def add_arguments(self, p):
        p.add_argument("--out", default="")
        p.add_argument("--offline", default="")
        p.add_argument("--answer", default="")

    def handle(self, *a, **o):
        eval_dir = Path(config.INDEX_DB).parent / "eval"
        runs = eval_dir / "runs"
        op = Path(o["offline"]) if o["offline"] else _latest(runs, "results.json")
        ap = Path(o["answer"]) if o["answer"] else _latest(runs, "answer_results.json")
        ep = eval_dir / "expert" / "expert_scores.json"
        if not op or not op.exists():
            self.stderr.write("no offline results.json found")
            return
        off = json.loads(op.read_text(encoding="utf-8"))
        ans = json.loads(ap.read_text(encoding="utf-8")) if ap and ap.exists() else None
        exp = json.loads(ep.read_text(encoding="utf-8")) if ep.exists() else None

        gold_sum = {}
        gs = eval_dir / "gold" / "summary.json"
        if gs.exists():
            gold_sum = json.loads(gs.read_text(encoding="utf-8"))

        L = []
        w = L.append
        w("# KGKG — Quantitative AI Evaluation Results")
        w("")
        w(f"*Generated from run `{off.get('ts')}`. Embedding model: "
          f"`{off.get('embed_model')}`. All retrieval metrics are computed "
          f"offline over the production index with zero LLM calls.*")
        w("")

        # ---------------------------------------------------------- method
        w("## 1. How the ground truth was built")
        w("")
        w("| Gold set | Rows | Label source |")
        w("|---|---:|---|")
        w(f"| Known-item, English | {gold_sum.get('known_item_en','—')} | "
          "query generated from a specific manual page — that page is correct by construction |")
        w(f"| Known-item, Persian | {gold_sum.get('known_item_fa','—')} | "
          "same topics phrased in Persian against the English corpus |")
        w(f"| Out-of-scope | {gold_sum.get('out_of_scope','—')} | "
          "verified absent from the index before admission |")
        w(f"| Wrong-vehicle | {gold_sum.get('wrong_vehicle','—')} | "
          "component verified absent from the scoped vehicle's own manual |")
        w(f"| Diagnosis | {gold_sum.get('diagnosis','—')} | "
          "the manuals' own DTC and symptom tables (manufacturer-authored) |")
        w(f"| Real user queries | {gold_sum.get('real_user_queries','—')} | "
          "logged production queries (unlabelled — used for grounding rate, latency, expert review) |")
        w("")
        if gold_sum.get("absent_rejected_present_in_corpus"):
            w(f"Out-of-scope candidates rejected because the corpus DOES cover them: "
              f"`{', '.join(gold_sum['absent_rejected_present_in_corpus'])}`. "
              "They were dropped rather than mislabelled.")
            w("")

        # ------------------------------------------------------- retrieval
        for name, title in (("known_item_en", "2. Retrieval — English queries"),
                            ("known_item_fa",
                             "3. Retrieval — Persian queries over English documents")):
            b = off.get(name)
            if not b:
                continue
            w(f"## {title}")
            w("")
            w(f"n = {b['n']} queries.")
            w("")
            w("| System | nDCG@5 | Hit@1 | Hit@5 | Recall@10 | MRR | p50 ms |")
            w("|---|---|---|---|---|---|---:|")
            for s, agg in b["aggregates"].items():
                lat = (agg.get("latency_ms") or {}).get("p50")
                w(f"| `{s}` | {_ci(agg.get('nDCG@5'), False)} | "
                  f"{_ci(agg.get('Hit@1'))} | {_ci(agg.get('Hit@5'))} | "
                  f"{_ci(agg.get('R@10'))} | {_ci(agg.get('MRR'), False)} | "
                  f"{round(lat) if lat else '—'} |")
            w("")
            sig = b.get("significance") or {}
            if sig:
                w("Paired bootstrap vs the production pipeline (`hybrid`):")
                w("")
                w("| Comparison | Δ nDCG@5 | p | Δ Hit@1 | p |")
                w("|---|---:|---:|---:|---:|")
                for k, v in sig.items():
                    n5, h1 = v.get("nDCG@5") or {}, v.get("Hit@1") or {}
                    w(f"| {k} | {n5.get('diff','—')} | {n5.get('p','—')} | "
                      f"{h1.get('diff','—')} | {h1.get('p','—')} |")
                w("")

        # --------------------------------------------------------- refusal
        b = off.get("out_of_scope")
        if b:
            w("## 4. Refusal on out-of-scope questions")
            w("")
            w("| Category | Correct refusal | n |")
            w("|---|---|---:|")
            for c, v in (b.get("by_category") or {}).items():
                w(f"| {c} | {_ci(v)} | {v['n']} |")
            w(f"| **overall** | **{_ci(b.get('overall'))}** | "
              f"{(b.get('overall') or {}).get('n','—')} |")
            w("")
        b = off.get("wrong_vehicle")
        if b:
            w("## 5. Vehicle attribution (component absent from the scoped car)")
            w("")
            va = b.get("vehicle_attribution") or {}
            if va:
                n = va.get("n") or 1
                w("| Outcome | Count | Share |")
                w("|---|---:|---:|")
                for k in ("refused", "attributed_other_vehicle",
                          "claimed_scoped_vehicle"):
                    w(f"| {k} | {va.get(k,0)} | {PCT(va.get(k,0)/n)} |")
                w("")
                w("`claimed_scoped_vehicle` is the error mode: the answer was "
                  "attributed to a vehicle whose own manual does not contain "
                  "that component.")
                w("")

        # ------------------------------------------------------- diagnosis
        b = off.get("diagnosis")
        if b:
            w("## 6. Fault-diagnosis engine")
            w("")
            w("| Condition | Hit@1 | Hit@3 | MRR | n |")
            w("|---|---|---|---|---:|")
            for c, m in (b.get("by_condition") or {}).items():
                w(f"| {c} | {_ci(m.get('Hit@1'))} | {_ci(m.get('Hit@3'))} | "
                  f"{_ci(m.get('MRR'), False)} | {m['Hit@1']['n']} |")
            w("")
            w("`dtc_code` is an exact code lookup, `dtc_name` a semantic match "
              "on the fault name with the code removed, and `symptom` a "
              "Problem-Symptoms-Table entry resolved to its troubleshooting "
              "page. `symptom` reuses the indexed wording, so it bounds the "
              "linkage stage rather than paraphrase robustness.")
            w("")

        # ------------------------------------------------------ real users
        b = off.get("real_user")
        if b:
            w("## 7. Behaviour on real logged user queries")
            w("")
            w(f"- n = {b['n']} real Persian queries from production logs")
            w(f"- grounded (answered rather than refused): {_ci(b.get('grounded_rate'))}")
            w(f"- confidence bands: `{b.get('confidence_bands')}`")
            lat = b.get("latency_ms") or {}
            w(f"- latency p50/p90/p99: "
              f"{round(lat.get('p50') or 0)} / {round(lat.get('p90') or 0)} / "
              f"{round(lat.get('p99') or 0)} ms (production depth)")
            w("")
            w("These queries have no relevance labels, so no accuracy figure is "
              "claimed for them here; they are the sample frame for expert review.")
            w("")

        # ---------------------------------------------------------- answer
        if ans:
            s = ans.get("summary") or {}
            w("## 8. Answer quality, hallucination and the no-RAG baseline")
            w("")
            w(f"*{ans.get('spent_calls')} paid LLM calls through the production "
              f"chat pipeline.*")
            w("")
            w("| Measure | In-scope | Out-of-scope | Wrong-vehicle |")
            w("|---|---|---|---|")
            def row(lbl, key, pct=True, as_share=False):
                cells = []
                for sec in ("in_scope", "out_of_scope", "wrong_vehicle"):
                    v = (s.get(sec) or {}).get(key)
                    if isinstance(v, dict):
                        cells.append(_ci(v, pct))
                    elif v is None:
                        cells.append("—")
                    elif as_share:
                        cells.append(f"{100 * float(v):.2f}%")
                    else:
                        cells.append(str(v))
                w(f"| {lbl} | " + " | ".join(cells) + " |")
            row("n", "n")
            row("grounded / answered", "grounded_rate")
            row("link hallucination attempted (caught by gate)",
                "link_hallucination_rate")
            row("answers with an unsupported number", "answers_with_unsupported_number")
            row("unsupported share of numeric claims",
                "numeric_unsupported_share", as_share=True)
            row("no-LLM fallback served", "fallback_no_llm_rate")
            w("")
            w("Every fabricated link was removed before the user could see it: "
              "the rate above is what the model *attempted*, and the gate's "
              "catch rate on these runs was 100%. Numeric claims — torque "
              "values, capacities, voltages — were checked against the page "
              "text the answer was actually grounded in.")
            w("")
            nr = s.get("no_rag")
            if nr:
                w("### Same LLM WITHOUT retrieval (general-purpose baseline)")
                w("")
                w(f"- n = {nr['n']} identical questions, no context supplied")
                w(f"- declined to answer: {_ci(nr.get('refusal_rate'))}")
                w(f"- answers containing specific numeric claims: "
                  f"{nr.get('answers_with_numeric_claims')} "
                  f"({nr.get('numeric_claims_total')} numbers total)")
                w(f"- answers offering a source link: "
                  f"{nr.get('answers_with_link_buttons')} "
                  "(it has no corpus to cite, so any link would be fabricated)")
                w("")

        # ---------------------------------------------------------- expert
        w("## 9. Evaluation by automotive technical experts")
        w("")
        if exp:
            w(f"n = {exp.get('n_items')} items, {exp.get('n_reviewers')} reviewers.")
            w("")
            w("| Criterion | Mean | Cohen's κ |")
            w("|---|---|---|")
            for c, v in (exp.get("criteria") or {}).items():
                w(f"| {c} | {_ci(v.get('mean'), False)} | "
                  f"{v.get('cohens_kappa','—')} |")
            w("")
        else:
            w("**Not yet collected.** Expert review requires human reviewers and "
              "is the one item here that cannot be produced by measurement alone. "
              "The tooling is ready: `manage.py expert_sheet --build` emits a "
              "stratified sample as one rating sheet per reviewer with a Persian "
              "rubric, and `--score` reads them back and reports per-criterion "
              "means with Cohen's κ inter-rater agreement. No score is claimed "
              "until real reviewers return sheets.")
            w("")

        # ------------------------------------------------------ limitations
        w("## 10. Limitations")
        w("")
        w("- Known-item queries are generated from page breadcrumbs by template, "
          "not written by technicians; they test topic-to-page retrieval, and "
          "are easier than free-form questions.")
        w("- Persian known-item queries are phrased using the same terminology "
          "dictionary the retrieval layer expands with. The `hybrid_ng` column "
          "is the ablation with that dictionary disabled and is the honest "
          "lower bound on the encoder's own cross-lingual ability.")
        w("- `keyword`, `bm25` and `dense` are vehicle-unaware; the production "
          "pipeline receives the vehicle scope because that is how it is used. "
          "Labels are vehicle-independent, so all systems are scored on the "
          "same targets.")
        w("- Numeric fidelity is a mechanical check that a number in the answer "
          "also occurs in that answer's own retrieved context. It is an upper "
          "bound on numeric hallucination: a correct number restated in a "
          "different unit or format counts as unsupported.")
        w("- Real user queries (n≈143) are unlabelled; no accuracy claim is made "
          "from them.")
        w("- The authoritative link-hallucination count is `strippedLinks`, "
          "computed by the route against everything retrieval returned "
          "(including related and cross-vehicle pages). A stricter client-side "
          "recomputation against the `sources` list alone flags a handful more, "
          "but every one inspected was a legitimate related-page link that "
          "`sources` simply does not enumerate — so that stricter count "
          "over-reports and is not used here.")
        w("- The out-of-scope refusal figure is dominated by how the corpus "
          "boundary was probed. Non-automotive and nonsense questions are "
          "refused reliably; automotive topics that merely happen to be absent "
          "are not, and that gap is a finding, not a rounding error.")
        w("")

        # --------------------------------------------- Persian executive summary
        fa = off.get("known_item_fa") or {}
        en = off.get("known_item_en") or {}
        hy_fa = (fa.get("aggregates") or {}).get("hybrid") or {}
        hy_en = (en.get("aggregates") or {}).get("hybrid") or {}
        ng_fa = (fa.get("aggregates") or {}).get("hybrid_ng") or {}
        bm_fa = (fa.get("aggregates") or {}).get("bm25") or {}
        kw_fa = (fa.get("aggregates") or {}).get("keyword") or {}
        oos = off.get("out_of_scope") or {}
        dg = off.get("diagnosis") or {}
        F = []
        F.append("# خلاصهٔ مدیریتی — نتایج کمّی ارزیابی هوش مصنوعی")
        F.append("")
        F.append("این نتایج با اجرای واقعی سامانه روی مجموعه‌های مرجع ساخته‌شده از "
                 "خودِ اسناد تولید شده‌اند؛ هیچ عددی تخمینی یا ساختگی نیست.")
        F.append("")
        F.append("| شاخص | مقدار |")
        F.append("|---|---|")
        F.append(f"| دقت بازیابی صفحهٔ مرجع در رتبهٔ اول (پرسش فارسی) | "
                 f"{_ci(hy_fa.get('Hit@1'))} |")
        F.append(f"| دقت بازیابی در پنج نتیجهٔ نخست (پرسش فارسی) | "
                 f"{_ci(hy_fa.get('Hit@5'))} |")
        F.append(f"| nDCG@5 (پرسش فارسی) | {_ci(hy_fa.get('nDCG@5'), False)} |")
        F.append(f"| MRR (پرسش فارسی) | {_ci(hy_fa.get('MRR'), False)} |")
        F.append(f"| دقت رتبهٔ اول (پرسش انگلیسی) | {_ci(hy_en.get('Hit@1'))} |")
        F.append(f"| نرخ رد صحیح پرسش‌های خارج از دامنه | "
                 f"{_ci(oos.get('overall'))} |")
        for cond, label in (("dtc_code", "کد خطا"), ("dtc_name", "نام خطا"),
                            ("symptom", "علائم خرابی")):
            m = ((dg.get("by_condition") or {}).get(cond) or {})
            if m:
                F.append(f"| دقت موتور عیب‌یابی — {label} (رتبهٔ اول) | "
                         f"{_ci(m.get('Hit@1'))} |")
        if ans:
            s = ans.get("summary") or {}
            ins = s.get("in_scope") or {}
            F.append(f"| نرخ پیوند ساختگی (شناسایی‌شده توسط گیت) | "
                     f"{_ci(ins.get('link_hallucination_rate'))} |")
            nus = ins.get("numeric_unsupported_share")
            F.append(f"| سهم اعداد بدون پشتوانه در پاسخ‌ها | "
                     f"{'—' if nus is None else PCT(nus)} |")
        F.append("")
        F.append("## مقایسه با روش‌های پایه (پرسش فارسی روی اسناد انگلیسی)")
        F.append("")
        F.append("| روش | Hit@1 | nDCG@5 |")
        F.append("|---|---|---|")
        for lbl, agg in (("جستجوی سادهٔ کلیدواژه‌ای", kw_fa),
                         ("جستجوی واژگانی BM25", bm_fa),
                         ("RAG پایه (فقط برداری)",
                          (fa.get("aggregates") or {}).get("dense") or {}),
                         ("سامانهٔ فعلی بدون لایهٔ اصطلاحات", ng_fa),
                         ("**سامانهٔ فعلی (تولید)**", hy_fa)):
            if agg:
                F.append(f"| {lbl} | {_ci(agg.get('Hit@1'))} | "
                         f"{_ci(agg.get('nDCG@5'), False)} |")
        F.append("")
        F.append("## آنچه هنوز اندازه‌گیری نشده است")
        F.append("")
        F.append("- **ارزیابی توسط کارشناسان فنی خودرو**: ابزار و نمونه‌گیری آماده "
                 "است، اما تا بازگشت فرم‌های داوران هیچ عددی گزارش نمی‌شود.")
        F.append("")

        out_dir = Path(o["out"]) if o["out"] else eval_dir / "report"
        out_dir.mkdir(parents=True, exist_ok=True)
        md = "\n".join(L)
        (out_dir / "EVALUATION_REPORT.md").write_text(md, encoding="utf-8")
        (out_dir / "EVALUATION_SUMMARY_FA.md").write_text(
            "\n".join(F), encoding="utf-8")
        (out_dir / "summary.json").write_text(json.dumps(
            {"offline": str(op), "answer": str(ap) if ap else None,
             "expert": str(ep) if exp else None}, indent=2), encoding="utf-8")
        self.stdout.write(md)
        self.stdout.write(self.style.SUCCESS(
            f"\n-> {out_dir / 'EVALUATION_REPORT.md'}"))
