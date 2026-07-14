"""Integration tests for the serving layer's caching + invalidation, with the
embedding model and vector index stubbed out (so CI needs no GPU / built index).

Covers: exact-key cache, paraphrase (semantic) cache, and clear_cache() — the
path the feedback views now call on every rate/pin so answers don't go stale.

    cd KG_backend
    DJANGO_DEBUG=true .venv/bin/python manage.py test api.rag.test_service -v 2
"""
import unittest

import numpy as np

from api.rag import config, service, retrieve


class ServiceCacheTest(unittest.TestCase):
    def setUp(self):
        service.clear_cache()
        self._orig = {
            'embed_query': retrieve.embed_query,
            'assist': retrieve.assist,
            'LOG_QUERIES': config.LOG_QUERIES,
            'RERANK': getattr(config, 'RERANK', False),
            'SEM': config.SEM_CACHE_ENABLED,
        }
        config.LOG_QUERIES = False        # no sqlite writes in the test
        config.RERANK = False
        config.SEM_CACHE_ENABLED = True

        # Every query embeds to the SAME unit vector -> cosine 1.0 between any
        # two queries, so the semantic cache always considers them paraphrases.
        self._fixed_vec = np.array([1.0] + [0.0] * 9, dtype=np.float32)
        retrieve.embed_query = lambda q: self._fixed_vec

        self.calls = []
        def fake_assist(query, brand=None, model=None, car_stem=None, k=None, qvec=None,
                        allowed_cars=None):
            self.calls.append(query)
            return {'query': query,
                    'scope': {'brand': brand, 'model': model, 'car_stem': car_stem},
                    'hits': [{'blob_id': 1, 'score': 0.9}], 'grounded': True}
        retrieve.assist = fake_assist

    def tearDown(self):
        retrieve.embed_query = self._orig['embed_query']
        retrieve.assist = self._orig['assist']
        config.LOG_QUERIES = self._orig['LOG_QUERIES']
        config.RERANK = self._orig['RERANK']
        config.SEM_CACHE_ENABLED = self._orig['SEM']
        service.clear_cache()

    def test_exact_key_cache_skips_retrieval(self):
        service.assist('brake fluid', model='Corolla')
        service.assist('brake fluid', model='Corolla')      # identical key
        self.assertEqual(len(self.calls), 1)                # second served cached

    def test_semantic_cache_serves_paraphrase(self):
        service.assist('how to bleed brakes', model='Corolla')
        # Different wording, same scope -> exact-key miss but semantic-cache hit
        # (stubbed embeddings are identical), so retrieval must NOT run again.
        service.assist('bleeding the brakes procedure', model='Corolla')
        self.assertEqual(len(self.calls), 1)

    def test_scope_separates_semantic_cache(self):
        service.assist('q', model='Corolla')
        service.assist('q2', model='Yaris')                 # different scope
        self.assertEqual(len(self.calls), 2)                # no cross-scope reuse

    def test_clear_cache_forces_recompute(self):
        service.assist('brake fluid', model='Corolla')
        service.clear_cache()                               # what rate/pin trigger
        service.assist('brake fluid', model='Corolla')
        self.assertEqual(len(self.calls), 2)                # recomputed after clear

    def test_allowed_cars_is_part_of_cache_identity(self):
        # A restricted caller must never be served an unrestricted (or
        # differently-restricted) caller's cached answer. Same query+scope but a
        # different allow-list is a cache MISS -> retrieval runs again.
        service.assist('brake fluid', model='Corolla')                      # unrestricted
        service.assist('brake fluid', model='Corolla', allowed_cars={'Corolla'})
        service.assist('brake fluid', model='Corolla', allowed_cars={'Yaris'})
        self.assertEqual(len(self.calls), 3)                # three distinct identities
        # And the allow-list is forwarded to the retriever unchanged.
        service.clear_cache()
        seen = {}
        orig = retrieve.assist
        def capture(query, **kw):
            seen['allowed'] = kw.get('allowed_cars')
            return orig(query, **kw)
        retrieve.assist = capture
        try:
            service.assist('brakes', model='Corolla', allowed_cars={'Corolla', 'Yaris'})
        finally:
            retrieve.assist = orig
        self.assertEqual(seen['allowed'], {'Corolla', 'Yaris'})


if __name__ == '__main__':
    unittest.main()
