"""Serving-layer paths not covered by test_service.py: diagnose() and search()
caching and filtering, cache expiry and eviction, the optional reranker and
warm-up. The retriever, the diagnostic engine and the embedding model are
stubbed, so no index or model is needed.

The two filters here are product rules, not optimisations:
  * search() drops hits from other cars and junk below the corpus boundary
    (an out-of-domain query must come back empty, not with five nearest
    neighbours);
  * diagnose() with an allow-list must not disclose the fleet roster through
    its ``available_cars`` hint.
"""
from unittest import mock

from django.test import SimpleTestCase

from api.rag import config, retrieve, service


def hit(title, car='camry', sim=0.9, bm25=0.0):
    return {'title': title, 'car_stem': car, 'similarity': sim, 'title_path': f'/{title}',
            'app_url': f'/x/{title}', 'segments': [title], 'matched_via': 'vector',
            'explain': {'bm25': bm25}, 'text': f'text of {title}'}


class ServiceTestCase(SimpleTestCase):
    def setUp(self):
        service.clear_cache()
        self.addCleanup(service.clear_cache)
        for name, value in (('LOG_QUERIES', False), ('RERANK', False)):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)


class SearchTests(ServiceTestCase):
    def run_search(self, result, **kw):
        with mock.patch.object(retrieve, 'assist', return_value=result) as ra:
            out = service.search('brake pad', car_stem=kw.pop('car_stem', 'camry'), **kw)
        return out, ra

    def test_blank_query_never_reaches_the_retriever(self):
        with mock.patch.object(retrieve, 'assist') as ra:
            self.assertEqual(service.search('   '), [])
        ra.assert_not_called()

    def test_other_cars_hits_are_dropped_and_shape_is_navigation_only(self):
        out, _ = self.run_search({'grounded': True, 'hits': [hit('A'), hit('B', car='supra'), hit('C')]})
        self.assertEqual([o['title'] for o in out], ['A', 'C'])
        self.assertEqual(set(out[0]), {'title', 'segments', 'path', 'app_url', 'node_type',
                                       'is_leaf', 'similarity', 'matched_via'})
        self.assertNotIn('text', out[0])

    def test_out_of_domain_query_keeps_only_real_matches(self):
        res = {'grounded': False, 'top_similarity': 0.2,
               'hits': [hit('noise', sim=0.1), hit('keyword', sim=0.0, bm25=3.2),
                        hit('close', sim=config.SEARCH_SIM_FLOOR + 0.01)]}
        out, _ = self.run_search(res)
        self.assertEqual([o['title'] for o in out], ['keyword', 'close'])

    def test_overfetch_then_trim_to_limit(self):
        hits = [hit(f'h{i}') for i in range(50)]
        out, ra = self.run_search({'grounded': True, 'hits': hits}, limit=5)
        self.assertEqual(len(out), 5)
        self.assertEqual(ra.call_args.kwargs['k'],
                         min(5 * config.SEARCH_OVERFETCH, config.SEARCH_MAX_DEPTH))

    def test_cached_per_limit_and_per_allow_list(self):
        res = {'grounded': True, 'hits': [hit('A')]}
        with mock.patch.object(retrieve, 'assist', return_value=res) as ra:
            service.search('q', car_stem='camry', limit=10)
            service.search('q', car_stem='camry', limit=10)
            self.assertEqual(ra.call_count, 1)
            service.search('q', car_stem='camry', limit=20)
            service.search('q', car_stem='camry', limit=10, allowed_cars={'camry'})
            self.assertEqual(ra.call_count, 3)

    def test_missing_index_propagates_for_the_keyword_fallback(self):
        with mock.patch.object(retrieve, 'assist', side_effect=FileNotFoundError('index')):
            with self.assertRaises(FileNotFoundError):
                service.search('q', car_stem='camry')


