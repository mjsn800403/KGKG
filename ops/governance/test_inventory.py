"""Tests for gen_inventory.py: the docs-versus-code drift check must fail for the right reasons.

Each test builds a tiny git repository in a temp directory and points the script at it. The
important property: regenerating docs/generated/doc-debt.json inside a change must NOT make a
new undocumented item pass, because the binding baseline is the target branch's copy.
"""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest

import gen_inventory as g

CI = "name: ci\njobs:\n  backend:\n    runs-on: x\n  governance:\n    runs-on: x\n"
MODELS = ("from django.db import models\n\n\nclass Widget(models.Model):\n"
          "    \"\"\"A widget.\"\"\"\n")
WIDGETS = '"""Widget helpers."""\nimport os\nX = os.environ.get("KG_WIDGET_MODE", "a")\n'
WIDGETS_PLUS = WIDGETS + 'Y = os.environ.get("KG_WIDGET_NEW", "b")\n'
BASE = 'origin/work'


class InventoryDriftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.old_root = g.ROOT
        g.ROOT = self.root
        self.write('KG_backend/api/models.py', MODELS)
        self.write('KG_backend/api/widgets.py', WIDGETS)
        self.write('KG_backend/api/management/commands/frob.py', '"""Frob the widgets."""\n')
        self.write('KG_backend/api/migrations/0001_initial.py', '')
        self.write('kg_frontend/src/app/page.js', 'export default 1\n')
        self.write('.github/workflows/ci.yml', CI)
        self.write('ops/run.sh', 'echo hi\n')
        self.write('docs/README.md', 'Widget widgets.py KG_WIDGET_MODE frob run.sh\n')

    def tearDown(self):
        g.ROOT = self.old_root
        self.tmp.cleanup()

    # helpers ----------------------------------------------------------------
    def write(self, rel, text):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)

    def git(self, *a):
        subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *a], cwd=self.root,
                       check=True, capture_output=True)

    def make_base(self):
        """Regenerate, commit, and expose the commit as origin/work (the trusted baseline)."""
        self.run_main()
        self.git('init', '-q')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'base')
        self.git('update-ref', 'refs/remotes/origin/work', 'HEAD')

    def run_main(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = g.main(list(argv))
        return code, err.getvalue()

    def check(self):
        return self.run_main('--check', '--base-ref', BASE, '--require-base')

    # basics -----------------------------------------------------------------
    def test_generated_tree_passes_check(self):
        self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.run_main('--check')[0], 0)

    def test_missing_inventory_fails(self):
        code, err = self.run_main('--check')
        self.assertEqual(code, 1)
        self.assertIn('out of date', err)

    def test_word_boundary(self):
        self.assertTrue(g._documented('KG_A', 'uses KG_A here'))
        self.assertFalse(g._documented('KG_A', 'uses KG_AB here'))
        self.assertFalse(g._documented('KG_A', 'uses XKG_A here'))

    def test_changelog_and_design_records_do_not_count_as_documentation(self):
        self.write('KG_backend/api/widgets.py', WIDGETS_PLUS.replace('KG_WIDGET_NEW', 'KG_ONLY_IN_CHANGELOG'))
        self.write('docs/CHANGELOG.md', 'KG_ONLY_IN_CHANGELOG\n')
        self.write('docs/superpowers/specs/x.md', 'KG_ONLY_IN_CHANGELOG\n')
        self.assertIn('KG_ONLY_IN_CHANGELOG', g.build()[1]['env'])

    # the ratchet ------------------------------------------------------------
    def test_unchanged_branch_passes_with_a_baseline(self):
        self.make_base()
        self.assertEqual(self.check()[0], 0)

    def test_regenerating_the_debt_file_cannot_excuse_a_new_item(self):
        """The bypass the reviewer found: add an undocumented env var, regenerate, push."""
        self.make_base()
        self.write('KG_backend/api/widgets.py', WIDGETS_PLUS)
        self.run_main()                       # regenerate inventory.md AND doc-debt.json
        self.assertIn('KG_WIDGET_NEW', json.load(open(os.path.join(self.root, g.OUT_DEBT)))['env'])
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn('NEW undocumented env: KG_WIDGET_NEW', err)

    def test_hand_editing_the_debt_file_does_not_help_either(self):
        self.make_base()
        self.write('KG_backend/api/widgets.py', WIDGETS_PLUS)
        self.run_main()
        p = os.path.join(self.root, g.OUT_DEBT)
        d = json.load(open(p))
        d['env'] = [x for x in d['env'] if x != 'KG_WIDGET_NEW']   # pretend it is not debt
        open(p, 'w').write(json.dumps(d))
        code, err = self.check()
        self.assertEqual(code, 1)                       # the file no longer matches the code
        self.assertIn('does not match the code', err)

    def test_documenting_the_new_item_passes(self):
        self.make_base()
        self.write('KG_backend/api/widgets.py', WIDGETS_PLUS)
        self.write('docs/README.md', 'Widget widgets.py KG_WIDGET_MODE KG_WIDGET_NEW frob run.sh\n')
        self.run_main()
        self.assertEqual(self.check()[0], 0)

    def test_reviewed_exception_with_reason_passes_without_reason_fails(self):
        self.make_base()
        self.write('KG_backend/api/widgets.py', WIDGETS_PLUS)
        self.run_main()
        self.write(g.OUT_EXC, json.dumps({'env': {'KG_WIDGET_NEW': 'internal test knob, owner approved #123'}}))
        self.assertEqual(self.check()[0], 0)
        self.write(g.OUT_EXC, json.dumps({'env': {'KG_WIDGET_NEW': '  '}}))
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn('has no reason', err)

    def test_existing_debt_does_not_block_ordinary_work(self):
        """Debt already on the target branch is acknowledged; unrelated changes still pass."""
        self.write('KG_backend/api/widgets.py', WIDGETS_PLUS)       # debt exists before the base
        self.make_base()
        self.write('KG_backend/api/other.py', '"""Other."""\n')       # ordinary work
        self.write('docs/README.md', 'Widget widgets.py other.py KG_WIDGET_MODE frob run.sh\n')
        self.run_main()
        self.assertEqual(self.check()[0], 0)

    def test_paying_debt_down_passes_and_must_be_recorded(self):
        self.write('KG_backend/api/widgets.py', WIDGETS_PLUS)
        self.make_base()
        self.write('docs/README.md', 'Widget widgets.py KG_WIDGET_MODE KG_WIDGET_NEW frob run.sh\n')
        code, err = self.check()
        self.assertEqual(code, 1)                      # stale record: must regenerate
        self.run_main()
        self.assertEqual(self.check()[0], 0)

    def test_base_without_baseline_file_is_the_bootstrap_case(self):
        self.write('KG_backend/api/widgets.py', WIDGETS_PLUS)
        self.run_main()
        os.remove(os.path.join(self.root, g.OUT_DEBT))
        os.remove(os.path.join(self.root, g.OUT_MD))
        self.git('init', '-q')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'base without inventory')
        self.git('update-ref', 'refs/remotes/origin/work', 'HEAD')
        self.run_main()
        self.assertEqual(self.check()[0], 0)

    def test_unreadable_base_ref_fails_instead_of_passing(self):
        self.run_main()
        self.git('init', '-q')
        code, err = self.run_main('--check', '--base-ref', 'origin/nope', '--require-base')
        self.assertEqual(code, 1)
        self.assertIn('cannot read base ref', err)

    def test_require_base_without_a_ref_fails(self):
        self.run_main()
        code, err = self.run_main('--check', '--require-base')
        self.assertEqual(code, 1)
        self.assertIn('no base ref given', err)


if __name__ == '__main__':
    unittest.main()
