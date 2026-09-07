"""Serving layer: fast, safe wrapper around retrieval for the web app.

Goals:
  * keep the site responsive — repeated/common questions are served from an
    in-process TTL cache without touching the model or the vector index;
  * never crash the GPU under concurrent requests — a single lock serialises the
    embedding/search step (MPS/torch is not thread-safe), which on one machine is
    plenty fast (a query embeds in tens of ms);
  * optional cross-encoder rerank for a precision boost on a real server;
  * log every query for analytics + future tuning.

The page-serving endpoints (car browsing) never call this — only the assistant
does — so normal site navigation is never blocked by RAG work.
"""
import threading
import time
from collections import OrderedDict, deque

from . import config, retrieve, feedback

_LOCK = threading.Lock()
_CACHE = OrderedDict()     # key -> (expiry_monotonic, result)
_DIAG_CACHE = OrderedDict()
_SEARCH_CACHE = OrderedDict()   # (key, limit) -> (expiry, light results)
_SEM_CACHE = deque(maxlen=config.SEM_CACHE_MAX)   # (qvec_np, scope_tuple, result)
_RERANKER = None


def warmup():
    """Pre-load the embedding model and open the index connection so the first
    user query is fast. Best-effort; never raises. Called once at server start
    (see api.apps.ApiConfig.ready) when KG_WARMUP is enabled."""
    from . import embed, store
    try:
        if config.INDEX_DB.exists():
            store.get_index_ro()
    except Exception:
        pass
    embed.warmup()


def _acs(allowed_cars):
    """Canonical, hashable form of a car allow-list for cache keys/scopes.

    ``None`` (unrestricted) and a concrete set must never collide — a restricted
    caller must not be served an unrestricted caller's cached answer, and vice
    versa. Returns None for unrestricted, else a sorted tuple."""
    return None if allowed_cars is None else tuple(sorted(allowed_cars))


def _key(query, brand, model, car_stem, allowed_cars=None):
    return ((query or '').strip().lower(), brand or '', model or '', car_stem or '',
            _acs(allowed_cars))


def _cache_get(key):
    item = _CACHE.get(key)
    if not item:
        return None
    exp, res = item
    if exp < time.monotonic():
        _CACHE.pop(key, None)
        return None
    _CACHE.move_to_end(key)
    return res


def _cache_put(key, res):
    _CACHE[key] = (time.monotonic() + config.CACHE_TTL, res)
    _CACHE.move_to_end(key)
    while len(_CACHE) > config.CACHE_MAX:
        _CACHE.popitem(last=False)


def clear_cache():
    _CACHE.clear()
    _DIAG_CACHE.clear()
    _SEM_CACHE.clear()
    _SEARCH_CACHE.clear()


def _sem_cache_get(qvec, scope):
    """Paraphrase-tolerant cache: serve a recent answer whose query embedding is
    near-identical (cosine >= SEM_CACHE_SIM) and was asked in the same scope.
    qvec is unit-normalised, so cosine == dot. Rides on the already-computed
    embedding, so the only added cost is a tiny dot product per cached entry."""
    if not config.SEM_CACHE_ENABLED or qvec is None:
        return None
    import numpy as np
    best, best_sim = None, config.SEM_CACHE_SIM
    for cv, cscope, res in _SEM_CACHE:
        if cscope != scope:
            continue
        sim = float(np.dot(qvec, cv))
        if sim >= best_sim:
            best_sim, best = sim, res
    return best


def _sem_cache_put(qvec, scope, result):
    if config.SEM_CACHE_ENABLED and qvec is not None:
        _SEM_CACHE.append((qvec, scope, result))


