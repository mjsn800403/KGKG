"""Offline RAG evaluation harness — measures retrieval quality with ZERO LLM
calls and ZERO per-request cost on the live site.

    python manage.py eval_rag --bootstrap   # seed a goldset from real click logs
    python manage.py eval_rag               # score against the goldset
    python manage.py eval_rag --k 8 --limit 200

Reads a gold set at  Database_warehouse/_rag/eval/goldset.jsonl  (one JSON object
per line):
    {"query": "...", "brand": "...", "model": "...", "car": "...",
     "expected_app_urls": ["/Toyota/2025/..."], "out_of_scope": false}

Metrics (binary relevance over app_url): Hit@k, MRR, nDCG@k, Recall@k,
Precision@k; refusal-correctness for out_of_scope rows; confidence-band
calibration; and latency percentiles. Writes a run file under _rag/eval/runs/.
"""
import json
import time
from datetime import datetime

from django.core.management.base import BaseCommand

from api.rag import config, retrieve, feedback, evalmetrics, evalreport


def _relevant(entry):
    """The relevant-id set for a gold row (app_url is the default key)."""
    return set(entry.get('expected_app_urls') or
               [str(b) for b in (entry.get('expected_blob_ids') or [])])


def _ranked_ids(result, use_blob):
    return [(str(h['blob_id']) if use_blob else h['app_url']) for h in result['hits']]


