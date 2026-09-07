"""ZIP-inbox ingestion: the bridge between the source downloader and the
processing pipeline.

Until now the two halves of ingestion were disconnected: the downloader
(``kgtv-downloader/downloader.py``) was run by hand and dropped ZIPs in
``/root/downloads``, and the HTML parser (``htmlparser_logical.py``) was run
by hand on a desktop to turn those ZIPs into warehouse ``.db`` files. This
module puts both under pipeline control:

* ``scan_inbox``       — discover vehicle-manual ZIPs in the inbox roots,
  normalize legacy model-only filenames to the ``KGTV <year> <brand>
  <model>.zip`` convention (brand/year read from the ZIP's own inner top-level
  folder, no extraction needed), and register each ZIP as a ``ZipPackage``
  row — the parse queue. A duplicate guard keeps re-downloads of
  already-ingested cars out of the queue.
* ``parse_zip_package`` — run one queued ZIP through the parser into
  ``Database_warehouse``/``static_warehouse`` + the catalog, then clean up the
  extracted tree and intermediate crawl DB (ZIPs themselves are kept as the
  source archive).
* ``execute_download_request`` — fetch a queued ``DownloadRequest`` from the
  upstream source site (with the downloader's own pacing/backoff) and register
  the resulting ZIPs.

The downloader and parser stay standalone-usable scripts; they are loaded
here via importlib from their canonical locations in the project root.
"""
import importlib.util
import os
import re
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.utils import timezone

from .rag import config

PROJECT_ROOT = Path(settings.BASE_DIR).parent          # /opt/KGKG

# Manual bundles are hundreds of MB; anything tiny is not a vehicle manual
# (font archives, npm fixtures, ...) and is ignored by the scanner.
MIN_ZIP_BYTES = 5 * 1024 * 1024

# The parse/download stages refuse to continue when free disk drops below this
# (each ZIP temporarily needs its extracted tree + crawl DB on top of the
# permanent warehouse copy).
DISK_MIN_FREE_GB = float(os.environ.get('KG_PIPELINE_MIN_FREE_GB', '20'))

_INNER_DIR_RE = re.compile(r'^(\d{4})\s+(\S+)\s+(.+)$')   # "<year> <brand> <model>"


def inbox_roots():
    """Directories scanned for vehicle-manual ZIPs (colon-separated env
    override; the first root receives new downloads)."""
    raw = os.environ.get('KG_ZIP_INBOX', '/root/downloads:/root/Downloads')
    return [Path(p).expanduser() for p in raw.split(':') if p.strip()]


def sanitize_filename(name):
    """Same character policy as the downloader (keep names interoperable)."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


# ---------------------------------------------------------------------------
# External script loading (they live outside the Django package on purpose:
# both remain standalone CLI tools)
# ---------------------------------------------------------------------------
_parser_mod = None
_downloader_mod = None


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load {name} from {path}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def parser_module():
    global _parser_mod
    if _parser_mod is None:
        path = os.environ.get('KG_PARSER_PATH',
                              str(PROJECT_ROOT / 'htmlparser_logical.py'))
        _parser_mod = _load_module('kg_htmlparser_logical', path)
    return _parser_mod


def downloader_module():
    global _downloader_mod
    if _downloader_mod is None:
        path = os.environ.get('KG_DOWNLOADER_PATH',
                              str(PROJECT_ROOT / 'kgtv-downloader' / 'downloader.py'))
        _downloader_mod = _load_module('kg_source_downloader', path)
    return _downloader_mod


def warehouse_stem(car_name, year):
    """The parser's stem rule (single source of truth lives in the parser)."""
    return parser_module().warehouse_stem(car_name, year)


# ---------------------------------------------------------------------------
# Disk guard
# ---------------------------------------------------------------------------

def disk_free_gb(path='/'):
    return shutil.disk_usage(path).free / (1024 ** 3)


def check_disk_guard():
    """Raise (and alert) when free disk is below the safety floor — better a
    paused, resumable job than a full disk taking the site down."""
    free = disk_free_gb()
    if free < DISK_MIN_FREE_GB:
        try:
            from . import monitoring
            monitoring._raise_alert(
                'pipeline_disk_low', 'critical',
                f'پردازش بسته‌ها متوقف شد: فضای آزاد دیسک {free:.1f}GB است '
                f'(حداقل لازم {DISK_MIN_FREE_GB:.0f}GB). فضای دیسک را آزاد کنید و ادامه دهید.',
                {'free_gb': round(free, 1), 'min_gb': DISK_MIN_FREE_GB})
        except Exception:
            pass
        raise RuntimeError(
            f'disk free {free:.1f}GB below the {DISK_MIN_FREE_GB:.0f}GB floor')
    return free


