"""Unit tests for the standalone scoring/calibration core (no Django, no DB).

Run from this directory so `import scoring` resolves without the Django app
import chain:

    cd KG_backend/api/rag
    ../../.venv/bin/python -m unittest test_scoring -v
"""
import unittest

try:                                  # runnable standalone (from this dir)...
    import scoring
except ModuleNotFoundError:           # ...and under Django's test discovery
    from api.rag import scoring


class TestClassifyQuery(unittest.TestCase):
    def test_bare_dtc_code_routes_to_code_kind_fts_dominant(self):
        r = scoring.classify_query('P0301')
        self.assertEqual(r['kind'], 'code')
        # exact code lookup -> keyword side must dominate the dense side
        self.assertGreater(r['weights']['fts'], r['weights']['vec'])

    def test_subcoded_dtc_is_code(self):
        self.assertEqual(scoring.classify_query('b27c0-57')['kind'], 'code')

    def test_code_embedded_in_persian_sentence_still_code(self):
        # a code present anywhere dominates: exact-code lookup is the priority
        self.assertEqual(scoring.classify_query('کد خطای U0129 روشنه')['kind'], 'code')

    def test_pure_alpha_latin_word_is_not_a_code(self):
        # "brake" matches the loose DTC shape but has no digit -> NOT a code
        self.assertNotEqual(scoring.classify_query('brake fluid')['kind'], 'code')

    def test_persian_natural_language_is_semantic_dense_dominant(self):
        r = scoring.classify_query('موتور لرزش داره و چراغ چک روشنه')
        self.assertEqual(r['kind'], 'semantic')
        self.assertGreaterEqual(r['weights']['vec'], r['weights']['fts'])

    def test_short_latin_keyword_spec_is_lexical_fts_dominant(self):
        r = scoring.classify_query('brake fluid torque 26 Nm')
        self.assertEqual(r['kind'], 'lexical')
        self.assertGreaterEqual(r['weights']['fts'], r['weights']['vec'])

    def test_empty_query_is_balanced_mixed(self):
        r = scoring.classify_query('')
        self.assertEqual(r['kind'], 'mixed')
        self.assertEqual(r['weights']['vec'], r['weights']['fts'])

    def test_glossary_terms_do_not_break_classification(self):
        # eng_terms expansion is appended for matching but must not flip a
        # Persian semantic query into lexical
        r = scoring.classify_query('روغن ترمز رو چطور عوض کنم', eng_terms='brake fluid')
        self.assertEqual(r['kind'], 'semantic')


class TestCalibrate(unittest.TestCase):
    def _sig(self, **over):
        s = dict(rrf=0.5, sim=0.5, bm25=0.5, centrality=0.0,
                 vehicle_boost=1.0, boilerplate=1.0, feedback=1.0)
        s.update(over)
        return s

    def test_returns_final_and_explain(self):
        r = scoring.calibrate(self._sig())
        self.assertIn('final', r)
        self.assertIn('explain', r)
        self.assertIsInstance(r['final'], float)

    def test_monotonic_in_similarity(self):
        lo = scoring.calibrate(self._sig(sim=0.1))['final']
        hi = scoring.calibrate(self._sig(sim=0.9))['final']
        self.assertGreater(hi, lo)

    def test_monotonic_in_bm25(self):
        lo = scoring.calibrate(self._sig(bm25=0.1))['final']
        hi = scoring.calibrate(self._sig(bm25=0.9))['final']
        self.assertGreater(hi, lo)

    def test_boilerplate_penalty_lowers_score(self):
        full = scoring.calibrate(self._sig(boilerplate=1.0))['final']
        pen = scoring.calibrate(self._sig(boilerplate=0.4))['final']
        self.assertLess(pen, full)

    def test_vehicle_boost_raises_score(self):
        base = scoring.calibrate(self._sig(vehicle_boost=1.0))['final']
        boosted = scoring.calibrate(self._sig(vehicle_boost=1.5))['final']
        self.assertGreater(boosted, base)

    def test_feedback_penalty_lowers_score(self):
        neutral = scoring.calibrate(self._sig(feedback=1.0))['final']
        downvoted = scoring.calibrate(self._sig(feedback=0.85))['final']
        self.assertLess(downvoted, neutral)

    def test_explain_exposes_components(self):
        ex = scoring.calibrate(self._sig(vehicle_boost=1.5, boilerplate=0.4))['explain']
        for key in ('rrf', 'sim', 'bm25', 'boosts', 'final'):
            self.assertIn(key, ex)
        self.assertIn('vehicle', ex['boosts'])
        self.assertIn('boilerplate', ex['boosts'])
        self.assertIn('feedback', ex['boosts'])


class TestConfidenceBand(unittest.TestCase):
    def test_strong_match_clear_winner_is_high(self):
        r = scoring.confidence_band(final=0.9, margin=0.3, sim=0.82)
        self.assertEqual(r['band'], 'high')
        self.assertTrue(r['label_fa'])

    def test_weak_similarity_is_low(self):
        r = scoring.confidence_band(final=0.2, margin=0.05, sim=0.30)
        self.assertEqual(r['band'], 'low')

    def test_middling_is_medium(self):
        r = scoring.confidence_band(final=0.5, margin=0.1, sim=0.6)
        self.assertEqual(r['band'], 'medium')

    def test_band_is_one_of_three(self):
        for f, m, s in [(0.1, 0.0, 0.1), (0.5, 0.1, 0.55), (0.95, 0.4, 0.9)]:
            self.assertIn(scoring.confidence_band(f, m, s)['band'],
                          ('high', 'medium', 'low'))


class TestFeedbackMultiplier(unittest.TestCase):
    def test_no_signal_is_neutral(self):
        self.assertEqual(scoring.feedback_multiplier(up=0, down=0, clicks=0), 1.0)

    def test_below_min_count_is_neutral(self):
        # a single stray vote must not move ranking
        self.assertEqual(
            scoring.feedback_multiplier(up=1, down=0, clicks=0, min_count=3), 1.0)

    def test_strong_positive_above_one_capped(self):
        m = scoring.feedback_multiplier(up=50, down=0, clicks=20, min_count=3)
        self.assertGreater(m, 1.0)
        self.assertLessEqual(m, 1.2)

    def test_strong_negative_below_one_capped(self):
        m = scoring.feedback_multiplier(up=0, down=50, clicks=0, min_count=3)
        self.assertLess(m, 1.0)
        self.assertGreaterEqual(m, 0.85)

    def test_caps_are_respected_at_extremes(self):
        hi = scoring.feedback_multiplier(up=10_000, down=0, clicks=0, min_count=3)
        lo = scoring.feedback_multiplier(up=0, down=10_000, clicks=0, min_count=3)
        self.assertLessEqual(hi, 1.2)
        self.assertGreaterEqual(lo, 0.85)


if __name__ == '__main__':
    unittest.main()
