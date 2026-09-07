"""Baseline retrievers, so the production pipeline is compared against
something instead of reported in a vacuum.

All systems answer the SAME queries over the SAME index and are scored by the
same code against the same blob-level labels:

  keyword    boolean term match, NO relevance ranking and NO terminology layer
             -- i.e. "we just added a search box". A Persian query cannot match
             English pages here; that is the honest baseline, not a bug.
  bm25       FTS5/BM25 lexical ranking, with the terminology layer
  dense      bge-m3 vector kNN only -- plain "baseline RAG": no fusion, no
             re-ranking, no vehicle context, no graph expansion
  hybrid     the production pipeline (api.rag.retrieve.assist), as deployed
  hybrid_ng  production pipeline with Persian->English term expansion DISABLED,
             isolating the dictionary's contribution from the multilingual
             encoder's own cross-lingual ability

Fairness note carried into the report: `hybrid`/`hybrid_ng` receive the vehicle
scope because that is how the product is used, and they use it to boost
in-vehicle pages. `keyword`/`bm25`/`dense` are vehicle-unaware by construction.
Relevance labels are blob-level and vehicle-independent, so all systems are
scored on identical targets.
"""
from __future__ import annotations

import contextlib
import json
import os
import re

from api.rag import store, embed, glossary, retrieve, service, scoring, config

TOPK = 10              # deep enough to score @1..@10 for every system

# Stripped from the naive baseline's boolean query. Without this, an AND search
# for "how do I remove the X" fails on the function words and the baseline
# collapses for reasons no real search box would suffer — that would be a
# strawman, not a baseline.
_STOP = frozenset("""
a an the of for to in on at by with from is are was were be been do does did
how what where when which who why can could should would i you it this that
these those my your and or not no yes please tell me show my's s
""".split())


def _fts_expr(query, use_glossary=True, op=" OR ", drop_stopwords=False):
    q = query
    if use_glossary:
        eng, _ = glossary.expand(query)
        if eng:
            q = f"{query} {eng}"
    toks = []
    for raw in q.replace('"', " ").split():
        t = "".join(ch for ch in raw if ch.isalnum())
        if len(t) < 2:
            continue
        if drop_stopwords and t.lower() in _STOP:
            continue
        toks.append(t)
    toks = list(dict.fromkeys(toks))
    return op.join(toks) if toks else None


# ------------------------------------------------------------- systems
def run_keyword(index, query, car_stem, k=TOPK, **_):
    """Simple search box: boolean term match, document order, no ranking,
    no Persian->English expansion.

    Tries AND (all terms) first, as a real search box would, and falls back to
    OR when that returns nothing.
    """
    for op in (" AND ", " OR "):
        expr = _fts_expr(query, use_glossary=False, op=op, drop_stopwords=True)
        if not expr:
            return []
        try:
            rows = index.execute(
                "SELECT rowid FROM blobs_fts WHERE blobs_fts MATCH ? "
                "LIMIT ?", (expr, k)).fetchall()
        except Exception:
            return []
        if rows:
            return [r[0] for r in rows]
    return []


def run_bm25(index, query, car_stem, k=TOPK, use_glossary=True, **_):
    """FTS5/BM25 lexical retrieval only."""
    expr = _fts_expr(query, use_glossary)
    if not expr:
        return []
    try:
        rows = index.execute(
            "SELECT rowid FROM blobs_fts WHERE blobs_fts MATCH ? "
            "ORDER BY rank LIMIT ?", (expr, k)).fetchall()
    except Exception:
        return []
    return [r[0] for r in rows]


def run_dense(index, query, car_stem, k=TOPK, qvec=None, use_glossary=True, **_):
    """Dense vector kNN only — 'baseline RAG': no fusion, no re-ranking, no
    vehicle context, no graph expansion."""
    if qvec is None:
        q = query
        if use_glossary:
            eng, _ = glossary.expand(query)
            if eng:
                q = f"{query} {eng}"
        qvec = embed.encode([q], is_query=True)[0]
    qlist = qvec.tolist() if hasattr(qvec, "tolist") else list(qvec)
    qblob = store.pack_f32(qlist)
    rows = index.execute(
        "SELECT rowid AS bid FROM vec_blobs "
        "WHERE embedding MATCH vec_quantize_int8(vec_f32(?),'unit') AND k = ? "
        "ORDER BY distance", (qblob, k)).fetchall()
    return [r[0] for r in rows]


