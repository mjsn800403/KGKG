"""Query-time DIAGNOSTIC RULE ENGINE (deterministic; no LLM in the logic).

Given a car and a customer input (a Persian symptom OR a DTC code), this maps it
to a ranked, conditional diagnostic chain grounded entirely in the manual:

  intent = 'dtc'      -> direct DTC lookup: inheritance scope, the ordered
                          diagnostic aspects (Description -> Symptom/Circuit Tests
                          -> Procedure), sibling DTCs in the same component
                          (horizontal), the repair's labor time (via the unified
                          index's labor_time edges) and the same code in other
                          vehicles.
  intent = 'symptom'  -> Persian symptom is glossary-expanded + embedded, matched
                          against this car's symptom + DTC indexes, then walked
                          through symptom_link to candidate DTCs ("if symptom X ->
                          maybe Y, maybe Z"), each carrying its own step chain.

Vertical chaining = climbing/scoping the inheritance tree (system/subsystem/
component); horizontal chaining = sibling DTCs + labor/crosslink edges. The whole
thing reads two small files (the per-car sidecar + the unified index) and never
calls an external service.
"""
import re

from . import config, store, embed, glossary, scoring, feedback
from .diag_build import open_diag, norm_code


# --- matched_via / band helpers (parity with the assist evidence panel) -----
def _band(sim, margin=None):
    """Confidence band for a diagnostic candidate, reusing the same thresholds
    the assist path uses so the evidence panel reads consistently."""
    m = config.CONF_HIGH_MARGIN if margin is None else margin
    return scoring.confidence_band(sim, m, sim, high_sim=config.CONF_HIGH_SIM,
                                   high_margin=config.CONF_HIGH_MARGIN,
                                   low_sim=config.CONF_LOW_SIM)


# how a candidate was found -> the evidence panel's matched_via vocabulary
_SOURCE_VIA = {'symptom_table': 'diagnostic', 'direct': 'semantic',
               'related': 'diagnostic', 'exact_code': 'exact_code'}


# --- car resolution --------------------------------------------------------
def _resolve_stem(brand, model, car_stem):
    """The frontend passes the car_name (== on-disk DB stem) as `model` and/or
    `car`. Pick the first that has a built sidecar."""
    for cand in (car_stem, model):
        if cand and config.diag_db_path(cand).exists():
            return cand
    return None


def available_cars():
    if not config.DIAG_DIR.exists():
        return []
    return sorted(p.name[:-len('.diag.db')] for p in config.DIAG_DIR.glob('*.diag.db'))


# --- unified-index bridges (labor time + cross-vehicle) --------------------
def _blob_for_node(index, car_stem, node_id):
    row = index.execute(
        "SELECT blob_id FROM occurrences WHERE car_stem=? AND node_id=? LIMIT 1",
        (car_stem, node_id)).fetchone()
    return row['blob_id'] if row else None


def _labor_for_node(index, car_stem, node_id, allowed_cars=None):
    """Labor-time page(s) linked to a procedure node, via labor_time edges."""
    bid = _blob_for_node(index, car_stem, node_id)
    if bid is None:
        return []
    edges = index.execute(
        "SELECT dst_blob, weight FROM edges WHERE src_blob=? AND relation='labor_time' "
        "ORDER BY weight DESC LIMIT 3", (bid,)).fetchall()
    out = []
    for e in edges:
        occs = index.execute(
            "SELECT car_stem, brand, model, variant, year, title, title_path "
            "FROM occurrences WHERE blob_id=? ORDER BY (car_stem=?) DESC",
            (e['dst_blob'], car_stem)).fetchall()
        # Cite the pinned car's own occurrence first; otherwise only a vehicle
        # the caller may open (a labor link to a forbidden car dead-ends on the
        # access-denied page).
        occ = next((o for o in occs
                    if o['car_stem'] == car_stem or allowed_cars is None
                    or o['car_stem'] in allowed_cars), None)
        if occ:
            from .retrieve import _app_url
            url, _ = _app_url(occ)
            out.append({'title': occ['title'], 'app_url': url})
    return out


