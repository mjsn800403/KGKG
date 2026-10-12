#!/usr/bin/env python3
"""Truncate the WAL of every per-car content DB.

Serving connections are opened mode=ro (see api/cardb.py) and read-only
connections cannot checkpoint, so the WAL that ingest leaves behind is never
reclaimed and grows unbounded. This job opens each DB read-write and runs
wal_checkpoint(TRUNCATE), shrinking the -wal back to 0 bytes.

Globs the warehouse at run time, so it automatically covers every car that
exists now or is added later. Safe to run while the site serves traffic:
readers hold no persistent lock, busy_timeout absorbs momentary contention,
and TRUNCATE only reclaims already-committed WAL frames.
"""
import glob
import os
import sqlite3
import sys
import time

WAREHOUSE = os.environ.get(
    "KG_WAREHOUSE", "/opt/KGKG/KG_backend/Database_warehouse")


def main():
    dbs = sorted(glob.glob(os.path.join(WAREHOUSE, "*.db")))
    total_before = total_after = 0
    failed = 0
    for db in dbs:
        wal = db + "-wal"
        before = os.path.getsize(wal) if os.path.exists(wal) else 0
        total_before += before
        try:
            conn = sqlite3.connect(db, timeout=30)
            conn.execute("PRAGMA busy_timeout = 30000")
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            conn.close()
            if row and row[0] != 0:
                # busy: a checkpoint could not complete fully this pass
                print(f"BUSY  {os.path.basename(db)} -> {row}", file=sys.stderr)
        except sqlite3.Error as e:
            failed += 1
            print(f"ERROR {os.path.basename(db)}: {e}", file=sys.stderr)
        after = os.path.getsize(wal) if os.path.exists(wal) else 0
        total_after += after
    mb = 1024 * 1024
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
          f"checkpointed {len(dbs)} dbs, "
          f"WAL {total_before / mb:.0f}MB -> {total_after / mb:.0f}MB, "
          f"{failed} errors")


if __name__ == "__main__":
    main()
