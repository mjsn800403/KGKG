#!/usr/bin/env python3
"""TIS crawl -> car database, the TIS counterpart of ``htmlparser_logical.py``.

Input is one vehicle folder written by the TIS crawler (``toyota_tis.py``)::

    downloads_tis/<Model>_<Year>/<CAT>/<publication>/...     CAT = RM, NCF, CR, EWD, SB_TT, ...
    downloads_tis/_assets/<hash>_<name>                       shared, content-addressed assets

Output is exactly what the LEMON parser produces, so every later pipeline stage
(catalog, schema, RAG, diag, audit) and the car browser read it unchanged:

* ``<stem>.db`` with the same ``nodes`` table (root -> category -> publication
  -> folders -> leaves; leaves carry the page HTML in ``content``);
* the car's images in ``static_warehouse/<stem>/``, referenced from content as
  ``../images/<file>`` (the backend rewrites that to ``/media/<stem>/<file>``);
* manual cross-links rewritten to ``pages/<DocID>.html`` with each leaf's
  ``href`` set to the same, which is the form the backend's link resolver and
  the frontend's link interception already understand.

Tree order and titles come from the crawler's saved sidebar (``_viewer/nav.html``
for manuals, the EWD pub's ``index.html``), i.e. TIS's own order. Pages on disk
that the sidebar does not list are still ingested (appended under their folder),
so nothing crawled is lost. PDF-only publications (bulletins, QTG, accessories)
become one leaf per PDF, linking to the PDF in the car's media folder.

Standalone use:  python tis_parser.py "<vehicle folder>" --out /tmp/out
"""
import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

warnings.filterwarnings('ignore', category=MarkupResemblesLocatorWarning)

BRAND = 'Toyota'
SLASH = '⁄'            # same in-name slash escape as htmlparser_logical

# Category folder -> (display title, order). Anything not listed is ignored
# (Summary/_list are TIS search listings, resources/ewdappu are viewer files).
CATEGORIES = [
    ('RM', 'Repair Manual'),
    ('NCF', 'New Car Features'),
    ('CR', 'Collision Repair Manual'),
    ('EWD', 'Electrical Wiring Diagram'),
    ('SB_TT', 'Service Bulletins'),
    ('SC', 'Special Service Campaigns'),
    ('QTG', 'Quick Training Guides'),
    ('ACCY', 'Accessories'),
]
SKIP_DIRS = {'_list', '_viewer', '_app', 'fig', 'img', 'image', 'images'}
DROP_TAGS = ('script', 'style', 'link', 'meta', 'title', 'head', 'noscript',
             'iframe', 'frame', 'frameset', 'form', 'input', 'button', 'select',
             'textarea', 'object', 'embed')

_VEH_RE = re.compile(r'^(?P<model>.+)_(?P<year>\d{4})$')
_DOCID_RE = re.compile(r'Doc ID:\s*</b>\s*([A-Z0-9]+)', re.I)


def vehicle_meta(vehicle_dir):
    """(brand, year, model) from a ``<Model>_<Year>`` folder name, else None."""
    m = _VEH_RE.match(Path(vehicle_dir).name)
    if not m:
        return None
    return BRAND, int(m.group('year')), m.group('model').strip()


def assets_dir_for(vehicle_dir):
    return Path(vehicle_dir).parent / '_assets'


def content_files(vehicle_dir):
    """Every ingestible page/document under a vehicle (used for readiness and
    change detection): manual pages, EWD leaf pages, PDFs."""
    out = []
    for cat, _ in CATEGORIES:
        root = Path(vehicle_dir) / cat
        if not root.is_dir():
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f == 'content.html' or f.lower().endswith('.pdf') or (
                        cat == 'EWD' and f == 'index.html'):
                    out.append(Path(dirpath) / f)
    return out


def clean_title(text):
    """Undo the crawler's filename sanitising where it is unambiguous
    ('ADAS _ AD' was 'ADAS / AD', 'QT023A_ Multipoint' was 'QT023A: ...') and
    escape real slashes so they never split the logical path."""
    t = re.sub(r'\s+', ' ', text or '').strip()
    t = t.replace(' _ ', ' / ')
    t = re.sub(r'(?<=[\w)])_ ', ': ', t)
    return t.replace('/', SLASH) or '(untitled)'


