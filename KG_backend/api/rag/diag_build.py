"""Build the per-car DIAGNOSTIC SIDECAR — the data tier of the rule engine.

For one car we derive, purely from that car's own `nodes` tree (read-only), a
small self-contained DB under _rag/diag/<car_stem>.diag.db holding:

  * dtc        — one row per DTC code node, with its inheritance ancestors
                 (system / subsystem / component) flattened from parent_id, the
                 Description text + the "code sets when ..." trigger sentence,
                 and which diagnostic aspects exist.
  * dtc_step   — the ordered diagnostic chain under each DTC (Description ->
                 Symptom Tests -> Circuit Tests -> Procedure -> Wiring ...).
  * symptom    — rows parsed from the manual's "Problem Symptoms Table" pages.
  * symptom_link — symptom -> suspected DTC / diagnostic page. Built
                 DETERMINISTICALLY: (a) the table's own <a> link to the page
                 (manufacturer-authored, highest weight); (b) inheritance
                 proximity (DTCs in the same subsystem). Embedding is used only
                 for ranking at query time, never to invent a link.
  * sym_vec / dtc_vec / diag_fts — tiny (~1-2k rows/car) int8 + keyword indexes
                 so a Persian symptom maps to the English manual via bge-m3.

Nothing here writes to the original car DB. The whole _rag/diag/ folder is
deletable; the engine then degrades to general RAG.
"""
import re
import time
from urllib.parse import quote

import sqlite3
import sqlite_vec
from bs4 import BeautifulSoup

from . import config, store, embed, ingest

# A single manual page often documents SEVERAL related DTCs together (e.g. the
# misfire codes P0300..P0304 share one node titled
# "DTC P0300-00: ...; DTC P0301-00: Cylinder 1 Misfire Detected; ..."). Match
# every "DTC <code>:" segment so each code is individually indexed, all pointing
# at the same node (same diagnostic steps / procedure).
_MULTI_DTC_RE = re.compile(r'DTC\s+([A-Za-z][0-9A-Za-z]{3,4}(?:-\d{1,3})?)\s*:\s*')


def _parse_codes_from_title(t):
    """Return [(code, name), ...] for every DTC documented in a node title.
    Single-code titles yield one pair; combined pages yield several."""
    ms = list(_MULTI_DTC_RE.finditer(t))
    out = []
    for i, m in enumerate(ms):
        start = m.end()
        end = ms[i + 1].start() if i + 1 < len(ms) else len(t)
        name = ingest._DATE_WIN_RE.sub('', t[start:end]).strip(' ;')
        out.append((m.group(1), name))
    return out


