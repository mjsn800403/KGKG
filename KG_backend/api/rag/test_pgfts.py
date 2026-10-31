"""The PostgreSQL keyword backend switch: dispatch, scoping, FTS5 fallback.

    cd KG_backend
    DJANGO_DEBUG=true .venv/bin/python manage.py test api.rag.test_pgfts -v 2
"""
import unittest
from unittest import mock

from api.rag import config, pgfts, retrieve


class _Rows:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def execute(self, sql, args):
        self.calls += 1
        return self

    def fetchall(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class Bm25BackendTest(unittest.TestCase):
    def test_sqlite_default_never_touches_postgres(self):
        idx = _Rows([{'bid': 4, 'bm': -3.0}])
        with mock.patch.object(config, 'FTS_BACKEND', 'sqlite'), \
                mock.patch.object(pgfts, 'search') as ps:
            self.assertEqual(retrieve._bm25(idx, 'brake OR pad', 5), [(4, -3.0)])
        ps.assert_not_called()

    def test_pg_used_when_configured(self):
        idx = _Rows([])
        with mock.patch.object(config, 'FTS_BACKEND', 'pg'), \
                mock.patch.object(pgfts, 'search', return_value=[(7, -9.0)]) as ps:
            self.assertEqual(retrieve._bm25(idx, 'brake OR pad', 5), [(7, -9.0)])
        ps.assert_called_once_with('brake OR pad', 5)
        self.assertEqual(idx.calls, 0)

    def test_pg_failure_falls_back_to_fts5(self):
        idx = _Rows([{'bid': 1, 'bm': -2.0}])
        with mock.patch.object(config, 'FTS_BACKEND', 'pg'), \
                mock.patch.object(pgfts, 'search', return_value=None):
            self.assertEqual(retrieve._bm25(idx, 'brake', 5), [(1, -2.0)])

    def test_scoped_pg_filters_by_the_cars_blobs(self):
        with mock.patch.object(config, 'FTS_BACKEND', 'pg'), \
                mock.patch.object(pgfts, 'search', return_value=[(3, -1.0)]) as ps:
            self.assertEqual(retrieve._bm25_scoped(_Rows([]), 'brake', {3, 8}), [(3, -1.0)])
        self.assertEqual(ps.call_args.args[2], {3, 8})

    def test_scoped_fts5_keeps_only_own_blobs_up_to_the_cap(self):
        rows = [{'bid': b, 'bm': -float(b)} for b in (9, 3, 8, 5)]
        with mock.patch.object(config, 'FTS_BACKEND', 'sqlite'), \
                mock.patch.object(config, 'SCOPE_FTS_K', 2):
            self.assertEqual(retrieve._bm25_scoped(_Rows(rows), 'x', {3, 5, 8}), [(3, -3.0), (8, -8.0)])

    def test_unreachable_postgres_returns_none(self):
        with mock.patch.object(config, 'PGVEC_DSN', 'host=127.0.0.1 port=1 dbname=x connect_timeout=1'):
            from api.rag import pgvec
            pgvec._local.conn = None
            self.assertIsNone(pgfts.search('brake', 3))

    def test_empty_query_is_empty(self):
        self.assertEqual(pgfts.search('', 3), [])
