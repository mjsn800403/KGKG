"""Keyword-index (FTS) schema tests.

The index uses a CONTENTLESS fts5 table (content='') so the full page text is
stored ONCE in blobs.text and never duplicated inside the FTS shadow tables,
plus a porter stemmer + diacritic folding so 'brakes' / 'replacing' / 'rotors'
match 'brake' / 'replace' / 'rotor'. These tests pin both properties.

    cd KG_backend
    DJANGO_DEBUG=true .venv/bin/python manage.py test api.rag.test_fts -v 2
"""
import tempfile
import unittest
from pathlib import Path

from api.rag import store


def _seed(conn):
    conn.executemany(
        "INSERT INTO blobs(blob_id, content_hash, kind, title, comp_readable, text) "
        "VALUES (?,?,?,?,?,?)",
        [(1, 'h1', 'repair', 'Brake Pad', 'Brakes › Pad',
          'replace the front brake pads and rotor'),
         (2, 'h2', 'repair', 'Engine Oil', 'Engine › Oil',
          'engine oil change capacity 4.2 quarts')])
    conn.commit()


class FtsContentlessTest(unittest.TestCase):
    def _index(self):
        path = Path(tempfile.mkdtemp()) / 'idx.db'
        conn = store.open_index(path=path, vec=True, write=True)
        store.init_index_schema(conn)
        _seed(conn)
        return conn

    def test_init_schema_fts_is_contentless(self):
        conn = self._index()
        shadow = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'blobs_fts_%'")]
        # contentless fts5 never creates the %_content table (the storage win)
        self.assertNotIn('blobs_fts_content', shadow)

    def test_rebuild_is_contentless_and_stems(self):
        conn = self._index()
        store.rebuild_fts(conn, log=lambda *a, **k: None)
        shadow = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'blobs_fts_%'")]
        self.assertNotIn('blobs_fts_content', shadow)
        # porter stemming: inflected queries still hit the brake blob (id 1)
        for q in ('brakes', 'replacing', 'rotors', 'braking'):
            rows = conn.execute(
                "SELECT rowid FROM blobs_fts WHERE blobs_fts MATCH ? ORDER BY rank",
                (q,)).fetchall()
            self.assertEqual([r[0] for r in rows], [1], f"query {q!r}")

    def test_clear_data_keeps_queryable_fts(self):
        conn = self._index()
        store.rebuild_fts(conn, log=lambda *a, **k: None)
        store.clear_data(conn)
        # contentless FTS can't be DELETEd -> clear_data drops & recreates it;
        # it must still exist and be queryable (empty) afterwards.
        rows = conn.execute(
            "SELECT rowid FROM blobs_fts WHERE blobs_fts MATCH 'brake'").fetchall()
        self.assertEqual(rows, [])

    def test_inline_insert_still_works(self):
        # ingest writes FTS rows inline (rowid,text,title,comp); that must keep
        # working on the contentless table so the build path is unchanged.
        conn = self._index()
        conn.execute(
            "INSERT INTO blobs_fts(rowid, text, title, comp) VALUES (3,?,?,?)",
            ('coolant antifreeze radiator flush', 'Coolant', 'Cooling'))
        conn.commit()
        rows = conn.execute(
            "SELECT rowid FROM blobs_fts WHERE blobs_fts MATCH 'radiator'").fetchall()
        self.assertEqual([r[0] for r in rows], [3])


if __name__ == '__main__':
    unittest.main()
