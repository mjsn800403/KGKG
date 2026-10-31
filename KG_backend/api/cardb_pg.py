"""PostgreSQL-backed per-vehicle databases (KG_CARDB_PG), sqlite3-compatible.

A car listed in KG_CARDB_PG (file names, '|'-separated, e.g.
"GR86 Premium, Standard Trans.db", or '*' for every loaded car) is served from its own PostgreSQL schema
(``car_<md5 of the file name>``) holding the same tables as its SQLite file,
loaded by ops/cardb/pg_car_load.py. cardb.connect() hands back a PgCarConn,
which speaks the small sqlite3 surface the views use: execute()/cursor(),
'?' parameters, rows indexable by name and position, dict(row).

SQLite-only SQL in the callers is translated on the fly:
  ?                     -> %s
  printf('%08d', x)     -> lpad((x)::text, 8, '0')
  title|content|href|path LIKE ?  -> <col>_lc LIKE lower(?)   (stored lowercase
                           twin: SQLite LIKE is case-insensitive, ILIKE was 5x slower)
  any other LIKE        -> ILIKE
"""
import hashlib
import logging
import os
import re
import threading
import time

log = logging.getLogger(__name__)
_tls = threading.local()

_PRINTF = re.compile(r"printf\('%08d',\s*([^)]+)\)")
# columns loaded with a stored lowercase twin (ops/cardb/pg_car_load.py)
_LC_LIKE = re.compile(r'\b((?:\w+\.)?(?:title|content|href|path))\s+LIKE\s+\?')
_LIKE = re.compile(r'\bLIKE\b')


def pg_cars():
    # '|'-separated: car file names themselves contain commas
    return {s.strip() for s in os.environ.get('KG_CARDB_PG', '').split('|') if s.strip()}


# public.car_dbs lists every loaded car: (filename, schema, nodes, loaded_at)
REGISTRY = 'public.car_dbs'
_loaded = {'at': -1e9, 'files': frozenset()}
_LOADED_TTL_S = 60.0


def _dsn():
    from .rag import config
    return os.environ.get('KG_CARDB_PG_DSN') or config.PGVEC_DSN


def loaded_files():
    """File names of the cars loaded into PostgreSQL (cached; empty if unreachable)."""
    now = time.monotonic()
    if now - _loaded['at'] >= _LOADED_TTL_S:
        try:
            import psycopg
            with psycopg.connect(_dsn(), connect_timeout=3) as c:
                rows = c.execute(f'SELECT filename FROM {REGISTRY}').fetchall()
            _loaded['files'] = frozenset(r[0] for r in rows)
        except Exception:
            log.warning('cannot list PostgreSQL car databases', exc_info=True)
        _loaded['at'] = now
    return _loaded['files']


def forget_cache():
    _loaded['at'] = -1e9


def is_pg(filename):
    """Is this car served from PostgreSQL? KG_CARDB_PG lists file names, or
    is '*' for every car whose schema has been loaded."""
    cars = pg_cars()
    if not cars:
        return False
    name = os.path.basename(str(filename))
    if name in cars:
        return True
    return '*' in cars and name in loaded_files()


def schema_for(filename):
    # a stable, identifier-safe name, not a security boundary
    return 'car_' + hashlib.md5(filename.encode('utf-8'), usedforsecurity=False).hexdigest()[:16]


_SQLITE_MASTER = ("(SELECT 'table'::text AS type, table_name::text AS name FROM "
                  "information_schema.tables WHERE table_schema = current_schema()) sqlite_master")


def translate(sql):
    if sql.lstrip().upper().startswith('PRAGMA QUICK_CHECK'):
        return "SELECT 'ok'"
    sql = re.sub(r'\bsqlite_master\b', _SQLITE_MASTER, sql)
    sql = _PRINTF.sub(lambda m: f"lpad(({m.group(1)})::text, 8, '0')", sql)
    sql = _LC_LIKE.sub(lambda m: f'{m.group(1)}_lc LIKE lower(?)', sql)
    sql = re.sub(r'(?<!_lc )\bLIKE\b(?! lower\(\?\))', 'ILIKE', sql)
    sql = sql.replace('%', '%%').replace('%%%%', '%%')     # literal % for psycopg
    return sql.replace('?', '%s')


