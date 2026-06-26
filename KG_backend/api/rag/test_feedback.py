"""Integration tests for the human-in-the-loop feedback store (sqlite only,
no embedding model). Exercises the real feedback.db schema + queries against a
throwaway DB so CI can run them with no GPU and no built index.

Run under Django's test runner (config imports django.conf.settings):

    cd KG_backend
    DJANGO_DEBUG=true .venv/bin/python manage.py test api.rag.test_feedback -v 2
"""
import tempfile
import unittest
from pathlib import Path

from api.rag import config, feedback


class FeedbackStoreTest(unittest.TestCase):
    def setUp(self):
        # Redirect every feedback path to a fresh temp dir; restore in tearDown.
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig = (config.RAG_DIR, config.FEEDBACK_DB)
        config.RAG_DIR = tmp
        config.FEEDBACK_DB = tmp / 'feedback.db'
        feedback.invalidate_boost_cache()

    def tearDown(self):
        config.RAG_DIR, config.FEEDBACK_DB = self._orig
        feedback.invalidate_boost_cache()
        self._tmp.cleanup()

    def test_downvote_is_recorded_and_listed(self):
        feedback.rate('روغن ترمز', {'model': 'Corolla'}, 'assist',
                      [11, 22], verdict=-1, reason='wrong', comment='bad link')
        rows = feedback.recent_downvotes(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['query'], 'روغن ترمز')
        self.assertEqual(rows[0]['reason'], 'wrong')

    def test_upvote_not_in_downvote_queue(self):
        feedback.rate('q', {}, 'assist', [1], verdict=1)
        self.assertEqual(feedback.recent_downvotes(), [])

    def test_blob_boost_map_moves_ranking_after_enough_signal(self):
        # FB_MIN_COUNT signals are required before a blob's feedback can move it.
        for _ in range(config.FB_MIN_COUNT + 1):
            feedback.rate('q', {}, 'assist', [], verdict=1, blob_id=42)
        feedback.invalidate_boost_cache()
        boosts = feedback.blob_boost_map()
        self.assertIn(42, boosts)
        self.assertGreater(boosts[42], 1.0)            # consistent 👍 -> up-rank

    def test_pinned_match_fires_on_near_identical_vector(self):
        vec = [1.0] + [0.0] * 9                          # unit vector
        ok = feedback.add_override('برف پاک کن', vec, '/Toyota/2022/X/wipers',
                                   title='Wipers', note='verified')
        self.assertTrue(ok)
        hit = feedback.pinned_match(vec)                 # cosine == 1.0 >= PIN_SIM
        self.assertIsNotNone(hit)
        self.assertEqual(hit['app_url'], '/Toyota/2022/X/wipers')

    def test_pinned_match_misses_on_orthogonal_vector(self):
        feedback.add_override('p', [1.0] + [0.0] * 9, '/a')
        ortho = [0.0, 1.0] + [0.0] * 8                   # cosine 0 with the pin
        self.assertIsNone(feedback.pinned_match(ortho))

    def test_log_query_persists_and_aggregates_common_queries(self):
        result = {'scope': {'model': 'X'}, 'hits': [{'blob_id': 1, 'score': 0.9}]}
        for _ in range(2):
            feedback.log_query('same q', result.get('scope'), result)
        common = feedback.common_queries(min_count=2)
        self.assertTrue(any(q == 'same q' and n >= 2 for q, n in common))


if __name__ == '__main__':
    unittest.main()
