"""The pgvector backend switch: dispatch, scoped ids, and the sqlite-vec fallback.

    cd KG_backend
    DJANGO_DEBUG=true .venv/bin/python manage.py test api.rag.test_pgvec -v 2
"""
import unittest
from unittest import mock

from api.rag import config, pgvec, retrieve


class _Rows:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None

    def execute(self, sql, args):
        self.sql = sql
        return self

    def fetchall(self):
        return self.rows


class KnnBackendTest(unittest.TestCase):
    def test_sqlite_default_does_not_touch_postgres(self):
        idx = _Rows([{'bid': 7, 'dist': 0.25}])
        with mock.patch.object(config, 'VEC_BACKEND', 'sqlite'), \
                mock.patch.object(pgvec, 'knn') as pk:
            self.assertEqual(retrieve._knn(idx, [0.0], b'', 5), [(7, 0.25)])
        pk.assert_not_called()

    def test_pgvector_used_when_configured(self):
        idx = _Rows([])
        with mock.patch.object(config, 'VEC_BACKEND', 'pgvector'), \
                mock.patch.object(pgvec, 'knn', return_value=[(3, 0.1)]) as pk:
            self.assertEqual(retrieve._knn(idx, [0.0], b'', 5, [3, 4]), [(3, 0.1)])
        pk.assert_called_once_with([0.0], 5, [3, 4])
        self.assertIsNone(idx.sql)

    def test_pgvector_failure_falls_back_to_sqlite_vec(self):
        idx = _Rows([{'bid': 9, 'dist': 0.5}])
        with mock.patch.object(config, 'VEC_BACKEND', 'pgvector'), \
                mock.patch.object(pgvec, 'knn', return_value=None):
            self.assertEqual(retrieve._knn(idx, [0.0], b'', 5, [9]), [(9, 0.5)])
        self.assertIn('rowid IN (9)', idx.sql)

    def test_unreachable_postgres_returns_none(self):
        with mock.patch.object(config, 'PGVEC_DSN', 'host=127.0.0.1 port=1 dbname=x connect_timeout=1'):
            pgvec._local.conn = None
            self.assertIsNone(pgvec.knn([0.0] * 4, 3))