class DiagnoseTests(ServiceTestCase):
    def test_roster_hint_is_cut_to_the_callers_cars(self):
        res = {'available_cars': ['camry', 'supra', 'rav4']}
        with mock.patch('api.rag.diag.diagnose', return_value=res):
            out = service.diagnose('P0300', allowed_cars={'camry'})
        self.assertEqual(out['available_cars'], ['camry'])
        self.assertEqual(res['available_cars'], ['camry', 'supra', 'rav4'])   # source not mutated

    def test_unrestricted_caller_sees_the_engine_answer(self):
        res = {'available_cars': ['camry', 'supra']}
        with mock.patch('api.rag.diag.diagnose', return_value=res):
            self.assertEqual(service.diagnose('P0300')['available_cars'], ['camry', 'supra'])

    def test_cached_and_scoped_by_allow_list(self):
        with mock.patch('api.rag.diag.diagnose', return_value={'ok': 1}) as d:
            service.diagnose('P0300', car_stem='camry')
            service.diagnose('P0300', car_stem='camry')
            service.diagnose('P0300', car_stem='camry', allowed_cars={'camry'})
        self.assertEqual(d.call_count, 2)

    def test_expired_entry_is_recomputed(self):
        clock = [1000.0]
        with mock.patch('api.rag.diag.diagnose', return_value={'ok': 1}) as d, \
             mock.patch.object(service.time, 'monotonic', side_effect=lambda: clock[0]):
            service.diagnose('P0300')
            clock[0] += config.DIAG_CACHE_TTL + 1
            service.diagnose('P0300')
        self.assertEqual(d.call_count, 2)


class CacheMechanicsTests(ServiceTestCase):
    def test_exact_cache_expires(self):
        clock = [50.0]
        with mock.patch.object(service.time, 'monotonic', side_effect=lambda: clock[0]):
            service._cache_put('k', {'v': 1})
            self.assertEqual(service._cache_get('k'), {'v': 1})
            clock[0] += config.CACHE_TTL + 1
            self.assertIsNone(service._cache_get('k'))
        self.assertNotIn('k', service._CACHE)

    def test_least_recently_used_entry_is_evicted(self):
        with mock.patch.object(config, 'CACHE_MAX', 2):
            service._cache_put('a', 1)
            service._cache_put('b', 2)
            service._cache_get('a')            # touch a -> b is now oldest
            service._cache_put('c', 3)
        self.assertEqual(list(service._CACHE), ['a', 'c'])

    def test_semantic_cache_never_crosses_scopes(self):
        import numpy as np
        v = np.array([1.0, 0.0], dtype=np.float32)
        with mock.patch.object(config, 'SEM_CACHE_ENABLED', True):
            service._sem_cache_put(v, ('Toyota', '', 'camry', ('camry',)), {'r': 'camry'})
            self.assertIsNone(service._sem_cache_get(v, ('Toyota', '', 'supra', ('supra',))))
            self.assertEqual(service._sem_cache_get(v, ('Toyota', '', 'camry', ('camry',))),
                             {'r': 'camry'})
            self.assertIsNone(service._sem_cache_get(None, ('Toyota', '', 'camry', ('camry',))))


class RerankAndWarmupTests(ServiceTestCase):
    def test_reranker_reorders_only_the_candidate_window(self):
        hits = [hit('a'), hit('b'), hit('c'), hit('tail')]
        result = {'hits': hits}
        fake = mock.Mock()
        fake.predict.return_value = [0.1, 0.9, 0.5]
        with mock.patch.object(config, 'RERANK_CANDIDATES', 3), \
             mock.patch.object(service, '_get_reranker', return_value=fake):
            service._rerank('q', result)
        self.assertEqual([h['title'] for h in result['hits']], ['b', 'c', 'a', 'tail'])
        self.assertTrue(result['reranked'])

    def test_assist_survives_a_broken_reranker(self):
        with mock.patch.object(config, 'RERANK', True), \
             mock.patch.object(retrieve, 'embed_query', return_value=None), \
             mock.patch.object(retrieve, 'assist', return_value={'hits': [hit('a')]}), \
             mock.patch.object(service, '_rerank', side_effect=RuntimeError('no model')):
            self.assertEqual(service.assist('q')['hits'][0]['title'], 'a')

    def test_warmup_never_raises_and_skips_a_missing_index(self):
        with mock.patch.object(config, 'INDEX_DB', mock.Mock(exists=lambda: False)), \
             mock.patch('api.rag.embed.warmup') as ew, \
             mock.patch('api.rag.store.get_index_ro') as gi:
            service.warmup()
        gi.assert_not_called()
        ew.assert_called_once()
        with mock.patch.object(config, 'INDEX_DB', mock.Mock(exists=lambda: True)), \
             mock.patch('api.rag.embed.warmup'), \
             mock.patch('api.rag.store.get_index_ro', side_effect=OSError('locked')):
            service.warmup()                                   # swallowed
