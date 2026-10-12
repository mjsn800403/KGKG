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
