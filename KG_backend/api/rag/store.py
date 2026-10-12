"""Database access for the RAG layer.

Two kinds of connections:
  * read-only connections to the ORIGINAL car DBs (mode=ro -> writes are
    impossible at the OS/driver level, so the originals can never be touched);
  * a read/write connection to our own unified index DB under _rag/.
"""
import sqlite3
import struct
import threading
import numpy as np
import sqlite_vec

from . import config


# --- keyword index (FTS) schema --------------------------------------------
# Contentless (content='') so the page text is NOT duplicated inside the FTS
# shadow tables -- the display copy lives in blobs.text; the FTS keeps only its
# inverted index (roughly halves the on-disk keyword footprint). The porter
# stemmer + diacritic folding lift recall so 'brakes'/'replacing' match
# 'brake'/'replace'. rowid == blob_id. retrieve.py only reads rowid + bm25(),
# never a stored column, so contentless is transparent to serving.
FTS_TOKENIZE = "porter unicode61 remove_diacritics 2"


def _fts_ddl(if_not_exists=True):
    ine = "IF NOT EXISTS " if if_not_exists else ""
    return (f"CREATE VIRTUAL TABLE {ine}blobs_fts USING fts5("
            f"text, title, comp, content='', tokenize='{FTS_TOKENIZE}')")


# --- original car DB: strictly read-only -----------------------------------
def open_car_ro(db_path):
    """Open an original car DB read-only. ``mode=ro`` makes any write attempt
    fail with an error rather than mutating the file."""
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# --- unified index DB: our own read/write store -----------------------------
def open_index(path=None, vec=True, write=True, check_same_thread=True):
    """Open (creating if needed) the unified index DB with sqlite-vec loaded."""
    path = path or config.INDEX_DB
    config.RAG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    if vec:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    if write:
        conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


# --- process-wide cached read connection for serving ------------------------
# Opening a fresh connection AND reloading the sqlite-vec extension on every
# query costs tens of ms plus page-cache/mmap warmup. The serving path is
# read-only and already serialised by the service layer's lock, so we keep a
# single shared connection and reuse it. (check_same_thread=False because
# gunicorn/Django may dispatch requests on different worker threads; concurrent
# use is still gated by service._LOCK.)
_INDEX_RO = None
_INDEX_RO_LOCK = threading.Lock()


def get_index_ro(path=None):
    """Return the cached read-only serving connection, opening it once."""
    global _INDEX_RO
    if _INDEX_RO is not None:
        return _INDEX_RO
    with _INDEX_RO_LOCK:
        if _INDEX_RO is None:
            _INDEX_RO = open_index(path=path, vec=True, write=False,
                                   check_same_thread=False)
        return _INDEX_RO


def reset_index_ro():
    """Drop the cached serving connection (e.g. after a rebuild). Next
    get_index_ro() reopens it."""
    global _INDEX_RO
    with _INDEX_RO_LOCK:
        if _INDEX_RO is not None:
            try:
                _INDEX_RO.close()
            except Exception:
                pass
            _INDEX_RO = None


