"""PartSouq EPC crawl -> KGKG parts-catalog ingest.

Source: a legacy-engine PartSouq crawl on this server (default
``/root/Desktop/partsouq2``) laid out as::

    downloads/<FRAME>/index.html            vehicle page (4 EPC categories)
    downloads/<FRAME>/_groups/index.html    the Groups treegrid (canonical
                                            labels, gids, hierarchy, ORDER)
    downloads/<FRAME>/_groups/<DIR>/index.html
                                            one leaf page per functional group:
                                            1..N illustration sections, each an
                                            exploded-view GIF + a parts table
    downloads/_assets/<hash8>_<fig>.gif     shared diagram images

This module mirrors the manuals pipeline shape (scan -> parse -> validate ->
build -> catalog -> audit) but for parts. Staging lives OUTSIDE the warehouse
(``/root/parts_build/staging.db``); only fully validated vehicles are built
into ``Database_warehouse/_parts/<car_name>.db`` + shared images copied to
``static_warehouse/_parts_assets/``.

Import discipline: NO module-level Django imports — parse workers run in a
multiprocessing pool and must not drag Django into child processes. Stages
that need the ORM (catalog) import lazily inside the function.
"""
import csv
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import sqlite3
import time
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup

SCHEMA_VERSION = 1

# The four fixed EPC categories, in the catalog's own presentation order.
CATEGORY_ORDER = ['Engine/Fuel/Tool', 'Power Train/Chassis', 'Body/Interior', 'Electrical']

# Persian labels for the EPC categories (UI chrome only; English kept as data).
CATEGORY_FA = {
    'Engine/Fuel/Tool': 'موتور / سوخت / ابزار',
    'Power Train/Chassis': 'انتقال قدرت / شاسی',
    'Body/Interior': 'بدنه / داخلی',
    'Electrical': 'برق و الکترونیک',
}

# Activity-analytics category ids (mirrors access.CONTENT_CATEGORIES ids).
CATEGORY_ANALYTICS = {
    'Engine/Fuel/Tool': 'engine',
    'Power Train/Chassis': 'transmission',
    'Body/Interior': 'body',
    'Electrical': 'electrical',
}

QTY_INT_RE = re.compile(r'^0*(\d{1,3})$')
QTY_X_RE = re.compile(r'^[Xx](\d{1,3})$')
GID_SUFFIX_RE = re.compile(r'\s*\(gid (\d+)\)$')
TREEGRID_ID_RE = re.compile(r'treegrid-(\d+)(?:\s|$)')
TREEGRID_PARENT_RE = re.compile(r'treegrid-parent-(\d+)')
ASSET_GIF_RE = re.compile(r'_assets/([A-Za-z0-9]{8}_[A-Za-z0-9.\-]+\.gif)')
GID_IN_URL_RE = re.compile(r'[?&]gid=(\d+)')

PART_TABLE_HEAD = ['Number', 'Name', 'Code', 'Note', 'Quantity', 'Range']


