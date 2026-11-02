"""Query adapter in embed.encode: questions only, normalised, and a bad path is ignored.

    cd KG_backend
    DJANGO_DEBUG=true .venv/bin/python manage.py test api.rag.test_query_adapter -v 2
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from api.rag import config, embed


class _Model:
    def encode(self, texts, **kw):
        v = np.zeros((len(texts), 4), dtype=np.float32)
        v[:, 0] = 1.0
        return v


class QueryAdapterTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        U = np.zeros((4, 1), dtype=np.float32); U[1, 0] = 1.0     # adds e1 * (V q)
        V = np.zeros((1, 4), dtype=np.float32); V[0, 0] = 1.0     # V q = q[0]
        np.savez(self.dir / 'adapter.npz', U=U, V=V)
        embed._ADAPTER.clear()
        self.p = [mock.patch.object(embed, 'get_model', return_value=_Model()),
                  mock.patch.object(config, 'QUERY_PREFIX', ''),
                  mock.patch.object(config, 'PASSAGE_PREFIX', '')]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        embed._ADAPTER.clear()
        self._tmp.cleanup()

    def test_off_by_default(self):
        with mock.patch.object(config, 'QUERY_ADAPTER', ''):
            np.testing.assert_allclose(embed.encode(['q'], is_query=True)[0], [1, 0, 0, 0])

    def test_applied_to_queries_and_normalised(self):
        with mock.patch.object(config, 'QUERY_ADAPTER', str(self.dir)):
            v = embed.encode(['q'], is_query=True)[0]
        r = 1 / np.sqrt(2)
        np.testing.assert_allclose(v, [r, r, 0, 0], rtol=1e-6)

    def test_never_applied_to_pages(self):
        with mock.patch.object(config, 'QUERY_ADAPTER', str(self.dir)):
            np.testing.assert_allclose(embed.encode(['p'], is_query=False)[0], [1, 0, 0, 0])

    def test_missing_adapter_serves_base_vectors(self):
        with mock.patch.object(config, 'QUERY_ADAPTER', str(self.dir / 'nope')):
            np.testing.assert_allclose(embed.encode(['q'], is_query=True)[0], [1, 0, 0, 0])
