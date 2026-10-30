"""Tests for the governance gates (ops/governance/).

Two rules, both of which exist because the 2026-10-30 evaluation found the
organisation could not demonstrate task tracking or knowledge maintenance:

  * check_traceability — a change has to say which tracked item it serves,
    so "which change closed which task" is answerable mechanically rather
    than from memory;
  * check_docs_freshness — every document has a named owner and a review
    interval, so decay is a query instead of an impression.

Standard library only, like the scripts themselves: they have to run on a
host where the application's virtualenv is the thing that is broken.

    python3 -m unittest discover -s ops/governance -t ops/governance -p 'test_*.py'
"""
import datetime
import os
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_docs_freshness as freshness          # noqa: E402
import check_traceability as trace                # noqa: E402


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------

class ReferencesIssueTests(unittest.TestCase):
    def test_a_bare_hash_number_is_a_reference(self):
        self.assertTrue(trace.references_issue('', 'Closes #42'))
        self.assertTrue(trace.references_issue('', 'see #7 for context'))

    def test_a_reference_in_the_title_counts(self):
        self.assertTrue(trace.references_issue('fix(ops): tighten the gate (#15)', ''))

    def test_a_full_issue_url_counts(self):
        self.assertTrue(trace.references_issue(
            '', 'fixes https://github.com/mjsn800403/KGKG/issues/22'))

    def test_a_pull_request_url_also_counts(self):
        """A change that continues another change is traceable too."""
        self.assertTrue(trace.references_issue(
            '', 'follows https://github.com/mjsn800403/KGKG/pull/42'))

    def test_prose_with_no_reference_is_refused(self):
        self.assertFalse(trace.references_issue('fix the thing', 'It was broken.'))
        self.assertFalse(trace.references_issue('', ''))
        self.assertFalse(trace.references_issue(None, None))

    def test_a_markdown_heading_is_not_a_reference(self):
        """'## Summary' must not satisfy the rule by accident."""
        self.assertFalse(trace.references_issue('', '## Summary\n\n### Detail'))

    def test_a_hash_inside_a_word_is_not_a_reference(self):
        self.assertFalse(trace.references_issue('', 'colour is #1a2b3c and id abc#4'))

    def test_a_reference_inside_a_code_fence_does_not_count(self):
        """Quoting someone else's commit log is not a statement about THIS
        change; the rule is about what the author claims, not what they
        pasted."""
        body = textwrap.dedent('''
            Here is the log I was reading:

            ```
            abc1234 fix: something about #42
            ```
        ''')
        self.assertFalse(trace.references_issue('', body))

    def test_a_reference_outside_the_fence_still_counts(self):
        body = 'Closes #9\n\n```\nunrelated #42\n```\n'
        self.assertTrue(trace.references_issue('', body))


class TraceabilityMainTests(unittest.TestCase):
    def _event(self, title, body):
        fd, path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w') as fh:
            import json
            json.dump({'pull_request': {'title': title, 'body': body}}, fh)
        self.addCleanup(os.unlink, path)
        return path

    def test_a_referencing_pull_request_passes(self):
        self.assertEqual(trace.main(['--event', self._event('t', 'Closes #42')]), 0)

    def test_a_pull_request_without_a_reference_fails(self):
        self.assertEqual(trace.main(['--event', self._event('t', 'no ref here')]), 1)

    def test_a_null_body_is_handled(self):
        self.assertEqual(trace.main(['--event', self._event('t', None)]), 1)

    def test_a_non_pull_request_event_is_skipped_not_failed(self):
        """The job also runs on push, where there is no pull request to judge."""
        fd, path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w') as fh:
            fh.write('{"ref": "refs/heads/main"}')
        self.addCleanup(os.unlink, path)
        self.assertEqual(trace.main(['--event', path]), 0)

    def test_a_missing_event_file_is_skipped_not_failed(self):
        self.assertEqual(trace.main(['--event', '/nonexistent/event.json']), 0)


# ---------------------------------------------------------------------------
# Documentation freshness
# ---------------------------------------------------------------------------

