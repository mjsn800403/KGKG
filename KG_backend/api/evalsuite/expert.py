"""Expert-review tooling: sampling, rating sheet, and agreement scoring.

Evaluation by automotive technical experts cannot be simulated — it needs real
reviewers. What CAN be built in advance is everything around them, so that the
review is a data-collection exercise rather than a research project:

  1. a stratified, reproducible sample of real system outputs;
  2. a rating sheet (CSV, RTL-friendly) with an explicit rubric, one row per
     item, so two reviewers can work independently;
  3. a scorer that reads the completed sheets back and reports per-criterion
     means with confidence intervals, plus Cohen's kappa between reviewers so
     the reliability of the ratings themselves is visible.

The rubric deliberately separates RETRIEVAL quality (was the right manual page
found?) from ANSWER quality (was the Persian answer faithful to that page?),
because those are different failure modes with different fixes.
"""
from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from pathlib import Path

# criterion -> (Persian prompt shown to the reviewer, scale)
RUBRIC = [
    ("relevance",
     "آیا صفحهٔ ارجاع‌شده به پرسش مربوط است؟ (۱=بی‌ربط ... ۵=دقیقاً همان صفحه)",
     "1-5"),
    ("completeness",
     "آیا پاسخ برای انجام کار کافی است؟ (۱=ناقص ... ۵=کامل)", "1-5"),
    ("faithfulness",
     "آیا محتوای پاسخ با متن منبع مطابقت دارد و چیزی از خود نساخته است؟ "
     "(۱=ادعای بی‌پشتوانه ... ۵=کاملاً منطبق)", "1-5"),
    ("terminology",
     "آیا اصطلاحات فنی فارسی درست به‌کار رفته‌اند؟ (۱=غلط ... ۵=درست)", "1-5"),
    ("safety",
     "آیا هشدارها/نکات ایمنی لازم رعایت شده است؟ (۱=خطرناک ... ۵=کامل)", "1-5"),
    ("actionable",
     "آیا یک تکنسین می‌تواند مستقیماً بر اساس این پاسخ اقدام کند؟ (بله/خیر)",
     "yes/no"),
]

HEADER = ["item_id", "set", "car", "question", "top_page_title", "top_page_url",
          "confidence_band", "grounded", "answer_or_context"] + \
         [c for c, _p, _s in RUBRIC] + ["reviewer_note"]


def stratified_sample(pools, n_total, seed=1373):
    """Round-robin over pools (a dict of label -> rows) for an even spread."""
    rng = random.Random(seed)
    picked, cursors = [], {}
    pools = {k: list(v) for k, v in pools.items() if v}
    for v in pools.values():
        rng.shuffle(v)
    labels = sorted(pools)
    for lab in labels:
        cursors[lab] = 0
    while len(picked) < n_total and labels:
        progressed = False
        for lab in labels:
            if len(picked) >= n_total:
                break
            i = cursors[lab]
            if i >= len(pools[lab]):
                continue
            cursors[lab] = i + 1
            row = dict(pools[lab][i])
            row["set"] = lab
            picked.append(row)
            progressed = True
        if not progressed:
            break
    return picked


def write_sheet(path: Path, rows, n_reviewers=2):
    """One CSV per reviewer, identical items, blank rating columns.

    UTF-8 BOM so Excel opens Persian correctly on Windows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for r in range(1, n_reviewers + 1):
        p = path.with_name(f"{path.stem}_reviewer{r}.csv")
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            for i, row in enumerate(rows, 1):
                w.writerow([
                    row.get("item_id", i), row.get("set", ""),
                    row.get("car", ""), row.get("query", ""),
                    row.get("top_title", ""), row.get("top_app_url", ""),
                    row.get("band", ""), row.get("grounded", ""),
                    (row.get("answer") or row.get("context") or "")[:1500],
                ] + [""] * len(RUBRIC) + [""])
        written.append(p)
    # the rubric travels with the sheets so reviewers score the same thing
    guide = path.with_name(f"{path.stem}_RUBRIC.md")
    lines = ["# راهنمای ارزیابی کارشناسی", "",
             "هر ردیف را مستقل از دیگران امتیاز دهید. اگر صفحهٔ ارجاع‌شده را",
             "باز نکرده‌اید، امتیاز ندهید و در ستون یادداشت بنویسید «بررسی‌نشده».",
             ""]
    for c, prompt, scale in RUBRIC:
        lines.append(f"- **{c}** ({scale}): {prompt}")
    lines += ["", "## نکات", "- «۳» یعنی قابل قبول ولی نیازمند اصلاح.",
              "- برای پاسخ‌هایی که سامانه عمداً رد کرده (grounded=False)،",
              "  اگر رد کردن درست بوده است relevance=5 بدهید."]
    guide.write_text("\n".join(lines), encoding="utf-8")
    written.append(guide)
    return written


# ------------------------------------------------------------- scoring back
def cohens_kappa(a, b):
    """Cohen's kappa for two equal-length rating lists (categorical)."""
    pairs = [(x, y) for x, y in zip(a, b) if x not in (None, "") and y not in (None, "")]
    if len(pairs) < 2:
        return None
    n = len(pairs)
    cats = sorted({x for x, _ in pairs} | {y for _, y in pairs})
    obs = sum(1 for x, y in pairs if x == y) / n
    pa = defaultdict(int)
    pb = defaultdict(int)
    for x, y in pairs:
        pa[x] += 1
        pb[y] += 1
    exp = sum((pa[c] / n) * (pb[c] / n) for c in cats)
    if exp >= 1.0:
        return 1.0
    return round((obs - exp) / (1 - exp), 4)


def score_sheets(paths):
    """Read completed reviewer CSVs -> per-criterion means + kappa."""
    from api.evalsuite import stats

    sheets = []
    for p in paths:
        with open(p, encoding="utf-8-sig", newline="") as fh:
            sheets.append({r["item_id"]: r for r in csv.DictReader(fh)})
    if not sheets:
        return {}
    common = set(sheets[0])
    for s in sheets[1:]:
        common &= set(s)
    common = sorted(common)

    out = {"n_items": len(common), "n_reviewers": len(sheets), "criteria": {}}
    for crit, _prompt, scale in RUBRIC:
        vals, per_reviewer = [], []
        for s in sheets:
            col = []
            for k in common:
                v = (s[k].get(crit) or "").strip()
                col.append(v)
                if scale == "1-5":
                    try:
                        vals.append(float(v))
                    except ValueError:
                        pass
                elif v:
                    vals.append(1.0 if v.lower() in ("yes", "بله", "y", "1") else 0.0)
            per_reviewer.append(col)
        entry = {"mean": stats.bootstrap_ci(vals) if vals else {"n": 0}}
        if len(per_reviewer) >= 2:
            entry["cohens_kappa"] = cohens_kappa(per_reviewer[0], per_reviewer[1])
        out["criteria"][crit] = entry
    return out
