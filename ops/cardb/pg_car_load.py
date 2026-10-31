"""Copy one per-vehicle SQLite database into its own PostgreSQL schema.

    /root/pgmig/venv/bin/python ops/cardb/pg_car_load.py "<path to car>.db"

See api.cardb_pg.load_sqlite. The SQLite file is NOT touched (the pipeline's
pgcar stage uses cardb_pg.adopt, which also deletes it).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'KG_backend'))
from api.cardb_pg import load_sqlite                      # noqa: E402

if __name__ == '__main__':
    load_sqlite(sys.argv[1])
