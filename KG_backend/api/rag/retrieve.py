"""Stage 4 (query time): hybrid retrieval + graph expansion over the unified,
deduplicated index.

Pipeline for a user question:
  1. embed the query once (multilingual -> a Persian question hits English data);
  2. int8 vector kNN + FTS keyword search over all chunks, fused with RRF and
     aggregated to the blob level;
  3. boost blobs that occur in the page's vehicle / model / brand context and
     pick the occurrence to cite from that context;
  4. expand each top blob through the graph (labor_time / crosslink / semantic)
     and gather exact "same procedure in other vehicles" corroboration from the
     blob's other occurrences;
  5. return structured context + citations (real in-app URLs).

Everything here only READS the index. No LLM, no external service.
"""
from urllib.parse import quote

from . import config, store, embed, glossary, scoring, feedback


def _fts_match(query):
    """Safe FTS5 MATCH string: keep alphanumeric tokens (len>=2), OR them."""
    toks = []
    for raw in query.replace('"', ' ').split():
        t = ''.join(ch for ch in raw if ch.isalnum())
        if len(t) >= 2:
            toks.append(t)
    return ' OR '.join(toks) if toks else None


def _app_url(occ):
    """In-app navigation URL, mirroring the frontend's buildNodeHref:
    /{brand}/{year}/{car_stem}/{seg}/{seg}... -- one segment per breadcrumb
    level below the vehicle root (which is dropped, matching car_view)."""
    segs = [s for s in (occ['title_path'] or '').split(' › ') if s][1:]
    year = occ['year'] if occ['year'] is not None else ''
    base = f"/{quote(occ['brand'] or '')}/{year}/{quote(occ['car_stem'])}"
    if segs:
        base += '/' + '/'.join(quote(s) for s in segs)
    return base, segs


def _occurrences(index, blob_id):
    return index.execute(
        "SELECT car_stem, brand, model, variant, year, title, title_path, "
        "system_tags, href FROM occurrences WHERE blob_id=?", (blob_id,)
    ).fetchall()


def _occurrences_bulk(index, blob_ids):
    """All occurrences for a set of blobs in ONE query -> {blob_id: [rows]}.

    Replaces a per-blob SELECT in the ranking loop (dozens of round-trips for one
    request collapse to a single IN-scan). `ORDER BY blob_id, occ_id` reproduces
    the per-blob query's natural occ_id order, so _pick_occurrence chooses the
    same occurrence as before — behaviour is identical, only faster."""
    out = {}
    ids = list(blob_ids)
    for i in range(0, len(ids), 900):          # stay under SQLite's variable cap
        chunk = ids[i:i + 900]
        ph = ','.join('?' * len(chunk))
        rows = index.execute(
            "SELECT blob_id, car_stem, brand, model, variant, year, title, "
            f"title_path, system_tags, href FROM occurrences WHERE blob_id IN ({ph}) "
            "ORDER BY blob_id, occ_id", tuple(chunk)).fetchall()
        for r in rows:
            out.setdefault(r['blob_id'], []).append(r)
    return out


def _car_indexed(index, car_stem):
    """True if this exact vehicle has any content in the unified index. Tested
    against the `occurrences` table (index-backed by idx_occ_car, so O(1)) —
    that's the authoritative "what can actually be served for this car", and a
    car with zero occurrences cannot ground an answer no matter what the query
    is. Used to short-circuit before the expensive vector/keyword scan."""
    return index.execute(
        "SELECT 1 FROM occurrences WHERE car_stem=? LIMIT 1", (car_stem,)
    ).fetchone() is not None


def _no_scope_result(query, brand, model, car_stem, kind, reason):
    """Honest empty answer when the pinned vehicle isn't in the index at all —
    returned instead of silently citing a DIFFERENT car's manual, which for
    repair data (torque specs, procedures) would be actively unsafe. `reason`
    lets the chat layer phrase it precisely ("this vehicle isn't loaded yet")
    rather than a generic no-answer."""
    return {'query': query,
            'scope': {'brand': brand, 'model': model, 'car_stem': car_stem},
            'count': 0, 'hits': [], 'kind': kind,
            'grounded': False, 'top_similarity': 0.0,
            'car_indexed': False, 'out_of_scope': reason,
            'confidence_band': scoring.confidence_band(0.0, 0.0, 0.0)}


