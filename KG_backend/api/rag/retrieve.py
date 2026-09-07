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
import re

from urllib.parse import quote

import logging
from collections import OrderedDict

from . import config, store, embed, glossary, scoring, feedback

logger = logging.getLogger(__name__)


def _fts_match(query):
    """Safe FTS5 MATCH string: keep alphanumeric tokens (len>=2), OR them.

    With ``config.FTS_CLEAN`` the string is also filtered, which matters most for
    Persian. A Persian query arrives here as the question plus its glossary
    expansion, so it carries ~9 Persian tokens that match zero pages of an English
    index, plus the occasional English stopword from the expansion. The stopwords
    are the harmful part: "and" occurs on 200,760 of 301,369 pages, so ORing it in
    hands BM25 credit to two-thirds of the corpus.
    """
    toks, seen = [], set()
    for raw in query.replace('"', ' ').split():
        t = ''.join(ch for ch in raw if ch.isalnum())
        if len(t) < 2:
            continue
        if config.FTS_CLEAN:
            low = t.lower()
            if low in config.FTS_STOPWORDS or low in seen:
                continue
            seen.add(low)
        toks.append(t)
    if config.FTS_CLEAN:
        # Tokens that cannot match the English index are dead weight -- but only
        # drop them if something usable is left, so an unexpanded Persian query
        # still behaves exactly as before rather than losing its keyword side.
        usable = [t for t in toks if t.isascii()]
        if usable:
            toks = usable
    return ' OR '.join(toks) if toks else None


def _enc(s):
    """Mirror the frontend's encodeURIComponent (buildNodeHref) EXACTLY: encode
    every reserved char including '/'. Node titles routinely contain a literal
    slash ("A/C", "[03/2022 -        ]"); quote's default safe='/' would leave it
    raw, splitting one breadcrumb title into two URL path segments — a link the
    frontend can never resolve."""
    return quote(s or '', safe='')


# Vehicle-root title_path prefix looks like "Toyota: 2025: 4Runner TRD Pro".
_ROOT_YEAR_RE = re.compile(r'^[^›]*?:\s*((?:19|20)\d{2})\s*:')


def _app_url(occ):
    """In-app navigation URL, mirroring the frontend's buildNodeHref:
    /{brand}/{year}/{car_stem}/{seg}/{seg}... -- one segment per breadcrumb
    level below the vehicle root (which is dropped, matching car_view)."""
    segs = [s for s in (occ['title_path'] or '').split(' › ') if s][1:]
    # Frontend route is /{brand}/{year}/{car_stem}/... — year is a real path
    # segment there, so a missing year must not collapse into an empty segment
    # (`/brand//stem`, a broken link). An occurrence without a year (metadata
    # gap in older builds) falls back to the year embedded in the vehicle-root
    # breadcrumb ("Toyota: 2025: <stem>"), then to the literal 'unknown'
    # (which car_view resolves tolerantly by brand+name).
    year = occ['year']
    if year is None:
        m = _ROOT_YEAR_RE.match(occ['title_path'] or '')
        year = m.group(1) if m else 'unknown'
    base = f"/{_enc(occ['brand'])}/{year}/{_enc(occ['car_stem'])}"
    if segs:
        # In-title '/' -> U+2044 so it survives as one URL path segment
        # (the Next router splits a literal '/'); frontend swaps it back.
        base += '/' + '/'.join(_enc(s.replace('/', '⁄')) for s in segs)
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