# ---------------------------------------------------------------------------
# ZIP inspection / normalization / registration
# ---------------------------------------------------------------------------

def zip_inner_meta(zip_path):
    """(brand, year, car_name) read from the ZIP's inner top-level folder
    ("<year> <brand> <model>/") without extracting. None when unrecognizable
    (not a source manual bundle)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return None
    if not names:
        return None
    prefix = os.path.commonprefix(names)
    if '/' not in prefix:
        return None
    top = prefix.split('/')[0].strip()
    m = _INNER_DIR_RE.match(top)
    if not m:
        return None
    return m.group(2), int(m.group(1)), m.group(3).strip()


def source_zip_name(brand, year, car_name):
    return sanitize_filename(f'KGTV {year} {brand} {car_name}.zip')


def register_zip(path, normalize=False, dry_run=False):
    """Ensure a ZipPackage row for ``path``. Returns (pkg_or_None, action):

    action ∈ 'registered' | 'renamed+registered' | 'kept' | 'refreshed'
             | 'duplicate' | 'unrecognized'.
    The duplicate guard: a ZIP whose target stem already has a warehouse .db,
    or is already covered by another queued/parsed package, is registered as
    ``skipped_duplicate`` so it will never be parsed (re-downloads of ingested
    cars under new filenames stay inert).
    """
    from .models import ZipPackage
    path = Path(path)
    meta = zip_inner_meta(path)
    if meta is None:
        return None, 'unrecognized'
    brand, year, car_name = meta

    renamed = False
    if normalize and not path.name.startswith('KGTV '):
        target = path.with_name(source_zip_name(brand, year, car_name))
        if target != path and not target.exists():
            if not dry_run:
                path.rename(target)
                path = target
            renamed = True
        # target already exists -> keep this file's name; the stem-level
        # duplicate guard below makes it inert anyway.

    stem = warehouse_stem(car_name, year)
    try:
        st = path.stat()
    except OSError:
        return None, 'unrecognized'

    stem_on_disk = (config.WAREHOUSE_DIR / f'{stem}.db').exists()
    queued_elsewhere = (ZipPackage.objects
                        .filter(stem=stem, status__in=('pending', 'parsing', 'done'))
                        .exclude(path=str(path)).exists())
    fresh_status = ('skipped_duplicate' if (stem_on_disk or queued_elsewhere)
                    else 'pending')

    fields = dict(zip_name=path.name, size=st.st_size, mtime=st.st_mtime,
                  brand=brand, year=year, car_name=car_name, stem=stem)

    pkg = ZipPackage.objects.filter(path=str(path)).first()
    if pkg is None:
        action = 'renamed+registered' if renamed else 'registered'
        if fresh_status == 'skipped_duplicate':
            action = 'duplicate'
        if dry_run:
            return None, action
        pkg = ZipPackage.objects.create(path=str(path), status=fresh_status, **fields)
        return pkg, action

    sig_changed = (pkg.size != st.st_size or abs((pkg.mtime or 0) - st.st_mtime) > 1.0)
    if sig_changed:
        if dry_run:
            return pkg, 'refreshed'
        for k, v in fields.items():
            setattr(pkg, k, v)
        pkg.status = fresh_status
        pkg.error = ''
        pkg.save()
        return pkg, 'refreshed'
    return pkg, 'kept'


def scan_inbox(normalize=False, dry_run=False, log=None):
    """Walk the inbox roots, (optionally) normalize legacy filenames, and
    register every vehicle-manual ZIP. Returns a summary dict."""
    from .models import ZipPackage
    say = log or (lambda m: None)
    summary = {'found': 0, 'registered': 0, 'renamed': 0, 'kept': 0,
               'refreshed': 0, 'duplicates': 0, 'unrecognized': [],
               'removed_missing': 0}
    seen = set()
    for root in inbox_roots():
        if not root.exists():
            continue
        for zp in sorted(root.rglob('*.zip')):
            try:
                if zp.stat().st_size < MIN_ZIP_BYTES:
                    continue
            except OSError:
                continue
            summary['found'] += 1
            pkg, action = register_zip(zp, normalize=normalize, dry_run=dry_run)
            if action == 'unrecognized':
                summary['unrecognized'].append(str(zp))
                say(f'?? unrecognized (no "<year> <brand> <model>/" root): {zp}')
                continue
            if action in ('registered', 'renamed+registered'):
                summary['registered'] += 1
                if action == 'renamed+registered':
                    summary['renamed'] += 1
                say(f'++ queued: {pkg.zip_name if pkg else zp.name}')
            elif action == 'duplicate':
                summary['duplicates'] += 1
            elif action == 'refreshed':
                summary['refreshed'] += 1
            if pkg is not None:
                seen.add(pkg.path)
    # Drop pending rows whose file vanished (moved/deleted between scans).
    if not dry_run:
        for pkg in ZipPackage.objects.filter(status='pending'):
            if pkg.path not in seen and not Path(pkg.path).exists():
                summary['removed_missing'] += 1
                pkg.delete()
    return summary


# ---------------------------------------------------------------------------
# Parse one queued ZIP into the warehouse
# ---------------------------------------------------------------------------

def _ledger_row(zip_name):
    try:
        con = sqlite3.connect(
            f"file:{Path(settings.DATABASES['default']['NAME'])}?mode=ro", uri=True)
        try:
            return con.execute(
                'SELECT status, pages_processed, error FROM processing_status '
                'WHERE zip_name = ?', (zip_name,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _cleanup_after_parse(parser, zip_path, log=None):
    """Free the temporary artifacts a successful parse leaves next to the ZIP:
    the extracted HTML tree and the intermediate crawl DB (the warehouse holds
    the durable copy). The ZIP itself is kept as the source archive."""
    say = log or (lambda m: None)
    tree = parser.zip_extract_dir(zip_path, zip_path.parent)
    if tree and tree.exists() and tree != zip_path.parent:
        shutil.rmtree(tree, ignore_errors=True)
        say(f'cleaned extracted tree: {tree.name}')
    crawl_db = zip_path.parent / zip_path.name.replace('KGTV ', '').replace('.zip', '.db')
    for suffix in ('', '-wal', '-shm'):
        p = Path(str(crawl_db) + suffix)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def parse_zip_package(pkg, cancel_event=None, log=None):
    """Run one ZipPackage through the HTML parser into the warehouse.

    Returns 'done' | 'skipped' | 'failed' | 'paused'. On success the catalog
    row is upserted directly with the ZIP's authoritative brand/year (the
    catalog-sync stage remains as a validating backstop), and the temporary
    extraction artifacts are removed.
    """
    from .models import Car
    say = log or (lambda m: None)
    zip_path = Path(pkg.path)
    if not zip_path.exists():
        pkg.status, pkg.error = 'failed', 'zip file missing on disk'
        pkg.save(update_fields=['status', 'error', 'updated_at'])
        return 'failed'

    # Duplicate re-check at execution time (state may have changed since scan).
    if (config.WAREHOUSE_DIR / f'{pkg.stem}.db').exists():
        pkg.status = 'skipped_duplicate'
        pkg.save(update_fields=['status', 'updated_at'])
        say(f'skip (stem already in warehouse): {pkg.stem}')
        return 'skipped'

    parser = parser_module()
    backend_dir = Path(settings.BASE_DIR)
    ledger = parser.ProcessingLedger(backend_dir / 'db.sqlite3')

    pkg.status = 'parsing'
    pkg.save(update_fields=['status', 'updated_at'])

    try:
        result = parser.process_single_zip(
            zip_path, backend_dir, config.WAREHOUSE_DIR,
            backend_dir / 'static_warehouse', zip_path.parent,
            ledger, cancel_event, False)
    except Exception as e:
        pkg.status, pkg.error = 'failed', f'{e.__class__.__name__}: {e}'[:500]
        pkg.save(update_fields=['status', 'error', 'updated_at'])
        return 'failed'

    if cancel_event is not None and cancel_event.is_set():
        # Crawl checkpointed; put the package back in the queue for resume.
        pkg.status = 'pending'
        pkg.save(update_fields=['status', 'updated_at'])
        return 'paused'

    row = _ledger_row(zip_path.name)
    if result is None:
        if row and row[0] == 'completed':
            # Parser skipped it as already fully processed earlier — the
            # warehouse copy exists, so this package is simply done.
            pkg.status, pkg.pages_processed = 'done', int(row[1] or 0)
            pkg.save(update_fields=['status', 'pages_processed', 'updated_at'])
            return 'done'
        pkg.status = 'failed'
        pkg.error = (row[2] if row and row[2] else 'parse produced no result')[:500]
        pkg.save(update_fields=['status', 'error', 'updated_at'])
        return 'failed'

    # Authoritative catalog upsert: brand/year/name come from the ZIP itself.
    # car_name == warehouse stem (the fleet-wide identity invariant).
    Car.objects.update_or_create(
        car_name=result['car_name'],
        defaults={'brand_name': result['brand'], 'year': result['year'],
                  'db_address': result['db_address']})

    _cleanup_after_parse(parser, zip_path, log=say)

    pkg.status = 'done'
    pkg.error = ''
    pkg.pages_processed = int(row[1] or 0) if row else 0
    pkg.save(update_fields=['status', 'error', 'pages_processed', 'updated_at'])
    say(f'parsed into warehouse: {result["car_name"]} ({result["brand"]} {result["year"]})')
    return 'done'


# ---------------------------------------------------------------------------
# Execute a download request
# ---------------------------------------------------------------------------

def list_source(url, name_filter=''):
    """Synchronous listing of a Brand/Year page, annotated with local state.
    Returns {url, vehicles: [{name, bundle_url, downloaded, ingested}]}."""
    dl = downloader_module()
    session = dl.build_session(1)
    url = dl.correct_brand_case(session, url)
    vehicles = dl.get_vehicles(session, url)
    needle = (name_filter or '').strip().lower()
    if needle:
        vehicles = [v for v in vehicles if needle in v['name'].lower()]

    out = []
    save_dir = _save_dir_for(url)
    for v in vehicles:
        bp = [unquote(p) for p in urlparse(v['bundle_url']).path.strip('/').split('/')]
        downloaded = False
        stem = None
        if len(bp) == 4:                      # ['bundle', brand, year, model]
            brand, year, model = bp[1], int(bp[2]), bp[3]
            stem = warehouse_stem(model, year)
            for cand in (save_dir / source_zip_name(brand, year, model),
                         save_dir / f'{sanitize_filename(model)}.zip'):
                if cand.exists() and zipfile.is_zipfile(cand):
                    downloaded = True
                    break
        out.append({
            'name': v['name'],
            'bundle_url': v['bundle_url'],
            'downloaded': downloaded,
            'ingested': bool(stem) and (config.WAREHOUSE_DIR / f'{stem}.db').exists(),
        })
    return {'url': url, 'vehicles': out}


def _save_dir_for(url):
    """Mirror the downloader CLI's convention: <first inbox root>/<Brand>_<Year>."""
    dl = downloader_module()
    parts = [p for p in urlparse(url).path.strip('/').split('/') if p]
    brand_year = '_'.join(unquote(p) for p in parts[-2:]) if len(parts) >= 2 else 'manuals'
    return inbox_roots()[0] / dl.sanitize_filename(brand_year)