class StalenessRuleTests(unittest.TestCase):
    """The same rule as KnowledgeArticle.is_stale, so the repository and the
    product never disagree about what 'stale' means."""

    def test_a_document_inside_its_interval_is_fresh(self):
        today = datetime.date(2026, 10, 30)
        self.assertFalse(freshness.is_stale(datetime.date(2026, 9, 1), 180, today))

    def test_a_document_past_its_interval_is_stale(self):
        today = datetime.date(2026, 10, 30)
        self.assertTrue(freshness.is_stale(datetime.date(2025, 1, 1), 180, today))

    def test_the_boundary_day_is_not_yet_stale(self):
        today = datetime.date(2026, 10, 30)
        reviewed = today - datetime.timedelta(days=180)
        self.assertFalse(freshness.is_stale(reviewed, 180, today))
        self.assertTrue(freshness.is_stale(reviewed - datetime.timedelta(days=1), 180, today))

    def test_a_never_reviewed_document_is_stale(self):
        self.assertTrue(freshness.is_stale(None, 180, datetime.date(2026, 10, 30)))


class DocsRegistryTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.docs = os.path.join(self.root, 'docs')
        os.makedirs(os.path.join(self.docs, 'adr'))
        self.today = datetime.date(2026, 10, 30)

    def _doc(self, name):
        path = os.path.join(self.docs, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as fh:
            fh.write('# doc\n')

    def _registry(self, text):
        with open(os.path.join(self.docs, 'OWNERS.toml'), 'w') as fh:
            fh.write(textwrap.dedent(text))

    def _run(self):
        return freshness.check(self.docs, today=self.today)

    def test_a_fully_owned_and_fresh_registry_passes(self):
        self._doc('01-overview.md')
        self._registry('''
            ["01-overview.md"]
            owner = "someone"
            reviewed = 2026-10-01
            review_days = 180
        ''')
        self.assertEqual(self._run(), [])

    def test_a_document_missing_from_the_registry_is_reported(self):
        self._doc('01-overview.md')
        self._doc('02-architecture.md')
        self._registry('''
            ["01-overview.md"]
            owner = "someone"
            reviewed = 2026-10-01
            review_days = 180
        ''')
        problems = self._run()
        self.assertEqual(len(problems), 1)
        self.assertIn('02-architecture.md', problems[0])
        self.assertIn('not in', problems[0])

    def test_an_unowned_document_is_reported(self):
        self._doc('01-overview.md')
        self._registry('''
            ["01-overview.md"]
            owner = ""
            reviewed = 2026-10-01
            review_days = 180
        ''')
        problems = self._run()
        self.assertEqual(len(problems), 1)
        self.assertIn('no owner', problems[0])

    def test_a_stale_document_is_reported(self):
        self._doc('01-overview.md')
        self._registry('''
            ["01-overview.md"]
            owner = "someone"
            reviewed = 2025-01-01
            review_days = 180
        ''')
        problems = self._run()
        self.assertEqual(len(problems), 1)
        self.assertIn('review', problems[0].lower())

    def test_a_registry_entry_for_a_deleted_document_is_reported(self):
        """A registry that lists files nobody can read is how ownership rots
        quietly; the gate has to notice in both directions."""
        self._doc('01-overview.md')
        self._registry('''
            ["01-overview.md"]
            owner = "someone"
            reviewed = 2026-10-01
            review_days = 180

            ["99-deleted.md"]
            owner = "someone"
            reviewed = 2026-10-01
            review_days = 180
        ''')
        problems = self._run()
        self.assertEqual(len(problems), 1)
        self.assertIn('99-deleted.md', problems[0])

    def test_adr_files_are_covered_too(self):
        self._doc('adr/0001-thing.md')
        self._registry('')
        problems = self._run()
        self.assertEqual(len(problems), 1)
        self.assertIn('adr/0001-thing.md', problems[0])

    def test_design_records_are_not_maintained_documentation(self):
        """docs/superpowers/specs/ holds dated design records — what we decided
        on a particular day. A historical record cannot go stale and should not
        be re-reviewed every six months, so it is outside the gate. Living
        documentation is everything else."""
        self._doc('superpowers/specs/2026-10-27-some-design.md')
        self._doc('01-overview.md')
        self._registry("""
            ["01-overview.md"]
            owner = "someone"
            reviewed = 2026-10-01
            review_days = 180
        """)
        self.assertEqual(self._run(), [])

    def test_the_registry_itself_needs_no_entry(self):
        self._doc('01-overview.md')
        self._registry('''
            ["01-overview.md"]
            owner = "someone"
            reviewed = 2026-10-01
            review_days = 180
        ''')
        self.assertEqual(self._run(), [])

    def test_a_missing_registry_is_one_clear_problem_not_a_crash(self):
        self._doc('01-overview.md')
        problems = self._run()
        self.assertEqual(len(problems), 1)
        self.assertIn('OWNERS.toml', problems[0])


if __name__ == '__main__':
    unittest.main()
