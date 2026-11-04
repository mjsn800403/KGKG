"""The documentation package is a reproducible snapshot of tracked files and never carries secret-like content."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_docs_package as b  # noqa: E402


class Package(unittest.TestCase):
    def build(self):
        d = tempfile.mkdtemp()
        out = io.StringIO()
        old, sys.stdout = sys.stdout, out
        try:
            self.assertEqual(b.main(['--out', d]), 0)
        finally:
            sys.stdout = old
        names = [f for f in os.listdir(d) if f.endswith('.zip')]
        self.assertEqual(len(names), 1)
        return os.path.join(d, names[0])

    def test_contents_and_manifest(self):
        path = self.build()
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            self.assertIn('docs/README.md', names)
            self.assertIn('docs/fa/README.md', names)
            self.assertIn('docs/AGENTS.md', names)
            self.assertIn('MANIFEST.json', names)
            self.assertIn('README-PACKAGE.txt', names)
            self.assertFalse([n for n in names if n.startswith('docs/superpowers/')])
            m = json.loads(z.read('MANIFEST.json'))
            self.assertEqual(len(m['source_commit']), 40)
            self.assertEqual(len(m['files']), len(names) - 2)

    def test_reproducible(self):
        a, c = self.build(), self.build()
        self.assertEqual(open(a, 'rb').read(), open(c, 'rb').read())

    def test_secret_pattern_matches(self):
        self.assertTrue(b.SECRET.search('-----BEGIN RSA PRIVATE KEY-----'))
        self.assertTrue(b.SECRET.search('password = "abcdefghijklmnopqrstuvwxyz0123"'))
        self.assertFalse(b.SECRET.search('KG_PG_PASSWORD names only, never values'))


if __name__ == '__main__':
    unittest.main()
