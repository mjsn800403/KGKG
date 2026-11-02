"""Keyword search (BM25) on PostgreSQL (RAG_FTS_BACKEND=pg).

Same formula as SQLite FTS5's bm25() with column weights (see
ops/rag/pgfts_load.py), over schema rag in the pgvector database. Returns the
FTS5 sign convention (more negative = better) so the fusion code is unchanged.
Any failure returns None and retrieve falls back to FTS5.
"""
import logging

from . import config, pgvec

log = logging.getLogger(__name__)

_SQL = """
WITH q AS (SELECT DISTINCT lexeme FROM unnest(to_tsvector('english', %(q)s))),
s AS (
  SELECT t.blob_id,
    greatest(1e-6, ln((st.n - f.df + 0.5) / (f.df + 0.5))) *
    (w.tf * 2.2) / (w.tf + 1.2 * (0.25 + 0.75 * d.dl / st.avgdl)) AS sc
  FROM q
  JOIN rag.terms t USING (lexeme)
  JOIN rag.df f USING (lexeme)
  JOIN rag.doclen d USING (blob_id)
  CROSS JOIN rag.stats st
  CROSS JOIN LATERAL (SELECT %(wc)s * t.tf_comp + %(wt)s * t.tf_title + %(wx)s * t.tf_text AS tf) w
  {scope})
SELECT blob_id, -sum(sc) AS bm FROM s GROUP BY blob_id ORDER BY bm LIMIT %(k)s
"""
_GLOBAL = _SQL.format(scope='')
_SCOPED = _SQL.format(scope='WHERE t.blob_id = ANY(%(ids)s)')


def search(fts_query, k, ids=None):
    """[(blob_id, bm25)] best first (bm25 negative, like FTS5), or None on error.

    fts_query is retrieve's FTS5 MATCH string ('a OR b OR c'); ids restricts
    the search to those blobs (a car's own pages)."""
    if not fts_query:
        return []
    args = {'q': fts_query.replace(' OR ', ' '), 'k': int(k),
            'wc': config.FTS_W_COMP, 'wt': config.FTS_W_TITLE, 'wx': config.FTS_W_TEXT}
    try:
        if ids:
            args['ids'] = list(ids)
            rows = pgvec._conn().execute(_SCOPED, args).fetchall()
        else:
            rows = pgvec._conn().execute(_GLOBAL, args).fetchall()
        return [(int(b), float(bm)) for b, bm in rows]
    except Exception as e:
        log.warning('pg keyword search failed, falling back to FTS5: %s', e)
        pgvec._local.conn = None
        return None
