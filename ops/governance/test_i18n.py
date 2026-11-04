"""Tests for check_i18n.py (temporary directories, standard library only)."""
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_i18n  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)


class I18n(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.d = os.path.join(self.t.name, 'docs')
        write(os.path.join(self.d, 'i18n.toml'), 'files = [\n  "a.md",\n]\n')
        write(os.path.join(self.d, 'a.md'), '# A\n\ntext\n')

    def tearDown(self):
        self.t.cleanup()

    def fa(self, text):
        write(os.path.join(self.d, 'fa', 'a.md'), text)

    def test_missing_twin_fails(self):
        self.assertTrue(any('missing Persian twin' in e for e in check_i18n.check(self.d)))

    def test_stamped_twin_passes(self):
        self.fa('# الف\n')
        check_i18n.stamp(self.d)
        self.assertEqual(check_i18n.check(self.d), [])

    def test_english_change_fails_until_restamped(self):
        self.fa('# الف\n')
        check_i18n.stamp(self.d)
        write(os.path.join(self.d, 'a.md'), '# A\n\nchanged\n')
        self.assertTrue(any('English source changed' in e for e in check_i18n.check(self.d)))
        check_i18n.stamp(self.d)
        self.assertEqual(check_i18n.check(self.d), [])

    def test_missing_stamp_fails(self):
        self.fa('# الف\n')
        self.assertTrue(any('first line must be' in e for e in check_i18n.check(self.d)))

    def test_crlf_does_not_change_digest(self):
        self.fa('# الف\n')
        check_i18n.stamp(self.d)
        write(os.path.join(self.d, 'a.md'), '# A\r\n\r\ntext\r\n')
        self.assertEqual(check_i18n.check(self.d), [])

    def test_unlisted_persian_file_fails(self):
        write(os.path.join(self.d, 'fa', 'b.md'), '# ب\n')
        self.assertTrue(any('not listed' in e for e in check_i18n.check(self.d)))

    def test_wrong_name_in_stamp_fails(self):
        self.fa('<!-- i18n-source: other.md sha256:000000000000 -->\n# الف\n')
        self.assertTrue(any('expected a.md' in e for e in check_i18n.check(self.d)))


if __name__ == '__main__':
    unittest.main()