@contextlib.contextmanager
def glossary_disabled():
    """Temporarily neutralise Persian->English term expansion (the `_ng`
    ablation): same pipeline, same index, same query — dictionary removed."""
    orig = glossary.expand
    glossary.expand = lambda q: ("", {})
    try:
        yield
    finally:
        glossary.expand = orig


def run_hybrid(index, query, car_stem, k=TOPK, qvec=None, use_glossary=True, **_):
    """The production retrieval pipeline, exactly as the site serves it.

    Returns the full result dict (not just ids) so the caller can also read
    `grounded`, `confidence_band` and the cited `app_url`s.
    """
    ctx = contextlib.nullcontext() if use_glossary else glossary_disabled()
    with ctx:
        return retrieve.assist(query, brand=None, model=None,
                               car_stem=car_stem, k=k, qvec=qvec)


@contextlib.contextmanager
def _fts_weights(text=1.0, title=1.0, comp=1.0):
    """Temporarily set the BM25 column weights."""
    old = (config.FTS_W_TEXT, config.FTS_W_TITLE, config.FTS_W_COMP)
    config.FTS_W_TEXT, config.FTS_W_TITLE, config.FTS_W_COMP = text, title, comp
    try:
        yield
    finally:
        config.FTS_W_TEXT, config.FTS_W_TITLE, config.FTS_W_COMP = old


@contextlib.contextmanager
def _fts_clean(on=True):
    old = config.FTS_CLEAN
    config.FTS_CLEAN = on
    try:
        yield
    finally:
        config.FTS_CLEAN = old


def run_hybrid_fc(index, query, car_stem, k=TOPK, qvec=None, use_glossary=True, **_):
    """Production pipeline with the FTS MATCH string cleaned (see _fts_match)."""
    ctx = contextlib.nullcontext() if use_glossary else glossary_disabled()
    with ctx, _fts_clean(True):
        return retrieve.assist(query, brand=None, model=None,
                               car_stem=car_stem, k=k, qvec=qvec)


def run_hybrid_notw(index, query, car_stem, k=TOPK, qvec=None, use_glossary=True, **_):
    """Pipeline with FLAT bm25 column weights -- the pre-2026-09-07 behaviour.

    Kept so the title-weighting decision stays falsifiable now that the defaults
    have changed: comparing `hybrid` against `hybrid_tw` once both read the new
    defaults compares a config against itself, which is exactly the mistake that
    produced an identical-looking A/B.
    """
    ctx = contextlib.nullcontext() if use_glossary else glossary_disabled()
    with ctx, _fts_weights(1.0, 1.0, 1.0):
        return retrieve.assist(query, brand=None, model=None,
                               car_stem=car_stem, k=k, qvec=qvec)


def run_hybrid_tw(index, query, car_stem, k=TOPK, qvec=None, use_glossary=True, **_):
    """Production pipeline with the page title weighted in BM25.

    blobs_fts is fts5(text, title, comp); default bm25 weights rate a term in the
    body as highly as one in the title, and in a service manual the title is the
    component name.
    """
    ctx = contextlib.nullcontext() if use_glossary else glossary_disabled()
    with ctx, _fts_weights(1.0, 8.0, 4.0):
        return retrieve.assist(query, brand=None, model=None,
                               car_stem=car_stem, k=k, qvec=qvec)


def run_hybrid_sfts(index, query, car_stem, k=TOPK, qvec=None, use_glossary=True, **_):
    """Production pipeline + the car-scoped keyword pass (retrieve scope_fts).

    The global vector/keyword sides rank the whole corpus, so a single car's
    pages compete against 301,369 blobs; this adds a keyword pass restricted to
    the scoped car. Purely additive to the candidate pool.
    """
    ctx = contextlib.nullcontext() if use_glossary else glossary_disabled()
    with ctx:
        return retrieve.assist(query, brand=None, model=None,
                               car_stem=car_stem, k=k, qvec=qvec, scope_fts=True)


