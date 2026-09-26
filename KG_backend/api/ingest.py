"""ZIP-inbox ingestion: the bridge between manually placed ZIPs and the
processing pipeline.

ZIPs are placed in ``/root/downloads`` by hand; the pipeline no longer
downloads anything itself (the old source downloader was moved off the
application, and TIS crawls are observed through ``tis_crawler``). This module
puts the HTML parser (``htmlparser_logical.py``) under pipeline control:

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

TIS crawls use the same queue. A finished vehicle folder written by the TIS
crawler (``<Model>_<Year>/`` next to a shared ``_assets/``) — in the TIS inbox
(``/root/downloads/tis``) or the crawler's own output folder — is registered as
a ``ZipPackage`` whose path is the folder, and ``parse_zip_package`` sends it
to ``tis_parser.py`` instead of the ZIP parser. Both produce the same car
database and media layout, so every later stage is source-agnostic.
The parser stays a standalone-usable script; it is loaded here via importlib
from its canonical location in the project root.
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
# External script loading (it lives outside the Django package on purpose:
# it remains a standalone CLI tool)
# ---------------------------------------------------------------------------
_parser_mod = None


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


def warehouse_stem(car_name, year):
    """The parser's stem rule (single source of truth lives in the parser)."""
    return parser_module().warehouse_stem(car_name, year)


_tis_mod = None


def tis_module():
    global _tis_mod
    if _tis_mod is None:
        path = os.environ.get('KG_TIS_PARSER_PATH',
                              str(PROJECT_ROOT / 'tis_parser.py'))
        _tis_mod = _load_module('kg_tis_parser', path)
    return _tis_mod


def tis_roots():
    """Folders holding TIS vehicle crawls (``<Model>_<Year>/`` + ``_assets/``):
    the TIS inbox for crawls copied in from elsewhere, and the on-server
    crawler's own output folder (colon-separated ``KG_TIS_INBOX`` overrides
    the whole list)."""
    from . import tis_crawler
    raw = os.environ.get('KG_TIS_INBOX',
                         f'/root/downloads/tis:{tis_crawler.OUT_DIR}')
    return [Path(p).expanduser() for p in raw.split(':') if p.strip()]


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


def register_tis_vehicle(vdir, dry_run=False):
    """Ensure a ZipPackage row for a TIS vehicle folder. Same contract and
    duplicate guard as ``register_zip``; the folder's signature is the total
    size / newest mtime of its pages, so a re-crawl requeues it.

    Extra actions: 'empty' (no pages yet, e.g. a crawl that only reached the
    listings) and 'in_progress' (the on-server crawler is writing to it)."""
    from .models import ZipPackage
    from . import tis_crawler
    tis = tis_module()
    vdir = Path(vdir)
    meta = tis.vehicle_meta(vdir)
    if meta is None:
        return None, 'unrecognized'
    brand, year, car_name = meta
    files = tis.content_files(vdir)
    if not files:
        return None, 'empty'
    if (tis_crawler.OUT_DIR in vdir.parents and tis_crawler.status_running()):
        return None, 'in_progress'
    size = mtime = 0
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        size += st.st_size
        mtime = max(mtime, st.st_mtime)

    stem = warehouse_stem(car_name, year)
    stem_on_disk = (config.WAREHOUSE_DIR / f'{stem}.db').exists()
    queued_elsewhere = (ZipPackage.objects
                        .filter(stem=stem, status__in=('pending', 'parsing', 'done'))
                        .exclude(path=str(vdir)).exists())
    fresh_status = ('skipped_duplicate' if (stem_on_disk or queued_elsewhere)
                    else 'pending')
    fields = dict(zip_name=f'TIS {year} {brand} {car_name}', size=size,
                  mtime=mtime, brand=brand, year=year, car_name=car_name,
                  stem=stem)

    pkg = ZipPackage.objects.filter(path=str(vdir)).first()
    if pkg is None:
        action = 'duplicate' if fresh_status == 'skipped_duplicate' else 'registered'
        if dry_run:
            return None, action
        pkg = ZipPackage.objects.create(path=str(vdir), status=fresh_status, **fields)
        return pkg, action
    if pkg.size != size or abs((pkg.mtime or 0) - mtime) > 1.0:
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
    for root in tis_roots():
        if not root.is_dir():
            continue
        for vdir in sorted(d for d in root.iterdir() if d.is_dir()):
            if tis_module().vehicle_meta(vdir) is None:
                continue
            pkg, action = register_tis_vehicle(vdir, dry_run=dry_run)
            if action in ('empty', 'in_progress'):
                say(f'.. TIS {vdir.name}: {action}, not queued')
                continue
            summary['found'] += 1
            if action == 'registered':
                summary['registered'] += 1
                say(f'++ queued: {pkg.zip_name if pkg else vdir.name}')
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

    if zip_path.is_dir():
        return _parse_tis_package(pkg, log=say)

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


def _parse_tis_package(pkg, log=None):
    """Parse one queued TIS vehicle folder into the warehouse + catalog. Uses
    the ZIP parser's image publisher so both sources share one image store."""
    from .models import Car
    say = log or (lambda m: None)
    pkg.status = 'parsing'
    pkg.save(update_fields=['status', 'updated_at'])
    try:
        result = tis_module().process_vehicle(
            Path(pkg.path), config.WAREHOUSE_DIR,
            Path(settings.BASE_DIR) / 'static_warehouse', stem=pkg.stem,
            publish_images=parser_module()._publish_images, log=say)
    except Exception as e:
        pkg.status, pkg.error = 'failed', f'{e.__class__.__name__}: {e}'[:500]
        pkg.save(update_fields=['status', 'error', 'updated_at'])
        return 'failed'
    Car.objects.update_or_create(
        car_name=result['car_name'],
        defaults={'brand_name': result['brand'], 'year': result['year'],
                  'db_address': result['db_address']})
    pkg.status, pkg.error, pkg.pages_processed = 'done', '', result['pages']
    pkg.save(update_fields=['status', 'error', 'pages_processed', 'updated_at'])
    say(f'parsed TIS into warehouse: {result["car_name"]} ({result["pages"]} pages)')
    return 'done'