def assist(query, brand=None, model=None, car_stem=None, k=None, qvec=None,
           allowed_cars=None, expand=True, with_text=True, scope_fts=False):
    """Retrieve grounded manual excerpts for ``query``.

    ``allowed_cars`` (a set/frozenset of car_stems, or None) hard-restricts which
    vehicles may be CITED. It is the authorization boundary for the car-less
    general assistant: without it, a logged-in user with access to one vehicle
    could receive grounded excerpts from any indexed vehicle. When set, every
    returned hit — including expert-pinned overrides — is cited from an occurrence
    inside the allow-list; blobs with no allowed occurrence are dropped before
    ranking. ``None`` preserves the unrestricted behavior (single-car pages, whose
    access the caller already checked, and internal/eval callers).

    ``expand`` / ``with_text`` let a caller opt out of the two per-hit costs the
    assistant needs but site search does not: relationship-graph expansion and
    the 3 KB page body. Search over-fetches candidates to survive its own
    per-car filter, and paying those costs on discarded hits is pure waste.

    ``scope_fts`` adds a keyword pass restricted to ``car_stem`` itself. The
    global vector/keyword sides rank the whole corpus, so for a single car --
    about 2% of it -- they surface few of that car's pages; this reaches them
    directly instead of fetching five times deeper globally and discarding the
    rest.

    It is OFF by default, and site search is its only caller. Enabling it for the
    assistant was measured (`hybrid_sfts`, n=250 per language) and REJECTED: on
    English nDCG@5 -0.042 and R@10 -0.039, both p<0.001, 66 queries worse against
    21 better; Persian directionally worse on every metric. All ten metrics fell,
    at +50% latency.

    The candidates are additive but the SCORING is not. bm25 is normalised across
    the candidate set, so a larger pool shifts every calibrated score, and scoped
    hits enter with keyword ranks 0..N that can outrank globally better matches.
    R@10 falling shows worse pages displacing good ones inside the top 10, not
    merely reordering them. Deeper recall helps a 30-row search list and hurts a
    5-hit answer: same mechanism, opposite verdicts."""
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
            # bm25() takes per-column weights (text, title, comp). Ordering by
            # the weighted value rather than `rank` also changes WHICH pages are
            # fetched, not just how they score -- a title match now competes.
            fts = index.execute(
                "SELECT rowid AS bid, bm25(blobs_fts, ?, ?, ?) AS bm FROM blobs_fts "
                "WHERE blobs_fts MATCH ? ORDER BY bm LIMIT ?",
                (config.FTS_W_TEXT, config.FTS_W_TITLE, config.FTS_W_COMP,
                 fts_query, fts_k)).fetchall()
            for rank, r in enumerate(fts):
                bump(r['bid'], rank, wf, bm25=float(r['bm']))
        except Exception:
            pass

    # Car-scoped keyword pass: the global cut above ranks all 301,369 blobs, so a
    # single car's pages are mostly below it. Joining occurrences pulls this car's
    # keyword matches in directly. Same weight as the global keyword side -- these
    # are the same signal, just not starved by corpus-wide competition.
    if scope_fts and car_stem and fts_query:
        try:
            # Deep single-table FTS scan, then intersect with this car's blobs in
            # Python. Joining occurrences inside the query instead cost ~3.6s;
            # FTS5 also refuses bm25() whenever the MATCH table is joined.
            own = _car_blob_ids(index, car_stem)
            taken = 0
            for r in index.execute(
                    "SELECT rowid AS bid, bm25(blobs_fts, ?, ?, ?) AS bm "
                    "FROM blobs_fts WHERE blobs_fts MATCH ? ORDER BY bm LIMIT ?",
                    (config.FTS_W_TEXT, config.FTS_W_TITLE, config.FTS_W_COMP,
                     fts_query, config.SCOPE_FTS_SCAN)):
                if r['bid'] in own:
                    bump(r['bid'], taken, wf, bm25=float(r['bm']))
                    taken += 1
                    if taken >= config.SCOPE_FTS_K:
                        break
        except Exception:
            # additive pass: never fail the query over it, but do not hide the
            # failure the way a bare `pass` did.
            logger.warning('scoped FTS pass failed for car_stem=%r', car_stem,
                           exc_info=True)

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
        if allowed_cars is not None:
            # Authorization gate: cite only from vehicles the caller may open.
            occs = [o for o in occs if o['car_stem'] in allowed_cars]
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
        related = _expand(index, bid, brand, model, car_stem,
                          allowed_cars=allowed_cars) if (expand and i < expand_n) else []
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
            'text': _blob_text(index, bid) if with_text else '',
            'related': related, 'cross_vehicle': cross,
        })

    if pin_bid is not None and not any(h['blob_id'] == pin_bid for h in hits):
        ph = _pinned_hit(index, pin, brand, model, car_stem,
                         allowed_cars=allowed_cars)
        # A pin is an expert override, but it must still respect the caller's
        # vehicle allow-list — never surface a pinned excerpt from a car the
        # user cannot open.
        if ph and (allowed_cars is None or ph.get('car_stem') in allowed_cars):
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
        # Hard vehicle-scope gate (part 2): verify the evidence we are about to
        # cite actually belongs to the pinned vehicle, and say so when it does
        # not. Part 1 above only catches a vehicle missing from the index
        # entirely; this catches the commoner and more dangerous case — the
        # vehicle IS indexed, but the component being asked about is not part
        # of it, so the nearest neighbour is another car's page.
        ev = _evidence_scope(index, hits, car_stem)
        if ev:
            out['evidence'] = ev
            if ev['title_absent_from_vehicle']:
                out['out_of_scope'] = 'title_absent_from_vehicle'
    return out