# --- sidecar DB ------------------------------------------------------------
def open_diag(path, write=True):
    """Open (creating if needed) a per-car diagnostic sidecar with sqlite-vec."""
    config.DIAG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    if write:
        conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def init_diag_schema(conn):
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS dtc (
        did        INTEGER PRIMARY KEY,
        code       TEXT UNIQUE NOT NULL,    -- 'P0301', 'B27C0-57'
        name       TEXT,                    -- human-readable fault name
        system     TEXT, subsystem TEXT, component TEXT,
        node_id    TEXT,                    -- the DTC code node in the car tree
        app_url    TEXT,                    -- link to its Description (or itself)
        desc_text  TEXT,                    -- Description leaf, cleaned (head)
        trigger_text TEXT,                  -- "the code sets when ..." sentence
        has_symptom_test INTEGER DEFAULT 0,
        has_circuit_test INTEGER DEFAULT 0,
        has_procedure    INTEGER DEFAULT 0,
        has_wiring       INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS dtc_step (
        code TEXT NOT NULL, step_order INTEGER, aspect TEXT,
        node_id TEXT, app_url TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_step_code ON dtc_step(code);

    CREATE TABLE IF NOT EXISTS symptom (
        symptom_id INTEGER PRIMARY KEY,
        text       TEXT NOT NULL,
        suspected  TEXT,
        system     TEXT, subsystem TEXT, component TEXT,
        table_node_id TEXT, app_url TEXT
    );
    CREATE TABLE IF NOT EXISTS symptom_link (
        symptom_id  INTEGER NOT NULL,
        target_kind TEXT NOT NULL,          -- 'dtc' | 'page'
        target_code TEXT,                   -- when target_kind='dtc'
        target_node_id TEXT,
        target_title TEXT,
        target_app_url TEXT,
        weight REAL DEFAULT 1.0,
        source TEXT                         -- 'symptom_table' | 'inheritance' | 'technician'
    );
    CREATE INDEX IF NOT EXISTS idx_slink_sym ON symptom_link(symptom_id);

    CREATE VIRTUAL TABLE IF NOT EXISTS sym_vec USING vec0(
        embedding int8[{config.EMBED_DIM}] distance_metric=cosine);   -- rowid = symptom_id
    CREATE VIRTUAL TABLE IF NOT EXISTS dtc_vec USING vec0(
        embedding int8[{config.EMBED_DIM}] distance_metric=cosine);   -- rowid = dtc.did
    CREATE VIRTUAL TABLE IF NOT EXISTS diag_fts USING fts5(text, kind, ref);

    CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    conn.commit()


# --- helpers ---------------------------------------------------------------
def norm_code(s):
    """Canonical DTC code key for matching: upper-case, '-' as the separator."""
    return (s or '').strip().upper().replace(':', '-')


def _taxonomy(chain):
    """(system, subsystem, component) from a full breadcrumb chain (titles
    root..node). The section root ('Repair and Diagnosis') is located, then the
    two levels under it are system/subsystem; component is the node's direct
    parent (chain[-2])."""
    sec = 0
    for i, t in enumerate(chain):
        if (t or '').strip().lower() in config.DIAG_SECTION_ROOTS:
            sec = i
            break
    levels = chain[sec + 1:-1]          # below the section, excluding the node
    system = levels[0] if levels else ''
    subsystem = levels[1] if len(levels) > 1 else ''
    component = chain[-2] if len(chain) >= 2 else ''
    return system, subsystem, component


def _enc(s):
    """Mirror the frontend's encodeURIComponent (buildNodeHref) exactly: encode
    EVERY reserved char including '/' (a node title can contain a literal '/',
    e.g. a '[03/2022 - ]' date window), so each breadcrumb level stays one URL
    path segment that the frontend round-trips with decodeURIComponent."""
    return quote(s or '', safe='')


def _app_url(meta, car_stem, chain):
    """In-app URL for a node, identical convention to the frontend buildNodeHref:
    /{brand}/{year}/{car_stem}/{seg}/... where segs are the breadcrumb titles
    below the vehicle root (chain[0])."""
    segs = [s for s in chain[1:] if s]
    # A missing year must not collapse into an empty path segment
    # ("/brand//stem" is a link the frontend router cannot match). 'unknown'
    # is resolved tolerantly by car_view (brand+name fallback).
    year = meta['year'] if meta['year'] is not None else 'unknown'
    base = f"/{_enc(meta['brand'])}/{year}/{_enc(car_stem)}"
    if segs:
        base += '/' + '/'.join(_enc(s) for s in segs)
    return base


_TRIGGER_HINTS = (
    'is output when', 'is set when', 'sets when', 'is stored when',
    'is detected when', 'output when', 'set when', 'detected when',
)


def _trigger_sentence(text):
    """The full sentence describing WHEN the code sets — the symptom trigger.
    Snaps to sentence boundaries so it never starts mid-word."""
    flat = ' '.join((text or '').split())
    # drop a leading '<dtc title>: Description' echo if present
    if ': Description' in flat:
        flat = flat.split(': Description', 1)[1].strip()
    low = flat.lower()
    for hint in _TRIGGER_HINTS:
        i = low.find(hint)
        if i != -1:
            start = flat.rfind('.', 0, i) + 1          # sentence start (0 if none)
            end = flat.find('.', i)
            return flat[start:(end + 1 if end != -1 else i + 200)].strip()
    end = flat.find('.')
    return (flat[:end + 1] if end != -1 else flat[:200]).strip()


def _aspect_rank(aspect):
    a = (aspect or '').strip().lower()
    for i, key in enumerate(config.DTC_ASPECT_ORDER):
        if key in a:
            return i
    return len(config.DTC_ASPECT_ORDER) + 1


# --- extraction ------------------------------------------------------------
def _load_tree(src):
    """Light tree load (no content): maps for breadcrumbs + children + parent."""
    rows = src.execute(
        "SELECT id, parent_id, title, file_type, sort_order FROM nodes").fetchall()
    crumbs = ingest.build_breadcrumbs(rows)
    title = {r['id']: (r['title'] or '') for r in rows}
    parent = {r['id']: r['parent_id'] for r in rows}
    children = {}
    for r in rows:
        children.setdefault(r['parent_id'], []).append(
            (r['sort_order'] if r['sort_order'] is not None else 0, r['id']))
    for k in children:
        children[k].sort()
    # title -> node ids (for resolving the symptom-table <a> link text)
    title2ids = {}
    for r in rows:
        title2ids.setdefault((r['title'] or '').strip(), []).append(r['id'])
    return rows, crumbs, title, parent, children, title2ids


def _fetch_content(src, node_ids):
    """Batch-fetch content for a set of node ids -> {id: cleaned_text}."""
    out = {}
    ids = list(node_ids)
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        ph = ','.join('?' * len(chunk))
        for r in src.execute(
                f"SELECT id, content FROM nodes WHERE id IN ({ph})", chunk):
            out[r['id']] = ingest.html_to_text(r['content'])
    return out


def _extract_dtcs(src, meta, car_stem, crumbs, title, parent, children):
    """Return (dtc_rows, step_rows). A DTC code node = title matches the code
    pattern AND its parent is NOT itself a DTC (which would make it an aspect
    leaf like '... : Description'). Code nodes' parents are component groups; the
    aspect leaves' parents are the code nodes -> cleanly excluded."""
    dtc_nodes = []                       # (node_id, code, name)
    for nid, t in title.items():
        if not config.DTC_TITLE_RE.match(t):         # title starts with a DTC code
            continue
        pt = title.get(parent.get(nid))
        if pt and config.DTC_TITLE_RE.match(pt):     # this node is an aspect leaf
            continue
        # a node may document several DTCs at once -> index each of them
        for code, name in _parse_codes_from_title(t):
            dtc_nodes.append((nid, code, name))

    # The same code appears several times (two parallel section trees + date
    # windows + multiple subsystems). Keep ONE representative per code: the node
    # with the most aspect children, i.e. the fullest diagnostic chain.
    best = {}
    for nid, code, name in dtc_nodes:
        key = norm_code(code)
        n_kids = len(children.get(nid, []))
        if key not in best or n_kids > best[key][0]:
            best[key] = (n_kids, nid, code, name)
    dtc_nodes = [(nid, code, name) for _n, nid, code, name in best.values()]

    # description leaves to fetch (the first 'Description' aspect of each DTC)
    desc_target = {}                     # dtc_node_id -> description child id
    aspect_map = {}                      # dtc_node_id -> [(rank, order, aspect, child_id)]
    for nid, code, name in dtc_nodes:
        kids = children.get(nid, [])
        aspects = []
        for order, (so, cid) in enumerate(kids):
            ct = title.get(cid, '')
            parent_t = title.get(nid, '')
            aspect = ct[len(parent_t):].lstrip(' :').strip() if ct.startswith(parent_t) else ct
            if not aspect:
                aspect = ct.split(':')[-1].strip() or ct
            aspects.append((_aspect_rank(aspect), order, aspect, cid))
            if 'description' in aspect.lower() and nid not in desc_target:
                desc_target[nid] = cid
        if not aspects:                  # childless DTC: treat itself as Description
            aspects = [(0, 0, 'Description', nid)]
            desc_target[nid] = nid
        aspect_map[nid] = aspects

    contents = _fetch_content(src, set(desc_target.values()))

    dtc_rows, step_rows = [], []
    did = 0
    for nid, code, name in dtc_nodes:
        key = norm_code(code)
        did += 1
        chain = crumbs.get(nid, [name])
        system, subsystem, component = _taxonomy(chain)
        aspects = sorted(aspect_map.get(nid, []))
        desc_text = contents.get(desc_target.get(nid, ''), '')[:1000]
        has = {'symptom test': 0, 'circuit test': 0, 'procedure': 0, 'wiring': 0}
        for _r, _o, aspect, cid in aspects:
            al = aspect.lower()
            for kk in has:
                if kk in al:
                    has[kk] = 1
            cchain = crumbs.get(cid, chain + [aspect])
            step_rows.append((key, len(step_rows), aspect, cid,
                              _app_url(meta, car_stem, cchain)))
        # the DTC's own link points at its Description (a real leaf)
        desc_chain = crumbs.get(desc_target.get(nid), chain)
        dtc_rows.append((
            did, key, name, system, subsystem, component, nid,
            _app_url(meta, car_stem, desc_chain), desc_text,
            _trigger_sentence(desc_text),
            has['symptom test'], has['circuit test'], has['procedure'], has['wiring'],
        ))
    # re-key step_rows so step_order is per-DTC, not global
    per = {}
    fixed_steps = []
    for code, _gorder, aspect, cid, url in step_rows:
        idx = per.get(code, 0)
        per[code] = idx + 1
        fixed_steps.append((code, idx, aspect, cid, url))
    return dtc_rows, fixed_steps


def _parse_symptom_table(html):
    """Yield (symptom, suspected, link_text, link_href) rows from a Problem
    Symptoms Table page. Columns are matched by header (Symptom / Suspected Area
    / Link), falling back to positional [0,1,2]."""
    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return
    for table in soup.find_all('table'):
        headers = [th.get_text(' ', strip=True).lower()
                   for th in table.find_all('th')]
        s_idx, a_idx = 0, 1
        for i, h in enumerate(headers):
            if 'symptom' in h:
                s_idx = i
            elif 'suspect' in h:
                a_idx = i
        for tr in table.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) < 2:
                continue
            symptom = tds[s_idx].get_text(' ', strip=True) if s_idx < len(tds) else ''
            suspected = tds[a_idx].get_text(' ', strip=True) if a_idx < len(tds) else ''
            if not symptom:
                continue
            link_text, link_href = '', ''
            for td in tds:
                a = td.find('a')
                if a is not None:
                    link_text = a.get_text(' ', strip=True)
                    link_href = a.get('href') or ''
                    break
            yield symptom, suspected, link_text, link_href


def _extract_symptoms(src, meta, car_stem, crumbs, title, title2ids,
                      code_by_node, dtc_by_subsystem):
    """Return (symptom_rows, link_rows). Symptom rows come from Problem Symptoms
    Table pages; links are (a) the table's own <a> target resolved by title, and
    (b) inheritance proximity to DTCs in the same subsystem."""
    pst_ids = [nid for nid, t in title.items()
               if (t or '').strip().lower().startswith(config.DIAG_SYMPTOM_TABLE_TITLES[0])]

    symptom_rows, link_rows = [], []
    sid = 0
    seen = set()                 # dedup identical rows across duplicated PST pages
    for nid in pst_ids:
        html = src.execute("SELECT content FROM nodes WHERE id=?", (nid,)).fetchone()
        if not html or not html[0]:
            continue
        chain = crumbs.get(nid, [title.get(nid, '')])
        system, subsystem, component = _taxonomy(chain)
        app_url = _app_url(meta, car_stem, chain)
        for symptom, suspected, link_text, _href in _parse_symptom_table(html[0]):
            dedup_key = (symptom.strip().lower(), subsystem.lower(),
                         (suspected or '').strip().lower())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            sid += 1
            symptom_rows.append((sid, symptom, suspected, system, subsystem,
                                 component, nid, app_url))
            # (a) manufacturer link: resolve the <a> text to a node by title
            target_id = None
            if link_text:
                cands = title2ids.get(link_text.strip())
                if cands:
                    target_id = cands[0]
            if target_id is not None:
                tcode = code_by_node.get(target_id)
                tchain = crumbs.get(target_id, [link_text])
                turl = _app_url(meta, car_stem, tchain)
                if tcode:
                    link_rows.append((sid, 'dtc', tcode, target_id, link_text,
                                      turl, config.DIAG_W_TABLE_LINK, 'symptom_table'))
                else:
                    link_rows.append((sid, 'page', None, target_id, link_text,
                                      turl, config.DIAG_W_TABLE_LINK, 'symptom_table'))
            # (b) inheritance: DTCs in the same subsystem (vertical proximity)
            for code in dtc_by_subsystem.get(subsystem, [])[:20]:
                link_rows.append((sid, 'dtc', code, None, None, None,
                                  config.DIAG_W_INHERITANCE, 'inheritance'))
    return symptom_rows, link_rows


# --- embeddings ------------------------------------------------------------
def _embed_rows(diag, table_vec, items, log):
    """items: list of (rowid, text). Encodes with bge-m3, stores int8 vectors."""
    if not items:
        return
    texts = [t for _id, t in items]
    vecs = embed.encode(texts, batch_size=32)
    rows = [(rid, store.pack_f32(v)) for (rid, _t), v in zip(items, vecs)]
    diag.executemany(
        f"INSERT INTO {table_vec}(rowid, embedding) "
        f"VALUES (?, vec_quantize_int8(vec_f32(?), 'unit'))", rows)
    diag.commit()


# --- entry point -----------------------------------------------------------
def build_car(car_stem, rebuild=False, log=print):
    """Build the diagnostic sidecar for one car. Returns a stats dict."""
    src_path = config.WAREHOUSE_DIR / f"{car_stem}.db"
    if not src_path.exists():
        raise FileNotFoundError(str(src_path))
    out_path = config.diag_db_path(car_stem)
    if rebuild:
        for suffix in ('', '-wal', '-shm'):
            p = out_path.with_name(out_path.name + suffix)
            if p.exists():
                p.unlink()

    meta = config.car_meta(car_stem)
    t0 = time.time()
    src = store.open_car_ro(src_path)
    try:
        rows, crumbs, title, parent, children, title2ids = _load_tree(src)
        log(f"    {car_stem[:38]:38s} nodes={len(title)}")

        dtc_rows, step_rows = _extract_dtcs(src, meta, car_stem, crumbs, title, parent, children)
        code_by_node = {r[6]: r[1] for r in dtc_rows}          # node_id -> code
        dtc_by_subsystem = {}
        for r in dtc_rows:
            dtc_by_subsystem.setdefault(r[4], []).append(r[1])  # subsystem -> [code]

        symptom_rows, link_rows = _extract_symptoms(
            src, meta, car_stem, crumbs, title, title2ids,
            code_by_node, dtc_by_subsystem)
    finally:
        src.close()

    diag = open_diag(out_path)
    try:
        init_diag_schema(diag)
        for t in ('dtc', 'dtc_step', 'symptom', 'symptom_link', 'diag_fts'):
            diag.execute(f"DELETE FROM {t}")
        for t in ('sym_vec', 'dtc_vec'):
            try:
                diag.execute(f"DELETE FROM {t}")
            except Exception:
                pass

        diag.executemany(
            "INSERT INTO dtc(did,code,name,system,subsystem,component,node_id,"
            "app_url,desc_text,trigger_text,has_symptom_test,has_circuit_test,"
            "has_procedure,has_wiring) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", dtc_rows)
        diag.executemany(
            "INSERT INTO dtc_step(code,step_order,aspect,node_id,app_url) "
            "VALUES (?,?,?,?,?)", step_rows)
        diag.executemany(
            "INSERT INTO symptom(symptom_id,text,suspected,system,subsystem,"
            "component,table_node_id,app_url) VALUES (?,?,?,?,?,?,?,?)", symptom_rows)
        diag.executemany(
            "INSERT INTO symptom_link(symptom_id,target_kind,target_code,"
            "target_node_id,target_title,target_app_url,weight,source) "
            "VALUES (?,?,?,?,?,?,?,?)", link_rows)
        # FTS (keyword half of the hybrid search)
        diag.executemany(
            "INSERT INTO diag_fts(text,kind,ref) VALUES (?,?,?)",
            [(f"{r[1]} {r[2] or ''}", 'symptom', str(r[0])) for r in symptom_rows] +
            [(f"{r[2]} {r[8] or ''}", 'dtc', r[1]) for r in dtc_rows])
        diag.commit()

        log(f"    embedding {len(symptom_rows)} symptoms + {len(dtc_rows)} DTCs "
            f"(bge-m3; first load ~20-30s) ...")
        _embed_rows(diag, 'sym_vec',
                    [(r[0], f"{r[5]}\n{r[1]}") for r in symptom_rows], log)
        _embed_rows(diag, 'dtc_vec',
                    [(r[0], f"{r[2]}\n{(r[8] or '')[:400]}") for r in dtc_rows], log)

        for k, v in (('embed_model', config.EMBED_MODEL),
                     ('embed_dim', str(config.EMBED_DIM)),
                     ('car_stem', car_stem)):
            diag.execute("INSERT OR REPLACE INTO meta(k,v) VALUES (?,?)", (k, v))
        diag.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('built_at',datetime('now'))")
        diag.commit()
    finally:
        diag.close()

    stats = {'car': car_stem, 'dtc': len(dtc_rows), 'steps': len(step_rows),
             'symptoms': len(symptom_rows), 'links': len(link_rows),
             'secs': round(time.time() - t0, 1)}
    log(f"    -> dtc={stats['dtc']} symptoms={stats['symptoms']} "
        f"links={stats['links']} ({stats['secs']}s)  {out_path.name}")
    return stats
