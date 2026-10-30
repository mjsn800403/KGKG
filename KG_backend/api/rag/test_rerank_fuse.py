"""Rerank fusion (RAG_RERANK_FUSE): blend of cross-encoder score and retrieval order.

    cd KG_backend
    DJANGO_DEBUG=true .venv/bin/python manage.py test api.rag.test_rerank_fuse -v 2
"""
import unittest
from unittest import mock

from api.rag import config, service


class _CE:
    def __init__(self, scores):
        self.scores = scores

    def predict(self, pairs):
        return self.scores[:len(pairs)]


def _result(n):
    return {'hits': [{'blob_id': i, 'title': f't{i}', 'text': 'x'} for i in range(n)]}


class RerankFuseTest(unittest.TestCase):
    def _run(self, scores, w):
        res = _result(len(scores))
        with mock.patch.object(service, '_get_reranker', return_value=_CE(scores)), \
                mock.patch.object(config, 'RERANK_FUSE', w):
            service._rerank('q', res)
        return [h['blob_id'] for h in res['hits']]

    def test_pure_rerank_when_weight_is_one(self):
        self.assertEqual(self._run([0.1, 0.2, 0.9], 1.0), [2, 1, 0])

    def test_weight_zero_keeps_retrieval_order(self):
        self.assertEqual(self._run([0.1, 0.2, 0.9], 0.0), [0, 1, 2])

    def test_blend_moves_a_strong_rerank_up_one_place_not_to_the_top_from_last(self):
        # second page far ahead on the cross-encoder: promoted over the first
        self.assertEqual(self._run([0.0, 5.0, 0.0], 0.4), [1, 0, 2])
        # last page far ahead: climbs one place, the retrieval top stays first
        self.assertEqual(self._run([0.0, 0.0, 5.0], 0.4), [0, 2, 1])

    def test_zfuse_is_scale_free(self):
        a = service._zfuse([1, 2, 3], [0, -1, -2], 0.5)
        b = service._zfuse([10, 20, 30], [0, -1, -2], 0.5)
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y)