def sanitize_label(text):
    """EXACT copy of the crawler's directory-name sanitizer (partsouq.py:55)."""
    text = re.sub(r'[\\/*?:"<>|]', '_', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def nfkc(text):
    return unicodedata.normalize('NFKC', text or '').strip()


def sha1(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# Staging database
# ---------------------------------------------------------------------------

STAGING_SCHEMA = """
CREATE TABLE IF NOT EXISTS crawl_frames (
    frame TEXT PRIMARY KEY,
    region TEXT, model_name TEXT, year_seen INT,
    date_from TEXT, date_to TEXT,
    engine TEXT, transmission TEXT, steering TEXT, destination TEXT, grade TEXT,
    meta_source TEXT,          -- csv | parsed | none
    vehicle_name TEXT, vehicle_year INT,
    n_tree_nodes INT, n_tree_leaves INT, n_dirs INT
);
CREATE TABLE IF NOT EXISTS group_tree (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frame TEXT NOT NULL,
    tree_id INT NOT NULL,          -- treegrid-N id within this frame
    parent_tree_id INT,            -- treegrid-parent-M (NULL = top level)
    label TEXT NOT NULL,
    gid INT,
    sort_order INT NOT NULL,       -- document order in the treegrid
    is_leaf INT NOT NULL DEFAULT 0,
    matched_dir TEXT,              -- _groups/<DIR> holding this leaf's page
    page_status TEXT,              -- ok | cloudflare | parse_error | no_page
    category TEXT,                 -- from the leaf page title
    n_sections INT DEFAULT 0,
    n_rows INT DEFAULT 0,
    UNIQUE(frame, tree_id)
);
CREATE INDEX IF NOT EXISTS idx_tree_frame ON group_tree(frame, parent_tree_id, sort_order);
CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_row INT NOT NULL REFERENCES group_tree(id),
    section_index INT NOT NULL,
    container_id TEXT,
    figure_code TEXT,
    image_file TEXT,               -- basename inside _assets/
    image_exists INT DEFAULT 0,
    caption TEXT,
    n_rows INT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sections_tree ON sections(tree_row, section_index);
CREATE TABLE IF NOT EXISTS part_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id INT NOT NULL REFERENCES sections(id),
    row_index INT NOT NULL,
    callout TEXT, pn TEXT, pn_display TEXT,
    name_en TEXT, note TEXT, qty_raw TEXT, qty INT,
    qty_display TEXT,              -- '1', '8', or 'X' (EPC "as required")
    date_range TEXT,
    is_xref INT DEFAULT 0,
    valid INT DEFAULT 1,
    invalid_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_rows_section ON part_rows(section_id, row_index);
CREATE TABLE IF NOT EXISTS section_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id INT NOT NULL REFERENCES sections(id),
    code TEXT,                     -- data-codeonimage (matches part_rows.callout)
    x INTEGER, y INTEGER,          -- data-position, in the image's native pixels
    w INTEGER, h INTEGER,          -- data-size (label box), native pixels
    title TEXT
);
CREATE INDEX IF NOT EXISTS idx_labels_section ON section_labels(section_id);
CREATE TABLE IF NOT EXISTS parsed_pages (
    page_path TEXT PRIMARY KEY,    -- relative to src root
    mtime_ns INT, size INT, status TEXT
);
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT, severity TEXT,      -- hard | warn | info
    frame TEXT, ref TEXT, code TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def staging_conn(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(STAGING_SCHEMA)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def add_issue(conn, stage, severity, frame, ref, code, detail=''):
    conn.execute(
        'INSERT INTO issues(stage, severity, frame, ref, code, detail) VALUES (?,?,?,?,?,?)',
        (stage, severity, frame, ref, code, str(detail)[:1000]))


# ---------------------------------------------------------------------------
# Stage: scan — enumerate frames, resolve metadata, derive the vehicle map
# ---------------------------------------------------------------------------

ATTR_KEYS = {'Engine', 'Transmission', 'Steering', 'Destination', 'Grade',
             'Production', 'Body', 'Model year', 'Frame', 'Trans'}


def list_frames(src):
    base = Path(src) / 'downloads'
    return sorted(d.name for d in base.iterdir()
                  if d.is_dir() and not d.name.startswith('_'))


def load_frames_csv(src):
    """toyotaepc_frames.csv -> {frame: rowdict}. Missing file is tolerated."""
    out = {}
    p = Path(src) / 'toyotaepc_frames.csv'
    if not p.is_file():
        return out
    with open(p, encoding='utf-8', newline='') as fh:
        for row in csv.DictReader(fh):
            frame = (row.get('frame') or '').strip()
            if frame:
                out[frame] = row
    return out


def parse_frame_attrs(index_html_path):
    """Best-effort attribute extraction from a frame's vehicle page (used only
    for frames absent from the CSV). Looks for a two-column attribute table."""
    try:
        html = Path(index_html_path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return {}
    soup = BeautifulSoup(html, 'html.parser')
    attrs = {}
    for tr in soup.find_all('tr'):
        tds = tr.find_all('td')
        if len(tds) < 2:
            continue
        key = tds[0].get_text(' ', strip=True)
        val = tds[1].get_text(' ', strip=True)
        if key in ATTR_KEYS and val:
            attrs[key] = val
    return attrs


def engine_family(frame):
    """Bucket id from the frame-code prefix (Toyota platform coding)."""
    if frame.startswith(('MXGA10', 'MXGA15')):
        return 'gas20'          # 2.0L M20A
    if frame.startswith(('MXGH10', 'MXGH15')):
        return 'hyb20'          # 2.0L hybrid
    if frame.startswith('ZSG10'):
        return 'gas18'          # 1.8L 2ZR
    if frame.startswith('ZVG10'):
        return 'hyb18'          # 1.8L hybrid gen-1
    if frame.startswith(('ZVG11', 'ZVG12', 'ZVG13', 'ZVG15', 'ZVG16')):
        return 'hybfl'          # hybrid facelift generation
    return 'other'


FAMILY_VEHICLE = {
    'gas20': ('Corolla Cross 2.0 M20A', 2022),
    'hyb20': ('Corolla Cross 2.0 Hybrid', 2023),
    'gas18': ('Corolla Cross 1.8 2ZR', 2022),
    'hyb18': ('Corolla Cross 1.8 Hybrid', 2022),
    'hybfl': ('Corolla Cross Hybrid', 2024),
    'other': ('Corolla Cross', 2022),
}


def vehicle_for_frame(frame, meta):
    """Deterministic frame -> (car_name, year). US frames with a known grade
    get a per-grade vehicle; everything else buckets by engine family."""
    region = (meta.get('region') or '').strip()
    grade = (meta.get('grade') or '').strip()
    year = None
    try:
        year = int(meta.get('year_seen') or 0) or None
    except (TypeError, ValueError):
        year = None
    if region == 'US' and grade and year:
        return f'Corolla Cross {grade} (Parts {year})', year
    fam = engine_family(frame)
    base, default_year = FAMILY_VEHICLE[fam]
    y = year or default_year
    return f'{base} (Parts {y})', y


def stage_scan(conn, src, report_dir, log=print):
    frames = list_frames(src)
    csv_meta = load_frames_csv(src)
    n_csv = n_parsed = n_none = 0
    for frame in frames:
        row = csv_meta.get(frame)
        if row:
            meta = {
                'region': row.get('region') or '',
                'model_name': row.get('model_name') or '',
                'year_seen': row.get('year_seen') or None,
                'date_from': row.get('date_from') or '',
                'date_to': row.get('date_to') or '',
                'engine': row.get('engine') or '',
                'transmission': row.get('transmission') or '',
                'steering': row.get('steering') or '',
                'destination': row.get('destination') or '',
                'grade': row.get('grade') or '',
                'meta_source': 'csv',
            }
            n_csv += 1
        else:
            attrs = parse_frame_attrs(Path(src) / 'downloads' / frame / 'index.html')
            meta = {
                'region': '', 'model_name': 'Corolla Cross', 'year_seen': None,
                'date_from': attrs.get('Production', ''), 'date_to': '',
                'engine': attrs.get('Engine', ''),
                'transmission': attrs.get('Transmission', attrs.get('Trans', '')),
                'steering': attrs.get('Steering', ''),
                'destination': attrs.get('Destination', ''),
                'grade': attrs.get('Grade', ''),
                'meta_source': 'parsed' if attrs else 'none',
            }
            if attrs:
                n_parsed += 1
            else:
                n_none += 1
                add_issue(conn, 'scan', 'warn', frame, 'index.html',
                          'frame_meta_missing', 'no CSV row and no parsable attribute table')
        car_name, year = vehicle_for_frame(frame, meta)
        try:
            year_seen = int(meta['year_seen']) if meta['year_seen'] else None
        except (TypeError, ValueError):
            year_seen = None
        conn.execute("""
            INSERT INTO crawl_frames(frame, region, model_name, year_seen, date_from,
                date_to, engine, transmission, steering, destination, grade,
                meta_source, vehicle_name, vehicle_year)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(frame) DO UPDATE SET region=excluded.region,
                model_name=excluded.model_name, year_seen=excluded.year_seen,
                date_from=excluded.date_from, date_to=excluded.date_to,
                engine=excluded.engine, transmission=excluded.transmission,
                steering=excluded.steering, destination=excluded.destination,
                grade=excluded.grade, meta_source=excluded.meta_source,
                vehicle_name=excluded.vehicle_name, vehicle_year=excluded.vehicle_year
        """, (frame, meta['region'], meta['model_name'], year_seen,
              meta['date_from'], meta['date_to'], meta['engine'],
              meta['transmission'], meta['steering'], meta['destination'],
              meta['grade'], meta['meta_source'], car_name, year))
    conn.commit()
    write_vehicle_map(conn, src, report_dir)
    log(f'scan: {len(frames)} frames ({n_csv} csv, {n_parsed} parsed, {n_none} bare)')
    return len(frames)


def write_vehicle_map(conn, src, report_dir):
    rows = conn.execute("""
        SELECT vehicle_name, vehicle_year, frame, region, engine, transmission,
               steering, destination, grade, date_from, date_to, meta_source
        FROM crawl_frames ORDER BY vehicle_name, frame
    """).fetchall()
    vehicles = {}
    for r in rows:
        v = vehicles.setdefault(r['vehicle_name'], {
            'car_name': r['vehicle_name'], 'brand_name': 'Toyota',
            'year': r['vehicle_year'], 'frames': []})
        v['frames'].append({k: r[k] for k in (
            'frame', 'region', 'engine', 'transmission', 'steering',
            'destination', 'grade', 'date_from', 'date_to', 'meta_source')})
    out = {'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
           'source': str(src), 'vehicles': sorted(vehicles.values(),
                                                  key=lambda v: (v['year'], v['car_name']))}
    rd = Path(report_dir)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / 'vehicle_map.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    lines = ['# Parts vehicle map', '']
    for v in out['vehicles']:
        lines.append(f"## {v['car_name']} — Toyota {v['year']} ({len(v['frames'])} frames)")
        for f in v['frames']:
            bits = [f['frame']]
            for k in ('region', 'engine', 'transmission', 'steering', 'destination', 'grade'):
                if f.get(k):
                    bits.append(f"{k}={f[k]}")
            if f.get('date_from'):
                bits.append(f"prod={f['date_from']}-{f.get('date_to') or ''}")
            lines.append('- ' + ' | '.join(bits))
        lines.append('')
    (rd / 'vehicle_map.md').write_text('\n'.join(lines), encoding='utf-8')
    return out


# ---------------------------------------------------------------------------
# Stage: parse — treegrid + leaf pages (multiprocessing on leaf pages)
# ---------------------------------------------------------------------------

def parse_treegrid(html):
    """The Groups treegrid -> list of node dicts in document order.

    Real pages render some rows twice (~13 of ~500 per frame): dedupe by
    tree_id keeping the FIRST occurrence; a later duplicate that disagrees on
    (parent, label, gid) marks the kept node with ``dup_conflict`` so the
    caller can surface it as an issue instead of silently mis-treeing."""
    soup = BeautifulSoup(html, 'html.parser')
    nodes = []
    by_id = {}
    for tr in soup.find_all('tr'):
        cls = ' '.join(tr.get('class') or [])
        m = TREEGRID_ID_RE.search(cls + ' ')
        if not m:
            continue
        tree_id = int(m.group(1))
        pm = TREEGRID_PARENT_RE.search(cls)
        parent = int(pm.group(1)) if pm else None
        a = tr.find('a')
        gid = None
        if a is not None and a.get('href'):
            gm = GID_IN_URL_RE.search(a['href'])
            if gm:
                gid = int(gm.group(1))
        label = tr.get_text(' ', strip=True)
        label = re.sub(r'\s+', ' ', label).strip()
        if not label:
            continue
        if tree_id in by_id:
            first = by_id[tree_id]
            if (first['parent'], first['label'], first['gid']) != (parent, label, gid):
                first['dup_conflict'] = (
                    f"dup row disagrees: parent={parent} label={label!r} gid={gid}")
            continue
        node = {'tree_id': tree_id, 'parent': parent, 'label': label, 'gid': gid,
                'dup_conflict': None}
        by_id[tree_id] = node
        nodes.append(node)
    # leaf = a node no other node claims as parent
    parents = {n['parent'] for n in nodes if n['parent'] is not None}
    for n in nodes:
        n['is_leaf'] = n['tree_id'] not in parents
    return nodes


def parse_group_page(path):
    """One leaf group page -> dict {status, gid, category, sections:[...]}.

    Pure function (no db, no Django) — safe for pool workers."""
    try:
        html = Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError as e:
        return {'status': 'parse_error', 'error': f'read: {e}'}
    if not html.strip():
        # zero-byte save — the crawler wrote the file but the fetch failed.
        # A fetch-failure class like 'cloudflare', not a parser defect.
        return {'status': 'empty_page'}
    if '<title>Just a moment' in html or 'cf-mitigated' in html[:4000]:
        return {'status': 'cloudflare'}
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.get_text(strip=True) if soup.title else ''
    if title.startswith('Just a moment'):
        return {'status': 'cloudflare'}
    category = title.split(' | ')[0].strip() if ' | ' in title else ''
    if category not in CATEGORY_ORDER:
        return {'status': 'parse_error', 'error': f'unrecognized category in title: {title[:120]}'}
    gid = None
    og = soup.find('meta', attrs={'property': 'og:url'})
    if og and og.get('content'):
        gm = GID_IN_URL_RE.search(og['content'])
        if gm:
            gid = int(gm.group(1))

    # Illustration sections: every <img data-container="zoom_container_X"> is a
    # diagram; dedupe by container id, keep document order.
    sections = []
    seen = set()
    for img in soup.find_all('img', attrs={'data-container': True}):
        cid = img['data-container']
        if not cid.startswith('zoom_container_') or cid in seen:
            continue
        seen.add(cid)
        src = img.get('src') or ''
        am = ASSET_GIF_RE.search(src)
        image_file = am.group(1) if am else None
        figure = None
        if image_file and '_' in image_file:
            figure = image_file.split('_', 1)[1].rsplit('.', 1)[0]
        alt = nfkc(img.get('alt') or '')
        caption = alt
        # nearest preceding h2 (the plate caption)
        h2 = img.find_previous('h2')
        if h2 is not None:
            h2t = nfkc(h2.get_text(' ', strip=True))
            if h2t:
                caption = h2t
        # Callout landmarks: partsouq overlays a <div class="lable"> per callout
        # inside the image's zoom container. data-position is the (x,y) in the
        # image's native pixel space; data-codeonimage matches a part_rows.callout.
        # These are the coordinates the interactive highlight needs — captured
        # here so the diagram can drive/echo the parts table client-side.
        labels = []
        cont = soup.find(id=cid)
        if cont is not None:
            for lab in cont.find_all('div', attrs={'data-codeonimage': True}):
                pos = (lab.get('data-position') or '').split(',')
                if len(pos) < 2:
                    continue
                try:
                    lx = int(round(float(pos[0])))
                    ly = int(round(float(pos[1])))
                except ValueError:
                    continue
                lw = lh = None
                siz = (lab.get('data-size') or '').split(',')
                if len(siz) >= 2:
                    try:
                        lw = int(round(float(siz[0])))
                        lh = int(round(float(siz[1])))
                    except ValueError:
                        lw = lh = None
                labels.append({'code': nfkc(lab.get('data-codeonimage') or ''),
                               'x': lx, 'y': ly, 'w': lw, 'h': lh,
                               'title': nfkc(lab.get('data-title') or '')})
        sections.append({'container_id': cid, 'figure_code': figure,
                         'image_file': image_file, 'caption': caption,
                         'labels': labels, 'rows': []})

    # Part tables: every table whose thead matches the EPC column set, in
    # document order; positional pairing with the sections above.
    tables = []
    for thead in soup.find_all('thead'):
        head_cells = [th.get_text(' ', strip=True) for th in thead.find_all(['th', 'td'])]
        head_cells = [h for h in head_cells if h]
        if head_cells[:2] == ['Number', 'Name'] and 'Quantity' in head_cells:
            tables.append(thead)
    if not sections and not tables:
        # Well-formed head, no catalog body: a truncated/blocked fetch, not a
        # real group. Distinct status so it is REPORTED as a coverage gap
        # instead of counting as a successful import that build silently drops.
        return {'status': 'no_content', 'gid': gid, 'category': category}
    if len(tables) != len(sections):
        return {'status': 'parse_error', 'gid': gid, 'category': category,
                'error': f'section/table mismatch: {len(sections)} sections vs {len(tables)} tables'}

    for si, thead in enumerate(tables):
        table = thead.find_parent('table')
        body = table.find('tbody') if table else None
        rows_parent = body or table
        if rows_parent is None:
            continue
        ri = 0
        for tr in rows_parent.find_all('tr'):
            cls = tr.get('class') or []
            if not any(str(c).startswith('part-search-tr') for c in cls):
                continue
            tds = tr.find_all('td')
            if len(tds) < 3:
                continue
            texts = [nfkc(td.get_text(' ', strip=True)) for td in tds]
            # canonical PN from the search link's q= param, display from text
            pn = ''
            a = tds[0].find('a')
            if a is not None and a.get('href'):
                qm = re.search(r'[?&]q=([A-Za-z0-9\-]+)', a['href'])
                if qm:
                    pn = qm.group(1)
            pn_display = texts[0]
            if not pn:
                pn = re.sub(r'[^A-Za-z0-9]', '', pn_display)
            name_en = texts[1] if len(texts) > 1 else ''
            callout = texts[2] if len(texts) > 2 else ''
            note = texts[3] if len(texts) > 3 else ''
            qty_raw = texts[4] if len(texts) > 4 else ''
            date_range = texts[5] if len(texts) > 5 else ''
            sections[si]['rows'].append({
                'row_index': ri, 'callout': callout, 'pn': pn,
                'pn_display': pn_display, 'name_en': name_en, 'note': note,
                'qty_raw': qty_raw, 'date_range': date_range})
            ri += 1
    return {'status': 'ok', 'gid': gid, 'category': category, 'sections': sections}


def classify_row(row):
    """-> (qty:int|None, qty_display:str|None, is_xref:bool, valid:bool, reason:str|None)

    ``qty_display`` is what the catalog publishes: the integer as text, or the
    literal 'X' — the EPC's "as required" quantity (sealants, clips, …), which
    is a legitimate quantity value, not missing data."""
    pn = row['pn']
    qty_raw = row['qty_raw']
    is_xref = (not row['name_en'] and not qty_raw
               and row['callout'] in (pn, row['pn_display']))
    if is_xref:
        return None, None, True, True, None
    if not pn:
        return None, None, False, False, 'missing_pn'
    qty = None
    qty_display = None
    m = QTY_INT_RE.match(qty_raw)
    if m:
        qty = int(m.group(1))
        qty_display = str(qty)
    else:
        m = QTY_X_RE.match(qty_raw)
        if m:
            qty = int(m.group(1))
            qty_display = str(qty)
        elif qty_raw.upper() == 'X':
            qty_display = 'X'
    if qty_display is None:
        return None, None, False, False, 'qty_unparsed' if qty_raw else 'missing_qty'
    if not row['name_en']:
        return qty, qty_display, False, False, 'missing_name'
    return qty, qty_display, False, True, None


def _match_dirs_to_leaves(leaves, dirs):
    """Map crawl dirs -> tree leaves. '(gid N)' dirs match by gid; plain dirs
    match the first not-yet-taken leaf whose sanitized label equals the dir
    (the crawler visited leaves in tree order and only suffixed collisions)."""
    result = {}          # dir -> leaf tree_id
    taken = set()
    by_gid = {n['gid']: n for n in leaves if n['gid'] is not None}
    for d in dirs:
        m = GID_SUFFIX_RE.search(d)
        if m:
            gid = int(m.group(1))
            leaf = by_gid.get(gid)
            if leaf is not None:
                result[d] = leaf['tree_id']
                taken.add(leaf['tree_id'])
    for d in dirs:
        if d in result:
            continue
        for n in leaves:
            if n['tree_id'] in taken:
                continue
            if sanitize_label(n['label']) == d:
                result[d] = n['tree_id']
                taken.add(n['tree_id'])
                break
    return result


def _purge_frame(conn, frame):
    """Drop everything staged for one frame, children first — rebuilding a
    treegrid re-keys group_tree, so anything hanging off the old ids must go
    with it or it becomes unreachable garbage that later gates still count."""
    conn.execute("""DELETE FROM part_rows WHERE section_id IN (
                        SELECT s.id FROM sections s
                        JOIN group_tree g ON g.id = s.tree_row
                        WHERE g.frame=?)""", (frame,))
    conn.execute('DELETE FROM sections WHERE tree_row IN '
                 '(SELECT id FROM group_tree WHERE frame=?)', (frame,))
    conn.execute('DELETE FROM group_tree WHERE frame=?', (frame,))
    conn.execute('DELETE FROM parsed_pages WHERE page_path LIKE ?',
                 (f'{frame}/_groups/%',))
    conn.execute("DELETE FROM issues WHERE frame=? AND stage='parse'", (frame,))


def _iter_parse_jobs(src, frames, conn, force=False):
    base = Path(src) / 'downloads'
    for frame in frames:
        gdir = base / frame / '_groups'
        if not gdir.is_dir():
            continue
        for d in sorted(p.name for p in gdir.iterdir() if p.is_dir()):
            page = gdir / d / 'index.html'
            if not page.is_file():
                continue
            rel = f'{frame}/_groups/{d}/index.html'
            st = page.stat()
            if not force:
                prev = conn.execute(
                    'SELECT mtime_ns, size FROM parsed_pages WHERE page_path=?',
                    (rel,)).fetchone()
                if prev and prev['mtime_ns'] == st.st_mtime_ns and prev['size'] == st.st_size:
                    continue
            yield (frame, d, str(page), rel, st.st_mtime_ns, st.st_size)


def _parse_one(job):
    frame, d, page, rel, mtime_ns, size = job
    out = parse_group_page(page)
    return frame, d, rel, mtime_ns, size, out


def stage_parse(conn, src, jobs=4, frames_filter=None, force=False, log=print):
    base = Path(src) / 'downloads'
    frames = frames_filter or list_frames(src)
    assets_dir = base / '_assets'

    # 1) treegrids (fast, serial). A frame's tree is rebuilt only when its
    #    _groups/index.html changed (or --force): rebuilding re-keys tree rows,
    #    so it must cascade-purge that frame's sections/rows/parsed-page marks
    #    or a later resumed parse would leave them orphaned.
    for frame in frames:
        tg = base / frame / '_groups' / 'index.html'
        if not tg.is_file():
            _purge_frame(conn, frame)
            add_issue(conn, 'parse', 'hard', frame, '_groups/index.html',
                      'treegrid_missing')
            continue
        st = tg.stat()
        sig = f'{st.st_mtime_ns}:{st.st_size}'
        prev = conn.execute('SELECT v FROM meta WHERE k=?',
                            (f'treegrid:{frame}',)).fetchone()
        have_rows = conn.execute('SELECT 1 FROM group_tree WHERE frame=? LIMIT 1',
                                 (frame,)).fetchone()
        if prev and prev['v'] == sig and have_rows and not force:
            continue
        _purge_frame(conn, frame)
        try:
            nodes = parse_treegrid(tg.read_text(encoding='utf-8', errors='replace'))
        except Exception as e:
            add_issue(conn, 'parse', 'hard', frame, '_groups/index.html',
                      'treegrid_parse_error', e)
            continue
        if not nodes:
            add_issue(conn, 'parse', 'hard', frame, '_groups/index.html',
                      'treegrid_empty')
            continue
        gdir = base / frame / '_groups'
        dirs = sorted(p.name for p in gdir.iterdir() if p.is_dir())
        leaves = [n for n in nodes if n['is_leaf']]
        match = _match_dirs_to_leaves(leaves, dirs)
        leaf_dir = {v: k for k, v in match.items()}
        for n in nodes:
            if n.get('dup_conflict'):
                add_issue(conn, 'parse', 'warn', frame, n['label'],
                          'treegrid_dup_conflict', n['dup_conflict'])
        for order, n in enumerate(nodes):
            conn.execute("""
                INSERT INTO group_tree(frame, tree_id, parent_tree_id, label, gid,
                    sort_order, is_leaf, matched_dir, page_status)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (frame, n['tree_id'], n['parent'], n['label'], n['gid'], order,
                  1 if n['is_leaf'] else 0, leaf_dir.get(n['tree_id']),
                  None if n['is_leaf'] else ''))
        for n in leaves:
            if n['tree_id'] not in leaf_dir:
                conn.execute(
                    "UPDATE group_tree SET page_status='no_page' WHERE frame=? AND tree_id=?",
                    (frame, n['tree_id']))
        # Dirs that match no LEAF are usually BRANCH pages: the crawler also
        # saved every parent node, whose content is just the union of its
        # children's. Those are expected and skipped, not anomalies — only a
        # dir matching neither a leaf nor a branch is a real warning.
        branch_names = set()
        for n in nodes:
            if n['is_leaf']:
                continue
            s = sanitize_label(n['label'])
            branch_names.add(s)
            if n['gid']:
                branch_names.add(f'{s} (gid {n["gid"]})')
        for d in dirs:
            if d in match:
                continue
            if d in branch_names:
                continue          # counted once, at page-handling time
            add_issue(conn, 'parse', 'warn', frame, d, 'dir_unmatched',
                      'crawl dir matches no tree node')
        conn.execute("""
            UPDATE crawl_frames SET n_tree_nodes=?, n_tree_leaves=?, n_dirs=?
            WHERE frame=?""", (len(nodes), len(leaves), len(dirs), frame))
        conn.execute("""INSERT INTO meta(k, v) VALUES (?, ?)
                        ON CONFLICT(k) DO UPDATE SET v=excluded.v""",
                     (f'treegrid:{frame}', sig))
        conn.commit()

    # 2) leaf pages (the heavy part) — pool of pure-function workers
    tree_rows = {}
    for r in conn.execute('SELECT id, frame, matched_dir, gid FROM group_tree '
                          'WHERE matched_dir IS NOT NULL'):
        tree_rows[(r['frame'], r['matched_dir'])] = (r['id'], r['gid'])

    # Branch (non-leaf) nodes also got crawled as pages — their content is the
    # union of their children's, so importing them would duplicate every part.
    # Classify their dirs as intentionally skipped, not as unmatched noise.
    branch_dirs = set()
    for r in conn.execute('SELECT frame, label, gid FROM group_tree WHERE is_leaf=0'):
        s = sanitize_label(r['label'])
        branch_dirs.add((r['frame'], s))
        if r['gid']:
            branch_dirs.add((r['frame'], f'{s} (gid {r["gid"]})'))

    joblist = list(_iter_parse_jobs(src, frames, conn, force=force))
    log(f'parse: {len(joblist)} pages to parse (jobs={jobs})')
    done = 0
    t0 = time.time()

    def handle(frame, d, rel, mtime_ns, size, out):
        nonlocal done
        key = (frame, d)
        tr = tree_rows.get(key)
        status = out['status']
        if tr is None:
            if key in branch_dirs:
                add_issue(conn, 'parse', 'info', frame, d, 'branch_page_skipped',
                          'branch-node page; children carry the same parts')
            else:
                add_issue(conn, 'parse', 'warn', frame, d, 'page_without_tree_leaf')
        else:
            row_id, tree_gid = tr
            conn.execute('DELETE FROM part_rows WHERE section_id IN '
                         '(SELECT id FROM sections WHERE tree_row=?)', (row_id,))
            conn.execute('DELETE FROM section_labels WHERE section_id IN '
                         '(SELECT id FROM sections WHERE tree_row=?)', (row_id,))
            conn.execute('DELETE FROM sections WHERE tree_row=?', (row_id,))
            # Re-parsing one page must also retire the issues it raised last
            # time, or a since-fixed hard issue would block --stage build forever.
            conn.execute("DELETE FROM issues WHERE stage='parse' AND frame=? AND ref=?",
                         (frame, d))
            if status == 'ok':
                if out.get('gid') and tree_gid and out['gid'] != tree_gid:
                    add_issue(conn, 'parse', 'hard', frame, d, 'gid_mismatch',
                              f"page gid {out['gid']} != tree gid {tree_gid}")
                    status = 'parse_error'
            if status == 'ok':
                n_rows_total = 0
                for si, sec in enumerate(out['sections']):
                    img = sec['image_file']
                    exists = 1 if (img and (assets_dir / img).is_file()) else 0
                    cur = conn.execute("""
                        INSERT INTO sections(tree_row, section_index, container_id,
                            figure_code, image_file, image_exists, caption, n_rows)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (row_id, si, sec['container_id'], sec['figure_code'],
                          img, exists, sec['caption'], len(sec['rows'])))
                    sec_id = cur.lastrowid
                    for row in sec['rows']:
                        qty, qty_display, is_xref, valid, reason = classify_row(row)
                        conn.execute("""
                            INSERT INTO part_rows(section_id, row_index, callout, pn,
                                pn_display, name_en, note, qty_raw, qty, qty_display,
                                date_range, is_xref, valid, invalid_reason)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (sec_id, row['row_index'], row['callout'], row['pn'],
                              row['pn_display'], row['name_en'], row['note'],
                              row['qty_raw'], qty, qty_display, row['date_range'],
                              1 if is_xref else 0, 1 if valid else 0, reason))
                    for lab in sec.get('labels', []):
                        conn.execute("""
                            INSERT INTO section_labels(section_id, code, x, y, w, h, title)
                            VALUES (?,?,?,?,?,?,?)
                        """, (sec_id, lab['code'], lab['x'], lab['y'],
                              lab['w'], lab['h'], lab['title']))
                    n_rows_total += len(sec['rows'])
                conn.execute("""
                    UPDATE group_tree SET page_status='ok', category=?, n_sections=?, n_rows=?
                    WHERE id=?""", (out['category'], len(out['sections']),
                                    n_rows_total, row_id))
            else:
                conn.execute('UPDATE group_tree SET page_status=? WHERE id=?',
                             (status, row_id))
                if status == 'parse_error':
                    add_issue(conn, 'parse', 'hard', frame, d, 'parse_error',
                              out.get('error', ''))
        conn.execute("""
            INSERT INTO parsed_pages(page_path, mtime_ns, size, status)
            VALUES (?,?,?,?)
            ON CONFLICT(page_path) DO UPDATE SET mtime_ns=excluded.mtime_ns,
                size=excluded.size, status=excluded.status
        """, (rel, mtime_ns, size, status))
        done += 1
        if done % 500 == 0:
            conn.commit()
            rate = done / max(time.time() - t0, 1e-6)
            log(f'  parsed {done}/{len(joblist)} ({rate:.1f}/s)')

    if jobs and jobs > 1 and len(joblist) > 50:
        ctx = multiprocessing.get_context('spawn')
        with ctx.Pool(processes=jobs) as pool:
            for frame, d, rel, mtime_ns, size, out in pool.imap_unordered(
                    _parse_one, joblist, chunksize=16):
                handle(frame, d, rel, mtime_ns, size, out)
    else:
        for job in joblist:
            handle(*_parse_one(job))
    conn.commit()
    log(f'parse: done ({done} pages in {time.time() - t0:.0f}s)')
    return done