def _cross_vehicle_for_node(index, car_stem, node_id, allowed_cars=None):
    bid = _blob_for_node(index, car_stem, node_id)
    if bid is None:
        return []
    occs = index.execute(
        "SELECT car_stem, brand, model, variant, year, title, title_path "
        "FROM occurrences WHERE blob_id=? AND car_stem!=?", (bid, car_stem)).fetchall()
    from .retrieve import _app_url
    out, seen = [], set()
    for o in occs:
        if allowed_cars is not None and o['car_stem'] not in allowed_cars:
            continue          # never surface content of vehicles the user lacks
        key = (o['model'], o['variant'])
        if key in seen:
            continue
        seen.add(key)
        url, _ = _app_url(o)
        out.append({'car_stem': o['car_stem'], 'model': o['model'],
                    'variant': o['variant'], 'title': o['title'], 'app_url': url})
        if len(out) >= config.CROSS_VEHICLE_MAX:
            break
    return out


# --- representative blob for a DTC (bridges to the unified index) -----------
def _repr_blob(diag, index, car_stem, code):
    """The unified-index blob that best represents a DTC for this car — its
    Description leaf (a content page), falling back to the first step. Used to
    apply the closed-loop feedback boost (keyed by blob_id) and to let a 👍/👎 on
    a diagnosis target a concrete source, exactly like the assist path."""
    if index is None:
        return None
    steps = diag.execute(
        "SELECT node_id, aspect FROM dtc_step WHERE code=? ORDER BY step_order",
        (code,)).fetchall()
    if not steps:
        return None
    desc = next((s['node_id'] for s in steps
                 if 'description' in (s['aspect'] or '').lower()), None)
    node_id = desc if desc is not None else steps[0]['node_id']
    try:
        return _blob_for_node(index, car_stem, node_id)
    except Exception:
        return None


# --- assembling a candidate DTC -------------------------------------------
def _dtc_payload(diag, index, car_stem, row, reason=None, confidence=None,
                 blob_id=None, matched_via=None, band=None, explain=None,
                 allowed_cars=None):
    code = row['code']
    steps = diag.execute(
        "SELECT aspect, app_url, node_id FROM dtc_step WHERE code=? "
        "ORDER BY step_order LIMIT ?", (code, config.DIAG_STEPS_MAX)).fetchall()
    procedure, labor, desc_node = None, [], None
    for s in steps:
        al = (s['aspect'] or '').lower()
        if desc_node is None and 'description' in al:
            desc_node = s['node_id']
        if 'procedure' in al and procedure is None:
            procedure = {'title': s['aspect'], 'app_url': s['app_url']}
            if index is not None:
                try:
                    labor = _labor_for_node(index, car_stem, s['node_id'],
                                            allowed_cars=allowed_cars)
                except Exception:
                    labor = []
    if desc_node is None and steps:
        desc_node = steps[0]['node_id']
    siblings = [r['code'] for r in diag.execute(
        "SELECT code FROM dtc WHERE component=? AND code!=? LIMIT 6",
        (row['component'], code))]
    cross = []
    # cross-vehicle uses a CONTENT leaf (the Description), not the DTC folder node
    # (folders carry no content, so they are absent from the unified occurrences).
    if index is not None and desc_node is not None:
        try:
            cross = _cross_vehicle_for_node(index, car_stem, desc_node,
                                            allowed_cars=allowed_cars)
        except Exception:
            cross = []
    # representative blob: lets a verdict on this diagnosis feed the same
    # blob-keyed feedback loop the assist path uses (closes the HITL gap).
    if blob_id is None and index is not None and desc_node is not None:
        try:
            blob_id = _blob_for_node(index, car_stem, desc_node)
        except Exception:
            blob_id = None
    band = band or (_band(float(confidence)) if confidence is not None else None)
    return {
        'code': code, 'name': row['name'],
        'inheritance_path': ' › '.join(x for x in
                                       (row['system'], row['subsystem'], row['component']) if x),
        'system': row['system'], 'subsystem': row['subsystem'], 'component': row['component'],
        'trigger': row['trigger_text'], 'description': (row['desc_text'] or '')[:700],
        'app_url': row['app_url'], 'blob_id': blob_id,
        'has_symptom_test': bool(row['has_symptom_test']),
        'has_circuit_test': bool(row['has_circuit_test']),
        'steps': [{'aspect': s['aspect'], 'app_url': s['app_url']} for s in steps],
        'procedure': procedure, 'labor_time': labor,
        'sibling_dtcs': siblings, 'cross_vehicle': cross,
        'reason': reason, 'confidence': round(float(confidence), 3) if confidence is not None else None,
        'matched_via': matched_via,
        'confidence_band': band['band'] if band else None,
        'confidence_label': band['label_fa'] if band else None,
        'explain': explain,
    }


