"""Pure, dependency-free retrieval-evaluation metrics (no Django, no numpy).

Binary-relevance ranking metrics over an ordered list of retrieved ids and a
set of relevant ids, plus confidence-calibration bucketing and a percentile
helper. Kept standalone so the offline eval harness logic is unit-testable.
"""
import math


def hit_at_k(ranked, relevant, k):
    return 1 if any(r in relevant for r in ranked[:k]) else 0


def mrr(ranked, relevant):
    for i, r in enumerate(ranked, start=1):
        if r in relevant:
            return 1.0 / i
    return 0.0


def recall_at_k(ranked, relevant, k):
    if not relevant:
        return 0.0
    found = sum(1 for r in ranked[:k] if r in relevant)
    return found / len(relevant)


def precision_at_k(ranked, relevant, k):
    if k <= 0:
        return 0.0
    found = sum(1 for r in ranked[:k] if r in relevant)
    return found / k


def ndcg_at_k(ranked, relevant, k):
    if not relevant:
        return 0.0
    dcg = 0.0
    for i, r in enumerate(ranked[:k], start=1):
        if r in relevant:
            dcg += 1.0 / math.log2(i + 1)
    ideal_n = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_n + 1))
    return dcg / idcg if idcg > 0 else 0.0


def calibration_buckets(samples):
    """samples: iterable of (band, hit_bool) -> {band: {'n', 'hit_rate'}}.
    A well-calibrated system has high hit_rate in the 'high' band, low in 'low'."""
    agg = {}
    for band, hit in samples:
        slot = agg.setdefault(band, [0, 0])
        slot[0] += 1
        if hit:
            slot[1] += 1
    return {b: {'n': n, 'hit_rate': (h / n if n else 0.0)} for b, (n, h) in agg.items()}


def percentile(xs, p):
    """Nearest-rank percentile of a numeric list (p in [0,100]); None if empty."""
    vals = sorted(v for v in xs if v is not None)
    if not vals:
        return None
    if p <= 0:
        return vals[0]
    if p >= 100:
        return vals[-1]
    rank = math.ceil(p / 100.0 * len(vals))
    return vals[min(rank, len(vals)) - 1]