def _pick_occurrence(occs, brand, model, car_stem):
    """Choose which occurrence of a blob to cite, preferring the page context."""
    if car_stem:
        for o in occs:
            if o['car_stem'] == car_stem:
                return o, config.BOOST_CAR
    if model:
        for o in occs:
            if (o['model'] or '').lower() == model.lower():
                return o, config.BOOST_MODEL
    if brand:
        for o in occs:
            if (o['brand'] or '').lower() == brand.lower():
                return o, config.BOOST_BRAND
    return occs[0], 1.0


def _blob_text(index, blob_id, max_chars=3000):
    row = index.execute("SELECT text FROM blobs WHERE blob_id=?", (blob_id,)).fetchone()
    return (row['text'] or '')[:max_chars] if row else ''


def embed_query(query):
    """Embed a user query exactly as assist() would (glossary-expanded), so the
    service layer can embed ONCE and reuse the vector for the semantic cache and
    the retrieval call. Returns a unit vector (numpy array)."""
    eng_terms, _ = glossary.expand(query)
    embed_q = f"{query} {eng_terms}".strip() if eng_terms else query
    return embed.encode([embed_q], is_query=True)[0]


def _centrality_map(index, blob_ids):
    """One grouped query: blob_id -> soft-normalised graph degree in [0,1).
    A blob that is a hub of labor/crosslink/semantic edges is more canonical."""
    if not blob_ids:
        return {}
    ph = ','.join('?' * len(blob_ids))
    rows = index.execute(
        f"SELECT src_blob, COUNT(*) AS deg FROM edges WHERE src_blob IN ({ph}) "
        f"GROUP BY src_blob", tuple(blob_ids)).fetchall()
    c = config.CENTRALITY_C
    return {r['src_blob']: r['deg'] / (r['deg'] + c) for r in rows}


def _matched_via(kind, sim, bm25_norm, vehicle_boost, pinned=False):
    if pinned:
        return 'expert_verified'
    if kind == 'code':
        return 'exact_code'
    if vehicle_boost > 1.0 and sim >= config.CONF_LOW_SIM:
        return 'vehicle'
    return 'keyword' if bm25_norm >= sim else 'semantic'


