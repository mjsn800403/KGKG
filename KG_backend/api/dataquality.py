"""Vehicle-warehouse data-quality engine.

Answers three questions the platform admin keeps asking:

  1. Is any vehicle in the fleet a *duplicate* of another? Detected two ways:
     by name (a ``"X (1)"`` copy of ``"X"``, or two catalog rows with the same
     normalized brand/name/year) and by *content fingerprint* (the manual tree
     hashed with the car-specific root stripped, so byte-identical manuals are
     found no matter what the file is called).
  2. Is every vehicle *complete*? Each per-car DB is measured against the
     canonical manual schema (the section list every Toyota/Lexus manual
     shares). Titles are normalized ("Drivelines & Axles" == "Drivelines and
     Axles") and powertrain-specific sections are only required where they
     apply (no "Hybrid/Electric Powertrain" demanded of a gasoline 4Runner).
  3. Did every *process* run for every vehicle? Cross-checks: catalog row
     exists, static image assets exist, the RAG semantic index covers the car,
     the diagnostic sidecar exists, and the SQLite file itself passes an
     integrity check.

The full scan walks every warehouse DB (~1s per DB, minutes for the fleet), so
results are persisted in DataQualityRun and served from there. Refreshes run
in a background thread (see run_audit_async).

Nothing here writes to the per-car DBs — they are opened strictly read-only.
Fix actions (quarantine / dedupe) live in remediate() and only ever *move*
files into Database_warehouse/_quarantine/, never delete.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import traceback

from django.db import close_old_connections
from django.utils import timezone

from .rag import config


# ---------------------------------------------------------------------------
# Canonical manual schema
# ---------------------------------------------------------------------------
# requirement: 'core'      -> every vehicle must have it, non-empty
#              'combustion'-> required unless the vehicle is a pure EV
#              'electrified'-> required only for hybrid / EV vehicles
#              'optional'  -> informational; absence is not a defect
CANONICAL_SECTIONS = {
    'accessories & equipment':            'core',
    'body & frame':                       'core',
    'brakes':                             'core',
    'drivelines & axles':                 'core',
    'electrical':                         'core',
    'engine mechanical':                  'combustion',
    'engine performance':                 'combustion',
    'general information':                'core',
    'heating, ventilation & a/c (hvac)':  'core',
    'hybrid/electric powertrain':         'electrified',
    'maintenance':                        'core',
    'quick lookups':                      'core',
    'restraints':                         'core',
    'steering':                           'core',
    'suspension':                         'core',
    'transmission':                       'core',
    'external pages':                     'optional',
    'labor times: other variant':         'optional',
}

MAIN_ROOT = 'repair and diagnosis'          # sections live under this root
_COPY_SUFFIX_RE = re.compile(r'^(?P<base>.+?)\s*\((?P<n>\d+)\)$')
_LEXUS_HYBRID_RE = re.compile(r'\b\d{3}h\b', re.IGNORECASE)   # NX 350h, RX 500h ...


def normalize_section(title):
    """Canonical form of a section title: case-, whitespace- and '&'/'and'-
    insensitive, so crawler-run title drift doesn't read as a missing section.

    Also maps U+2044 (fraction slash) back to '/': the crawler stores paths
    with '/' inside titles substituted by '⁄' (a real '/' would break the
    breadcrumb encoding), so "A/C (HVAC)" arrives here as "A⁄C (HVAC)"."""
    t = re.sub(r'\s+', ' ', (title or '').strip().lower())
    t = t.replace('⁄', '/')
    t = t.replace(' and ', ' & ')
    return t


# Whole-model powertrains that the trim naming does NOT mark: these models are
# electrified (or engine-less) in every variant of this fleet's era, so section
# expectations must not demand combustion sections from a Mirai or skip the
# hybrid sections of a Prius.
_ELECTRIFIED_MODEL_PREFIXES = ('prius', 'sienna', 'venza', 'crown', 'mirai',
                               'rav4 prime')
_NO_COMBUSTION_MODEL_PREFIXES = ('bz4x', 'mirai')


def is_electrified(stem):
    """Hybrid or EV, by naming convention (Hybrid trims, bZ4X EVs, Lexus 'h')
    plus whole-model knowledge for lines whose trims carry no marker."""
    s = stem.lower()
    return ('hybrid' in s or 'bz4x' in s or bool(_LEXUS_HYBRID_RE.search(s))
            or s.startswith(_ELECTRIFIED_MODEL_PREFIXES))


def is_pure_ev(stem):
    """No combustion engine at all (battery EV or fuel cell)."""
    return stem.lower().startswith(_NO_COMBUSTION_MODEL_PREFIXES)


def expected_sections(stem):
    """{normalized_title: requirement} for this specific vehicle."""
    out = {}
    for title, req in CANONICAL_SECTIONS.items():
        if req == 'electrified' and not is_electrified(stem):
            continue
        if req == 'combustion' and is_pure_ev(stem):
            continue
        out[title] = req
    return out


# ---------------------------------------------------------------------------
# Per-vehicle scan
# ---------------------------------------------------------------------------

def _ro(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def audit_vehicle_db(path):
    """Single read-only pass over one per-car DB. Returns a JSON-able dict.

    Deliberately one full-table sweep (path, depth, node_type, content length)
    aggregated in Python — measured ~1s on the largest (976MB / 110k-node) DB,
    vs minutes for per-section LIKE subqueries.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    info = {
        'stem': stem,
        'size_mb': round(os.path.getsize(path) / 1e6, 1),
        'integrity': None, 'error': None,
        'total_nodes': 0, 'content_leaves': 0, 'empty_leaves': 0,
        'content_mb': 0.0, 'sections': [], 'fingerprint': None,
    }
    try:
        con = _ro(path)
        cur = con.cursor()
    except sqlite3.Error as e:
        info['error'] = f'cannot open: {e}'
        info['integrity'] = 'unreadable'
        return info
    try:
        info['integrity'] = cur.execute('PRAGMA quick_check(1)').fetchone()[0]
        has_nodes = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nodes'").fetchone()
        if not has_nodes:
            info['error'] = 'no nodes table'
            return info

        # Strip the tree's own root path, NOT the filename stem: a copied file
        # keeps its original root inside (e.g. "NX 250 FWD (1).db" whose paths
        # still start with "NX 250 FWD/"), and the fingerprint must be
        # identical for identical trees regardless of what the file is called.
        root_row = cur.execute(
            'SELECT path FROM nodes WHERE depth = 0 LIMIT 1').fetchone()
        root_prefix = root_row[0] if root_row else stem
        prefix_len = len(root_prefix) + 1

        secs = {}          # normalized -> {title, nodes, content_leaves, mb}
        fp_rows = []
        for p, depth, ntype, clen in cur.execute(
                'SELECT path, depth, node_type, coalesce(length(content),0) FROM nodes'):
            info['total_nodes'] += 1
            if clen > 0:
                info['content_leaves'] += 1
                info['content_mb'] += clen
            elif ntype == 'leaf':
                info['empty_leaves'] += 1
            rel = p[prefix_len:] if p.startswith(root_prefix) else p
            fp_rows.append((rel, clen))
            parts = rel.split('/')
            # Sections sit at depth 2: <root>/<section>/...
            if len(parts) >= 2 and parts[0].strip().lower() == MAIN_ROOT:
                key = normalize_section(parts[1])
                s = secs.setdefault(key, {'title': parts[1], 'nodes': 0,
                                          'content_leaves': 0, 'mb': 0.0})
                s['nodes'] += 1
                if clen > 0:
                    s['content_leaves'] += 1
                    s['mb'] += clen

        info['content_mb'] = round(info['content_mb'] / 1e6, 1)
        for s in secs.values():
            s['mb'] = round(s['mb'] / 1e6, 2)
        info['sections'] = [dict(normalized=k, **v) for k, v in sorted(secs.items())]

        h = hashlib.sha1()
        for rel, clen in sorted(fp_rows):
            h.update(f'{rel}|{clen}\n'.encode('utf-8', 'replace'))
        info['fingerprint'] = h.hexdigest()
    except sqlite3.DatabaseError as e:
        info['error'] = str(e)
        if info['integrity'] == 'ok':
            info['integrity'] = 'error'
    finally:
        con.close()
    return info