class TisParser:
    def __init__(self, vehicle_dir, stem, db_path, images_dir, log=None):
        self.vdir = Path(vehicle_dir).resolve()
        self.assets = assets_dir_for(self.vdir).resolve()
        self.stem = stem
        self.db_path = Path(db_path)
        self.images_dir = Path(images_dir)
        self.say = log or (lambda m: None)
        self.rows = {}                 # path -> row
        self.leaf_docid = {}           # resolved page file -> docid
        self.leaves = []               # (path, file, kind)
        self.published = {}            # source file -> published name
        self.media_base = f'/media/{quote(stem)}'

    # ------------------------------------------------------------ tree build
    def _add(self, path, title, node_type, file_type, depth, order,
             root_order=None, href=None, source=None):
        base, n = path, 2
        while path in self.rows:            # sibling title collision
            path = f'{base} ({n})'
            n += 1
        parent = path.rsplit('/', 1)[0] if '/' in path else None
        self.rows[path] = dict(
            id=hashlib.sha1(path.encode('utf-8')).hexdigest(),
            parent_id=(hashlib.sha1(parent.encode('utf-8')).hexdigest()
                       if parent else None),
            path=path, title=title.replace(SLASH, '/'), node_type=node_type,
            file_type=file_type, href=href, source_file=source,
            sort_order=order, depth=depth, root_order=root_order, content=None)
        return path

    def _leaf(self, parent_path, title, order, file, kind):
        path = self._add(f'{parent_path}/{title}', title, 'leaf', 'end_path',
                         parent_path.count('/') + 1, order, source=str(file))
        self.leaves.append((path, Path(file), kind))
        return path

    def _walk_tree(self, node, parent_path, base_dir, kind, seen):
        """Mirror a crawler sidebar (<details><summary>..</summary><div class=grp>
        <a class=leaf ..>) under parent_path. Returns the next sort order."""
        order = 0
        for el in node.find_all(['details', 'a'], recursive=False):
            if el.name == 'details':
                summ = el.find('summary')
                title = clean_title(summ.get_text() if summ else '')
                path = self._add(f'{parent_path}/{title}', title, 'folder',
                                 'intermediate_path', parent_path.count('/') + 1,
                                 order)
                grp = el.find('div', class_='grp', recursive=False) or el
                self._walk_tree(grp, path, base_dir, kind, seen)
                order += 1
            elif 'leaf' in (el.get('class') or []):
                href = el.get('href') or ''
                target = (base_dir / unquote(urlsplit(href).path)).resolve()
                if not target.is_file() or target in seen:
                    continue
                seen.add(target)
                self._leaf(parent_path, clean_title(el.get_text()), order,
                           target, kind)
                order += 1
        return order

    def _orphans(self, pub_dir, pub_path, kind, seen):
        """Pages on disk the sidebar did not list: file them under the node for
        their folder (created on demand), so no crawled page is dropped."""
        added = 0
        name = 'content.html' if kind == 'manual' else 'index.html'
        for f in sorted(pub_dir.rglob(name)):
            f = f.resolve()
            rel = f.parent.relative_to(pub_dir.resolve()).parts
            if f in seen or any(p in SKIP_DIRS for p in rel) or not rel:
                continue
            seen.add(f)
            parent = pub_path
            for seg in rel[:-1]:
                t = clean_title(seg)
                cand = f'{parent}/{t}'
                if cand not in self.rows:
                    self._add(cand, t, 'folder', 'intermediate_path',
                              cand.count('/'), 50_000 + added)
                parent = cand
            self._leaf(parent, clean_title(rel[-1]), 50_000 + added, f, kind)
            added += 1
        return added

    def build_tree(self):
        self._add(self.stem, self.stem, None, 'root_path', 0, 0)
        root_order = 0
        for cat, cat_title in CATEGORIES:
            cdir = self.vdir / cat
            if not cdir.is_dir():
                continue
            pubs = sorted(d for d in cdir.iterdir()
                          if d.is_dir() and d.name not in SKIP_DIRS)
            if not pubs:
                continue
            cpath = self._add(f'{self.stem}/{cat_title}', cat_title, 'root',
                              'intermediate_path', 1, root_order,
                              root_order=root_order)
            root_order += 1
            for porder, pub in enumerate(pubs):
                self._build_pub(cat, pub, cpath, porder)
        # Drop folders that ended up with no leaf below them.
        live = set()
        for path, _f, _k in self.leaves:
            p = path
            while '/' in p:
                p = p.rsplit('/', 1)[0]
                live.add(p)
        for path in [p for p, r in self.rows.items()
                     if r['file_type'] == 'intermediate_path' and p not in live]:
            del self.rows[path]

    def _build_pub(self, cat, pub, cpath, porder):
        ptitle = clean_title(pub.name)
        pdfs = sorted(pub.rglob('*.pdf'))
        nav = pub / '_viewer' / 'nav.html'
        ewd_index = pub / 'index.html'
        if cat == 'EWD' and ewd_index.is_file():
            kind, tree_file, base = 'ewd', ewd_index, pub
        elif nav.is_file():
            kind, tree_file, base = 'manual', nav, nav.parent
        elif pdfs:
            kind, tree_file, base = 'pdf', None, pub
        elif list(pub.rglob('content.html')):
            kind, tree_file, base = 'manual', None, pub
        else:
            return
        ppath = self._add(f'{cpath}/{ptitle}', ptitle, 'folder',
                          'intermediate_path', 2, porder)
        if kind == 'pdf':
            if len(pdfs) == 1:
                # One document per publication: the publication IS the leaf.
                del self.rows[ppath]
                self._leaf(cpath, ptitle, porder, pdfs[0].resolve(), 'pdf')
            else:
                for i, f in enumerate(pdfs):
                    self._leaf(ppath, clean_title(f.stem), i, f.resolve(), 'pdf')
            return
        seen = set()
        if tree_file is not None:
            soup = BeautifulSoup(tree_file.read_text('utf-8', 'replace'),
                                 'html.parser')
            # The tree's sections are the siblings of the first <details>
            # (the EWD viewer wraps them in a sidebar container).
            first = soup.find('details')
            if first is not None:
                self._walk_tree(first.parent, ppath, base, kind, seen)
        n = self._orphans(pub, ppath, kind, seen)
        if n:
            self.say(f'  {ptitle}: {n} page(s) not in the sidebar, filed by folder')

    # ------------------------------------------------------------- content
    def _publish(self, src):
        """Stage a referenced file into the car's image folder and return the
        published name. Crawler assets are already content-addressed
        (<hash>_<name>); anything else (EWD figures, PDFs, whose names repeat
        across cars) gets a content-hash prefix, because the shared image store
        is keyed by filename."""
        src = Path(src)
        name = self.published.get(src)
        if name:
            return name
        if src.parent == self.assets:
            name = src.name
        else:
            h = hashlib.sha1(src.read_bytes()).hexdigest()[:10]
            name = f'{h}_{src.name}'
        dest = self.images_dir / name
        if not dest.exists():
            shutil.copy2(src, dest)
        self.published[src] = name
        return name

    def _resolve_local(self, ref, base_dir):
        """A relative reference -> existing file under the vehicle/assets, or None."""
        if not ref or re.match(r'^[a-z][a-z0-9+.\-]*:', ref, re.I) or ref.startswith('#'):
            return None
        path = unquote(urlsplit(ref).path)
        if not path:
            return None
        target = (base_dir / path).resolve() if not path.startswith('/') else None
        if target is None or not target.is_file():
            return None
        if self.vdir in target.parents or self.assets in target.parents:
            return target
        return None

    def _docid(self, file, html=None):
        if file in self.leaf_docid:
            return self.leaf_docid[file]
        m = _DOCID_RE.search(html) if html else None
        docid = m.group(1) if m else None
        if not docid:
            docid = 'TIS' + hashlib.sha1(
                str(file.relative_to(self.vdir)).encode('utf-8')).hexdigest()[:12].upper()
        self.leaf_docid[file] = docid
        return docid

    def _render(self, file, kind, title):
        if kind == 'pdf':
            name = self._publish(file)
            size = file.stat().st_size / 1048576
            return (f'<h2>{_esc(title)}</h2><p><a href="{self.media_base}/'
                    f'{quote(name)}">{_esc(file.name)}</a> (PDF, {size:.1f} MB)</p>')
        html = file.read_text('utf-8', 'replace')
        soup = BeautifulSoup(html, 'html.parser')
        body = soup.body or soup
        for t in body.find_all(DROP_TAGS):
            t.decompose()
        if kind == 'manual':
            # The TIS metadata header (Last Modified / Doc ID / Model / Title).
            for t in body.find_all('table', class_='side'):
                t.decompose()
        base = file.parent
        for img in body.find_all('img'):
            target = self._resolve_local(img.get('src'), base)
            if target is not None:
                img['src'] = f'../images/{self._publish(target)}'
        for a in body.find_all('a'):
            href = a.get('href')
            if not href:
                continue
            for attr in [k for k in a.attrs if k.lower().startswith('on') or k == 'target']:
                del a[attr]
            if href.lower().startswith(('javascript:', 'http:', 'https:')):
                del a['href']                 # dead / login-gated outside TIS
                continue
            target = self._resolve_local(href, base)
            if target is None:
                continue
            frag = urlsplit(href).fragment
            if target in self.leaf_docid:
                a['href'] = f'pages/{self.leaf_docid[target]}.html' + (f'#{frag}' if frag else '')
            elif target.name in ('content.html', 'index.html'):
                del a['href']                 # a page we did not ingest
            else:
                a['href'] = f'{self.media_base}/{quote(self._publish(target))}'
        for el in body.find_all(True):
            for attr in [k for k in el.attrs if k.lower().startswith('on')]:
                del el[attr]
        return body.decode_contents().strip()

    # ---------------------------------------------------------------- run
    def run(self):
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.build_tree()
        # Doc IDs first, so cross-links can point at pages parsed later.
        raw = {}
        for path, file, kind in self.leaves:
            if kind == 'manual':
                raw[file] = file.read_text('utf-8', 'replace')
                self._docid(file, raw[file])
            else:
                self._docid(file)
        for path, file, kind in self.leaves:
            row = self.rows.get(path)
            if row is None:
                continue
            row['href'] = f'pages/{self.leaf_docid[file]}.html'
            row['content'] = self._render(file, kind, row['title'])
        self._write_db()
        return len(self.leaves)

    def _write_db(self):
        if self.db_path.exists():
            self.db_path.unlink()
        con = sqlite3.connect(self.db_path)
        con.executescript("""
            CREATE TABLE nodes (
                id TEXT PRIMARY KEY, parent_id TEXT, path TEXT NOT NULL,
                title TEXT NOT NULL, node_type TEXT, file_type TEXT, href TEXT,
                source_file TEXT, sort_order INTEGER NOT NULL DEFAULT 0,
                depth INTEGER NOT NULL DEFAULT 0, root_order INTEGER,
                content TEXT, updated_at TEXT);
            CREATE INDEX idx_nodes_parent ON nodes(parent_id, sort_order);
            CREATE INDEX idx_nodes_path   ON nodes(path);
            CREATE INDEX idx_nodes_root   ON nodes(root_order);
            CREATE TABLE crawl_state (k TEXT PRIMARY KEY, v TEXT);
        """)
        now = datetime.now(timezone.utc).isoformat()
        cols = ('id', 'parent_id', 'path', 'title', 'node_type', 'file_type',
                'href', 'source_file', 'sort_order', 'depth', 'root_order',
                'content')
        con.executemany(
            f'INSERT INTO nodes ({",".join(cols)}, updated_at) VALUES '
            f'({",".join("?" * len(cols))}, ?)',
            [tuple(r[c] for c in cols) + (now,) for r in self.rows.values()])
        con.commit()
        con.close()