def assist(query, brand=None, model=None, car_stem=None, k=None, allowed_cars=None):
    """Cached, thread-safe assist. Same return shape as retrieve.assist, plus an
    exact-key cache, a semantic (paraphrase) cache, and per-request telemetry.

    ``allowed_cars`` (set of car_stems or None) is the vehicle authorization
    boundary; it is part of the cache identity so a restricted caller can never
    be served a broader caller's cached answer."""
    key = _key(query, brand, model, car_stem, allowed_cars)
    cached = _cache_get(key)
    if cached is not None:
        feedback.log_query(query, cached.get('scope'), cached, cached=True)
        return cached

    scope = (brand or '', model or '', car_stem or '', _acs(allowed_cars))
    t0 = time.monotonic()
    with _LOCK:
        # another thread may have populated it while we waited for the lock
        cached = _cache_get(key)
        if cached is not None:
            return cached
        # embed once (MPS not thread-safe -> under the lock), then try the
        # semantic cache before doing the full retrieval.
        qvec = None
        try:
            qvec = retrieve.embed_query(query)
        except Exception:
            qvec = None
        sem = _sem_cache_get(qvec, scope)
        if sem is not None:
            _cache_put(key, sem)
            feedback.log_query(query, sem.get('scope'), sem, cached=True)
            return sem
        result = retrieve.assist(query, brand=brand, model=model, car_stem=car_stem,
                                 k=k, qvec=qvec, allowed_cars=allowed_cars)
        if config.RERANK and result.get('hits'):
            try:
                _rerank(query, result)
            except Exception:
                pass
        _cache_put(key, result)
        _sem_cache_put(qvec, scope, result)

    latency_ms = (time.monotonic() - t0) * 1000.0
    feedback.log_query(query, result.get('scope'), result, cached=False,
                       latency_ms=latency_ms)
    return result


def diagnose(query, brand=None, model=None, car_stem=None, k=None, allowed_cars=None):
    """Cached, thread-safe diagnostic rule engine. Same lock as assist (MPS/torch
    is not thread-safe; embedding the query is the only GPU step). Returns the
    structured diagnosis from diag.diagnose.

    The engine is inherently single-car (a car-less query resolves no sidecar and
    returns only an ``available_cars`` name hint). When ``allowed_cars`` is given,
    that hint is filtered to the caller's own vehicles so the fleet roster is not
    disclosed. ``allowed_cars`` is part of the cache identity for the same reason
    as in ``assist``."""
    from . import diag
    key = _key(query, brand, model, car_stem, allowed_cars)
    item = _DIAG_CACHE.get(key)
    if item and item[0] >= time.monotonic():
        _DIAG_CACHE.move_to_end(key)
        return item[1]

    with _LOCK:
        item = _DIAG_CACHE.get(key)
        if item and item[0] >= time.monotonic():
            _DIAG_CACHE.move_to_end(key)
            return item[1]
        result = diag.diagnose(query, brand=brand, model=model, car_stem=car_stem,
                               k=k, allowed_cars=allowed_cars)
        if allowed_cars is not None and isinstance(result, dict) and 'available_cars' in result:
            result = dict(result)
            result['available_cars'] = [c for c in result['available_cars']
                                        if c in allowed_cars]
        _DIAG_CACHE[key] = (time.monotonic() + config.DIAG_CACHE_TTL, result)
        _DIAG_CACHE.move_to_end(key)
        while len(_DIAG_CACHE) > config.CACHE_MAX:
            _DIAG_CACHE.popitem(last=False)
    return result