# ---------------------------------------------------------------------------
# Stage: validate — gates + reports
# ---------------------------------------------------------------------------

def _q1(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def stage_validate(conn, src, report_dir, log=print):
    rd = Path(report_dir)
    rd.mkdir(parents=True, exist_ok=True)
    conn.execute("DELETE FROM issues WHERE stage='validate'")

    stats = {
        'frames': _q1(conn, 'SELECT COUNT(*) FROM crawl_frames'),
        'tree_nodes': _q1(conn, 'SELECT COUNT(*) FROM group_tree'),
        'tree_leaves': _q1(conn, 'SELECT COUNT(*) FROM group_tree WHERE is_leaf=1'),
        'pages_ok': _q1(conn, "SELECT COUNT(*) FROM group_tree WHERE page_status='ok'"),
        'pages_cloudflare': _q1(conn, "SELECT COUNT(*) FROM group_tree WHERE page_status='cloudflare'"),
        'pages_empty': _q1(conn, "SELECT COUNT(*) FROM group_tree WHERE page_status='empty_page'"),
        'pages_no_content': _q1(conn, "SELECT COUNT(*) FROM group_tree WHERE page_status='no_content'"),
        'pages_parse_error': _q1(conn, "SELECT COUNT(*) FROM group_tree WHERE page_status='parse_error'"),
        'pages_no_page': _q1(conn, "SELECT COUNT(*) FROM group_tree WHERE page_status='no_page' AND is_leaf=1"),
        'branch_pages_skipped': _q1(conn, "SELECT COUNT(*) FROM issues WHERE code='branch_page_skipped'"),
        'rows_qty_as_required': _q1(conn, "SELECT COUNT(*) FROM part_rows WHERE qty_display='X'"),
        'sections': _q1(conn, 'SELECT COUNT(*) FROM sections'),
        'sections_missing_image': _q1(conn, 'SELECT COUNT(*) FROM sections WHERE image_exists=0'),
        'rows_total': _q1(conn, 'SELECT COUNT(*) FROM part_rows'),
        'rows_valid': _q1(conn, 'SELECT COUNT(*) FROM part_rows WHERE valid=1 AND is_xref=0'),
        'rows_xref': _q1(conn, 'SELECT COUNT(*) FROM part_rows WHERE is_xref=1'),
        'rows_excluded': _q1(conn, 'SELECT COUNT(*) FROM part_rows WHERE valid=0'),
        'distinct_pns': _q1(conn, 'SELECT COUNT(DISTINCT pn) FROM part_rows WHERE valid=1'),
    }
    for code, n in conn.execute("""
        SELECT invalid_reason, COUNT(*) FROM part_rows WHERE valid=0
        GROUP BY invalid_reason"""):
        stats[f'excluded_{code}'] = n

    # HARD: duplicate (frame, gid)
    for r in conn.execute("""
        SELECT frame, gid, COUNT(*) c FROM group_tree
        WHERE gid IS NOT NULL AND is_leaf=1 GROUP BY frame, gid HAVING c > 1"""):
        add_issue(conn, 'validate', 'hard', r['frame'], str(r['gid']),
                  'dup_gid', f"{r['c']} tree leaves share gid")

    # HARD: duplicate sibling titles among servable leaves (breaks ?seg walk) —
    # resolved at build by suffixing " (gid)" but recorded here.
    for r in conn.execute("""
        SELECT frame, COALESCE(parent_tree_id, -1) p, label, COUNT(*) c
        FROM group_tree WHERE page_status='ok'
        GROUP BY frame, p, label HAVING c > 1"""):
        add_issue(conn, 'validate', 'warn', r['frame'], r['label'],
                  'dup_sibling_title', f"{r['c']} siblings share the title (gid-suffixed at build)")

    # Duplicate identical rows inside one section (true duplicates)
    for r in conn.execute("""
        SELECT s.tree_row, p.section_id, p.pn, p.callout, COUNT(*) c
        FROM part_rows p JOIN sections s ON s.id = p.section_id
        WHERE p.valid=1
        GROUP BY p.section_id, p.pn, p.callout, p.name_en, p.note, p.qty_raw, p.date_range
        HAVING c > 1 LIMIT 200"""):
        add_issue(conn, 'validate', 'warn', '', f"section {r['section_id']}",
                  'dup_row', f"pn {r['pn']} callout {r['callout']} x{r['c']}")

    # WARN: outlier quantities
    for r in conn.execute('SELECT id, pn, qty FROM part_rows WHERE qty > 20 LIMIT 100'):
        add_issue(conn, 'validate', 'warn', '', f"row {r['id']}", 'qty_outlier',
                  f"pn {r['pn']} qty {r['qty']}")

    conn.commit()
    hard = _q1(conn, "SELECT COUNT(*) FROM issues WHERE stage IN ('parse','validate') AND severity='hard'")
    stats['hard_issues'] = hard

    # Coverage per vehicle
    per_vehicle = []
    for r in conn.execute("""
        SELECT f.vehicle_name, f.vehicle_year, COUNT(DISTINCT f.frame) frames,
               SUM(CASE WHEN g.page_status='ok' THEN 1 ELSE 0 END) groups_ok,
               SUM(CASE WHEN g.page_status IN ('cloudflare','empty_page','no_content') THEN 1 ELSE 0 END) groups_cf,
               SUM(CASE WHEN g.page_status IN ('parse_error','no_page') THEN 1 ELSE 0 END) groups_bad
        FROM crawl_frames f LEFT JOIN group_tree g ON g.frame = f.frame AND g.is_leaf=1
        GROUP BY f.vehicle_name ORDER BY f.vehicle_year, f.vehicle_name"""):
        per_vehicle.append(dict(r))

    sample = [dict(r) for r in conn.execute("""
        SELECT p.pn, p.pn_display, p.name_en, p.callout, p.qty, p.note, p.date_range
        FROM part_rows p WHERE p.valid=1 ORDER BY RANDOM() LIMIT 50""")]

    report = {'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
              'stats': stats, 'per_vehicle': per_vehicle, 'sample_rows': sample}
    (rd / 'validate.json').write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                      encoding='utf-8')

    lines = ['# Parts import — validation report', '',
             f"Generated: {report['generated_at']}", '', '## Totals', '']
    for k, v in stats.items():
        lines.append(f'- {k}: {v}')
    lines += ['', '## Per vehicle', '',
              '| vehicle | year | frames | groups ok | fetch-failed | bad |',
              '|---|---|---|---|---|---|']
    for v in per_vehicle:
        lines.append(f"| {v['vehicle_name']} | {v['vehicle_year']} | {v['frames']} "
                     f"| {v['groups_ok'] or 0} | {v['groups_cf'] or 0} | {v['groups_bad'] or 0} |")
    lines += ['', '## Issue summary', '']
    for r in conn.execute("""
        SELECT stage, severity, code, COUNT(*) c FROM issues
        GROUP BY stage, severity, code ORDER BY severity, c DESC"""):
        lines.append(f"- [{r['severity']}] {r['stage']}/{r['code']}: {r['c']}")
    lines += ['', '## Random sample (50 valid rows)', '']
    for s in sample[:50]:
        lines.append(f"- {s['pn_display']} | {s['name_en']} | callout {s['callout']} "
                     f"| qty {s['qty']} | {s['note'][:40]} | {s['date_range']}")
    (rd / 'validate.md').write_text('\n'.join(lines), encoding='utf-8')
    log(f"validate: {stats['rows_valid']} valid rows, {stats['rows_xref']} xref, "
        f"{stats['rows_excluded']} excluded, {stats['sections_missing_image']} sections w/o image, "
        f"{hard} hard issues")
    return stats