def _fts_match(query):
    toks = []
    for raw in (query or '').replace('"', ' ').split():
        t = ''.join(ch for ch in raw if ch.isalnum())
        if len(t) >= 2:
            toks.append(t)
    return ' OR '.join(toks) if toks else None


# --- main entry ------------------------------------------------------------
def diagnose(query, brand=None, model=None, car_stem=None, k=None,
             allowed_cars=None):
    stem = _resolve_stem(brand, model, car_stem)
    if stem is None:
        return {'query': query, 'intent': 'unknown', 'error': 'no_diag_index',
                'available_cars': available_cars(), 'candidates': [], 'symptoms': []}
    path = config.diag_db_path(stem)
    diag = open_diag(path, write=False)
    index = None
    try:
        built = diag.execute("SELECT v FROM meta WHERE k='embed_model'").fetchone()
        if built and built[0] != config.EMBED_MODEL:
            raise RuntimeError(
                f"diag index for '{stem}' built with '{built[0]}' but server "
                f"RAG_EMBED_MODEL is '{config.EMBED_MODEL}'.")
        try:
            index = store.open_index(write=False)
        except Exception:
            index = None

        code, known = _detect_code(query, diag)
        if code is not None:
            return _diagnose_by_code(diag, index, stem, query, code, known,
                                     allowed_cars=allowed_cars)
        if _looks_like_repair(query):
            # a "how do I replace / torque / capacity" question is NOT a fault to
            # diagnose -> signal the proxy to fall back to the general repair RAG.
            return {'query': query, 'intent': 'repair', 'car_stem': stem,
                    'candidates': [], 'procedures': [], 'symptoms': []}
        return _diagnose_by_symptom(diag, index, stem, query, k,
                                    allowed_cars=allowed_cars)
    finally:
        diag.close()
        if index is not None:
            index.close()


# A "how-to / spec" question is a repair task (-> general RAG), not a fault to
# diagnose. A symptom marker overrides (e.g. "صدا می‌دهد، چطور درستش کنم" is still
# a fault). Markers are matched on the glossary-normalised query.
_REPAIR_MARKERS = (
    'چطور', 'چگونه', 'نحوه', 'تعویض', 'عوض کردن', 'عوض کنم', 'باز کردن', 'بستن',
    'نصب', 'گشتاور', 'مشخصات فنی', 'ظرفیت', 'سرویس', 'تنظیم', 'هواگیری', 'اولاب',
    'how to', 'replace', 'remove', 'install', 'torque', 'capacity', 'procedure',
    'specification', 'overhaul', 'bleed', 'adjust', 'how do i', 'how much',
)
_SYMPTOM_MARKERS = (
    'صدا', 'لرزش', 'نمیشه', 'نمی شود', 'نمیشود', 'کار نمی', 'روشن نمی', 'خاموش می',
    'چراغ چک', 'چراغ هشدار', 'هشدار', 'نشت', 'نشتی', 'بو می', 'دود', 'گرم می',
    'تک می', 'ریپ', 'لگد', 'کشش ندار', 'جواب نمی', 'قطع می', 'warning light',
    'noise', 'leak', 'rough', 'misfire', 'won t', 'wont', 'does not', 'doesn t',
)


