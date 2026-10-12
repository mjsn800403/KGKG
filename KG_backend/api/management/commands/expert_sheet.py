"""Build the expert-review sheets, or score completed ones.

    python manage.py expert_sheet --build --n 120
    python manage.py expert_sheet --score path/to/*_reviewer1.csv path/..._reviewer2.csv

--build draws a stratified sample from the LATEST evaluation run (so reviewers
rate exactly what was measured) and writes one CSV per reviewer plus a rubric.
--score reads the completed sheets back and reports per-criterion means with
confidence intervals and inter-rater agreement.
"""
import glob
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from api.rag import config
from api.evalsuite import expert


def _latest_run(runs_dir):
    cands = sorted([p for p in runs_dir.glob("*/results.json")],
                   key=lambda p: p.stat().st_mtime)
    return cands[-1] if cands else None


def _latest_answer(runs_dir):
    cands = sorted([p for p in runs_dir.glob("*/answer_results.json")],
                   key=lambda p: p.stat().st_mtime)
    return cands[-1] if cands else None


class Command(BaseCommand):
    help = "Create or score automotive-expert review sheets."

    def add_arguments(self, p):
        p.add_argument("--build", action="store_true")
        p.add_argument("--score", nargs="*", default=None)
        p.add_argument("--n", type=int, default=120)
        p.add_argument("--reviewers", type=int, default=2)
        p.add_argument("--seed", type=int, default=1373)
        p.add_argument("--out", default="")

    def handle(self, *a, **o):
        eval_dir = Path(config.INDEX_DB).parent / "eval"
        runs = eval_dir / "runs"

        if o["score"] is not None:
            paths = []
            for pat in o["score"]:
                paths.extend(glob.glob(pat))
            if not paths:
                self.stderr.write("no reviewer CSVs matched")
                return
            res = expert.score_sheets(sorted(paths))
            self.stdout.write(json.dumps(res, ensure_ascii=False, indent=2))
            (eval_dir / "expert" / "expert_scores.json").write_text(
                json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            return

        if not o["build"]:
            self.stderr.write("pass --build or --score")
            return

        pools = {}
        rp = _latest_run(runs)
        if rp:
            data = json.loads(rp.read_text(encoding="utf-8"))
            for name in ("known_item_fa", "known_item_en", "real_user"):
                block = data.get(name) or {}
                rows = []
                for r in (block.get("per_query") or []):
                    h = (r.get("systems") or {}).get("hybrid") or r
                    top5 = h.get("top5") or []
                    rows.append({"query": r.get("query"), "car": r.get("car"),
                                 "top_title": r.get("top_title"),
                                 "top_blob": top5[0] if top5 else None,
                                 "top_app_url": h.get("top_app_url"),
                                 "band": h.get("band"),
                                 "grounded": h.get("grounded"),
                                 "context": r.get("component") or ""})
                pools[name] = rows
            for name in ("out_of_scope", "wrong_vehicle"):
                block = data.get(name) or {}
                pools[name] = [{"query": r.get("query"), "car": r.get("car"),
                                "band": r.get("band"),
                                "grounded": r.get("grounded"),
                                "top_app_url": "", "top_title": "",
                                "context": r.get("category", "")}
                               for r in (block.get("per_query") or [])]
        ap = _latest_answer(runs)
        if ap:
            data = json.loads(ap.read_text(encoding="utf-8"))
            for label, rows in (data.get("raw") or {}).items():
                pools[f"answer_{label}"] = [
                    {"query": r.get("query"), "car": r.get("car"),
                     "band": r.get("band"), "grounded": r.get("grounded"),
                     "top_title": "", "top_app_url": "",
                     "answer": r.get("reply")}
                    for r in rows if "error" not in r]

        pools = {k: v for k, v in pools.items() if v}
        if not pools:
            self.stderr.write("no evaluation runs found to sample from")
            return
        rows = expert.stratified_sample(pools, o["n"], seed=o["seed"])
        # Resolve a human-readable page label for every row that cited one, so
        # a reviewer can tell what was returned without opening each link.
        from api.rag import store
        index = store.get_index_ro()
        need = [r["top_blob"] for r in rows if r.get("top_blob") and not r.get("top_title")]
        titles = {}
        if need:
            qs = ",".join("?" * len(need))
            for bid, t, comp in index.execute(
                    f"SELECT blob_id, title, comp_readable FROM blobs "
                    f"WHERE blob_id IN ({qs})", need):
                titles[bid] = f"{t} — {comp}" if comp else t
        for i, r in enumerate(rows, 1):
            r["item_id"] = i
            if not r.get("top_title") and r.get("top_blob") in titles:
                r["top_title"] = titles[r["top_blob"]]
        out_dir = Path(o["out"]) if o["out"] else (eval_dir / "expert")
        written = expert.write_sheet(out_dir / "expert_review", rows,
                                     n_reviewers=o["reviewers"])
        (out_dir / "expert_sample.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        counts = {}
        for r in rows:
            counts[r["set"]] = counts.get(r["set"], 0) + 1
        self.stdout.write(json.dumps(counts, ensure_ascii=False, indent=2))
        for p in written:
            self.stdout.write(self.style.SUCCESS(f"  -> {p}"))
