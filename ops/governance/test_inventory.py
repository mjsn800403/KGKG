"""Tests for gen_inventory.py: the docs-versus-code drift check must fail for the right reasons.

Each test builds a tiny repository in a temp directory and points the script at it.
"""
import contextlib
import io
import os
import tempfile
import unittest

import gen_inventory as g

CI = "name: ci\njobs:\n  backend:\n    runs-on: x\n  governance:\n    runs-on: x\n"
MODELS = ("from django.db import models\n\n\nclass Widget(models.Model):\n"
          "    \"\"\"A widget.\"\"\"\n")


class InventoryDriftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.old = (g.ROOT,)
        g.ROOT = self.root
        self.write('KG_backend/api/models.py', MODELS)
        self.write('KG_backend/api/widgets.py', '"""Widget helpers."""\nimport os\nX = os.environ.get("KG_WIDGET_MODE", "a")\n')
        self.write('KG_backend/api/management/commands/frob.py', '"""Frob the widgets."""\n')
        self.write('KG_backend/api/migrations/0001_initial.py', '')
        self.write('kg_frontend/src/app/page.js', 'export default 1\n')
        self.write('.github/workflows/ci.yml', CI)
        self.write('ops/run.sh', 'echo hi\n')
        self.write('docs/README.md', 'Widget widgets.py KG_WIDGET_MODE frob run.sh\n')

    def tearDown(self):
        g.ROOT = self.old[0]
        self.tmp.cleanup()

    def write(self, rel, text):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)

    def run_main(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = g.main(list(argv))
        return code, err.getvalue()

    def test_generated_tree_passes_check(self):
        self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.run_main('--check')[0], 0)

    def test_missing_inventory_fails(self):
        code, err = self.run_main('--check')
        self.assertEqual(code, 1)
        self.assertIn('out of date', err)

    def test_new_env_var_fails_until_regenerated_and_documented(self):
        self.run_main()
        self.write('KG_backend/api/widgets.py',
                   '"""Widget helpers."""\nimport os\nX = os.environ.get("KG_WIDGET_MODE", "a")\n'
                   'Y = os.environ.get("KG_WIDGET_NEW", "b")\n')
        code, err = self.run_main('--check')
        self.assertEqual(code, 1)
        self.assertIn('out of date', err)
        self.assertIn('KG_WIDGET_NEW', err)          # reported as undocumented, not only as stale
        # Regenerating alone records it as debt (the owner chooses that), and the check passes.
        self.run_main()
        self.assertEqual(self.run_main('--check')[0], 0)

    def test_documented_item_must_leave_the_debt_file(self):
        self.write('KG_backend/api/widgets.py',
                   '"""Widget helpers."""\nimport os\nY = os.environ.get("KG_WIDGET_NEW", "b")\n')
        self.run_main()                              # KG_WIDGET_NEW recorded as debt
        self.write('docs/README.md', 'Widget widgets.py KG_WIDGET_NEW frob run.sh\n')
        code, err = self.run_main('--check')
        self.assertEqual(code, 1)
        self.assertIn('remove it from', err)

    def test_changelog_and_design_records_do_not_count_as_documentation(self):
        self.write('KG_backend/api/widgets.py',
                   '"""Widget helpers."""\nimport os\nY = os.environ.get("KG_ONLY_IN_CHANGELOG", "b")\n')
        self.write('docs/CHANGELOG.md', 'KG_ONLY_IN_CHANGELOG\n')
        self.write('docs/superpowers/specs/x.md', 'KG_ONLY_IN_CHANGELOG\n')
        self.run_main()
        debt = g.build()[1]
        self.assertIn('KG_ONLY_IN_CHANGELOG', debt['env'])

    def test_word_boundary(self):
        self.assertTrue(g._documented('KG_A', 'uses KG_A here'))
        self.assertFalse(g._documented('KG_A', 'uses KG_AB here'))
        self.assertFalse(g._documented('KG_A', 'uses XKG_A here'))


if __name__ == '__main__':
    unittest.main()
