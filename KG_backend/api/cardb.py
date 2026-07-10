"""Pooled, read-only access to the per-vehicle content databases.

Serving previously opened a fresh ``sqlite3.connect`` per request and walked
breadcrumb chains with one query per ancestor. Under load that is a lot of
avoidable syscall + page-cache churn on 400-900MB files. This module gives:

* ``connect(path)`` — a per-thread cached connection, opened read-only
  (``mode=ro`` — serving can never corrupt a manual DB) with pragmas tuned
  for large read-mostly files (mmap, bigger page cache, busy timeout so a
  concurrent WAL checkpoint never surfaces as a 500).
  Connections are keyed by path and re-opened automatically if the underlying
  file is replaced (mtime/size change) — e.g. after a re-crawl or dedupe.
  A small per-thread LRU bounds file descriptors regardless of fleet size:
  scaling from 44 to 4,000 vehicles changes nothing here.

* ``breadcrumbs(conn, node_id)`` — the full ancestor title chain in ONE
  recursive-CTE query instead of a Python loop of per-parent queries
  (search results walked up to ~10 queries per row before).

* ``ready(car)`` / ``ready_path(path)`` — TTL-cached existence checks, so
  catalog listings stop stat()ing every fleet file on every request.

Thread-safety: sqlite3 connections stay on the thread that opened them
(default ``check_same_thread=True``); the pool is a ``threading.local``.
"""
import os
import sqlite3
import threading
import time

MAX_POOLED_PER_THREAD = int(os.environ.get('KG_CARDB_POOL', '8'))
READY_TTL_S = 30.0

_tls = threading.local()


def _pragmas(conn):
    cur = conn.cursor()
    # 256MB mmap: the OS page cache backs repeated tree walks with zero-copy
    # reads. Harmless if the file is smaller / memory is tight (best-effort).
    cur.execute('PRAGMA mmap_size = 268435456')
    cur.execute('PRAGMA cache_size = -16384')      # 16MB page cache
    cur.execute('PRAGMA temp_store = MEMORY')
    cur.execute('PRAGMA busy_timeout = 5000')
    cur.close()


def connect(path):
    """Read-only pooled connection to ``path`` for the current thread."""
    path = str(path)
    pool = getattr(_tls, 'pool', None)
    if pool is None:
        pool = _tls.pool = {}

    st = os.stat(path)                     # raises FileNotFoundError like before
    sig = (st.st_mtime_ns, st.st_size)

    entry = pool.get(path)
    if entry is not None:
        conn, old_sig, _ = entry
        if old_sig == sig:
            pool[path] = (conn, sig, time.monotonic())   # refresh LRU stamp
            return conn
        try:
            conn.close()                   # file was replaced -> reopen
        except sqlite3.Error:
            pass
        pool.pop(path, None)

    if len(pool) >= MAX_POOLED_PER_THREAD:
        oldest = min(pool, key=lambda k: pool[k][2])
        try:
            pool[oldest][0].close()
        except sqlite3.Error:
            pass
        pool.pop(oldest, None)

    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    _pragmas(conn)
    pool[path] = (conn, sig, time.monotonic())
    return conn


def breadcrumbs(conn, node_id):
    """Ancestor titles for ``node_id``, outermost first, excluding the root
    breadcrumb itself (matches what the old per-parent walk produced)."""
    rows = conn.execute("""
        WITH RECURSIVE chain(id, parent_id, title, depth) AS (
            SELECT id, parent_id, title, depth FROM nodes WHERE id = ?
            UNION ALL
            SELECT n.id, n.parent_id, n.title, n.depth
            FROM nodes n JOIN chain c ON n.id = c.parent_id
        )
        SELECT title, parent_id FROM chain ORDER BY depth
    """, (node_id,)).fetchall()
    # The old loop stopped once it reached a row with parent_id IS NULL and
    # did NOT include that row's title.
    return [r['title'] for r in rows if r['parent_id'] is not None]


# ---------------------------------------------------------------------------
# TTL-cached readiness checks
# ---------------------------------------------------------------------------
_ready_cache = {}
_ready_lock = threading.Lock()


def ready_path(path):
    """Does the car DB file exist? stat() at most once per READY_TTL_S."""
    path = str(path)
    now = time.monotonic()
    with _ready_lock:
        hit = _ready_cache.get(path)
        if hit is not None and now - hit[1] < READY_TTL_S:
            return hit[0]
    ok = os.path.isfile(path)
    with _ready_lock:
        _ready_cache[path] = (ok, now)
        if len(_ready_cache) > 4096:       # bound: prune expired entries
            for k in [k for k, v in _ready_cache.items() if now - v[1] >= READY_TTL_S]:
                _ready_cache.pop(k, None)
    return ok


def invalidate_ready_cache():
    with _ready_lock:
        _ready_cache.clear()