def assist(query, brand=None, model=None, car_stem=None, k=None, qvec=None):
    if not config.INDEX_DB.exists():
        raise FileNotFoundError(str(config.INDEX_DB))
    # Cached, process-wide read connection (no per-request connect + vec load).
    index = store.get_index_ro()
    # the served vectors are model/dimension-specific: refuse to embed the
    # query with a different model than the one the index was built with.
    built = index.execute("SELECT v FROM meta WHERE k='embed_model'").fetchone()
    if built and built[0] != config.EMBED_MODEL:
        raise RuntimeError(
            f"index built with '{built[0]}' but server RAG_EMBED_MODEL is "
            f"'{config.EMBED_MODEL}'. Start the server with the matching model.")
    # Persian -> English term expansion: a Persian query is augmented with
    # its English service terms so it matches the English manual data on BOTH
    # the vector and keyword sides (e.g. "روغن ترمز" also searches "brake fluid").
    eng_terms, _ = glossary.expand(query)
    embed_q = f"{query} {eng_terms}".strip() if eng_terms else query
    # query-adaptive fusion: a DTC code leans on keywords, a Persian
    # sentence on the dense side (see scoring.classify_query).
    cls = scoring.classify_query(query, eng_terms)
    wv, wf = cls['weights']['vec'], cls['weights']['fts']
    # scope-aware retrieval: on a vehicle/model/brand page, over-fetch candidates
    # so the car's own pages survive the global top-K (the penalty + boosts then
    # order them). Unscoped (site-wide) queries keep the cheaper default depth.
    scoped = bool(car_stem or model or brand)
    vec_k = config.SCOPED_VEC_K if scoped else config.RETRIEVE_VEC_K
    fts_k = config.SCOPED_FTS_K if scoped else config.RETRIEVE_FTS_K
    # Hard vehicle-scope gate (part 1): if the caller pinned an exact car that
    # has no content in the index at all, a global search's nearest neighbours
    # would necessarily be OTHER vehicles. Refuse honestly instead of citing
    # them — and skip the vector/keyword scan entirely (a real saving for the
    # many catalog cars not yet embedded).
    if car_stem and not _car_indexed(index, car_stem):
        return _no_scope_result(query, brand, model, car_stem, cls['kind'],
                                'car_not_indexed')
    # reuse a precomputed embedding (semantic cache) or embed once now
    if qvec is None:
        qvec = embed.encode([embed_q], is_query=True)[0]
    qlist = qvec.tolist() if hasattr(qvec, 'tolist') else list(qvec)
    qblob = store.pack_f32(qlist)
    fts_query = _fts_match(f"{query} {eng_terms}" if eng_terms else query)

    # 1) page-level candidates (vector + keyword), fused with WEIGHTED RRF
    blob_score = {}     # blob_id -> {'rrf','sim','bm25'}

    def bump(blob_id, rank, w, sim=None, bm25=None):
        s = blob_score.setdefault(blob_id, {'rrf': 0.0, 'sim': 0.0, 'bm25': None})
        s['rrf'] += w / (config.RRF_K + rank + 1)
        if sim is not None and sim > s['sim']:
            s['sim'] = sim
        if bm25 is not None and (s['bm25'] is None or bm25 < s['bm25']):
            s['bm25'] = bm25     # FTS5 bm25(): more negative == better

    vec = index.execute(
        "SELECT rowid AS bid, distance AS dist FROM vec_blobs "
        "WHERE embedding MATCH vec_quantize_int8(vec_f32(?),'unit') AND k=? "
        "ORDER BY distance", (qblob, vec_k)).fetchall()
    for rank, r in enumerate(vec):
        bump(r['bid'], rank, wv, sim=1.0 - float(r['dist']))

    if fts_query:
        try:
            fts = index.execute(
                "SELECT rowid AS bid, bm25(blobs_fts) AS bm FROM blobs_fts "
                "WHERE blobs_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, fts_k)).fetchall()
            for rank, r in enumerate(fts):
                bump(r['bid'], rank, wf, bm25=float(r['bm']))
        except Exception:
            pass

    if not blob_score:
        return {'query': query,
                'scope': {'brand': brand, 'model': model, 'car_stem': car_stem},
                'count': 0, 'hits': [], 'kind': cls['kind'],
                'grounded': False,
                'confidence_band': scoring.confidence_band(0.0, 0.0, 0.0)}

    # normalise RRF and BM25 across the candidate set so calibrate() blends
    # comparable [0,1] signals (BM25 is min==best, so flip the range).
    max_rrf = max(s['rrf'] for s in blob_score.values()) or 1.0
    bm_vals = [s['bm25'] for s in blob_score.values() if s['bm25'] is not None]
    bm_best, bm_worst = (min(bm_vals), max(bm_vals)) if bm_vals else (0.0, 0.0)
    bm_span = (bm_best - bm_worst) or 1.0
    cent = _centrality_map(index, list(blob_score.keys()))
    boost_map = feedback.blob_boost_map()
    occ_map = _occurrences_bulk(index, blob_score.keys())   # one query, not N

    # 2) context boost + boilerplate penalty + feedback boost -> calibrate
    ranked = []
    for bid, s in blob_score.items():
        occs = occ_map.get(bid)
        if not occs:
            continue
        occ, vboost = _pick_occurrence(occs, brand, model, car_stem)
        boiler = config.BOILERPLATE_PENALTY \
            if (occ['title'] or '').strip().lower() in config.BOILERPLATE_TITLES else 1.0
        bm25_norm = ((s['bm25'] - bm_worst) / bm_span) if s['bm25'] is not None else 0.0
        fb = boost_map.get(bid, 1.0)
        # out-of-scope penalty: on a scoped page, a blob that matched NO part of
        # the active scope has vehicle_boost==1.0 (no car/model/brand occurrence);
        # nudge it below in-scope content instead of letting it tie.
        scope_pen = config.SCOPE_PENALTY if (scoped and vboost == 1.0) else 1.0
        signals = {'rrf': s['rrf'] / max_rrf, 'sim': s['sim'], 'bm25': bm25_norm,
                   'centrality': cent.get(bid, 0.0), 'vehicle_boost': vboost,
                   'boilerplate': boiler, 'feedback': fb, 'scope': scope_pen}
        cal = scoring.calibrate(
            signals, w_rrf=config.SCORE_W_RRF, w_sim=config.SCORE_W_SIM,
            w_bm25=config.SCORE_W_BM25, w_cent=config.SCORE_W_CENT)
        cal['explain']['matched_via'] = _matched_via(cls['kind'], s['sim'], bm25_norm, vboost)
        ranked.append((cal['final'], s['sim'], bid, occ, occs, cal['explain']))
    ranked.sort(key=lambda x: x[0], reverse=True)

    # 3) adaptive depth: an easy query (clear top winner + strong match)
    # returns fewer hits and expands fewer graphs; ambiguous ones widen.
    top_final = ranked[0][0] if ranked else 0.0
    second = ranked[1][0] if len(ranked) > 1 else 0.0
    rel_margin = (top_final - second) / top_final if top_final > 0 else 0.0
    top_sim = ranked[0][1] if ranked else 0.0
    easy = rel_margin >= config.MARGIN_EASY and top_sim >= config.EASY_SIM
    k_eff = k or (config.FINAL_K_MIN if easy else config.FINAL_K_MAX)
    expand_n = config.EXPAND_EASY if easy else k_eff

    # 4) expert pinned override: a curated source that matches this query
    # pattern is surfaced at the top, tagged expert_verified.
    pin = feedback.pinned_match(qlist)
    pin_bid = pin['blob_id'] if pin else None

    # For an exact-code query the dense vector barely matches (the keyword
    # side carries it), so confidence is driven by BM25 strength, not sim.
    is_code = cls['kind'] == 'code'

    def _eff_sim(sim, explain):
        return max(sim, explain.get('bm25', 0.0)) if is_code else sim

    # 5) build hits
    hits = []
    for i, (final, sim, bid, occ, occs, explain) in enumerate(ranked[:k_eff]):
        app_url, segs = _app_url(occ)
        related = _expand(index, bid, brand, model, car_stem) if i < expand_n else []
        cross = _cross_vehicle(occ, occs)
        band = scoring.confidence_band(final, config.CONF_HIGH_MARGIN, _eff_sim(sim, explain),
                                       high_sim=config.CONF_HIGH_SIM,
                                       high_margin=config.CONF_HIGH_MARGIN,
                                       low_sim=config.CONF_LOW_SIM)
        hits.append({
            'blob_id': bid,
            'car_stem': occ['car_stem'], 'brand': occ['brand'],
            'model': occ['model'], 'variant': occ['variant'], 'year': occ['year'],
            'title': occ['title'], 'title_path': occ['title_path'],
            'system_tags': occ['system_tags'], 'segments': segs, 'app_url': app_url,
            'score': round(float(final), 5), 'similarity': round(float(sim), 4),
            'matched_via': explain['matched_via'],
            'confidence_band': band['band'], 'confidence_label': band['label_fa'],
            'explain': explain,
            'text': _blob_text(index, bid),
            'related': related, 'cross_vehicle': cross,
        })

    if pin_bid is not None and not any(h['blob_id'] == pin_bid for h in hits):
        ph = _pinned_hit(index, pin, brand, model, car_stem)
        if ph:
            hits.insert(0, ph)

    top_eff = _eff_sim(top_sim, ranked[0][5]) if ranked else 0.0
    top_margin = config.CONF_HIGH_MARGIN if is_code else rel_margin
    # grounding gate: a best match weaker than the floor means the query is
    # out-of-domain — refuse rather than surface a misleading nearest neighbour.
    grounded = len(hits) > 0 and top_eff >= config.GROUND_SIM_FLOOR
    if not grounded:
        overall = scoring.confidence_band(0.0, 0.0, 0.0)   # forced 'low'
    else:
        overall = scoring.confidence_band(top_final, top_margin, top_eff,
                                          high_sim=config.CONF_HIGH_SIM,
                                          high_margin=config.CONF_HIGH_MARGIN,
                                          low_sim=config.CONF_LOW_SIM)
    out = {'query': query,
           'scope': {'brand': brand, 'model': model, 'car_stem': car_stem},
           'count': len(hits), 'hits': hits, 'kind': cls['kind'],
           'grounded': grounded, 'top_similarity': round(float(top_eff), 4),
           'confidence_band': overall, 'adaptive': {'easy': easy, 'k': k_eff}}
    if car_stem:
        # The pinned car IS in the index (part-1 gate passed); flag it so the
        # chat layer can tell "vehicle loaded, just no strong match" apart from
        # "vehicle not loaded at all" (car_indexed=False above).
        out['car_indexed'] = True
    return out


def _pinned_hit(index, pin, brand, model, car_stem):
    """Build a top-of-list hit for an expert-pinned override (by blob_id)."""
    occs = _occurrences(index, pin['blob_id'])
    if not occs:
        return None
    occ, _ = _pick_occurrence(occs, brand, model, car_stem)
    app_url, segs = _app_url(occ)
    return {
        'blob_id': pin['blob_id'],
        'car_stem': occ['car_stem'], 'brand': occ['brand'], 'model': occ['model'],
        'variant': occ['variant'], 'year': occ['year'],
        'title': occ['title'], 'title_path': occ['title_path'],
        'system_tags': occ['system_tags'], 'segments': segs, 'app_url': app_url,
        'score': 1.0, 'similarity': round(float(pin.get('similarity', 1.0)), 4),
        'matched_via': 'expert_verified',
        'confidence_band': 'high', 'confidence_label': scoring._BAND_FA['high'],
        'explain': {'matched_via': 'expert_verified', 'note': pin.get('note') or 'expert-verified'},
        'text': _blob_text(index, pin['blob_id']),
        'related': _expand(index, pin['blob_id'], brand, model, car_stem),
        'cross_vehicle': _cross_vehicle(occ, occs),
    }


# --- graph neighbours (related pages) --------------------------------------
_REL_PRIORITY = {'labor_time': 0, 'crosslink': 1, 'semantic': 2}


def _expand(index, blob_id, brand, model, car_stem):
    edges = index.execute(
        "SELECT dst_blob, relation, weight FROM edges WHERE src_blob=?", (blob_id,)
    ).fetchall()
    edges = sorted(edges, key=lambda e: (_REL_PRIORITY.get(e['relation'], 9), -e['weight']))
    related, seen = [], set()
    for e in edges:
        if e['dst_blob'] in seen or len(related) >= config.GRAPH_EXPAND:
            continue
        seen.add(e['dst_blob'])
        occs = _occurrences(index, e['dst_blob'])
        if not occs:
            continue
        occ, _ = _pick_occurrence(occs, brand, model, car_stem)
        url, _segs = _app_url(occ)
        related.append({
            'title': occ['title'], 'title_path': occ['title_path'],
            'relation': e['relation'], 'app_url': url,
            'snippet': _blob_text(index, e['dst_blob'], max_chars=240),
        })
    return related


# --- exact "same procedure in other vehicles" (other occurrences) ----------
def _cross_vehicle(display_occ, occs):
    out, seen = [], set()
    for o in occs:
        if o['car_stem'] == display_occ['car_stem']:
            continue
        key = (o['model'], o['variant'])
        if key in seen:
            continue
        seen.add(key)
        if (o['model'] or '') == (display_occ['model'] or ''):
            scope = 'same_model'
        elif (o['brand'] or '') == (display_occ['brand'] or ''):
            scope = 'same_brand'
        else:
            scope = 'cross_brand'
        url, _ = _app_url(o)
        out.append({'car_stem': o['car_stem'], 'model': o['model'],
                    'variant': o['variant'], 'scope': scope,
                    'title': o['title'], 'app_url': url})
        if len(out) >= config.CROSS_VEHICLE_MAX:
            break
    # surface same_model first, then same_brand, then cross_brand
    order = {'same_model': 0, 'same_brand': 1, 'cross_brand': 2}
    out.sort(key=lambda c: order.get(c['scope'], 9))
    return out
