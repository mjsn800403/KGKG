"""Uncertainty and significance for the evaluation suite.

A single mean with no interval invites the question "is that just noise?", so
every headline number in the report ships with a 95% bootstrap confidence
interval, and every system-vs-system claim ships with a paired bootstrap
p-value. Pure stdlib, deterministic under `seed`.
"""
from __future__ import annotations

import random
from statistics import mean


def bootstrap_ci(values, n_boot=2000, alpha=0.05, seed=1373):
    """Percentile bootstrap CI for the mean of `values`."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"mean": None, "lo": None, "hi": None, "n": 0}
    if len(vals) == 1:
        return {"mean": vals[0], "lo": vals[0], "hi": vals[0], "n": 1}
    rng = random.Random(seed)
    n = len(vals)
    means = []
    for _ in range(n_boot):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return {"mean": round(mean(vals), 4), "lo": round(lo, 4),
            "hi": round(hi, 4), "n": n}


def paired_bootstrap(a, b, n_boot=2000, seed=1373):
    """Two-sided paired bootstrap test on mean(a) - mean(b).

    `a` and `b` are per-query scores for two systems on the SAME queries, in
    the same order. Returns the observed difference and a p-value for
    H0: no difference.
    """
    pairs = [(float(x), float(y)) for x, y in zip(a, b)
             if x is not None and y is not None]
    if len(pairs) < 2:
        return {"diff": None, "p": None, "n": len(pairs)}
    rng = random.Random(seed)
    n = len(pairs)
    obs = mean(x for x, _ in pairs) - mean(y for _, y in pairs)
    centred = [(x - y) - obs for x, y in pairs]
    extreme = 0
    for _ in range(n_boot):
        s = sum(centred[rng.randrange(n)] for _ in range(n)) / n
        if abs(s) >= abs(obs):
            extreme += 1
    return {"diff": round(obs, 4), "p": round((extreme + 1) / (n_boot + 1), 4),
            "n": n}


def wilson_ci(successes, total, z=1.96):
    """Wilson score interval for a proportion — better than normal-approx for
    the small, near-1.0 rates this suite produces (refusal accuracy etc.)."""
    if not total:
        return {"rate": None, "lo": None, "hi": None, "n": 0}
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = (z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5)) / denom
    return {"rate": round(p, 4), "lo": round(max(0.0, centre - half), 4),
            "hi": round(min(1.0, centre + half), 4), "n": total}