def search(query, brand=None, model=None, car_stem=None, limit=30, allowed_cars=None):
    """Cross-lingual site search, scoped to one car. Rides the same retriever the
    assistant uses (so a Persian query hits the English manual), then maps each
    hit down to the lightweight navigation shape the search UI consumes and
    keeps only results that actually occur in the requested car.

    Cached separately from assist() with `limit` in the key — the assistant calls
    with an adaptive k, so a shared key would let one path serve the other's
    truncated result set. Raises FileNotFoundError (no index) so the view can
    fall back to keyword search."""
    if not (query or '').strip():
        return []
    key = _key(query, brand, model, car_stem, allowed_cars) + (limit,)
    item = _SEARCH_CACHE.get(key)
    if item and item[0] >= time.monotonic():
        _SEARCH_CACHE.move_to_end(key)
        return item[1]

    with _LOCK:
        item = _SEARCH_CACHE.get(key)
        if item and item[0] >= time.monotonic():
            _SEARCH_CACHE.move_to_end(key)
            return item[1]
        # retrieve.assist checks the index exists (raising FileNotFoundError to
        # trigger the view's LIKE fallback) BEFORE embedding, so we let it embed
        # internally rather than loading the model on the fallback path.
        # Over-fetch before the per-car filter below. Asking for exactly `limit`
        # and then discarding another car's hits made the list collapse: measured
        # over 81 Persian queries at limit=30, the median result count was 7 and
        # 99% came back short. `related` and `text` are switched off because the
        # navigation shape below uses neither -- that is what makes the deeper
        # fetch cheap rather than three times the work.
        depth = min(limit * config.SEARCH_OVERFETCH, config.SEARCH_MAX_DEPTH)
        res = retrieve.assist(query, brand=brand, model=model, car_stem=car_stem,
                              k=depth, allowed_cars=allowed_cars,
                              expand=False, with_text=False, scope_fts=True)
        out = []
        # Corpus-boundary filter. The retriever already decides a query is
        # out-of-domain (grounded=False) but search ignored that verdict, so
        # "ssd" -- absent from all 301,369 pages -- returned five nearest
        # neighbours at similarity ~0.51, and so did outright gibberish.
        #
        # A result-level floor would be wrong: "brake pad" is a good query whose
        # top hit scores 0.0 on the vector side because the keyword side carried
        # it. So the test is per hit, across both signals: a result must have
        # real vector similarity OR a genuine keyword match. Junk has neither.
        weak = (not res.get('grounded')) and \
            (res.get('top_similarity') or 0.0) < config.SEARCH_SIM_FLOOR
        for h in res.get('hits', []):
            if weak:
                ex = h.get('explain') or {}
                has_kw = (ex.get('bm25') or 0.0) > 0.0
                if not has_kw and (h.get('similarity') or 0.0) < config.SEARCH_SIM_FLOOR:
                    continue
            # per-car search: drop hits whose chosen occurrence is another car's
            # (deduped shared content still surfaces — its occurrence in THIS car
            # is the one _pick_occurrence selected when car_stem was passed).
            if car_stem and h.get('car_stem') != car_stem:
                continue
            out.append({
                'title': h.get('title'),
                'segments': h.get('segments') or [],
                'path': h.get('title_path'),
                'app_url': h.get('app_url'),
                'node_type': None,
                'is_leaf': True,
                'similarity': h.get('similarity'),
                'matched_via': h.get('matched_via'),
            })
        out = out[:limit]
        _SEARCH_CACHE[key] = (time.monotonic() + config.CACHE_TTL, out)
        _SEARCH_CACHE.move_to_end(key)
        while len(_SEARCH_CACHE) > config.CACHE_MAX:
            _SEARCH_CACHE.popitem(last=False)
    return out


# --- optional cross-encoder reranker (server-grade precision) ----------------
def _get_reranker():
    global _RERANKER
    if _RERANKER is None:
        import torch
        from sentence_transformers import CrossEncoder
        device = 'mps' if torch.backends.mps.is_available() else 'cpu'
        _RERANKER = CrossEncoder(config.RERANK_MODEL, device=device, max_length=512)
    return _RERANKER


def _rerank(query, result):
    hits = result['hits']
    cand = hits[:config.RERANK_CANDIDATES]
    pairs = [(query, f"{h.get('title') or ''}\n{(h.get('text') or '')[:800]}") for h in cand]
    scores = _get_reranker().predict(pairs)
    for h, s in zip(cand, scores):
        h['rerank'] = float(s)
    cand.sort(key=lambda h: h.get('rerank', 0.0), reverse=True)
    result['hits'] = cand + hits[config.RERANK_CANDIDATES:]
    result['reranked'] = True