def _esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def process_vehicle(vehicle_dir, db_warehouse, static_warehouse, stem=None,
                    publish_images=None, log=None):
    """Parse one TIS vehicle folder into the warehouse. Returns the same dict
    as ``htmlparser_logical.process_single_zip`` (brand, year, car_name,
    db_address) plus ``pages``. ``publish_images`` is the LEMON parser's
    hardlinking publisher, so both sources share one image store."""
    meta = vehicle_meta(vehicle_dir)
    if meta is None:
        raise ValueError(f'not a TIS vehicle folder (<Model>_<Year>): {vehicle_dir}')
    brand, year, model = meta
    stem = stem or model
    db_warehouse, static_warehouse = Path(db_warehouse), Path(static_warehouse)
    work = static_warehouse / f'.tis-staging-{os.getpid()}'
    shutil.rmtree(work, ignore_errors=True)
    tmp_db = db_warehouse / f'.{stem}.tis-tmp.db'
    try:
        parser = TisParser(vehicle_dir, stem, tmp_db, work / 'images', log=log)
        pages = parser.run()
        if pages == 0:
            raise ValueError('no pages found in the TIS vehicle folder')
        if publish_images is not None:
            publish_images(work / 'images', static_warehouse / stem, static_warehouse)
        else:
            dest = static_warehouse / stem
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(work / 'images', dest)
        os.replace(tmp_db, db_warehouse / f'{stem}.db')
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if tmp_db.exists():
            tmp_db.unlink()
    return {'brand': brand, 'year': year, 'car_name': stem, 'pages': pages,
            'db_address': f'./Database_warehouse/{stem}.db'}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('vehicle_dir')
    ap.add_argument('--out', required=True, help='folder for <stem>.db and <stem>/ images')
    ap.add_argument('--stem', help='warehouse stem (default: the model name)')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    r = process_vehicle(a.vehicle_dir, out, out, stem=a.stem, log=print)
    print(r)


if __name__ == '__main__':
    main()
