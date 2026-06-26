"""Lightweight query log (self-improvement signal).

Every assist call is appended to a small sidecar DB, separate from the index so
it never interferes with serving. This is the raw material for: warming the
answer cache with common questions, spotting gaps ("asked but no good hit"),
and—later—learning to rank from real usage. Best-effort: any failure here is
swallowed so logging can never break an answer.
"""
import json
import math
import sqlite3
import threading
import time

from . import config, scoring

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id        INTEGER PRIMARY KEY,
    ts        TEXT DEFAULT (datetime('now')),
    query     TEXT,
    brand     TEXT, model TEXT, car_stem TEXT,
    n_hits    INTEGER,
    top_score REAL,
    top_blobs TEXT,     -- comma-joined blob_ids of the hits
    cached    INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS clicks (
    id        INTEGER PRIMARY KEY,
    ts        TEXT DEFAULT (datetime('now')),
    query     TEXT,
    blob_id   INTEGER,
    app_url   TEXT
);
-- explicit user verdicts (human-in-the-loop). One row per 👍/👎.
CREATE TABLE IF NOT EXISTS ratings (
    id        INTEGER PRIMARY KEY,
    ts        TEXT DEFAULT (datetime('now')),
    query     TEXT,
    brand     TEXT, model TEXT, car_stem TEXT,
    mode      TEXT,              -- 'assist' | 'diagnose'
    top_blobs TEXT,             -- the blobs shown when the verdict was given
    blob_id   INTEGER,          -- specific source rated (optional)
    verdict   INTEGER,          -- +1 up / -1 down
    reason    TEXT,             -- 'wrong' | 'irrelevant' | 'incomplete' | ...
    comment   TEXT
);
-- expert "pinned / verified answers": a curated source for a query pattern.
CREATE TABLE IF NOT EXISTS overrides (
    id            INTEGER PRIMARY KEY,
    ts            TEXT DEFAULT (datetime('now')),
    pattern_query TEXT,
    qvec          TEXT,         -- JSON unit vector of pattern_query (for matching)
    source_app_url TEXT,
    source_blob_id INTEGER,
    title         TEXT,
    note          TEXT,
    created_by    TEXT,
    active        INTEGER DEFAULT 1
);
"""

# migrations for an already-built feedback.db (idempotent, best-effort)
_MIGRATIONS = (
    "ALTER TABLE queries ADD COLUMN latency_ms REAL",
)


def _conn():
    config.RAG_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(config.FEEDBACK_DB), timeout=2.0)
    c.executescript(_SCHEMA)
    for stmt in _MIGRATIONS:
        try:
            c.execute(stmt)
        except sqlite3.OperationalError:
            pass    # column already present
    return c


def log_query(query, scope, result, cached=False, latency_ms=None):
    if not config.LOG_QUERIES:
        return
    try:
        hits = result.get('hits', []) if result else []
        top_blobs = ','.join(str(h.get('blob_id', '')) for h in hits[:8])
        top_score = hits[0]['score'] if hits else None
        c = _conn()
        c.execute(
            "INSERT INTO queries(query,brand,model,car_stem,n_hits,top_score,top_blobs,cached,latency_ms) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (query, (scope or {}).get('brand'), (scope or {}).get('model'),
             (scope or {}).get('car_stem'), len(hits), top_score, top_blobs,
             1 if cached else 0, latency_ms))
        c.commit()
        c.close()
    except Exception:
        pass


def log_click(query, blob_id, app_url):
    """Optional: the frontend can report which result the user opened — a strong
    relevance signal for future ranking."""
    if not config.LOG_QUERIES:
        return
    try:
        c = _conn()
        c.execute("INSERT INTO clicks(query,blob_id,app_url) VALUES (?,?,?)",
                  (query, blob_id, app_url))
        c.commit()
        c.close()
    except Exception:
        pass


def common_queries(limit=50, min_count=2):
    """Most-asked queries (for warming the cache). Returns [(query, count), ...]."""
    try:
        c = _conn()
        rows = c.execute(
            "SELECT query, COUNT(*) n FROM queries GROUP BY lower(query) "
            "HAVING n >= ? ORDER BY n DESC LIMIT ?", (min_count, limit)).fetchall()
        c.close()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Human-in-the-loop: record verdicts and turn them into a guarded ranking boost
# ---------------------------------------------------------------------------
def rate(query, scope, mode, top_blobs, verdict, blob_id=None, reason=None,
         comment=None):
    """Record an explicit 👍 (+1) / 👎 (-1) verdict. Best-effort."""
    if not config.LOG_QUERIES:
        return
    try:
        scope = scope or {}
        tb = ','.join(str(b) for b in top_blobs) if isinstance(top_blobs, (list, tuple)) else (top_blobs or '')
        c = _conn()
        c.execute(
            "INSERT INTO ratings(query,brand,model,car_stem,mode,top_blobs,blob_id,verdict,reason,comment) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (query, scope.get('brand'), scope.get('model'), scope.get('car_stem'),
             mode, tb, blob_id, 1 if int(verdict) >= 0 else -1, reason, comment))
        c.commit()
        c.close()
        invalidate_boost_cache()
    except Exception:
        pass


_BOOST_CACHE = {'at': 0.0, 'map': {}}
_BOOST_LOCK = threading.Lock()


def invalidate_boost_cache():
    _BOOST_CACHE['at'] = 0.0


def _decayed_counts():
    """Per-blob time-decayed (up, down, clicks) from ratings + clicks. Older
    signals fade with FB_HALF_LIFE_DAYS so the loop tracks current truth."""
    hl = max(1.0, config.FB_HALF_LIFE_DAYS)
    agg = {}    # blob_id -> [up, down, clicks]
    c = _conn()
    try:
        # ratings: a verdict can target a specific blob, else the whole hit set
        for blob_id, top_blobs, verdict, age_d in c.execute(
                "SELECT blob_id, top_blobs, verdict, "
                "(julianday('now') - julianday(ts)) AS age FROM ratings"):
            w = 0.5 ** (max(0.0, float(age_d or 0.0)) / hl)
            targets = [blob_id] if blob_id is not None else \
                [int(b) for b in (top_blobs or '').split(',') if b.strip().isdigit()]
            for b in targets:
                slot = agg.setdefault(int(b), [0.0, 0.0, 0.0])
                if int(verdict) >= 0:
                    slot[0] += w
                else:
                    slot[1] += w
        # clicks are a weak implicit positive
        for blob_id, age_d in c.execute(
                "SELECT blob_id, (julianday('now') - julianday(ts)) AS age FROM clicks "
                "WHERE blob_id IS NOT NULL"):
            w = 0.5 ** (max(0.0, float(age_d or 0.0)) / hl)
            agg.setdefault(int(blob_id), [0.0, 0.0, 0.0])[2] += w
    finally:
        c.close()
    return agg


def blob_boost_map():
    """{blob_id: multiplier} from decayed feedback, cached for FB_CACHE_TTL.
    Empty (no effect) when feedback boosting is disabled or there's no signal."""
    if not config.FEEDBACK_BOOST:
        return {}
    now = time.monotonic()
    if now - _BOOST_CACHE['at'] < config.FB_CACHE_TTL:
        return _BOOST_CACHE['map']
    with _BOOST_LOCK:
        if time.monotonic() - _BOOST_CACHE['at'] < config.FB_CACHE_TTL:
            return _BOOST_CACHE['map']
        out = {}
        try:
            counts = _decayed_counts()
            for bid, (up, down, clk) in counts.items():
                m = scoring.feedback_multiplier(
                    up, down, clk, min_count=config.FB_MIN_COUNT,
                    cap_lo=config.FB_CAP_LO, cap_hi=config.FB_CAP_HI)
                if m != 1.0:
                    out[bid] = m
        except Exception as e:
            import sys, traceback
            traceback.print_exc(file=sys.stderr)
            out = {}
        _BOOST_CACHE['map'] = out
        _BOOST_CACHE['at'] = time.monotonic()
        return out