# ---------------------------------------------------------------------------
# Stage: build — per-vehicle serving DBs + shared assets
# ---------------------------------------------------------------------------

VEHICLE_DB_SCHEMA = """
CREATE TABLE nodes (
    id TEXT PRIMARY KEY, parent_id TEXT, path TEXT NOT NULL, title TEXT NOT NULL,
    node_type TEXT, file_type TEXT, href TEXT, source_file TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0, depth INTEGER NOT NULL DEFAULT 0,
    root_order INTEGER, content TEXT, updated_at TEXT,
    frame TEXT, group_id INTEGER
);
CREATE INDEX idx_nodes_parent ON nodes(frame, parent_id, sort_order);
CREATE INDEX idx_nodes_path ON nodes(path);
CREATE TABLE frames (
    code TEXT PRIMARY KEY, engine TEXT, transmission TEXT, steering TEXT,
    destination TEXT, grade TEXT, region TEXT, date_from TEXT, date_to TEXT,
    sort_order INTEGER, is_default INTEGER DEFAULT 0,
    n_groups INTEGER DEFAULT 0, n_parts INTEGER DEFAULT 0
);
CREATE TABLE groups (
    id INTEGER PRIMARY KEY, frame TEXT NOT NULL, gid INTEGER, label TEXT,
    category TEXT, category_fa TEXT, node_id TEXT
);
CREATE INDEX idx_groups_frame ON groups(frame);
CREATE TABLE sections (
    id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id),
    section_index INTEGER, figure_code TEXT, image_url TEXT, caption TEXT
);
CREATE INDEX idx_sections_group ON sections(group_id, section_index);
CREATE TABLE part_rows (
    id INTEGER PRIMARY KEY, section_id INTEGER NOT NULL REFERENCES sections(id),
    row_index INTEGER, callout TEXT, pn TEXT, pn_display TEXT,
    name_en TEXT, name_fa TEXT, qty INTEGER, qty_display TEXT,
    note TEXT, date_range TEXT,
    is_xref INTEGER DEFAULT 0
);
CREATE INDEX idx_rows_section2 ON part_rows(section_id, row_index);
CREATE INDEX idx_rows_pn ON part_rows(pn);
CREATE TABLE section_labels (
    id INTEGER PRIMARY KEY, section_id INTEGER NOT NULL REFERENCES sections(id),
    code TEXT, x INTEGER, y INTEGER, w INTEGER, h INTEGER, title TEXT
);
CREATE INDEX idx_labels_section2 ON section_labels(section_id);
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
"""