def _rag_indexed_stems():
    """Car stems actually servable from the semantic index (occurrences is the
    source of truth — same rule the retrieval scope gate uses)."""
    if not config.INDEX_DB.exists():
        return set()
    try:
        con = _ro(config.INDEX_DB)
        try:
            return {r[0] for r in con.execute('SELECT DISTINCT car_stem FROM occurrences')}
        finally:
            con.close()
    except sqlite3.Error:
        return set()


def _static_dirs():
    from django.conf import settings
    root = settings.MEDIA_ROOT
    try:
        return {d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))}
    except OSError:
        return set()


# ---------------------------------------------------------------------------
# Fleet audit
# ---------------------------------------------------------------------------

def run_audit(fix=False, log=None):
    """Full warehouse audit. Returns (summary, vehicles, actions).

    With fix=True also performs the SAFE automatic remediations (see
    remediate()); destructive-looking steps only move files to _quarantine.
    """
    from .models import Car
    log = log or (lambda msg: None)

    db_files = config.car_db_files()
    log(f'scanning {len(db_files)} vehicle databases...')
    vehicles = []
    for p in db_files:
        vehicles.append(audit_vehicle_db(p))
        log(f'  scanned {p.stem}')

    cars = {c.car_name: c for c in Car.objects.all()}
    rag_stems = _rag_indexed_stems()
    statics = _static_dirs()
    diag_stems = {p.stem.replace('.diag', '') for p in
                  config.DIAG_DIR.glob('*.diag.db')} if config.DIAG_DIR.exists() else set()

    # --- duplicate detection -------------------------------------------------
    by_fp = {}
    for v in vehicles:
        if v['fingerprint']:
            by_fp.setdefault(v['fingerprint'], []).append(v['stem'])
    stems = {v['stem'] for v in vehicles}

    fp_of = {v['stem']: v['fingerprint'] for v in vehicles}
    duplicates = []            # true duplicates: same vehicle twice
    shared_content = []        # different trims, byte-identical manual (info)

    # A "<base> (N)" file whose base exists with identical content is the same
    # vehicle uploaded twice. Base missing or content differing = suspect copy
    # (surfaced for manual review, never auto-merged).
    # EXCEPTION: "(YYYY)" is the multi-year stem suffix ('Corolla Cross LE,
    # FWD (2023)' is a different MODEL YEAR of the base car, not a copy) —
    # a plausible model year is never treated as a copy counter.
    for s in sorted(stems):
        m = _COPY_SUFFIX_RE.match(s)
        if not m:
            continue
        if 1980 <= int(m.group('n')) <= 2100:
            continue
        base = m.group('base')
        if base in stems and fp_of.get(base) and fp_of[base] == fp_of.get(s):
            duplicates.append({'keep': base, 'remove': [s], 'fingerprint': fp_of[s]})
        else:
            duplicates.append({'keep': base if base in stems else None,
                               'remove': [s], 'fingerprint': None,
                               'note': 'copy-suffix file (base missing or content differs)'})

    # Identical manuals across genuinely different trims: legitimate (Toyota
    # ships one manual for several trims) — reported as information only.
    already_dup = {s for d in duplicates for s in d['remove']}
    for fp, group in by_fp.items():
        rest = sorted(set(group) - already_dup)
        if len(rest) > 1:
            shared_content.append(rest)

    # Catalog rows that collide on normalized identity.
    seen_names = {}
    catalog_dups = []
    for c in cars.values():
        key = (c.brand_name.strip().lower(),
               re.sub(r'\s+', ' ', c.car_name.strip().lower()), c.year)
        if key in seen_names:
            catalog_dups.append({'car_ids': [seen_names[key].id, c.id],
                                 'name': c.car_name})
        else:
            seen_names[key] = c

    # --- per-vehicle verdicts -------------------------------------------------
    remove_set = {s for d in duplicates for s in d['remove']}
    complete = incomplete = corrupt = 0
    for v in vehicles:
        stem = v['stem']
        exp = expected_sections(stem)
        have = {s['normalized']: s for s in v['sections']}
        missing = sorted(t for t, req in exp.items()
                         if req != 'optional' and t not in have)
        empty = sorted(t for t, req in exp.items()
                       if req != 'optional' and t in have
                       and have[t]['content_leaves'] == 0)
        optional_missing = sorted(t for t, req in exp.items()
                                  if req == 'optional' and t not in have)
        car = cars.get(stem)
        v.update({
            'car_id': car.id if car else None,
            'brand': car.brand_name if car else config.car_meta(stem)['brand'],
            'year': car.year if car else config.car_meta(stem)['year'],
            'cataloged': car is not None,
            'static_assets': stem in statics,
            'rag_indexed': stem in rag_stems,
            'diag_indexed': stem in diag_stems,
            'missing_sections': missing,
            'empty_sections': empty,
            'optional_missing': optional_missing,
            'is_duplicate': stem in remove_set,
            'shared_content_with': next(
                (sorted(set(g) - {stem}) for g in shared_content if stem in g), []),
        })
        if v['error'] or (v['integrity'] not in (None, 'ok')):
            v['status'] = 'corrupt'
            corrupt += 1
        elif stem in remove_set:
            v['status'] = 'duplicate'
        elif missing or empty or not v['cataloged']:
            v['status'] = 'incomplete'
            incomplete += 1
        else:
            v['status'] = 'complete'
            complete += 1
        # What still needs running for this vehicle (process backlog).
        todo = []
        if v['status'] == 'corrupt':
            todo.append('recrawl_source')
        else:
            if not v['cataloged']:
                todo.append('sync_car_catalog')
            if not v['rag_indexed']:
                todo.append('build_rag --add')
            if not v['diag_indexed']:
                todo.append('build_diag')
            if not v['static_assets']:
                todo.append('upload_static_assets')
        v['pending_processes'] = todo

    catalog_no_db = sorted(set(cars) - stems)

    summary = {
        'total_dbs': len(vehicles),
        'catalog_rows': len(cars),
        'complete': complete,
        'incomplete': incomplete,
        'corrupt': corrupt,
        'duplicates': duplicates,
        'catalog_duplicates': catalog_dups,
        'shared_content_groups': shared_content,
        'catalog_rows_without_db': catalog_no_db,
        'rag_indexed': sum(1 for v in vehicles if v.get('rag_indexed')),
        'diag_indexed': sum(1 for v in vehicles if v.get('diag_indexed')),
        'static_missing': sorted(s for s in stems if s not in statics),
        'warehouse_mb': round(sum(v['size_mb'] for v in vehicles), 1),
    }

    actions = []
    if fix:
        actions = remediate(vehicles, duplicates, log=log)

    return summary, vehicles, actions


