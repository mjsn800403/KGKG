"""A read-only index open must never create the index file.

sqlite3.connect() creates a missing database. When the serving path opened a
missing index that way, it left an empty file behind; every later request then
saw "index exists", failed on "no such table: meta" and answered 500 instead of
the documented 503, until someone deleted the file. The recommendations panel
opened the index without the existence check that retrieve.assist() has, so a
single page view was enough.
"""
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from api.rag import config, store


class ReadOnlyOpenTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # The folder exists (as _rag/ does in production); only the index is gone.
        self.missing = Path(self.tmp.name) / '_rag' / 'index.rag.db'
        self.missing.parent.mkdir()
        store.reset_index_ro()
        self.addCleanup(store.reset_index_ro)

    def test_missing_index_raises_and_creates_nothing(self):
        with self.assertRaises(FileNotFoundError):
            store.open_index(path=self.missing, vec=False, write=False)
        self.assertFalse(self.missing.exists())

    def test_cached_serving_connection_raises_and_creates_nothing(self):
        with mock.patch.object(config, 'INDEX_DB', self.missing):
            with self.assertRaises(FileNotFoundError):
                store.get_index_ro()
        self.assertFalse(self.missing.exists())

    def test_recommendations_without_an_index_are_empty_and_create_nothing(self):
        from api import recommend
        with mock.patch.object(config, 'INDEX_DB', self.missing):
            self.assertEqual(recommend._related_via_graph([], {'Some_Car'}, set(), 6), [])
        self.assertFalse(self.missing.exists())

    def test_write_open_still_creates_the_index_and_its_folder(self):
        target = Path(self.tmp.name) / 'new' / 'index.rag.db'
        conn = store.open_index(path=target, vec=False, write=True)
        conn.close()
        self.assertTrue(target.exists())
