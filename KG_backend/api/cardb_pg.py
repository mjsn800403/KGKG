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


_loaded = {'at': -1e9, 'schemas': frozenset()}
_LOADED_TTL_S = 60.0


def _loaded_schemas():
    """car_* schemas present in PostgreSQL (cached; empty if unreachable)."""
    now = time.monotonic()
    if now - _loaded['at'] >= _LOADED_TTL_S:
        try:
            import psycopg
            from .rag import config
            with psycopg.connect(os.environ.get('KG_CARDB_PG_DSN') or config.PGVEC_DSN,
                                 connect_timeout=3) as c:
                rows = c.execute(r"SELECT nspname FROM pg_namespace WHERE nspname LIKE 'car\_%'").fetchall()
            _loaded['schemas'] = frozenset(r[0] for r in rows)
        except Exception:
            log.warning('cannot list PostgreSQL car schemas', exc_info=True)
        _loaded['at'] = now
    return _loaded['schemas']


def is_pg(filename):
    """Is this car served from PostgreSQL? KG_CARDB_PG lists file names, or
    is '*' for every car whose schema has been loaded."""
    cars = pg_cars()
    if not cars:
        return False
    name = os.path.basename(str(filename))
    if name in cars:
        return True
    return '*' in cars and schema_for(name) in _loaded_schemas()


def schema_for(filename):
    # a stable, identifier-safe name, not a security boundary
    return 'car_' + hashlib.md5(filename.encode('utf-8'), usedforsecurity=False).hexdigest()[:16]


def translate(sql):
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