# ---------------------------------------------------------------------------
# Remediation (safe, reversible)
# ---------------------------------------------------------------------------

QUARANTINE_DIR = '_quarantine'


def _quarantine(path, log):
    """Move a file/dir into Database_warehouse/_quarantine/ (never delete)."""
    qdir = config.WAREHOUSE_DIR / QUARANTINE_DIR
    qdir.mkdir(parents=True, exist_ok=True)
    dest = qdir / os.path.basename(str(path))
    if os.path.exists(str(dest)):
        dest = qdir / f'{os.path.basename(str(path))}.{timezone.now():%Y%m%d%H%M%S}'
    shutil.move(str(path), str(dest))
    log(f'quarantined {path} -> {dest}')
    return str(dest)


def remediate(vehicles, duplicates, log=None):
    """Apply the safe automatic fixes. Returns a list of action records.

    * corrupt DB files        -> moved to _quarantine (they are unreadable and
                                 already invisible to the catalog/site);
    * true duplicate vehicles -> catalog row merged into the original (grants,
                                 activity history and catalog identity all
                                 repointed), then the copy's files quarantined;
    * healthy DBs             -> WAL checkpointed so stray -wal/-shm sidecar
                                 files are folded back into the main file.
    """
    from django.db import transaction
    from .models import ActivityLog, Car, CompanyCarAccess, UserCarAccess

    log = log or (lambda msg: None)
    actions = []
    by_stem = {v['stem']: v for v in vehicles}

    # 1. Quarantine corrupt DBs (never cataloged thanks to sync's validity gate,
    #    but keeping malformed files in the warehouse confuses every downstream
    #    process — and a future re-crawl will land a fresh file anyway).
    for v in vehicles:
        if v['status'] != 'corrupt':
            continue
        path = config.WAREHOUSE_DIR / f"{v['stem']}.db"
        if not path.exists():
            continue
        moved = [_quarantine(path, log)]
        for suffix in ('-wal', '-shm'):
            side = config.WAREHOUSE_DIR / f"{v['stem']}.db{suffix}"
            if side.exists():
                moved.append(_quarantine(side, log))
        # An orphaned catalog row for a corrupt file would 404 on open; drop it.
        stale = Car.objects.filter(car_name=v['stem'])
        if stale.exists():
            stale.delete()
            moved.append(f"removed catalog row for corrupt '{v['stem']}'")
        actions.append({'action': 'quarantine_corrupt', 'stem': v['stem'], 'detail': moved})

    # 2. Merge true duplicates into their originals.
    for dup in duplicates:
        keep_stem = dup.get('keep')
        for rm_stem in dup['remove']:
            v = by_stem.get(rm_stem)
            if v is None or v['status'] == 'corrupt':
                continue  # corrupt copies already quarantined above
            if dup.get('note'):
                # Copy-suffix name but no confirmed identical base: never
                # auto-merge on a name alone — flag for manual review.
                actions.append({'action': 'flag_suspect_copy', 'stem': rm_stem,
                                'detail': dup['note']})
                continue
            keep_car = Car.objects.filter(car_name=keep_stem).first()
            rm_car = Car.objects.filter(car_name=rm_stem).first()
            detail = []
            with transaction.atomic():
                if keep_car and rm_car:
                    # Repoint grants (skip ones the original already has).
                    for model, user_field in ((UserCarAccess, 'user_id'),
                                              (CompanyCarAccess, 'company_id')):
                        for row in model.objects.filter(car_id=rm_car.id):
                            exists = model.objects.filter(
                                car_id=keep_car.id,
                                **{user_field: getattr(row, user_field)}).exists()
                            if exists:
                                row.delete()
                            else:
                                row.car_id = keep_car.id
                                row.save(update_fields=['car_id'])
                        detail.append(f'migrated {model.__name__} rows')
                    n = ActivityLog.objects.filter(car_id=rm_car.id).update(car_id=keep_car.id)
                    detail.append(f'repointed {n} activity rows')
                    rm_id = rm_car.id
                    rm_car.delete()
                    detail.append(f'deleted catalog row #{rm_id} ({rm_stem})')
                elif rm_car:
                    rm_car.delete()
                    detail.append(f'deleted orphan catalog row ({rm_stem})')
            db_path = config.WAREHOUSE_DIR / f'{rm_stem}.db'
            if db_path.exists():
                detail.append(_quarantine(db_path, log))
            for suffix in ('-wal', '-shm'):
                side = config.WAREHOUSE_DIR / f'{rm_stem}.db{suffix}'
                if side.exists():
                    detail.append(_quarantine(side, log))
            from django.conf import settings
            static_dir = settings.MEDIA_ROOT / rm_stem
            if static_dir.exists():
                detail.append(_quarantine(static_dir, log))
            actions.append({'action': 'merge_duplicate', 'kept': keep_stem,
                            'removed': rm_stem, 'detail': detail})
            log(f'merged duplicate {rm_stem} -> {keep_stem}')

    # 3. Fold stray WAL sidecars back into their main files (read-only open
    #    can't checkpoint, so use a normal connection in passive mode — this
    #    never blocks readers).
    for v in vehicles:
        if v['status'] in ('corrupt', 'duplicate'):
            continue
        path = config.WAREHOUSE_DIR / f"{v['stem']}.db"
        wal = config.WAREHOUSE_DIR / f"{v['stem']}.db-wal"
        if not (path.exists() and wal.exists()):
            continue
        try:
            con = sqlite3.connect(str(path), timeout=5)
            con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            con.close()
            actions.append({'action': 'wal_checkpoint', 'stem': v['stem']})
        except sqlite3.Error as e:
            actions.append({'action': 'wal_checkpoint_failed', 'stem': v['stem'],
                            'detail': str(e)})

    return actions


