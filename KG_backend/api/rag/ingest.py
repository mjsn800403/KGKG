"""Stage 1: scan every car (read-only), deduplicate page content by hash, and
populate the unified index.

For each leaf page:
  * hash its cleaned text;
  * the FIRST time a hash is seen -> create one `blob`, clean + chunk it, write
    chunks + FTS rows (this is the only content we ever embed);
  * EVERY time -> record an `occurrence` (which car / node / breadcrumb / href).

So identical content across the five bZ4X types, or shared between RAV4 and
Corolla, is embedded once but remains addressable from every vehicle it lives in.
"""
import re
import hashlib
from bs4 import BeautifulSoup

from . import config, store


# --- HTML -> clean text -----------------------------------------------------
_WS_RE = re.compile(r'[ \t]+')
_NL_RE = re.compile(r'\n{3,}')
_DATE_WIN_RE = re.compile(r'\[[^\]]*\]')   # "[09/2021 - 11/2022]" model-year windows


def html_to_text(html):
    """Readable plain text from a manual page's HTML. Tables are flattened
    cell-by-cell with separators so spec/torque tables stay searchable."""
    if not html:
        return ''
    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return ''
    for tag in soup(['script', 'style']):
        tag.decompose()
    for table in soup.find_all('table'):
        lines = []
        for tr in table.find_all('tr'):
            cells = [c.get_text(' ', strip=True) for c in tr.find_all(['th', 'td'])]
            cells = [c for c in cells if c]
            if cells:
                lines.append(' | '.join(cells))
        table.replace_with('\n'.join(lines))
    text = soup.get_text('\n')
    text = _WS_RE.sub(' ', text)
    text = _NL_RE.sub('\n\n', text)
    return text.strip()


# --- breadcrumb + classification -------------------------------------------
def build_breadcrumbs(rows):
    """rows: sqlite3.Row with id, parent_id, title -> {node_id: [titles root..self]}."""
    parent, title = {}, {}
    for r in rows:
        parent[r['id']] = r['parent_id']
        title[r['id']] = r['title'] or ''
    crumbs = {}
    for nid in parent:
        chain, cur, seen = [], nid, set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            t = title.get(cur)
            if t:
                chain.append(t)
            cur = parent.get(cur)
        chain.reverse()
        crumbs[nid] = chain
    return crumbs


def classify(chain):
    """Return (kind, comp_readable, comp_key, system_tags) from a breadcrumb.

    The real breadcrumb is [vehicle-root, section-root, component levels..., leaf]
    where vehicle-root is e.g. "Toyota: 2025: bZ4X Nightshade" and section-root is
    "Repair and Diagnosis" | "Labor Times" | ... -- so kind comes from chain[1]
    and the component path from chain[2:].

    kind        : 'labor' | 'repair' | 'other'
    comp_readable: car-independent component path
                   (e.g. "Brakes › Mechanical - Hydraulic › Brake Hose › Remove & Replace")
    comp_key    : normalised (lowercased) component path for grouping.
    system_tags : the shallow component levels, for cheap structural grouping.
    """
    section = (chain[1] if len(chain) > 1 else '').strip().lower()
    if section in config.LABOR_ROOTS:
        kind = 'labor'
    elif section in config.REPAIR_ROOTS:
        kind = 'repair'
    else:
        kind = 'other'

    # component path: everything below the section root. Manual breadcrumbs are
    # heavily cumulative ("Service Data › Service Data › X" and Labor titles like
    # "Brake Hose: Remove & Replace"), so colon-split each level, strip date
    # windows / structural noise, and collapse CONSECUTIVE duplicates.
    comp, prev = [], None
    for seg in chain[2:]:
        s = _DATE_WIN_RE.sub('', seg).strip()
        if not s:
            continue
        for part in s.split(':'):
            p = part.strip()
            pl = p.lower()
            if not p or pl in config._DROP_CRUMB_TOKENS \
                    or pl in config.LABOR_ROOTS or pl in config.REPAIR_ROOTS:
                continue
            if p == prev:
                continue
            comp.append(p)
            prev = p
    comp_readable = ' › '.join(comp)
    comp_key = re.sub(r'\s+', ' ', comp_readable).strip().lower()
    system_tags = ' / '.join(comp[:3])
    return kind, comp_readable, comp_key, system_tags