def run_hybrid_rerank(index, query, car_stem, k=TOPK, qvec=None, use_glossary=True, **_):
    """Production retrieval + the cross-encoder reranker.

    Mirrors what `service.assist` does when RAG_RERANK=1, but without its cache
    (which would confound an offline sweep) and while still accepting a
    precomputed `qvec` like the other baselines.

    Deliberately NOT wrapped in try/except: in production a reranker that fails
    to load should degrade quietly, but in a benchmark a silent no-op would be
    reported as "the reranker does not help", which is worse than a crash.
    """
    ctx = contextlib.nullcontext() if use_glossary else glossary_disabled()
    with ctx:
        out = retrieve.assist(query, brand=None, model=None,
                              car_stem=car_stem, k=k, qvec=qvec)
    if out.get("hits"):
        service._rerank(query, out)
        if not out.get("reranked"):
            raise RuntimeError("reranker did not run - refusing to report a silent no-op")
    return out



# --- Phase 3 Task 1: per-layer ablations -----------------------------------
# Each context manager removes exactly ONE company-designed layer. They monkeypatch
# rather than take a flag because these layers were never built with an off switch —
# adding one to production code just to measure it would change the thing measured.

@contextlib.contextmanager
def _calibration_disabled():
    """Calibrated multi-signal blend -> raw RRF. Keeps the same candidates and
    the same fusion, drops only the learned weighting/multipliers."""
    orig = scoring.calibrate

    def raw(signals, **kw):
        rrf = float(signals.get('rrf', 0.0))
        return {'final': rrf,
                'explain': {'ablation': 'no_calibration', 'rrf': rrf,
                            'sim': float(signals.get('sim', 0.0)),
                            'bm25': float(signals.get('bm25', 0.0)),
                            'final': round(rrf, 6)}}
    scoring.calibrate = raw
    try:
        yield
    finally:
        scoring.calibrate = orig


@contextlib.contextmanager
def _adaptive_weights_disabled():
    """classify_query -> always the 'mixed' bucket, i.e. one fixed weight set
    for every query instead of per-path routing."""
    orig = scoring.classify_query

    def fixed(query, eng_terms=''):
        return {'kind': 'mixed', 'weights': dict(scoring.FUSION_WEIGHTS['mixed'])}
    scoring.classify_query = fixed
    try:
        yield
    finally:
        scoring.classify_query = orig


@contextlib.contextmanager
def _vehicle_scope_disabled():
    """Neutralise the vehicle signal: no out-of-scope penalty, and vehicle_boost
    forced to 1.0 inside scoring so a scoped hit gets no preference."""
    orig_pen = config.SCOPE_PENALTY
    orig_cal = scoring.calibrate
    config.SCOPE_PENALTY = 1.0

    def no_vehicle(signals, **kw):
        s = dict(signals)
        s['vehicle_boost'] = 1.0
        return orig_cal(s, **kw)
    scoring.calibrate = no_vehicle
    try:
        yield
    finally:
        config.SCOPE_PENALTY = orig_pen
        scoring.calibrate = orig_cal


@contextlib.contextmanager
def _graph_centrality_disabled():
    """Drop the relationship-graph centrality signal (edge-degree hub score)."""
    orig = retrieve._centrality_map
    retrieve._centrality_map = lambda *a, **k: {}
    try:
        yield
    finally:
        retrieve._centrality_map = orig


# --------------------------------------------------------------------------
# Multi-query expansion (Phase 2 Task 5)
# --------------------------------------------------------------------------
# The glossary substitutes TERMS; this substitutes the whole QUESTION. The LLM
# already in the product writes 2-3 English phrasings of the Persian query, each
# is retrieved independently, and the ranked lists are fused with RRF.
#
# Paraphrases are read from a pre-generated cache rather than called live, so
# the A/B is reproducible and re-runs cost nothing. If the approach wins, the
# live call is a small change to service.assist; if it does not, nothing shipped.
_MQ_CACHE = None


def _mq_paraphrases(query):
    global _MQ_CACHE
    if _MQ_CACHE is None:
        path = os.environ.get('RAG_MQ_CACHE', '/root/paraphrases_known_item_fa.json')
        try:
            with open(path, encoding='utf-8') as fh:
                _MQ_CACHE = json.load(fh)
        except Exception:
            _MQ_CACHE = {}
    return _MQ_CACHE.get(query) or []