def _looks_like_repair(query):
    n = glossary._norm_fa(query)
    if any(s in n for s in _SYMPTOM_MARKERS):
        return False
    return any(r in n for r in _REPAIR_MARKERS)


def _detect_code(query, diag):
    """Return (code, known). `known` is True if the code exists in this car."""
    for m in config.DTC_CODE_RE.finditer(query or ''):
        key = norm_code(m.group(1))
        row = diag.execute("SELECT code FROM dtc WHERE code=? OR code LIKE ? LIMIT 1",
                           (key, key + '-%')).fetchone()
        if row:
            return row['code'], True
        if re.match(r'^[A-Z]\d{4}$', key):     # code-shaped but not in this car
            return key, False
    return None, False


def _diagnose_by_code(diag, index, stem, query, code, known, allowed_cars=None):
    row = diag.execute("SELECT * FROM dtc WHERE code=?", (code,)).fetchone()
    if row is None:
        return {'query': query, 'intent': 'dtc', 'car_stem': stem, 'code': code,
                'known': False, 'grounded': False, 'top_similarity': 0.0,
                'confidence_band': _band(0.0), 'candidates': [], 'symptoms': [],
                'message': f'DTC {code} not found in this vehicle.'}
    # an exact code hit is fully grounded by definition (it IS in this car's data).
    payload = _dtc_payload(diag, index, stem, row, reason='direct_code',
                           confidence=1.0, matched_via='exact_code',
                           band=_band(1.0),
                           explain={'matched_via': 'exact_code', 'source': 'direct_code'},
                           allowed_cars=allowed_cars)
    return {'query': query, 'intent': 'dtc', 'car_stem': stem, 'known': True,
            'grounded': True, 'top_similarity': 1.0, 'confidence_band': _band(1.0),
            'candidates': [payload], 'symptoms': []}


