"""Unit tests for the pure offline-eval metric functions (no Django, no DB).

    cd KG_backend/api/rag
    ../../.venv/bin/python -m unittest test_evalmetrics -v
"""
import math
import unittest

try:                                  # runnable standalone (from this dir)...
    import evalmetrics as M
except ModuleNotFoundError:           # ...and under Django's test discovery
    from api.rag import evalmetrics as M


class TestRankMetrics(unittest.TestCase):
    def setUp(self):
        self.ranked = ['a', 'b', 'c', 'd']
        self.rel = {'b'}                 # one relevant, at rank 2

    def test_hit_at_k(self):
        self.assertEqual(M.hit_at_k(self.ranked, self.rel, 3), 1)
        self.assertEqual(M.hit_at_k(self.ranked, self.rel, 1), 0)

    def test_mrr_uses_first_relevant_rank(self):
        self.assertAlmostEqual(M.mrr(self.ranked, self.rel), 0.5)

    def test_mrr_zero_when_no_relevant_retrieved(self):
        self.assertEqual(M.mrr(self.ranked, {'z'}), 0.0)

    def test_recall_at_k(self):
        self.assertAlmostEqual(M.recall_at_k(self.ranked, self.rel, 3), 1.0)
        self.assertAlmostEqual(M.recall_at_k(self.ranked, self.rel, 1), 0.0)

    def test_recall_multi_relevant(self):
        self.assertAlmostEqual(M.recall_at_k(self.ranked, {'b', 'd'}, 3), 0.5)

    def test_precision_at_k(self):
        self.assertAlmostEqual(M.precision_at_k(self.ranked, self.rel, 3), 1.0 / 3.0)

    def test_ndcg_at_k_single_relevant_rank2(self):
        # rel at position 2 -> DCG = 1/log2(3); IDCG = 1/log2(2) = 1
        expected = (1.0 / math.log2(3)) / 1.0
        self.assertAlmostEqual(M.ndcg_at_k(self.ranked, self.rel, 3), expected, places=6)

    def test_ndcg_is_one_when_perfectly_ranked(self):
        self.assertAlmostEqual(M.ndcg_at_k(['b', 'a'], {'b'}, 2), 1.0)

    def test_empty_relevant_set_is_zero(self):
        self.assertEqual(M.recall_at_k(self.ranked, set(), 3), 0.0)
        self.assertEqual(M.ndcg_at_k(self.ranked, set(), 3), 0.0)


class TestCalibration(unittest.TestCase):
    def test_buckets_group_by_band_with_hit_rate(self):
        samples = [('high', True), ('high', True), ('high', False),
                   ('low', False), ('low', False)]
        b = M.calibration_buckets(samples)
        self.assertEqual(b['high']['n'], 3)
        self.assertAlmostEqual(b['high']['hit_rate'], 2.0 / 3.0)
        self.assertEqual(b['low']['n'], 2)
        self.assertAlmostEqual(b['low']['hit_rate'], 0.0)

    def test_empty(self):
        self.assertEqual(M.calibration_buckets([]), {})


class TestPercentiles(unittest.TestCase):
    def test_percentile_basic(self):
        xs = [10, 20, 30, 40, 50]
        self.assertEqual(M.percentile(xs, 50), 30)
        self.assertEqual(M.percentile(xs, 0), 10)
        self.assertEqual(M.percentile(xs, 100), 50)

    def test_percentile_empty_is_none(self):
        self.assertIsNone(M.percentile([], 50))


if __name__ == '__main__':
    unittest.main()
