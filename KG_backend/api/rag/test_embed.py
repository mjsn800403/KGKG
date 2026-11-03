"""Unit tests for embed._embed_text (the per-page embed input builder).

Pure string logic — no model, no DB. Pins the table-aware behaviour: spec/torque
rows that sit BELOW the prose head get pulled into the capped embed budget so the
dense vector can match them (FTS already indexes the whole page).

    cd KG_backend
    DJANGO_DEBUG=true .venv/bin/python manage.py test api.rag.test_embed -v 2
"""
import unittest

from api.rag import config, embed


class EmbedTextTest(unittest.TestCase):
    def test_prepends_component_breadcrumb(self):
        out = embed._embed_text('Brakes › Hose', 'Remove and replace the hose.')
        self.assertTrue(out.startswith('Brakes › Hose\n'))

    def test_pulls_below_head_spec_rows_into_budget(self):
        # a long prose head followed by a torque table far past EMBED_TEXT_CHARS
        prose = 'word ' * (config.EMBED_TEXT_CHARS // 2)   # ~cap chars of prose
        spec = 'Front caliper bolt | 107 Nm | 79 ft-lbf'
        text = prose + '\n' + spec
        out = embed._embed_text('Brakes', text)
        # the spec row (originally below the head) is now inside the embed input
        self.assertIn('107 Nm', out)

    def test_respects_char_cap(self):
        text = 'A | B | C\n' * 500 + 'tail prose'
        out = embed._embed_text('Comp', text)
        body = out.split('\n', 1)[1] if '\n' in out else out
        self.assertLessEqual(len(body), config.EMBED_TEXT_CHARS)

    def test_no_tables_is_plain_head(self):
        text = 'Just prose with no pipe-delimited table rows at all.'
        out = embed._embed_text('Comp', text)
        self.assertEqual(out, f"Comp\n{text}")

    def test_empty_text(self):
        self.assertEqual(embed._embed_text('Comp', ''), 'Comp\n')
        self.assertEqual(embed._embed_text('', ''), '')


if __name__ == '__main__':
    unittest.main()


class EncodeConcurrencyTest(unittest.TestCase):
    """A-06 (#30): at most config.EMBED_CONCURRENCY encodes run at once."""

    def setUp(self):
        import threading
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        test = self

        class SlowModel:
            def encode(self, texts, **kw):
                import time
                import numpy as np
                with test.lock:
                    test.active += 1
                    test.peak = max(test.peak, test.active)
                time.sleep(0.05)
                with test.lock:
                    test.active -= 1
                return np.zeros((len(texts), 4), dtype=np.float32)

        self._model, self._limit = embed._MODEL, config.EMBED_CONCURRENCY
        embed._MODEL = SlowModel()

    def tearDown(self):
        embed._MODEL, config.EMBED_CONCURRENCY = self._model, self._limit

    def _burst(self, limit, n=8):
        import threading
        config.EMBED_CONCURRENCY = limit
        ts = [threading.Thread(target=embed.encode, args=(['q'],)) for _ in range(n)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return self.peak

    def test_bounded(self):
        self.assertLessEqual(self._burst(2), 2)

    def test_zero_is_unbounded(self):
        self.assertGreater(self._burst(0), 2)