def execute_download_request(req, log=None, check_cancel=None, on_vehicle=None):
    """Run one DownloadRequest to completion (resumable: already-present valid
    ZIPs are skipped without hitting the server). Returns {'ok','skip','fail'}
    counts. ``check_cancel`` may raise to abort cooperatively; the request is
    left 'running' and re-executed (cheaply) on resume."""
    say = log or (lambda m: None)
    dl = downloader_module()

    req.status = 'running'
    req.vehicles_done = 0
    req.error = ''
    req.save(update_fields=['status', 'vehicles_done', 'error', 'updated_at'])

    session = dl.build_session(1)
    url = dl.correct_brand_case(session, req.url)
    vehicles = dl.get_vehicles(session, url)
    needle = (req.name_filter or '').strip().lower()
    if needle:
        vehicles = [v for v in vehicles if needle in v['name'].lower()]
    say(f'download request #{req.id}: {len(vehicles)} vehicle(s) '
        f'from {url}' + (f' (filter: {req.name_filter})' if needle else ''))

    save_dir = _save_dir_for(url)
    save_dir.mkdir(parents=True, exist_ok=True)

    req.listing = [{'name': v['name'], 'bundle_url': v['bundle_url'],
                    'state': 'pending'} for v in vehicles]
    req.vehicles_total = len(vehicles)
    req.save(update_fields=['listing', 'vehicles_total', 'updated_at'])

    counts = {'ok': 0, 'skip': 0, 'fail': 0}
    for i, v in enumerate(vehicles):
        if check_cancel is not None:
            check_cancel()
        check_disk_guard()
        state = dl.download_bundle(session, v, save_dir)
        counts[state] += 1
        req.listing[i]['state'] = state
        req.vehicles_done = i + 1
        req.save(update_fields=['listing', 'vehicles_done', 'updated_at'])
        if state in ('ok', 'skip'):
            bp = [unquote(p) for p in urlparse(v['bundle_url']).path.strip('/').split('/')]
            if len(bp) == 4:
                for cand in (save_dir / source_zip_name(bp[1], int(bp[2]), bp[3]),
                             save_dir / f'{sanitize_filename(v["name"])}.zip'):
                    if cand.exists():
                        register_zip(cand, normalize=True)
                        break
        if on_vehicle is not None:
            on_vehicle(v, state)

    failed = [e['name'] for e in req.listing if e['state'] == 'fail']
    req.status = 'failed' if (vehicles and counts['fail'] == len(vehicles)) else 'done'
    req.error = ('failed: ' + ', '.join(failed))[:500] if failed else ''
    req.finished_at = timezone.now()
    req.save(update_fields=['status', 'error', 'finished_at', 'updated_at'])
    say(f'download request #{req.id} finished: ok={counts["ok"]} '
        f'skip={counts["skip"]} fail={counts["fail"]}')
    return counts