def _hash(text):
    return hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest()


# --- main ingest pass -------------------------------------------------------
def ingest(index, only_cars=None, log=print):
    """Walk every car DB read-only, dedup page content into blobs (one row per
    unique cleaned page), and record an occurrence for every place each blob
    appears. Resumable builds start from a clean index (use --rebuild).
    Returns a stats dict."""
    files = config.car_db_files()
    if only_cars:
        files = [f for f in files if f.stem in only_cars]

    hash2blob = {r['content_hash']: r['blob_id']
                 for r in index.execute('SELECT content_hash, blob_id FROM blobs')}
    next_blob = (index.execute('SELECT COALESCE(MAX(blob_id),0) FROM blobs').fetchone()[0]) + 1

    n_leaves = n_blobs_new = n_occ = 0
    for f in files:
        stem = f.stem
        meta = config.car_meta(stem)
        src = store.open_car_ro(f)
        try:
            all_rows = src.execute("SELECT id, parent_id, title FROM nodes").fetchall()
            crumbs = build_breadcrumbs(all_rows)
            leaves = src.execute(
                "SELECT id, title, href, content FROM nodes "
                "WHERE content IS NOT NULL AND (href IS NULL OR href != '404.html')"
            ).fetchall()
        finally:
            src.close()

        blob_batch, fts_batch, occ_batch = [], [], []
        for leaf in leaves:
            text = html_to_text(leaf['content'])
            if not text or len(text) < config.MIN_TEXT_CHARS:
                continue
            n_leaves += 1
            h = _hash(text)
            chain = crumbs.get(leaf['id'], [leaf['title'] or ''])
            tpath = ' › '.join(chain)
            kind, comp_readable, comp_key, tags = classify(chain)

            blob_id = hash2blob.get(h)
            if blob_id is None:
                blob_id = next_blob
                next_blob += 1
                hash2blob[h] = blob_id
                n_blobs_new += 1
                title = leaf['title'] or (comp_readable.split(' › ')[-1] if comp_readable else '')
                blob_batch.append((blob_id, h, kind, title, comp_readable, text))
                fts_batch.append((blob_id, text, title, comp_readable))

            occ_batch.append((
                blob_id, stem, meta['brand'], meta['model'], meta['variant'], meta['year'],
                leaf['id'], leaf['title'], tpath, tags, leaf['href'],
            ))
            n_occ += 1

            if len(occ_batch) >= 2000:
                _flush(index, blob_batch, fts_batch, occ_batch)
                blob_batch, fts_batch, occ_batch = [], [], []
        _flush(index, blob_batch, fts_batch, occ_batch)
        log(f"    {stem[:40]:40s} leaves+={len(leaves):6d}  uniq_blobs_total={len(hash2blob):6d}")

    index.execute(
        "UPDATE blobs SET n_occ = (SELECT COUNT(*) FROM occurrences o WHERE o.blob_id = blobs.blob_id)")
    index.commit()
    return {'leaves': n_leaves, 'blobs': len(hash2blob), 'new_blobs': n_blobs_new, 'occ': n_occ}


def _flush(index, blob_batch, fts_batch, occ_batch):
    if blob_batch:
        index.executemany(
            "INSERT INTO blobs(blob_id, content_hash, kind, title, comp_readable, text) "
            "VALUES (?,?,?,?,?,?)", blob_batch)
        index.executemany(
            "INSERT INTO blobs_fts(rowid, text, title, comp) VALUES (?,?,?,?)", fts_batch)
    if occ_batch:
        index.executemany(
            "INSERT INTO occurrences(blob_id, car_stem, brand, model, variant, year, "
            "node_id, title, title_path, system_tags, href) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)", occ_batch)
    index.commit()