class Row(tuple):
    """sqlite3.Row look-alike: row[0], row['col'], keys(), dict(row)."""
    def __new__(cls, cols, values):
        r = super().__new__(cls, values)
        r._idx = cols
        return r

    def __getitem__(self, k):
        if isinstance(k, str):
            return tuple.__getitem__(self, self._idx[k])
        return tuple.__getitem__(self, k)

    def keys(self):
        return list(self._idx)


class _Cursor:
    def __init__(self, conn):
        self._c = conn.cursor()

    def execute(self, sql, params=()):
        self._c.execute(translate(sql), tuple(params))
        return self

    def _wrap(self, r):
        if r is None:
            return None
        cols = {d.name: i for i, d in enumerate(self._c.description)}
        return Row(cols, r)

    def fetchone(self):
        return self._wrap(self._c.fetchone())

    def fetchall(self):
        if self._c.description is None:
            return []
        cols = {d.name: i for i, d in enumerate(self._c.description)}
        return [Row(cols, r) for r in self._c.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        self._c.close()


class PgCarConn:
    def __init__(self, filename):
        import psycopg
        from .rag import config
        self.schema = schema_for(filename)
        self._pg = psycopg.connect(os.environ.get('KG_CARDB_PG_DSN') or config.PGVEC_DSN,
                                   autocommit=True, connect_timeout=3)
        self._pg.execute(f'SET search_path TO {self.schema}')

    def cursor(self):
        return _Cursor(self._pg)

    def execute(self, sql, params=()):
        return _Cursor(self._pg).execute(sql, params)

    def close(self):
        self._pg.close()


def open_ro(path):
    """A fresh (unpooled) connection for a PostgreSQL car, or None; the caller
    closes it, as with sqlite3.connect."""
    name = os.path.basename(str(path))
    return PgCarConn(name) if is_pg(name) else None


def _pgtype(decl):
    d = (decl or '').upper()
    if 'INT' in d:
        return 'bigint'
    if any(x in d for x in ('REAL', 'FLOA', 'DOUB')):
        return 'double precision'
    if 'BLOB' in d:
        return 'bytea'
    return 'text'


def load_sqlite(path, dsn=None, log=print):
    """Copy one car's SQLite file into its own schema and register it.

    Every table and index, SQLite's rowid kept as a column, lowercase twins for
    the LIKE-searched node columns. Built under <schema>_new and renamed into
    place, so readers never see a half-loaded car. Returns {table: rows}."""
    import sqlite3
    import psycopg
    name = os.path.basename(str(path))
    final = schema_for(name)
    tmp = final + '_new'
    src = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    pg = psycopg.connect(dsn or os.environ.get('KG_CARDB_ADMIN_DSN') or 'dbname=kgkg_vec',
                         autocommit=True)
    try:
        pg.execute(f'DROP SCHEMA IF EXISTS {tmp} CASCADE')
        pg.execute(f'CREATE SCHEMA {tmp}')
        counts = {}
        tables = [r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tables:
            cols = [(r[1], r[2], r[5]) for r in src.execute(f'PRAGMA table_info([{t}])')]
            pk = [c for c, _, k in sorted(cols, key=lambda x: x[2]) if k]
            ddl = 'rowid bigint, ' + ', '.join(f'"{c}" {_pgtype(d)}' for c, d, _ in cols)
            if pk:
                ddl += ', PRIMARY KEY (' + ', '.join(f'"{c}"' for c in pk) + ')'
            pg.execute(f'CREATE TABLE {tmp}."{t}" ({ddl})')
            names = 'rowid, ' + ', '.join(f'"{c}"' for c, _, _ in cols)
            with pg.cursor().copy(f'COPY {tmp}."{t}" ({names}) FROM STDIN') as cp:
                for r in src.execute(f'SELECT rowid, * FROM [{t}]'):
                    cp.write_row([v.replace('\x00', '') if isinstance(v, str) else v for v in r])
            counts[t] = src.execute(f'SELECT count(*) FROM [{t}]').fetchone()[0]
        for (sql,) in src.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
            m = re.match(r'CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s*\((.*)\)\s*$',
                         sql.strip(), re.S | re.I)
            if m:
                pg.execute(f'CREATE {m.group(1) or ""}INDEX {m.group(2)} ON {tmp}."{m.group(3)}" ({m.group(4)})')
        if 'nodes' in tables:
            pg.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
            for c in ('title', 'content', 'href', 'path'):
                pg.execute(f'ALTER TABLE {tmp}.nodes ADD COLUMN {c}_lc text '
                           f'GENERATED ALWAYS AS (lower({c})) STORED')
                if c != 'path':
                    pg.execute(f'CREATE INDEX ON {tmp}.nodes USING gin ({c}_lc gin_trgm_ops)')
            pg.execute(f'CREATE INDEX ON {tmp}.nodes (path_lc text_pattern_ops)')
        for t in tables:
            got = pg.execute(f'SELECT count(*) FROM {tmp}."{t}"').fetchone()[0]
            if got != counts[t]:
                raise RuntimeError(f'{name}: {t} has {got} rows in PostgreSQL, {counts[t]} in SQLite')
        pg.execute(f'CREATE TABLE IF NOT EXISTS {REGISTRY} (filename text PRIMARY KEY, '
                   'schema text NOT NULL, nodes bigint, loaded_at timestamptz DEFAULT now())')
        with pg.transaction():
            pg.execute(f'DROP SCHEMA IF EXISTS {final} CASCADE')
            pg.execute(f'ALTER SCHEMA {tmp} RENAME TO {final}')
            pg.execute(f'INSERT INTO {REGISTRY} (filename, schema, nodes) VALUES (%s, %s, %s) '
                       'ON CONFLICT (filename) DO UPDATE SET schema = EXCLUDED.schema, '
                       'nodes = EXCLUDED.nodes, loaded_at = now()',
                       (name, final, counts.get('nodes')))
        pg.execute(f'GRANT USAGE ON SCHEMA {final} TO kgkg')
        pg.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA {final} TO kgkg')
        pg.execute(f'GRANT SELECT ON {REGISTRY} TO kgkg')
        pg.execute(f'ANALYZE {final}.nodes' if 'nodes' in tables else 'SELECT 1')
    finally:
        src.close()
        pg.close()
    forget_cache()
    log(f'{name}: loaded into {final} ({counts.get("nodes")} nodes)')
    return counts


def adopt(path, log=print):
    """Move a new car from its SQLite file into PostgreSQL: load, re-check the
    node count through the serving connection, then delete the SQLite file."""
    counts = load_sqlite(path, log=log)
    con = PgCarConn(os.path.basename(str(path)))
    try:
        got = con.execute('SELECT count(*) FROM nodes').fetchone()[0]
    finally:
        con.close()
    if got != counts.get('nodes'):
        raise RuntimeError(f'{path}: {got} nodes served, {counts.get("nodes")} loaded; SQLite kept')
    for suffix in ('', '-wal', '-shm'):
        try:
            os.remove(f'{path}{suffix}')
        except FileNotFoundError:
            pass
    log(f'{os.path.basename(str(path))}: SQLite file removed')
    return counts


def connect(path):
    """PgCarConn for a car configured for PostgreSQL, else None (use SQLite).

    One connection per thread and car; a broken connection is reopened."""
    name = os.path.basename(str(path))
    if not is_pg(name):
        return None
    pool = getattr(_tls, 'pool', None)
    if pool is None:
        pool = _tls.pool = {}
    c = pool.get(name)
    if c is None or c._pg.closed or c._pg.broken:
        c = pool[name] = PgCarConn(name)
    return c
