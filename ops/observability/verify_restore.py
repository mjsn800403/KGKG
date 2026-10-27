#!/usr/bin/env python3
"""Restore test for the existing off-host snapshot.

A backup nobody has restored is a hypothesis. This opens the snapshot copy of
the portal database, checks its integrity, and compares the row counts of the
tables the business actually depends on against the live database — so the
answer is not "a file exists" but "the file is a usable database holding the
right data".

Read-only on both sides.
"""
import sqlite3
import sys
import time

SNAP = '/root/backup_snapshot/db.sqlite3'
LIVE = '/opt/KGKG/KG_backend/db.sqlite3'

TABLES = [
    'api_portaluser', 'api_company', 'api_companycaraccess', 'api_usercaraccess',
    'api_activitylog', 'api_chatlog', 'api_systemalert', 'api_trafficstat',
]


def conn(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=30)


def count(con, table):
    try:
        return con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    except sqlite3.DatabaseError as exc:
        return f'ERROR: {exc}'


snap, live = conn(SNAP), conn(LIVE)

print('integrity of the snapshot copy:')
t0 = time.time()
result = snap.execute('PRAGMA quick_check').fetchone()[0]
print(f'  quick_check: {result}  ({time.time() - t0:.1f}s)')

print(f'\n  {"table":28} {"snapshot":>10} {"live":>10}   delta')
mismatch_beyond_drift = []
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

with open('/root/backup_snapshot/SNAPSHOT_AT') as fh:
    print(f'\n  snapshot taken: {fh.read().strip()}')

ok = result == 'ok' and not mismatch_beyond_drift
print(f'\nRESTORE TEST: {"PASS" if ok else "NEEDS A LOOK"}')
if mismatch_beyond_drift:
    for row in mismatch_beyond_drift:
        print('  unexpected:', row)
sys.exit(0 if ok else 1)
