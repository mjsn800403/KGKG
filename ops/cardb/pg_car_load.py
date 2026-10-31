"""Copy one per-vehicle SQLite database into its own PostgreSQL schema.

    /root/pgmig/venv/bin/python ops/cardb/pg_car_load.py "<path to car>.db"

Every table (except sqlite_*) with every column, the same indexes, verified row
counts. Built under a temporary schema and renamed into place, so readers never
see a half-loaded car. The SQLite file is NOT touched. Serving switches to it
only when the file name is listed in KG_CARDB_PG.
"""
import json, os, re, sqlite3, sys, time
import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'KG_backend'))
from api.cardb_pg import schema_for                      # noqa: E402


def pgtype(decl):
    d = (decl or '').upper()
    if 'INT' in d:
        return 'bigint'
    if any(x in d for x in ('REAL', 'FLOA', 'DOUB')):
        return 'double precision'
    if 'BLOB' in d:
        return 'bytea'
    return 'text'


def main(path, dsn='dbname=kgkg_vec'):
    t0 = time.time()
    name = os.path.basename(path)
    final = schema_for(name)
    tmp = final + '_new'
    src = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    pg = psycopg.connect(dsn, autocommit=True)
    pg.execute(f'DROP SCHEMA IF EXISTS {tmp} CASCADE')
    pg.execute(f'CREATE SCHEMA {tmp}')
    counts = {}
    tables = [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tables:
        cols = [(r[1], r[2], r[5]) for r in src.execute(f'PRAGMA table_info([{t}])')]
        pk = [c for c, _, k in sorted(cols, key=lambda x: x[2]) if k]
        # SQLite's implicit rowid is kept as a real column, so queries that use
        # it (e.g. as the final tie-break) mean the same thing on both engines
        ddl = 'rowid bigint, ' + ', '.join(f'"{c}" {pgtype(d)}' for c, d, _ in cols)
        if pk:
            ddl += ', PRIMARY KEY (' + ', '.join(f'"{c}"' for c in pk) + ')'
        pg.execute(f'CREATE TABLE {tmp}."{t}" ({ddl})')
        names = 'rowid, ' + ', '.join(f'"{c}"' for c, _, _ in cols)
        n = 0
        with pg.cursor().copy(f'COPY {tmp}."{t}" ({names}) FROM STDIN') as cp:
            for r in src.execute(f'SELECT rowid, * FROM [{t}]'):
                cp.write_row([v.replace('\x00', '') if isinstance(v, str) else v for v in r])
                n += 1
        counts[t] = [src.execute(f'SELECT count(*) FROM [{t}]').fetchone()[0], n]
    for (sql,) in src.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
        m = re.match(r'CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s*\((.*)\)\s*$',
                     sql.strip(), re.S | re.I)
        if m:
            pg.execute(f'CREATE {m.group(1) or ""}INDEX {m.group(2)} ON {tmp}."{m.group(3)}" ({m.group(4)})')
    if 'nodes' in tables:
        # SQLite's LIKE is case-insensitive; PostgreSQL's ILIKE gets that with
        # locale-aware folding that measured 5x slower than plain LIKE. So the
        # LIKE-searched columns get a stored lowercase twin (cardb_pg rewrites
        # "col LIKE ?" to "col_lc LIKE lower(?)"), trigram-indexed.
        pg.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
        for c in ('title', 'content', 'href', 'path'):
            pg.execute(f'ALTER TABLE {tmp}.nodes ADD COLUMN {c}_lc text GENERATED ALWAYS AS (lower({c})) STORED')
            if c != 'path':
                pg.execute(f'CREATE INDEX ON {tmp}.nodes USING gin ({c}_lc gin_trgm_ops)')
        pg.execute(f'CREATE INDEX ON {tmp}.nodes (path_lc text_pattern_ops)')
    pg.execute(f'ANALYZE')
    for t in tables:
        counts[t][1] = pg.execute(f'SELECT count(*) FROM {tmp}."{t}"').fetchone()[0]
        assert counts[t][0] == counts[t][1], (t, counts[t])
    with pg.transaction():
        pg.execute(f'DROP SCHEMA IF EXISTS {final} CASCADE')
        pg.execute(f'ALTER SCHEMA {tmp} RENAME TO {final}')
    pg.execute(f'GRANT USAGE ON SCHEMA {final} TO kgkg')
    pg.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA {final} TO kgkg')
    size = pg.execute("SELECT pg_size_pretty(sum(pg_total_relation_size(c.oid))) FROM pg_class c "
                      "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s", (final,)).fetchone()[0]
    print(json.dumps({'car': name, 'schema': final, 'counts_sqlite_vs_pg': counts, 'pg_size': size,
                      'sqlite_bytes': os.path.getsize(path), 'seconds': round(time.time() - t0, 1)}, indent=2))


if __name__ == '__main__':
    main(sys.argv[1])