def run_hybrid_mq(index, query, car_stem, k=TOPK, qvec=None, use_glossary=True, **_):
    """Production pipeline run once per paraphrase, fused with RRF.

    Falls back to plain `hybrid` when no paraphrase is cached for the query, so
    an incomplete cache degrades the measurement toward the baseline rather than
    silently dropping queries from the set.
    """
    base = retrieve.assist(query, brand=None, model=None, car_stem=car_stem,
                           k=k, qvec=qvec)
    variants = _mq_paraphrases(query)
    if not variants:
        return base

    RRF_K = 60
    fused, seen = {}, {}
    runs = [base['hits'] or []]
    for v in variants:
        try:
            runs.append((retrieve.assist(v, brand=None, model=None,
                                         car_stem=car_stem, k=k)['hits']) or [])
        except Exception:
            pass
    for hits in runs:
        for rank, h in enumerate(hits):
            bid = h.get('blob_id')
            if bid is None:
                continue
            fused[bid] = fused.get(bid, 0.0) + 1.0 / (RRF_K + rank + 1)
            seen.setdefault(bid, h)
    order = sorted(fused, key=lambda b: fused[b], reverse=True)[:k]
    out = dict(base)
    out['hits'] = [seen[b] for b in order]
    out['count'] = len(out['hits'])
    out['mq_variants'] = len(runs)
    return out


def run_hybrid_mq1(index, query, car_stem, k=TOPK, qvec=None, use_glossary=True, **_):
    """Single best English paraphrase, no fusion — isolates translation from RRF."""
    variants = _mq_paraphrases(query)
    if not variants:
        return retrieve.assist(query, brand=None, model=None, car_stem=car_stem,
                               k=k, qvec=qvec)
    return retrieve.assist(variants[0], brand=None, model=None, car_stem=car_stem, k=k)


def _ablated(ctx_factory):
    def run(index, query, car_stem, k=TOPK, qvec=None, use_glossary=True, **_):
        with ctx_factory():
            return retrieve.assist(query, brand=None, model=None,
                                   car_stem=car_stem, k=k, qvec=qvec)
    return run


run_abl_nocal = _ablated(_calibration_disabled)
run_abl_fixedw = _ablated(_adaptive_weights_disabled)
run_abl_noscope = _ablated(_vehicle_scope_disabled)
run_abl_nocent = _ablated(_graph_centrality_disabled)


SYSTEMS = {
    "keyword":   dict(fn=run_keyword, dense=False, glossary=False, full=False),
    "bm25":      dict(fn=run_bm25,    dense=False, glossary=True,  full=False),
    "dense":     dict(fn=run_dense,   dense=True,  glossary=True,  full=False),
    "hybrid":    dict(fn=run_hybrid,  dense=True,  glossary=True,  full=True),
    "hybrid_ng": dict(fn=run_hybrid,  dense=True,  glossary=False, full=True),
    "hybrid_rr": dict(fn=run_hybrid_rerank, dense=True, glossary=True, full=True),
    "hybrid_sfts": dict(fn=run_hybrid_sfts, dense=True, glossary=True, full=True),
    "hybrid_tw": dict(fn=run_hybrid_tw, dense=True, glossary=True, full=True),
    "hybrid_notw": dict(fn=run_hybrid_notw, dense=True, glossary=True, full=True),
    "hybrid_fc": dict(fn=run_hybrid_fc, dense=True, glossary=True, full=True),
    "hybrid_mq": dict(fn=run_hybrid_mq, dense=True, glossary=True, full=True),
    "hybrid_mq1": dict(fn=run_hybrid_mq1, dense=True, glossary=True, full=True),
    "abl_nocal":   dict(fn=run_abl_nocal,   dense=True, glossary=True, full=True),
    "abl_fixedw":  dict(fn=run_abl_fixedw,  dense=True, glossary=True, full=True),
    "abl_noscope": dict(fn=run_abl_noscope, dense=True, glossary=True, full=True),
    "abl_nocent":  dict(fn=run_abl_nocent,  dense=True, glossary=True, full=True),
}