def init_index_schema(conn):
    """Create all tables for the unified, deduplicated, per-page index."""
    conn.executescript(f"""
    -- unique content blobs (content-addressed; one row per unique page) ----
    CREATE TABLE IF NOT EXISTS blobs (
        blob_id      INTEGER PRIMARY KEY,   -- == vec rowid
        content_hash TEXT UNIQUE NOT NULL,
        kind         TEXT,            -- 'labor' | 'repair' | 'other'
        title        TEXT,            -- representative leaf title
        comp_readable TEXT,           -- car-independent component breadcrumb
        text         TEXT NOT NULL,   -- full cleaned page text (for display + FTS)
        n_occ        INTEGER DEFAULT 0
    );

    -- every place a blob appears across the fleet --------------------------
    CREATE TABLE IF NOT EXISTS occurrences (
        occ_id      INTEGER PRIMARY KEY,
        blob_id     INTEGER NOT NULL,
        car_stem    TEXT NOT NULL,
        brand       TEXT, model TEXT, variant TEXT, year INTEGER,
        node_id     TEXT NOT NULL,
        title       TEXT,
        title_path  TEXT,            -- breadcrumb "A › B › C"
        system_tags TEXT,
        href        TEXT             -- original page filename
    );
    CREATE INDEX IF NOT EXISTS idx_occ_blob ON occurrences(blob_id);
    CREATE INDEX IF NOT EXISTS idx_occ_car  ON occurrences(car_stem);

    -- serving vectors: int8, cosine (rowid == blob_id) --------------------
    CREATE VIRTUAL TABLE IF NOT EXISTS vec_blobs USING vec0(
        embedding int8[{config.EMBED_DIM}] distance_metric=cosine
    );

    -- keyword search over page text (rowid == blob_id). Contentless +
    -- porter-stemmed; see FTS_TOKENIZE / _fts_ddl above. --------------------
    {_fts_ddl()};

    -- relationship graph (blob-level) -------------------------------------
    CREATE TABLE IF NOT EXISTS edges (
        src_blob INTEGER NOT NULL,
        dst_blob INTEGER NOT NULL,
        relation TEXT NOT NULL,          -- 'semantic' | 'crosslink' | 'labor_time'
        weight   REAL DEFAULT 1.0
    );
    CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_blob);

    CREATE TABLE IF NOT EXISTS cars (
        car_stem TEXT PRIMARY KEY, brand TEXT, model TEXT, variant TEXT,
        year INTEGER, n_occ INTEGER DEFAULT 0, built_at TEXT
    );
    CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    conn.commit()


def rebuild_fts(conn, log=print):
    """Drop and rebuild the contentless keyword index from blobs.text.

    Migrates an older *contained* FTS (which duplicated the page text in a
    blobs_fts_content shadow table) to the contentless + porter-stemmer form,
    re-tokenising every blob. SQLite-only: no embedding model, runs in seconds.
    Safe to run on the live index between builds -- the serving connection
    reopens lazily via reset_index_ro()."""
    conn.execute("DROP TABLE IF EXISTS blobs_fts")
    conn.execute(_fts_ddl())
    conn.execute(
        "INSERT INTO blobs_fts(rowid, text, title, comp) "
        "SELECT blob_id, text, title, comp_readable FROM blobs")
    try:                                  # merge b-tree segments -> faster MATCH
        conn.execute("INSERT INTO blobs_fts(blobs_fts) VALUES('optimize')")
    except Exception:
        pass
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]
    log(f"    blobs_fts rebuilt: {n} rows (contentless, porter stemmer)")
    return n


def optimize(conn, log=print):
    """Refresh the SQLite query-planner statistics (ANALYZE) + merge FTS
    segments. Cheap, SQLite-only; sharpens planning for the occurrences/edges
    joins and keeps keyword search fast. Run at the end of a build, or anytime."""
    conn.execute("ANALYZE")
    try:
        conn.execute("INSERT INTO blobs_fts(blobs_fts) VALUES('optimize')")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA optimize")
    except Exception:
        pass
    conn.commit()
    log("    ANALYZE + FTS optimize done")


def ensure_build_vec(conn):
    """Transient full-precision float table, used only to build the semantic
    graph. Dropped once edges are written so the served index stays int8-only."""
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_build USING vec0("
        f"embedding float[{config.EMBED_DIM}] distance_metric=cosine)"
    )
    conn.commit()


def drop_build_vec(conn):
    conn.execute("DROP TABLE IF EXISTS vec_build")
    conn.commit()


def clear_data(conn):
    """Wipe all content tables so a (re)ingest starts clean. Used when ingest
    has NOT completed (fresh index, or a build interrupted mid-ingest) so we
    never accumulate duplicate occurrences. The expensive embed stage is
    resumed separately and is never cleared once ingest is complete."""
    for t in ('blobs', 'occurrences', 'edges'):
        conn.execute(f"DELETE FROM {t}")
    # A contentless fts5 table rejects a plain DELETE, so reset it by dropping
    # and recreating the (empty) table instead.
    conn.execute("DROP TABLE IF EXISTS blobs_fts")
    conn.execute(_fts_ddl())
    try:
        conn.execute("DELETE FROM vec_blobs")
    except Exception:
        pass
    conn.execute("DROP TABLE IF EXISTS vec_build")
    conn.execute("DELETE FROM meta WHERE k='ingest_done'")
    conn.commit()


# --- float packing helpers (vec0 stores raw little-endian float32) ----------
def pack_f32(vec):
    """Pack a python/numpy float vector as little-endian float32 bytes."""
    a = np.asarray(vec, dtype=np.float32)
    return a.tobytes()
