"""Standalone scoring / calibration core for hybrid retrieval.

Deliberately dependency-free (no Django, no numpy, no DB): every function is a
pure transform over plain numbers, so it is trivially unit-testable and costs
microseconds per call. `retrieve.py` reads tunables from `config` and passes
them in; nothing here imports the rest of the app.

Three jobs:
  * classify_query  — route a query to per-path fusion weights (dense vs keyword)
  * calibrate       — blend the retrieval signals into one explainable score
  * confidence_band — map a score/margin/similarity to a high|medium|low band
plus feedback_multiplier, the guarded human-in-the-loop boost formula.
"""
import math
import re

# Per-path RRF weights by query kind. Exact-code lookups lean on the keyword
# side; natural-language Persian leans on the multilingual dense side.
FUSION_WEIGHTS = {
    'code':     {'vec': 0.30, 'fts': 1.00},
    'lexical':  {'vec': 0.60, 'fts': 1.00},
    'semantic': {'vec': 1.00, 'fts': 0.50},
    'mixed':    {'vec': 1.00, 'fts': 1.00},
}

# Default blend weights for calibrate(). Tunable via config without a rebuild.
SCORE_W_RRF = 0.30
SCORE_W_SIM = 0.45
SCORE_W_BM25 = 0.20
SCORE_W_CENT = 0.05

# A DTC code shape: 1 ASCII letter + 3-4 alphanumerics + optional -NN / :NN
# suffix (P0301, B27C0, U0129, b27c0-57). Used token-by-token; we additionally
# require the token to contain a digit so plain words ("brake", "fluid") that
# happen to fit the shape are NOT mistaken for codes.
_CODE_RE = re.compile(r'^[A-Za-z][0-9A-Za-z]{3,4}(?:[-:]\d{1,3})?$')
_PERSIAN_RE = re.compile(r'[؀-ۿ]')
_LATIN_RE = re.compile(r'[A-Za-z]')


def _has_dtc_code(query):
    for raw in (query or '').split():
        tok = raw.strip('.,;:!?()[]{}«»"\'')
        if _CODE_RE.match(tok) and any(c.isdigit() for c in tok) \
                and any(c.isalpha() for c in tok):
            return True
    return False


def classify_query(query, eng_terms=''):
    """Route a query to a kind + per-path fusion weights.

    The persian/latin ratio is measured on the ORIGINAL query only — the
    glossary's English expansion (eng_terms) is for matching, and must not flip
    a Persian natural-language question into the lexical bucket.
    """
    q = (query or '').strip()
    if not q:
        return {'kind': 'mixed', 'weights': dict(FUSION_WEIGHTS['mixed'])}
    # a code present anywhere wins: exact-code lookup is the priority path
    if _has_dtc_code(q):
        return {'kind': 'code', 'weights': dict(FUSION_WEIGHTS['code'])}

    persian = len(_PERSIAN_RE.findall(q))
    latin = len(_LATIN_RE.findall(q))
    words = q.split()
    if persian > latin and len(words) >= 2:
        kind = 'semantic'           # natural-language Persian sentence
    elif latin >= persian:
        kind = 'lexical'            # latin keywords / specs (torque, part names)
    else:
        kind = 'mixed'
    return {'kind': kind, 'weights': dict(FUSION_WEIGHTS[kind])}


def calibrate(signals, w_rrf=SCORE_W_RRF, w_sim=SCORE_W_SIM,
              w_bm25=SCORE_W_BM25, w_cent=SCORE_W_CENT):
    """Blend normalized retrieval signals into one final score + an `explain`.

    `signals` keys (all already normalized by the caller):
      rrf, sim, bm25, centrality  in [0,1];
      vehicle_boost, boilerplate, feedback  as multipliers (~1.0 neutral).
    """
    rrf = float(signals.get('rrf', 0.0))
    sim = float(signals.get('sim', 0.0))
    bm25 = float(signals.get('bm25', 0.0))
    cent = float(signals.get('centrality', 0.0))
    vehicle = float(signals.get('vehicle_boost', 1.0))
    boiler = float(signals.get('boilerplate', 1.0))
    feedback = float(signals.get('feedback', 1.0))
    scope = float(signals.get('scope', 1.0))      # <1 for out-of-scope blobs

    base = w_rrf * rrf + w_sim * sim + w_bm25 * bm25 + w_cent * cent
    final = base * vehicle * boiler * feedback * scope
    explain = {
        'rrf': round(rrf, 4), 'sim': round(sim, 4), 'bm25': round(bm25, 4),
        'centrality': round(cent, 4), 'base': round(base, 5),
        'boosts': {'vehicle': round(vehicle, 3), 'boilerplate': round(boiler, 3),
                   'feedback': round(feedback, 3), 'scope': round(scope, 3)},
        'final': round(final, 6),
    }
    return {'final': float(final), 'explain': explain}


# Persian band labels (high-stakes UI). 'low' carries an explicit verify warning.
_BAND_FA = {
    'high': 'مطمئن',
    'medium': 'نسبتاً مطمئن',
    'low': 'نامطمئن — با دفترچه راستی‌آزمایی کن',
}


def confidence_band(final, margin, sim, high_sim=0.75, high_margin=0.15,
                    low_sim=0.45):
    """High when the top match is both strong (sim) and a clear winner (margin);
    low when similarity is weak; medium otherwise."""
    if sim >= high_sim and margin >= high_margin:
        band = 'high'
    elif sim < low_sim:
        band = 'low'
    else:
        band = 'medium'
    return {'band': band, 'label_fa': _BAND_FA[band]}


def feedback_multiplier(up, down, clicks, min_count=3, cap_lo=0.85, cap_hi=1.2,
                        click_weight=0.5):
    """Guarded human-in-the-loop boost: aggregate signals -> a bounded multiplier.

    Guardrails: below `min_count` total signals it stays neutral (1.0) so a
    single stray vote can't move ranking; the result is hard-clamped to
    [cap_lo, cap_hi] so noise can never dominate the calibrated score. Callers
    pass time-decayed counts to fade stale feedback.
    """
    total = up + down + clicks
    if total < min_count:
        return 1.0
    net = up + click_weight * clicks - down
    score = net / (total + 1.0)          # in (-1, 1)
    if score >= 0:
        mult = 1.0 + score * (cap_hi - 1.0)
    else:
        mult = 1.0 + score * (1.0 - cap_lo)
    return max(cap_lo, min(cap_hi, mult))
