"""Diagnostic-engine regression check on the versioned gold sets (no LLM).

    cd KG_backend && python ../qa/eval/diag_check.py [--limit N] > result.json

Measures, through api.rag.diag.diagnose exactly as /api/diagnose/ calls it:
  * diagnosis.jsonl (manufacturer DTC and symptom tables): Hit@1 / Hit@3 and
    the share answered as grounded, per condition (dtc_code, dtc_name, symptom)
  * out_of_scope.jsonl (non-automotive, nonsense, automotive-but-absent): the
    share the engine wrongly answers as grounded with candidates

Run it before and after any change to diag.py ranking or grounding; both
numbers belong in the commit message.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KG_backend.settings')
# It runs on the production host: cap the embedding model's threads (default 2)
# so a measurement can never crowd out the live service.
_THREADS = os.environ.get('KG_QA_THREADS', '2')
for _v in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'TORCH_NUM_THREADS'):
    os.environ.setdefault(_v, _THREADS)
import torch  # noqa: E402

torch.set_num_threads(int(_THREADS))
import django  # noqa: E402

django.setup()
from api.rag import config, diag  # noqa: E402
from api.evalsuite import goldset  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()
    gold = config.RAG_DIR / 'eval' / 'gold'
    out = {'diagnosis': {}, 'out_of_scope': {}}

    rows = goldset.read_jsonl(gold / 'diagnosis.jsonl')
    rows = rows[:args.limit] if args.limit else rows
    acc = defaultdict(lambda: defaultdict(int))
    for r in rows:
        res = diag.diagnose(r['query'], car_stem=r['car'])
        a = acc[r['condition']]
        a['n'] += 1
        if r['condition'] in ('dtc_code', 'dtc_name'):
            ranked, want = [c.get('code') for c in res.get('candidates') or []], set(r.get('expected_codes') or [])
        else:
            ranked, want = [p.get('app_url') for p in res.get('procedures') or []], set(r.get('expected_app_urls') or [])
        a['hit1'] += bool(ranked[:1] and ranked[0] in want)
        a['hit3'] += bool(set(ranked[:3]) & want)
        a['grounded'] += bool(res.get('grounded'))
    for cond, a in sorted(acc.items()):
        n = a['n']
        out['diagnosis'][cond] = {'n': n, 'hit1': round(a['hit1'] / n, 3),
                                  'hit3': round(a['hit3'] / n, 3), 'grounded': round(a['grounded'] / n, 3)}

    oos = goldset.read_jsonl(gold / 'out_of_scope.jsonl')
    by = defaultdict(lambda: defaultdict(int))
    for r in oos:
        res = diag.diagnose(r['query'], car_stem=r['car'])
        b = by[r.get('category', '?')]
        b['n'] += 1
        b['wrongly_grounded'] += bool(res.get('grounded') and res.get('candidates'))
    for cat, b in sorted(by.items()):
        out['out_of_scope'][cat] = {'n': b['n'], 'wrongly_grounded': b['wrongly_grounded']}
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