def _diagnose_by_symptom(diag, index, stem, query, k, allowed_cars=None):
    k = k or config.DIAG_FINAL_CANDIDATES
    eng_terms, _ = glossary.expand(query)
    embed_q = f"{query} {eng_terms}".strip() if eng_terms else query
    qvec = embed.encode([embed_q], is_query=True)[0]
    qblob = store.pack_f32(qvec.tolist())
    fts_q = _fts_match(f"{query} {eng_terms}" if eng_terms else query)
    # query-adaptive fusion: the SAME router the assist path uses (scoring.
    # classify_query) — a Persian symptom sentence leans on the dense side, latin
    # keywords/codes on the keyword side. Replaces the old unweighted RRF.
    cls = scoring.classify_query(query, eng_terms)
    wv, wf = cls['weights']['vec'], cls['weights']['fts']

    # 1) candidate symptoms (vector + keyword, WEIGHTED RRF-fused)
    sym_score = {}

    def bump(d, key, rank, w, sim=None):
        s = d.setdefault(key, {'rrf': 0.0, 'sim': 0.0})
        s['rrf'] += w / (config.RRF_K + rank + 1)
        if sim is not None and sim > s['sim']:
            s['sim'] = sim

    for rank, r in enumerate(diag.execute(
            "SELECT rowid AS sid, distance AS dist FROM sym_vec "
            "WHERE embedding MATCH vec_quantize_int8(vec_f32(?),'unit') AND k=? "
            "ORDER BY distance", (qblob, config.DIAG_SYMPTOM_K))):
        bump(sym_score, r['sid'], rank, wv, sim=1.0 - float(r['dist']))
    if fts_q:
        try:
            for rank, r in enumerate(diag.execute(
                    "SELECT ref FROM diag_fts WHERE diag_fts MATCH ? AND kind='symptom' "
                    "ORDER BY rank LIMIT ?", (fts_q, config.DIAG_SYMPTOM_K))):
                bump(sym_score, int(r['ref']), rank, wf)
        except Exception:
            pass

    # 2) candidate DTCs matched DIRECTLY from the query (dense side)
    dtc_score = {}
    for rank, r in enumerate(diag.execute(
            "SELECT rowid AS did, distance AS dist FROM dtc_vec "
            "WHERE embedding MATCH vec_quantize_int8(vec_f32(?),'unit') AND k=? "
            "ORDER BY distance", (qblob, config.DIAG_DTC_K))):
        bump(dtc_score, r['did'], rank, wv, sim=1.0 - float(r['dist']))

    # 3) Build candidates with a clear PRECEDENCE of evidence (the manufacturer's
    #    own method is symptom -> Problem Symptoms Table -> suspected area / "How
    #    to Proceed", NOT a fuzzy symptom->DTC name match), so:
    #      table  = the symptom table's own <a> link to a DTC  (precise)
    #      direct = a confident semantic match of the query to a DTC name/desc
    #      inh    = the DTC merely shares the BEST-matched symptom's subsystem
    #               (broad context; fill-only, never allowed to dominate).
    #    Inheritance is taken MAX (not summed) and only from the single best
    #    symptom, so a subsystem with many codes can't flood the results.
    cand = {}     # code -> {'table','direct','inh','matched_symptom','source'}
    procs = {}    # app_url -> {'title', 'matched_symptom', 'score'}
    top_symptoms = sorted(sym_score.items(), key=lambda kv: kv[1]['rrf'], reverse=True)
    sym_rows = {}
    best_sid = top_symptoms[0][0] if top_symptoms else None

    def _c(code):
        return cand.setdefault(code, {'table': 0.0, 'direct': 0.0, 'inh': 0.0,
                                      'matched_symptom': None, 'source': None})

    for sid, s in top_symptoms[:config.DIAG_SYMPTOM_K]:
        row = diag.execute("SELECT * FROM symptom WHERE symptom_id=?", (sid,)).fetchone()
        if not row:
            continue
        sym_rows[sid] = row
        s_strength = s['rrf'] * 50.0 + s['sim']
        for lk in diag.execute(
                "SELECT target_kind, target_code, target_title, target_app_url, source "
                "FROM symptom_link WHERE symptom_id=?", (sid,)):
            if lk['target_kind'] == 'dtc':
                c = _c(lk['target_code'])
                if lk['source'] == 'symptom_table':
                    if s_strength > c['table']:
                        c['table'] = s_strength
                        c['matched_symptom'] = row['text']
                        c['source'] = 'symptom_table'
                elif lk['source'] == 'inheritance' and sid == best_sid:
                    c['inh'] = max(c['inh'], s_strength)
                    if c['source'] is None:
                        c['source'] = 'related'
                        c['matched_symptom'] = row['text']
            elif lk['target_kind'] == 'page' and lk['target_app_url']:
                p = procs.setdefault(lk['target_app_url'],
                                     {'title': lk['target_title'],
                                      'matched_symptom': row['text'], 'score': 0.0})
                p['score'] = max(p['score'], s_strength)

    # confident direct semantic matches only (DTC-name embeddings are terse and
    # noisy, so require a similarity floor before trusting them)
    for did, s in dtc_score.items():
        if s['sim'] < config.DIAG_DIRECT_SIM_FLOOR:
            continue
        drow = diag.execute("SELECT code FROM dtc WHERE did=?", (did,)).fetchone()
        if not drow:
            continue
        c = _c(drow['code'])
        c['direct'] = max(c['direct'], s['sim'])
        if c['source'] in (None, 'related'):
            c['source'] = 'direct'

    # closed-loop feedback: a candidate's representative blob may carry a guarded
    # 👍/👎 boost (the SAME blob-keyed map the assist path uses). Computed once for
    # the small candidate set, then folded into the rank score as a bounded
    # multiplier so confirmed-good fixes rise and confirmed-bad ones sink.
    boost_map = feedback.blob_boost_map() if index is not None else {}
    cand_blob, cand_fb = {}, {}

    def _fb(code):
        if code in cand_fb:
            return cand_fb[code]
        b = _repr_blob(diag, index, stem, code) if boost_map else None
        cand_blob[code] = b
        cand_fb[code] = boost_map.get(b, 1.0) if b is not None else 1.0
        return cand_fb[code]

    def _score(code, c):
        base = 100.0 * c['table'] + 30.0 * c['direct'] + 1.0 * c['inh']
        return base * _fb(code)

    strong = [(code, c) for code, c in cand.items() if c['table'] > 0 or c['direct'] > 0]
    weak = [(code, c) for code, c in cand.items()
            if c['table'] == 0 and c['direct'] == 0 and c['inh'] > 0]
    ranked = sorted(strong, key=lambda kv: _score(kv[0], kv[1]), reverse=True)
    if len(ranked) < k:          # fill remaining slots with broad "related" codes
        ranked += sorted(weak, key=lambda kv: kv[1]['inh'], reverse=True)[:k - len(ranked)]
    ranked = ranked[:k]

    candidates = []
    for code, info in ranked:
        row = diag.execute("SELECT * FROM dtc WHERE code=?", (code,)).fetchone()
        if not row:
            continue
        # honest, tier-based confidence: a manufacturer symptom-table link is
        # strong; a confident semantic match is its cosine; a same-subsystem
        # "related" code is low (it's a lead to check, not a diagnosis).
        if info['table'] > 0:
            conf = 0.9
        elif info['direct'] > 0:
            conf = round(info['direct'], 2)
        else:
            conf = 0.35
        fb = cand_fb.get(code, 1.0)
        # explain payload (parity with the assist evidence panel): which tier
        # found it, the symptom it matched, the raw tier signals + feedback boost.
        explain = {
            'source': info['source'],
            'matched_via': _SOURCE_VIA.get(info['source'], 'diagnostic'),
            'matched_symptom': info['matched_symptom'],
            'table': round(info['table'], 4), 'direct': round(info['direct'], 4),
            'inh': round(info['inh'], 4), 'boosts': {'feedback': round(fb, 3)},
        }
        candidates.append(_dtc_payload(
            diag, index, stem, row,
            reason={'kind': info['source'], 'matched_symptom': info['matched_symptom']},
            confidence=conf, blob_id=cand_blob.get(code),
            matched_via=_SOURCE_VIA.get(info['source'], 'diagnostic'),
            band=_band(conf), explain=explain, allowed_cars=allowed_cars))

    symptoms, _seen = [], set()
    for sid, _s in top_symptoms:
        if sid not in sym_rows:
            continue
        txt = sym_rows[sid]['text']
        if txt.strip().lower() in _seen:
            continue
        _seen.add(txt.strip().lower())
        symptoms.append({'text': txt, 'suspected': sym_rows[sid]['suspected'],
                         'app_url': sym_rows[sid]['app_url'],
                         'subsystem': sym_rows[sid]['subsystem']})
        if len(symptoms) >= 5:
            break

    procedures = [{'title': p['title'], 'app_url': url,
                   'matched_symptom': p['matched_symptom']}
                  for url, p in sorted(procs.items(), key=lambda kv: kv[1]['score'],
                                       reverse=True)[:config.DIAG_FINAL_CANDIDATES]]

    # grounding gate (parity with assist): strongest evidence is either a
    # manufacturer symptom-table link (inherently grounded) or a dense cosine.
    # Below GROUND_SIM_FLOOR with no table link -> out-of-domain, so the phraser
    # refuses rather than guessing from a weak nearest neighbour.
    best_sym_sim = max((s['sim'] for s in sym_score.values()), default=0.0)
    best_dtc_sim = max((s['sim'] for s in dtc_score.values()), default=0.0)
    top_sim = max(best_sym_sim, best_dtc_sim)
    has_table = any(c['table'] > 0 for c in cand.values())
    grounded = bool(candidates) and (has_table or top_sim >= config.GROUND_SIM_FLOOR)
    overall = _band(1.0 if has_table else top_sim) if grounded else _band(0.0)

    return {'query': query, 'intent': 'symptom', 'car_stem': stem,
            'kind': cls['kind'], 'grounded': grounded,
            'top_similarity': round(float(top_sim), 4), 'confidence_band': overall,
            'candidates': candidates, 'procedures': procedures, 'symptoms': symptoms}