# ---------------------------------------------------------------------------
# Async runner (admin "refresh" button)
# ---------------------------------------------------------------------------

_AUDIT_LOCK = threading.Lock()


def run_audit_to_db(fix=False):
    """Run the audit and persist a DataQualityRun row. Returns the run."""
    from .models import DataQualityRun
    run = DataQualityRun.objects.create(status='running')
    try:
        summary, vehicles, actions = run_audit(fix=fix)
        run.summary, run.vehicles, run.actions = summary, vehicles, actions
        run.status = 'done'
    except Exception:
        run.status = 'failed'
        run.error = traceback.format_exc()[-4000:]
    run.finished_at = timezone.now()
    run.save()
    return run


def run_audit_async(fix=False):
    """Kick off an audit in a daemon thread. Returns False if one is already
    running (the lock is process-local; the DB status row covers other workers)."""
    from .models import DataQualityRun
    if DataQualityRun.objects.filter(
            status='running',
            started_at__gte=timezone.now() - timezone.timedelta(minutes=30)).exists():
        return False

    def _worker():
        if not _AUDIT_LOCK.acquire(blocking=False):
            return
        try:
            run_audit_to_db(fix=fix)
        finally:
            _AUDIT_LOCK.release()
            close_old_connections()

    threading.Thread(target=_worker, name='kg-audit', daemon=True).start()
    return True
