"""Fuse retrieval order with the KG-Reranker score; pick the weight honestly.

score(c) = a * zscore(ce)[c] + (1 - a) * zscore(-retrieval_rank)[c]   (per question)
a = 0 is the live pipeline, a = 1 is the reranker alone.

The weight is chosen by 2-fold cross-validation: fold A picks the a with the best
mean nDCG@5 (EN+FA pooled), it is measured on fold B, and vice versa. The
reported numbers are only ever on held-out questions. Paired permutation test
against the live order on the same questions.
"""
import hashlib, json, math, random, sys
from collections import defaultdict

rows = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
GRID = [round(x * 0.05, 2) for x in range(21)]


def z(xs):
    m = sum(xs) / len(xs); s = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs)) or 1.0
    return [(x - m) / s for x in xs]


def ranked(r, a):
    c = r['cands']
    if not c:
        return []
    ce = z([x['ce'] for x in c]); rt = z([-i for i in range(len(c))])
    s = [a * p + (1 - a) * q for p, q in zip(ce, rt)]
    return [c[i]['blob_id'] for i in sorted(range(len(c)), key=lambda i: -s[i])]


def metrics(rk, rel):
    rel = set(rel)
    dcg = sum(1 / math.log2(i + 2) for i, b in enumerate(rk[:5]) if b in rel)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(5, len(rel))))
    mrr = next((1 / (i + 1) for i, b in enumerate(rk) if b in rel), 0.0)
    return {'nDCG@5': dcg / idcg if idcg else 0, 'Hit@1': float(bool(rk) and rk[0] in rel), 'MRR': mrr}


def fold(r):
    return int(hashlib.md5((r['set'] + r['query'] + str(r['car'])).encode()).hexdigest(), 16) % 2


def best_a(rs):
    def obj(a):
        return sum(metrics(ranked(r, a), r['rel'])['nDCG@5'] + metrics(ranked(r, a), r['rel'])['Hit@1'] for r in rs)
    return max(GRID, key=obj)


tune = [r for r in rows if r['set'] in ('known_item_en', 'known_item_fa')]
chosen = {f: best_a([r for r in tune if fold(r) != f]) for f in (0, 1)}
print('weight chosen on the other fold:', chosen)

rng = random.Random(0)
report = {'chosen_a': chosen, 'sets': {}}
for st in ('known_item_en', 'known_item_fa', 'known_item_fa_rev'):
    rs = [r for r in rows if r['set'] == st]
    base = [metrics(ranked(r, 0.0), r['rel']) for r in rs]
    new = [metrics(ranked(r, chosen[fold(r)]), r['rel']) for r in rs]
    report['sets'][st] = {}
    for m in ('nDCG@5', 'Hit@1', 'MRR'):
        d = [n[m] - b[m] for n, b in zip(new, base)]; obs = sum(d) / len(d)
        perm = sum(abs(sum(x if rng.random() < .5 else -x for x in d) / len(d)) >= abs(obs) - 1e-12 for _ in range(10000))
        report['sets'][st][m] = {'live': round(sum(b[m] for b in base) / len(rs), 3),
                                 'fused': round(sum(n[m] for n in new) / len(rs), 3),
                                 'delta': round(obs, 3), 'p': round((perm + 1) / 10001, 4), 'n': len(rs)}
        print(st, m, report['sets'][st][m])

# full curve, for the record (in-sample, not used for the claim)
curve = {}
for a in GRID:
    acc = defaultdict(float)
    for r in tune:
        for k, v in metrics(ranked(r, a), r['rel']).items():
            acc[k] += v / len(tune)
    curve[a] = {k: round(v, 3) for k, v in acc.items()}
report['curve_en_fa_pooled'] = curve
print('curve:', {a: (c['nDCG@5'], c['Hit@1']) for a, c in curve.items()})
json.dump(report, open(sys.argv[2], 'w'), indent=2)