def _term_pairs(data):
    """Yield (en, fa) from any shape the terminology store has used.

    The generated store is ``{version, generated_at, count, entries, fa_terms}``
    with ``entries`` a list of ``[en, fa]`` pairs — NOT a flat mapping, so the
    envelope keys must never be walked as if they were terms.
    """
    if isinstance(data, dict):
        entries = data.get('entries')
        if isinstance(entries, list):
            for row in entries:
                if isinstance(row, (list, tuple)) and len(row) >= 2:
                    yield row[0], row[1]
                elif isinstance(row, dict):
                    yield row.get('en'), row.get('fa')
            return
        # a genuinely flat {en: fa} mapping (older/hand-made files)
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                yield k, v
    elif isinstance(data, list):
        for row in data:
            if isinstance(row, dict):
                yield row.get('en'), row.get('fa')
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                yield row[0], row[1]


def load_fa_terms(backend_dir):
    """EN->FA exact-match dictionary from the terminology store (best-effort)."""
    out = {}
    generated = Path(backend_dir) / 'Database_warehouse' / '_rag' / 'terms_en_fa.json'
    book = Path(backend_dir).parent / 'Book1.csv'
    if generated.is_file():
        try:
            for en, fa in _term_pairs(json.loads(generated.read_text(encoding='utf-8'))):
                if en and fa and isinstance(en, str) and isinstance(fa, str):
                    out[nfkc(en).lower()] = fa.strip()
        except (json.JSONDecodeError, OSError, TypeError):
            pass
    if book.is_file():
        try:
            with open(book, encoding='utf-8-sig', newline='') as fh:
                for row in csv.reader(fh):
                    if len(row) >= 2 and row[0].strip() and row[1].strip():
                        out.setdefault(nfkc(row[0]).lower(), row[1].strip())
        except OSError:
            pass
    return out