_CAR_BLOBS = OrderedDict()          # car_stem -> frozenset(blob_id), small LRU


def _car_blob_ids(index, car_stem):
    """Every blob this car contains. Cached: the occurrences table has ~6M rows,
    and joining it per query cost more than the scoped pass was worth."""
    hit = _CAR_BLOBS.get(car_stem)
    if hit is not None:
        _CAR_BLOBS.move_to_end(car_stem)
        return hit
    ids = frozenset(r[0] for r in index.execute(
        "SELECT DISTINCT blob_id FROM occurrences WHERE car_stem = ?", (car_stem,)))
    _CAR_BLOBS[car_stem] = ids
    _CAR_BLOBS.move_to_end(car_stem)
    while len(_CAR_BLOBS) > config.CAR_BLOBS_CACHE:
        _CAR_BLOBS.popitem(last=False)
    return ids


def _vehicle_has_title(index, title, car_stem):
    """Does this vehicle have any page carrying ``title``?

    The blob title is the corpus's own name for a component, so this answers
    "is this component documented for this vehicle at all" without parsing the
    user's query — which is what makes it work in Persian as well as English.
    """
    t = (title or '').strip()
    if not t or not car_stem:
        return None
    row = index.execute(
        "SELECT 1 FROM occurrences o JOIN blobs b ON b.blob_id = o.blob_id "
        "WHERE o.car_stem = ? AND b.title = ? LIMIT 1", (car_stem, t)).fetchone()
    return bool(row)


def _evidence_scope(index, hits, car_stem):
    """Vehicle-scoped evidence verification.

    Standard RAG cites whatever ranks highest. Because deduplication makes one
    stored page addressable from many vehicles, a high-ranking page may belong
    to a DIFFERENT vehicle than the one the technician has open — and for repair
    data (torque values, procedures) presenting that silently is unsafe.

    Returns a dict describing where the evidence actually came from:
      in_vehicle     - the top hit is a page of the scoped vehicle
      cross_vehicle  - the top hit belongs to another vehicle; ``title_in_vehicle``
                       says whether the scoped vehicle has ANY page carrying that
                       same title. False is strong evidence the component is not
                       documented for this vehicle, but it is a statement about
                       titles, not a proof of absence — the rendered warning is
                       worded to claim only what was checked.
    """
    if not car_stem or not hits:
        return None
    top = hits[0]
    in_vehicle = top.get('car_stem') == car_stem
    n_in = sum(1 for h in hits if h.get('car_stem') == car_stem)
    present = None if in_vehicle else _vehicle_has_title(index, top.get('title'), car_stem)
    return {
        'scope': 'in_vehicle' if in_vehicle else 'cross_vehicle',
        'source_car_stem': top.get('car_stem'),
        'title_in_vehicle': present,
        'hits_in_vehicle': n_in,
        'hits_total': len(hits),
        # the loud case: evidence is from another vehicle AND this vehicle has no
        # page of that name.
        'title_absent_from_vehicle': (not in_vehicle) and present is False,
    }


def _pinned_hit(index, pin, brand, model, car_stem, allowed_cars=None):
    """Build a top-of-list hit for an expert-pinned override (by blob_id)."""
    occs = _occurrences(index, pin['blob_id'])
    if allowed_cars is not None:
        occs = [o for o in occs if o['car_stem'] in allowed_cars]
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
        'related': _expand(index, pin['blob_id'], brand, model, car_stem,
                           allowed_cars=allowed_cars),
        'cross_vehicle': _cross_vehicle(occ, occs),
    }


# --- graph neighbours (related pages) --------------------------------------
_REL_PRIORITY = {'labor_time': 0, 'crosslink': 1, 'semantic': 2}


def _expand(index, blob_id, brand, model, car_stem, allowed_cars=None):
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
        if allowed_cars is not None:
            # Same authorization boundary as the main hit list: never emit a
            # related-page link that cites a vehicle the caller cannot open.
            occs = [o for o in occs if o['car_stem'] in allowed_cars]
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