class Command(BaseCommand):
    help = 'Offline retrieval evaluation (no LLM, no per-request cost).'

    def add_arguments(self, parser):
        parser.add_argument('--bootstrap', action='store_true',
                            help='Seed goldset.jsonl from click logs, then exit.')
        parser.add_argument('--k', type=int, default=config.FINAL_K_MAX)
        parser.add_argument('--limit', type=int, default=0,
                            help='Cap number of gold rows evaluated (0 = all).')

    # -- bootstrap -----------------------------------------------------------
    def _bootstrap(self):
        evalreport.EVAL_DIR.mkdir(parents=True, exist_ok=True)
        rows, c = [], None
        try:
            c = feedback._conn()
            # group clicks by query: the clicked app_url is a real relevance label
            cur = c.execute(
                "SELECT query, brand, model, car_stem, GROUP_CONCAT(DISTINCT app_url) "
                "FROM clicks WHERE app_url IS NOT NULL AND app_url != '' "
                "GROUP BY lower(query)")
            for q, brand, model, car_stem, urls in cur.fetchall():
                rows.append({'query': q, 'brand': brand, 'model': model,
                             'car': car_stem,
                             'expected_app_urls': [u for u in (urls or '').split(',') if u],
                             'out_of_scope': False})
        except Exception:
            pass
        finally:
            if c:
                c.close()
        if not rows:
            # nothing learned yet: write a tiny illustrative seed so the harness
            # is runnable and the format is self-documenting.
            rows = [{'query': 'یک سوال که در داده‌ها نیست aksdjf',
                     'brand': None, 'model': None, 'car': None,
                     'expected_app_urls': [], 'out_of_scope': True}]
            self.stdout.write(self.style.WARNING(
                'No click history yet — wrote a 1-row illustrative seed. Add real '
                'rows to goldset.jsonl (see the file header format).'))
        with open(evalreport.GOLD_PATH, 'w', encoding='utf-8') as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + '\n')
        self.stdout.write(self.style.SUCCESS(
            f'Bootstrapped {len(rows)} gold rows -> {evalreport.GOLD_PATH}'))

    # -- evaluate ------------------------------------------------------------
    def handle(self, *args, **opts):
        if opts['bootstrap']:
            return self._bootstrap()
        if not evalreport.GOLD_PATH.exists():
            self.stdout.write(self.style.ERROR(
                f'No goldset at {evalreport.GOLD_PATH}. Run: manage.py eval_rag --bootstrap'))
            return

        gold = []
        with open(evalreport.GOLD_PATH, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line:
                    gold.append(json.loads(line))
        if opts['limit']:
            gold = gold[:opts['limit']]

        k = opts['k']
        per_query, lat, calib = [], [], []
        sums = {m: 0.0 for m in ('hit', 'mrr', 'ndcg', 'recall', 'precision')}
        scored = 0           # in-scope rows that have labels
        refusal_n = refusal_ok = 0

        for e in gold:
            scope = dict(brand=e.get('brand'), model=e.get('model'),
                         car_stem=e.get('car') or e.get('car_stem'))
            t0 = time.monotonic()
            try:
                # pass k through: without it k_eff falls back to the adaptive
                # FINAL_K_MIN/MAX (4-8) and --k would score a list it can never fill
                res = retrieve.assist(e['query'], k=k, **scope)
            except Exception as ex:
                per_query.append({'query': e['query'], 'error': str(ex)})
                continue
            dt = (time.monotonic() - t0) * 1000.0
            lat.append(dt)
            band = (res.get('confidence_band') or {}).get('band')
            grounded = res.get('grounded', res['count'] > 0)

            if e.get('out_of_scope'):
                refusal_n += 1
                ok = (not grounded) or band == 'low'
                refusal_ok += 1 if ok else 0
                per_query.append({'query': e['query'], 'out_of_scope': True,
                                  'refused_ok': ok, 'band': band, 'latency_ms': round(dt)})
                continue

            rel = _relevant(e)
            use_blob = bool(e.get('expected_blob_ids')) and not e.get('expected_app_urls')
            ranked = _ranked_ids(res, use_blob)
            if not rel:
                per_query.append({'query': e['query'], 'note': 'no labels (skipped scoring)',
                                  'band': band, 'latency_ms': round(dt)})
                continue
            row = {
                'hit': evalmetrics.hit_at_k(ranked, rel, k),
                'mrr': evalmetrics.mrr(ranked, rel),
                'ndcg': evalmetrics.ndcg_at_k(ranked, rel, k),
                'recall': evalmetrics.recall_at_k(ranked, rel, k),
                'precision': evalmetrics.precision_at_k(ranked, rel, k),
            }
            for m in sums:
                sums[m] += row[m]
            scored += 1
            calib.append((band or 'medium', bool(row['hit'])))
            per_query.append({'query': e['query'], 'band': band,
                              'latency_ms': round(dt), **{m: round(row[m], 4) for m in row}})

        agg = {m: round(sums[m] / scored, 4) for m in sums} if scored else {}
        agg['refusal_accuracy'] = round(refusal_ok / refusal_n, 4) if refusal_n else None
        report = {
            'ts': datetime.now().strftime('%Y%m%d_%H%M%S'),
            'k': k, 'n': len(gold), 'scored': scored, 'refusal_n': refusal_n,
            'aggregates': agg,
            'calibration': evalmetrics.calibration_buckets(calib),
            'latency_ms': {'p50': evalmetrics.percentile(lat, 50),
                           'p90': evalmetrics.percentile(lat, 90),
                           'p99': evalmetrics.percentile(lat, 99)},
            'per_query': per_query,
        }
        path = evalreport.write_run(report, report['ts'])

        self.stdout.write(self.style.SUCCESS(f'\nEvaluated {len(gold)} rows (scored {scored}):'))
        for m in ('hit', 'mrr', 'ndcg', 'recall', 'precision'):
            if m in agg:
                self.stdout.write(f'  {m:>10}@{k}: {agg[m]}')
        if agg.get('refusal_accuracy') is not None:
            self.stdout.write(f'  refusal_acc: {agg["refusal_accuracy"]} ({refusal_n} rows)')
        self.stdout.write(f'  calibration: {report["calibration"]}')
        self.stdout.write(f'  latency p50/p90/p99 ms: {report["latency_ms"]}')
        self.stdout.write(self.style.SUCCESS(f'  -> {path}'))
