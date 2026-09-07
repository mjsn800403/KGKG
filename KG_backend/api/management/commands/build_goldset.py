"""Build the evaluation gold sets.

    python manage.py build_goldset                # default sizes
    python manage.py build_goldset --n-en 250 --n-fa 250

Writes JSONL under Database_warehouse/_rag/eval/gold/ and prints a coverage
summary. Read-only with respect to the product: it only reads the index and
the diagnosis databases.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from api.rag import config, store
from api.evalsuite import goldset


class Command(BaseCommand):
    help = "Build known-item, cross-lingual, out-of-scope and diagnosis gold sets."

    def add_arguments(self, p):
        p.add_argument("--n-en", type=int, default=250)
        p.add_argument("--n-fa", type=int, default=250)
        p.add_argument("--n-code", type=int, default=150)
        p.add_argument("--n-name", type=int, default=150)
        p.add_argument("--n-symptom", type=int, default=200)
        p.add_argument("--n-wrong", type=int, default=60)
        p.add_argument("--seed", type=int, default=1373)

    def handle(self, *a, **o):
        out_dir = Path(config.INDEX_DB).parent / "eval" / "gold"
        out_dir.mkdir(parents=True, exist_ok=True)
        index = store.get_index_ro()

        cars = goldset.indexed_cars(index)
        self.stdout.write(f"indexed vehicles: {len(cars)}")

        self.stdout.write("building known-item sets (EN + FA) ...")
        en_rows, fa_rows = goldset.build_known_item(
            index, n_en=o["n_en"], n_fa=o["n_fa"], seed=o["seed"])
        goldset.write_jsonl(out_dir / "known_item_en.jsonl", en_rows)
        goldset.write_jsonl(out_dir / "known_item_fa.jsonl", fa_rows)

        self.stdout.write("building out-of-scope set ...")
        oos, kept, rejected = goldset.build_out_of_scope(index, cars, seed=o["seed"])
        wrong = goldset.build_wrong_vehicle(index, n=o["n_wrong"], seed=o["seed"])
        goldset.write_jsonl(out_dir / "out_of_scope.jsonl", oos)
        goldset.write_jsonl(out_dir / "wrong_vehicle.jsonl", wrong)

        self.stdout.write("building diagnosis sets ...")
        diag = goldset.build_diagnosis(
            index, cars, n_code=o["n_code"], n_name=o["n_name"],
            n_symptom=o["n_symptom"], seed=o["seed"])
        goldset.write_jsonl(out_dir / "diagnosis.jsonl", diag)

        # real, unlabelled user queries: carried through for latency /
        # grounding-rate measurement and as the expert-review sample frame
        real = []
        fb = Path(config.INDEX_DB).parent / "feedback.db"
        if fb.exists():
            import sqlite3
            c = sqlite3.connect(f"file:{fb}?mode=ro", uri=True)
            try:
                for q, brand, car in c.execute(
                        "SELECT query, brand, car_stem FROM queries "
                        "WHERE query IS NOT NULL AND trim(query) != ''"):
                    real.append({"query": q, "lang": "fa", "brand": brand,
                                 "car": car, "provenance": "real_user_query"})
            finally:
                c.close()
        goldset.write_jsonl(out_dir / "real_user.jsonl", real)

        def brk(rows, field):
            d = {}
            for r in rows:
                d[r.get(field)] = d.get(r.get(field), 0) + 1
            return dict(sorted(d.items(), key=lambda kv: -kv[1])[:12])

        summary = {
            "known_item_en": len(en_rows),
            "known_item_fa": len(fa_rows),
            "out_of_scope": len(oos),
            "out_of_scope_by_category": brk(oos, "category"),
            "wrong_vehicle": len(wrong),
            "absent_verified": kept,
            "absent_rejected_present_in_corpus": rejected,
            "diagnosis": len(diag),
            "diagnosis_by_condition": brk(diag, "condition"),
            "real_user_queries": len(real),
            "en_systems": brk(en_rows, "system"),
            "fa_systems": brk(fa_rows, "system"),
            "en_actions": brk(en_rows, "action"),
            "fa_actions": brk(fa_rows, "action"),
            "distinct_cars_en": len({r["car"] for r in en_rows}),
            "distinct_cars_fa": len({r["car"] for r in fa_rows}),
            "mean_relevant_en": round(
                sum(len(r["expected_blob_ids"]) for r in en_rows) / max(1, len(en_rows)), 2),
            "mean_relevant_fa": round(
                sum(len(r["expected_blob_ids"]) for r in fa_rows) / max(1, len(fa_rows)), 2),
        }
        (out_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        self.stdout.write(self.style.SUCCESS(f"-> {out_dir}"))
