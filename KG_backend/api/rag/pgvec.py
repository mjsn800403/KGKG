"""Vector KNN on PostgreSQL/pgvector (RAG_VEC_BACKEND=pgvector).

The served index keeps its pages, keyword index and graph in index.rag.db;
only the dense nearest-neighbour step moves. The table holds the same int8
codes as sqlite-vec (cosine ignores scale), built by ops/rag/pgvec_load.py,
with an HNSW index. Any failure returns None so retrieve falls back to
sqlite-vec: the vector store is an accelerator, never a single point of failure.
"""
import logging
import threading

from . import config

log = logging.getLogger(__name__)
_local = threading.local()


def _conn():
    c = getattr(_local, 'conn', None)
    if c is None or c.closed:
        import psycopg
        c = psycopg.connect(config.PGVEC_DSN, autocommit=True, connect_timeout=3)
        c.execute('SET hnsw.ef_search = %s' % int(config.PGVEC_EF_SEARCH))
        _local.conn = c
    return c


def _lit(qvec):
    """The query quantized exactly like sqlite-vec's vec_quantize_int8(.., 'unit'),
    so both backends rank the same int8 codes against the same int8 query
    (a float query here measured 87% top-40 overlap; quantized, 99.98%)."""
    step = 2.0 / 255
    return '[' + ','.join(str(max(-128, min(127, int((float(x) + 1.0) / step - 128))))
                          for x in qvec) + ']'


def knn(qvec, k, ids=None):
    """[(blob_id, cosine_distance)] nearest first, or None on any error.

    ids restricts the search to those blobs (a car's own pages): exact scan
    over the primary key, which is cheaper than HNSW for a few thousand rows.
    """
    try:
        q = _lit(qvec)
        if ids:
            # "+ 0" keeps the planner off the HNSW index: an index scan would
            # filter its ef_search candidates by car and drop the car's pages
            sql = ('SELECT blob_id, (embedding <=> %s::vector) + 0 AS d FROM blob_vec '
                   'WHERE blob_id = ANY(%s) ORDER BY d LIMIT %s')
            args = (q, list(ids), k)
        else:
            sql = 'SELECT blob_id, embedding <=> %s::vector AS d FROM blob_vec ORDER BY d LIMIT %s'
            args = (q, k)
        return [(int(b), float(d)) for b, d in _conn().execute(sql, args).fetchall()]
    except Exception as e:
        log.warning('pgvector knn failed, falling back to sqlite-vec: %s', e)
        _local.conn = None
        return None