def _frame_sort_key(fr):
    # LHD first, then explicit general markets, then code
    steering = (fr['steering'] or '').upper()
    return (0 if steering == 'LHD' else 1, fr['frame'])


def build_vehicle_db(conn, src, vehicle, out_path, media_prefix, fa_terms,
                     copy_asset, log=print):
    """Build ONE vehicle serving DB from staging. Returns counts dict."""
    frames = conn.execute("""
        SELECT * FROM crawl_frames WHERE vehicle_name=? ORDER BY frame
    """, (vehicle,)).fetchall()
    if not frames:
        raise ValueError(f'no frames for vehicle {vehicle}')
    car_name = vehicle
    tmp = Path(str(out_path) + '.tmp')
    if tmp.exists():
        tmp.unlink()
    vdb = sqlite3.connect(tmp)
    vdb.executescript(VEHICLE_DB_SCHEMA)
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    counts = {'frames': 0, 'groups': 0, 'sections': 0, 'rows': 0, 'xref_rows': 0,
              'pruned_groups': 0, 'pruned_sections': 0}
    ordered = sorted((dict(f) for f in frames), key=_frame_sort_key)
    next_group_id = 1

    for f_order, fr in enumerate(ordered):
        frame = fr['frame']
        tree = conn.execute("""
            SELECT * FROM group_tree WHERE frame=? ORDER BY sort_order
        """, (frame,)).fetchall()
        nodes = {r['tree_id']: dict(r) for r in tree}
        children = {}
        for r in tree:
            children.setdefault(r['parent_tree_id'], []).append(r['tree_id'])

        # servable leaf = page ok + >=1 section with image + >=1 kept row
        servable = {}
        for r in tree:
            if not r['is_leaf'] or r['page_status'] != 'ok':
                continue
            secs = conn.execute("""
                SELECT s.id, s.section_index, s.figure_code, s.image_file,
                       s.image_exists, s.caption
                FROM sections s WHERE s.tree_row=? ORDER BY s.section_index
            """, (r['id'],)).fetchall()
            keep = []
            for s in secs:
                if not s['image_exists']:
                    counts['pruned_sections'] += 1
                    continue
                rows = conn.execute("""
                    SELECT * FROM part_rows WHERE section_id=? AND (valid=1 OR is_xref=1)
                    ORDER BY row_index
                """, (s['id'],)).fetchall()
                if not rows:
                    counts['pruned_sections'] += 1
                    continue
                labels = conn.execute("""
                    SELECT code, x, y, w, h, title FROM section_labels
                    WHERE section_id=? ORDER BY id
                """, (s['id'],)).fetchall()
                keep.append((s, rows, labels))
            if keep:
                servable[r['tree_id']] = keep
            else:
                counts['pruned_groups'] += 1

        if not servable:
            continue

        # Keep ancestors of servable leaves. A parent id with no row of its own
        # (possible when the source tree references a node it never rendered)
        # must NOT enter keep_ids — every consumer below indexes `nodes`.
        keep_ids = set()
        for tid in servable:
            cur = tid
            while cur is not None and cur in nodes and cur not in keep_ids:
                keep_ids.add(cur)
                cur = nodes[cur]['parent_tree_id']

        # sibling title dedupe (seg walk matches by (parent, title))
        titles = {}
        for tid in keep_ids:
            n = nodes[tid]
            key = (n['parent_tree_id'], n['label'])
            titles.setdefault(key, []).append(tid)
        display_title = {}
        for (_p, label), ids in titles.items():
            if len(ids) == 1:
                display_title[ids[0]] = label
            else:
                for tid in sorted(ids, key=lambda t: nodes[t]['sort_order']):
                    g = nodes[tid]['gid']
                    display_title[tid] = f'{label} ({g})' if g else f'{label} #{tid}'

        def emit(tree_id, parent_node_path, parent_node_id, depth):
            nonlocal next_group_id
            n = nodes[tree_id]
            title = display_title[tree_id]
            path = f'{parent_node_path}/{title}'
            node_id = sha1(path)
            is_leaf = tree_id in servable
            kids = [k for k in children.get(tree_id, []) if k in keep_ids]
            vdb.execute("""
                INSERT INTO nodes(id, parent_id, path, title, node_type, file_type,
                    href, source_file, sort_order, depth, root_order, content,
                    updated_at, frame, group_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (node_id, parent_node_id, path, title,
                  # leaves are 'leaf' even at depth 1 (a top-level group with a
                  # page is real content, not a folder); non-leaf depth-1 nodes
                  # keep the manuals' 'root' convention.
                  'leaf' if is_leaf else ('root' if depth == 1 else 'folder'),
                  'parts_group' if is_leaf else 'parts_folder',
                  None, f'{frame}/_groups/{n["matched_dir"] or ""}',
                  n['sort_order'], depth, n['sort_order'] if depth == 1 else None,
                  None, now, frame, next_group_id if is_leaf else None))
            if is_leaf:
                gid_row = next_group_id
                next_group_id += 1
                vdb.execute("""
                    INSERT INTO groups(id, frame, gid, label, category, category_fa, node_id)
                    VALUES (?,?,?,?,?,?,?)
                """, (gid_row, frame, n['gid'], n['label'], n['category'],
                      CATEGORY_FA.get(n['category'] or '', ''), node_id))
                counts['groups'] += 1
                for s, rows, labels in servable[tree_id]:
                    copy_asset(s['image_file'])
                    cur = vdb.execute("""
                        INSERT INTO sections(group_id, section_index, figure_code,
                            image_url, caption)
                        VALUES (?,?,?,?,?)
                    """, (gid_row, s['section_index'], s['figure_code'],
                          f'{media_prefix}/{s["image_file"]}', s['caption']))
                    sec_id = cur.lastrowid
                    counts['sections'] += 1
                    for row in rows:
                        name_fa = fa_terms.get(nfkc(row['name_en']).lower()) if row['name_en'] else None
                        vdb.execute("""
                            INSERT INTO part_rows(section_id, row_index, callout, pn,
                                pn_display, name_en, name_fa, qty, qty_display,
                                note, date_range, is_xref)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (sec_id, row['row_index'], row['callout'], row['pn'],
                              row['pn_display'], row['name_en'], name_fa,
                              row['qty'], row['qty_display'], row['note'],
                              row['date_range'], row['is_xref']))
                        counts['rows'] += 1
                        if row['is_xref']:
                            counts['xref_rows'] += 1
                    for lab in labels:
                        vdb.execute("""
                            INSERT INTO section_labels(section_id, code, x, y, w, h, title)
                            VALUES (?,?,?,?,?,?,?)
                        """, (sec_id, lab['code'], lab['x'], lab['y'],
                              lab['w'], lab['h'], lab['title']))
            for k in sorted(kids, key=lambda t: nodes[t]['sort_order']):
                emit(k, path, node_id, depth + 1)

        root_path = f'{car_name}/{frame}'
        root_id = sha1(root_path)
        vdb.execute("""
            INSERT INTO nodes(id, parent_id, path, title, node_type, file_type,
                href, source_file, sort_order, depth, root_order, content,
                updated_at, frame, group_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (root_id, None, root_path, frame, None, 'root_path', None, None,
              f_order, 0, f_order, None, now, frame, None))
        top = [t for t in children.get(None, []) if t in keep_ids]
        for t in sorted(top, key=lambda x: nodes[x]['sort_order']):
            emit(t, root_path, root_id, 1)

        n_parts = vdb.execute(
            'SELECT COUNT(*) FROM part_rows p JOIN sections s ON s.id=p.section_id '
            'JOIN groups g ON g.id=s.group_id WHERE g.frame=?', (frame,)).fetchone()[0]
        n_groups = vdb.execute('SELECT COUNT(*) FROM groups WHERE frame=?', (frame,)).fetchone()[0]
        vdb.execute("""
            INSERT INTO frames(code, engine, transmission, steering, destination,
                grade, region, date_from, date_to, sort_order, is_default,
                n_groups, n_parts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (frame, fr['engine'], fr['transmission'], fr['steering'],
              fr['destination'], fr['grade'], fr['region'], fr['date_from'],
              fr['date_to'], f_order, 1 if f_order == 0 else 0,
              n_groups, n_parts))
        counts['frames'] += 1

    for k, v in [('schema_version', SCHEMA_VERSION), ('built_at', now),
                 ('source', str(src)), ('car_name', car_name),
                 ('counts', json.dumps(counts))]:
        vdb.execute('INSERT INTO meta(k, v) VALUES (?,?)', (k, json.dumps(v) if not isinstance(v, str) else v))
    vdb.commit()
    vdb.close()
    # os.replace is atomic and overwrites: readers always see either the old
    # DB or the new one, never a missing file (unlink-then-rename had a gap).
    os.replace(tmp, out_path)
    log(f'  built {Path(out_path).name}: {counts}')
    return counts


def stage_build(conn, src, backend_dir, report_dir, vehicles_filter=None, log=print):
    backend = Path(backend_dir)
    parts_dir = backend / 'Database_warehouse' / '_parts'
    parts_dir.mkdir(parents=True, exist_ok=True)
    assets_out = backend / 'static_warehouse' / '_parts_assets'
    assets_out.mkdir(parents=True, exist_ok=True)
    assets_src = Path(src) / 'downloads' / '_assets'
    fa_terms = load_fa_terms(backend)
    log(f'build: fa term dictionary entries: {len(fa_terms)}')

    copied = set()

    def copy_asset(name):
        """Copy a diagram once. Size is compared, not mere existence: a
        truncated file left by an interrupted run must be replaced, otherwise
        the audit's is_file() image gate would bless a half-written GIF."""
        if not name or name in copied:
            return
        src_file = assets_src / name
        dst = assets_out / name
        try:
            if not dst.exists() or dst.stat().st_size != src_file.stat().st_size:
                tmp_dst = dst.with_suffix(dst.suffix + '.part')
                shutil.copy2(src_file, tmp_dst)
                os.replace(tmp_dst, dst)
        except OSError as e:
            log(f'  WARN asset copy failed {name}: {e}')
            return
        copied.add(name)

    vehicles = [r[0] for r in conn.execute(
        'SELECT DISTINCT vehicle_name FROM crawl_frames ORDER BY vehicle_name')]
    if vehicles_filter:
        vehicles = [v for v in vehicles if v in vehicles_filter]
    # A full build owns the whole _parts dir: a DB left over from an earlier
    # vehicle naming would otherwise stay catalogued and served forever.
    if not vehicles_filter:
        current = {f'{v}.db' for v in vehicles}
        for stale in parts_dir.glob('*.db'):
            if stale.name not in current:
                stale.rename(stale.with_suffix('.db.stale'))
                log(f'  retired stale vehicle DB: {stale.name}')

    results = {}
    for v in vehicles:
        out_path = parts_dir / f'{v}.db'
        results[v] = build_vehicle_db(conn, src, v, out_path,
                                      '/media/_parts_assets', fa_terms,
                                      copy_asset, log=log)
    (Path(report_dir) / 'build.json').write_text(
        json.dumps({'built_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'vehicles': results, 'assets_copied': len(copied)},
                   ensure_ascii=False, indent=1), encoding='utf-8')
    log(f'build: {len(results)} vehicles, {len(copied)} assets copied')
    return results


# ---------------------------------------------------------------------------
# Stage: catalog — Car rows (Django ORM; lazy imports)
# ---------------------------------------------------------------------------

def stage_catalog(conn, backend_dir, log=print):
    from .models import Car          # noqa: lazy Django import
    from . import cardb
    parts_dir = Path(backend_dir) / 'Database_warehouse' / '_parts'
    created = []
    for r in conn.execute("""
        SELECT DISTINCT vehicle_name, vehicle_year FROM crawl_frames
        ORDER BY vehicle_year, vehicle_name"""):
        name, year = r['vehicle_name'], r['vehicle_year']
        if not (parts_dir / f'{name}.db').is_file():
            log(f'  catalog: skip {name} (no built DB)')
            continue
        car, was_created = Car.objects.get_or_create(
            brand_name='Toyota', car_name=name, year=year,
            defaults={'db_address': ''})
        created.append({'id': car.id, 'car_name': name, 'year': year,
                        'created': was_created})
    cardb.invalidate_ready_cache()
    log(f'catalog: {len(created)} vehicles registered '
        f'({sum(1 for c in created if c["created"])} new)')
    return created


# ---------------------------------------------------------------------------
# Stage: audit — re-prove gates against the BUILT artifacts
# ---------------------------------------------------------------------------

def stage_audit(conn, backend_dir, report_dir, log=print):
    backend = Path(backend_dir)
    parts_dir = backend / 'Database_warehouse' / '_parts'
    assets_out = backend / 'static_warehouse' / '_parts_assets'
    summary = {'audited_at': time.strftime('%Y-%m-%d %H:%M:%S'),
               'vehicles': {}, 'ok': True}
    for dbf in sorted(parts_dir.glob('*.db')):
        v = dbf.stem
        vdb = sqlite3.connect(f'file:{dbf}?mode=ro', uri=True)
        vdb.row_factory = sqlite3.Row
        problems = []
        n_frames = vdb.execute('SELECT COUNT(*) FROM frames').fetchone()[0]
        n_groups = vdb.execute('SELECT COUNT(*) FROM groups').fetchone()[0]
        n_sections = vdb.execute('SELECT COUNT(*) FROM sections').fetchone()[0]
        n_rows = vdb.execute('SELECT COUNT(*) FROM part_rows').fetchone()[0]
        n_xref = vdb.execute('SELECT COUNT(*) FROM part_rows WHERE is_xref=1').fetchone()[0]
        # gate: every non-xref row has pn + a published quantity + name
        # (qty_display='X' is the EPC's legitimate "as required" quantity)
        bad = vdb.execute("""
            SELECT COUNT(*) FROM part_rows
            WHERE is_xref=0 AND (pn IS NULL OR pn=''
                                 OR qty_display IS NULL OR qty_display=''
                                 OR name_en IS NULL OR name_en='')""").fetchone()[0]
        if bad:
            problems.append(f'{bad} published rows missing pn/qty/name')
        # gate: every section image exists on disk
        missing_img = 0
        for r in vdb.execute('SELECT image_url FROM sections'):
            fn = r['image_url'].rsplit('/', 1)[-1]
            if not (assets_out / fn).is_file():
                missing_img += 1
        if missing_img:
            problems.append(f'{missing_img} sections with missing image files')
        # gate: every section has >=1 row; every group >=1 section
        empty_sec = vdb.execute("""
            SELECT COUNT(*) FROM sections s
            WHERE NOT EXISTS (SELECT 1 FROM part_rows p WHERE p.section_id=s.id)""").fetchone()[0]
        if empty_sec:
            problems.append(f'{empty_sec} empty sections')
        empty_grp = vdb.execute("""
            SELECT COUNT(*) FROM groups g
            WHERE NOT EXISTS (SELECT 1 FROM sections s WHERE s.group_id=g.id)""").fetchone()[0]
        if empty_grp:
            problems.append(f'{empty_grp} empty groups')
        # gate: folder nodes must have children; sibling titles unique
        orphan_folders = vdb.execute("""
            SELECT COUNT(*) FROM nodes n
            WHERE n.node_type IN ('root','folder') AND n.depth >= 1
              AND NOT EXISTS (SELECT 1 FROM nodes c WHERE c.parent_id = n.id)""").fetchone()[0]
        if orphan_folders:
            problems.append(f'{orphan_folders} childless folder nodes')
        dup_titles = vdb.execute("""
            SELECT COUNT(*) FROM (
                SELECT frame, parent_id, title, COUNT(*) c FROM nodes
                GROUP BY frame, parent_id, title HAVING c > 1)""").fetchone()[0]
        if dup_titles:
            problems.append(f'{dup_titles} duplicate sibling titles')
        vdb.close()
        summary['vehicles'][v] = {
            'frames': n_frames, 'groups': n_groups, 'sections': n_sections,
            'rows': n_rows, 'xref_rows': n_xref, 'problems': problems}
        if problems:
            summary['ok'] = False
        log(f'  audit {v}: frames={n_frames} groups={n_groups} sections={n_sections} '
            f'rows={n_rows} problems={problems or "none"}')
    (parts_dir / 'report_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    (Path(report_dir) / 'audit.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    log(f'audit: ok={summary["ok"]}')
    return summary
