#!/usr/bin/env python3
"""Restore test for the existing off-host snapshot.

A backup nobody has restored is a hypothesis. This restores the snapshot copy
of the portal database, checks it, and compares the row counts of the tables
the business actually depends on against the live database — so the answer is
not "a file exists" but "the file is a usable database holding the right data".

Two engines, picked from KG_DB_ENGINE in .env.prod:

  * PostgreSQL: the snapshot is a pg_dump custom-format archive
    (portal.dump). It is restored into a throwaway database, counted, and the
    throwaway database is dropped again.
  * SQLite (before the move): the snapshot is db.sqlite3; integrity is
    checked with PRAGMA quick_check.

Read-only towards the live database on both engines.
"""
import sqlite3
import subprocess
import sys
import time

ENV_FILE = '/opt/KGKG/KG_backend/.env.prod'
SNAP_DIR = '/root/backup_snapshot'
LIVE_SQLITE = '/opt/KGKG/KG_backend/db.sqlite3'
RESTORE_DB = 'kgkg_restore_test'

TABLES = [
    'api_portaluser', 'api_company', 'api_companycaraccess', 'api_usercaraccess',
    'api_activitylog', 'api_chatlog', 'api_systemalert', 'api_trafficstat',
]


def _env(name, default=''):
    try:
        with open(ENV_FILE) as fh:
            for line in fh:
                if line.startswith(name + '='):
                    return line.split('=', 1)[1].strip().strip('"\'')
    except OSError:
        pass
    return default



def _ensure_psycopg():
    """System python3 has no psycopg; the backend venv does. Re-run under it."""
    try:
        import psycopg  # noqa: F401
    except ImportError:
        import os, sys
        venv = '/opt/KGKG/KG_backend/.venv/bin/python'
        if sys.executable != venv and os.path.exists(venv):
            os.execv(venv, [venv, *sys.argv])
        raise


PG = _env('KG_DB_ENGINE', 'sqlite').lower() in ('postgres', 'postgresql')


def count(con, table):
    try:
        cur = con.cursor()
        cur.execute(f'SELECT count(*) FROM "{table}"')
        return cur.fetchone()[0]
    except Exception as exc:                       # noqa: BLE001
        if PG:
            con.rollback()
        return f'ERROR: {exc}'


def open_pair():
    """(snapshot connection, live connection, integrity result, cleanup)"""
    if not PG:
        snap = sqlite3.connect(f'file:{SNAP_DIR}/db.sqlite3?mode=ro', uri=True, timeout=30)
        live = sqlite3.connect(f'file:{LIVE_SQLITE}?mode=ro', uri=True, timeout=30)
        return snap, live, snap.execute('PRAGMA quick_check').fetchone()[0], lambda: None

    _ensure_psycopg()
    import psycopg
    dump = f'{SNAP_DIR}/portal.dump'
    subprocess.run(['dropdb', '--if-exists', '--force', RESTORE_DB], check=True)
    subprocess.run(['createdb', RESTORE_DB], check=True)
    r = subprocess.run(['pg_restore', '--no-owner', '--no-privileges', '--exit-on-error',
                        '-d', RESTORE_DB, dump], capture_output=True, text=True)
    integrity = 'ok' if r.returncode == 0 else f'pg_restore failed: {r.stderr.strip()[-300:]}'
    snap = psycopg.connect(dbname=RESTORE_DB, autocommit=True)
    live = psycopg.connect(dbname=_env('KG_PG_NAME', 'kgkg'), autocommit=True)
    live.read_only = True

    def cleanup():
        snap.close()
        subprocess.run(['dropdb', '--if-exists', '--force', RESTORE_DB], check=False)
    return snap, live, integrity, cleanup


t0 = time.time()
snap, live, result, cleanup = open_pair()
print(f'engine: {"postgresql" if PG else "sqlite"}')
print(f'integrity of the restored snapshot: {result}  ({time.time() - t0:.1f}s)')

print(f'\n  {"table":28} {"snapshot":>10} {"live":>10}   delta')
mismatch_beyond_drift = []
try:
    for table in TABLES:
        s, l = count(snap, table), count(live, table)
        if isinstance(s, int) and isinstance(l, int):
            delta = l - s
            print(f'  {table:28} {s:>10} {l:>10}   {delta:+d}')
            # The snapshot is up to an hour old, so append-only tables may be
            # behind. A NEGATIVE delta would mean the snapshot has rows the live
            # database does not, which would be worth explaining.
            if delta < 0:
                mismatch_beyond_drift.append((table, s, l))
        else:
            print(f'  {table:28} {s!s:>10} {l!s:>10}')
            mismatch_beyond_drift.append((table, s, l))
finally:
    cleanup()

with open(f'{SNAP_DIR}/SNAPSHOT_AT') as fh:
    print(f'\n  snapshot taken: {fh.read().strip()}')

ok = result == 'ok' and not mismatch_beyond_drift
print(f'\nRESTORE TEST: {"PASS" if ok else "NEEDS A LOOK"}')
if mismatch_beyond_drift:
    for row in mismatch_beyond_drift:
        print('  unexpected:', row)
sys.exit(0 if ok else 1)