# ---------------------------------------------------------------------------
# Expert pinned answers (qvec-matched curated overrides)
# ---------------------------------------------------------------------------
def add_override(pattern_query, qvec, source_app_url, source_blob_id=None,
                 title=None, note=None, created_by=None):
    """Pin an expert-verified source for a query pattern. `qvec` is a unit
    embedding (list of floats) of pattern_query, stored for cosine matching."""
    try:
        c = _conn()
        c.execute(
            "INSERT INTO overrides(pattern_query,qvec,source_app_url,source_blob_id,"
            "title,note,created_by) VALUES (?,?,?,?,?,?,?)",
            (pattern_query, json.dumps(list(qvec)), source_app_url, source_blob_id,
             title, note, created_by))
        c.commit()
        c.close()
        return True
    except Exception:
        return False


def recent_downvotes(limit=50):
    """Recent 👎 verdicts for the admin review queue. Returns a list of dicts."""
    try:
        c = _conn()
        rows = c.execute(
            "SELECT ts, query, brand, model, car_stem, mode, top_blobs, blob_id, "
            "reason, comment FROM ratings WHERE verdict < 0 ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        c.close()
    except Exception:
        return []
    cols = ('ts', 'query', 'brand', 'model', 'car_stem', 'mode', 'top_blobs',
            'blob_id', 'reason', 'comment')
    return [dict(zip(cols, r)) for r in rows]


def pinned_match(qvec, floor=None):
    """Best active expert override whose pattern cosine-matches qvec >= floor,
    or None. `qvec` is a unit vector (so cosine == dot). The overrides table is
    tiny, so a plain Python scan is plenty fast."""
    floor = config.PIN_SIM if floor is None else floor
    try:
        q = [float(x) for x in qvec]
        c = _conn()
        rows = c.execute(
            "SELECT pattern_query,qvec,source_app_url,source_blob_id,title,note "
            "FROM overrides WHERE active=1").fetchall()
        c.close()
    except Exception:
        return None
    best, best_sim = None, floor
    for pattern, qvec_json, app_url, blob_id, title, note in rows:
        try:
            v = json.loads(qvec_json)
        except (ValueError, TypeError):
            continue
        if len(v) != len(q):
            continue
        sim = sum(a * b for a, b in zip(q, v))
        if sim >= best_sim:
            best_sim = sim
            best = {'pattern_query': pattern, 'app_url': app_url,
                    'blob_id': blob_id, 'title': title, 'note': note,
                    'similarity': round(float(sim), 4)}
    return best
