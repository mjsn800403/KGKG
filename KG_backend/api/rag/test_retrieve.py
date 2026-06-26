"""Integration test for the full query-time pipeline against a REAL (tiny)
sqlite-vec index built in a temp dir. Only the embedding *encoder* is stubbed
(deterministic basis vectors) so the test needs no model download / GPU, while
still exercising store.get_index_ro (the cached serving connection), the
vector+FTS fusion, occurrence pick, and the grounding gate.

    cd KG_backend
    DJANGO_DEBUG=true .venv/bin/python manage.py test api.rag.test_retrieve -v 2
"""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from api.rag import config, store, embed, retrieve


def _basis(idx):
    """Unit vector e_idx of width EMBED_DIM (quantises cleanly to int8 'unit')."""
    v = np.zeros(config.EMBED_DIM, dtype=np.float32)
    v[idx] = 1.0
    return v


# Map a piece of text to a deterministic vector by keyword, so a query about
# "brake" aligns with the brake blob and nothing else.
def _vec_for(text):
    t = (text or '').lower()
    if 'brake' in t:
        return _basis(0)
    if 'wiper' in t:
        return _basis(1)
    return _basis(2)


class RetrieveIntegrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig = (config.RAG_DIR, config.INDEX_DB, config.FEEDBACK_DB,
                      config.FEEDBACK_BOOST, config.LOG_QUERIES, embed.encode)
        config.RAG_DIR = tmp
        config.INDEX_DB = tmp / 'index.rag.db'
        config.FEEDBACK_DB = tmp / 'feedback.db'
        config.FEEDBACK_BOOST = False        # no boost-map DB dependency
        config.LOG_QUERIES = False
        store.reset_index_ro()

        # Deterministic encoder: encode([text]) -> (1, EMBED_DIM).
        embed.encode = lambda texts, **kw: np.stack([_vec_for(t) for t in texts])

        self._build_index()

    def tearDown(self):
        store.reset_index_ro()
        (config.RAG_DIR, config.INDEX_DB, config.FEEDBACK_DB,
         config.FEEDBACK_BOOST, config.LOG_QUERIES, embed.encode) = self._orig
        self._tmp.cleanup()

    def _build_index(self):
        conn = store.open_index(write=True)
        store.init_index_schema(conn)
        conn.execute("INSERT INTO meta(k,v) VALUES('embed_model',?)",
                     (config.EMBED_MODEL,))
        blobs = [
            (1, 'h1', 'Brake fluid replacement', 'Brakes', 'Brake fluid: bleed and refill the brake system.', _basis(0)),
            (2, 'h2', 'Wiper blade replacement', 'Wipers', 'Wiper blades: remove and install the wiper.', _basis(1)),
            (3, 'h3', 'Oil change', 'Engine', 'Engine oil: drain and refill.', _basis(2)),
        ]
        for bid, h, title, comp, text, vec in blobs:
            conn.execute(
                "INSERT INTO blobs(blob_id,content_hash,kind,title,comp_readable,text,n_occ) "
                "VALUES (?,?,?,?,?,?,1)", (bid, h, 'repair', title, comp, text))
            conn.execute(
                "INSERT INTO occurrences(blob_id,car_stem,brand,model,variant,year,"
                "node_id,title,title_path,system_tags,href) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (bid, 'Corolla', 'Toyota', 'Corolla', 'S', 2022, f'n{bid}', title,
                 f'Root › {comp} › {title}', comp, f'{bid}.html'))
            conn.execute(
                "INSERT INTO vec_blobs(rowid, embedding) "
                "VALUES (?, vec_quantize_int8(vec_f32(?), 'unit'))",
                (bid, store.pack_f32(vec)))
            conn.execute(
                "INSERT INTO blobs_fts(rowid,text,title,comp) VALUES (?,?,?,?)",
                (bid, text, title, comp))
        conn.commit()
        conn.close()

    def test_returns_grounded_brake_hit_on_top(self):
        res = retrieve.assist('brake fluid', brand='Toyota', model='Corolla',
                              car_stem='Corolla')
        self.assertTrue(res['grounded'])
        self.assertGreater(res['count'], 0)
        top = res['hits'][0]
        self.assertEqual(top['blob_id'], 1)
        self.assertEqual(top['model'], 'Corolla')
        self.assertTrue(top['app_url'].startswith('/Toyota/2022/Corolla'))

    def test_out_of_domain_query_is_not_grounded(self):
        # No keyword overlap AND an orthogonal vector -> top sim below the
        # grounding floor, so the pipeline refuses rather than guessing.
        embed.encode = lambda texts, **kw: np.stack([_basis(500) for _ in texts])
        res = retrieve.assist('quantum chromodynamics', brand='Toyota',
                              model='Corolla', car_stem='Corolla')
        self.assertFalse(res['grounded'])

    def test_shared_connection_is_reused_across_calls(self):
        c1 = store.get_index_ro()
        retrieve.assist('brake fluid', model='Corolla')
        c2 = store.get_index_ro()
        self.assertIs(c1, c2)            # one cached connection, not per-request


class ScopeAwareRetrievalTest(unittest.TestCase):
    """A blob that occurs in the user's car must outrank a *different* blob of
    identical relevance that only exists in another brand's vehicle."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig = (config.RAG_DIR, config.INDEX_DB, config.FEEDBACK_DB,
                      config.FEEDBACK_BOOST, config.LOG_QUERIES, embed.encode)
        config.RAG_DIR = tmp
        config.INDEX_DB = tmp / 'index.rag.db'
        config.FEEDBACK_DB = tmp / 'feedback.db'
        config.FEEDBACK_BOOST = False
        config.LOG_QUERIES = False
        store.reset_index_ro()
        embed.encode = lambda texts, **kw: np.stack([_vec_for(t) for t in texts])

        conn = store.open_index(write=True)
        store.init_index_schema(conn)
        conn.execute("INSERT INTO meta(k,v) VALUES('embed_model',?)", (config.EMBED_MODEL,))
        # blob 1: brake page in the Toyota Corolla the user is browsing.
        # blob 4: an EQUALLY-relevant but DIFFERENT brake page that exists only
        # in a Lexus (cross-brand) -> same vector, so only scope separates them.
        rows = [
            (1, 'h1', 'Toyota', 'Corolla', 'Corolla', 'Brake fluid bleed'),
            (4, 'h4', 'Lexus', 'NX 350h', 'NX 350h', 'Brake fluid bleed'),
        ]
        for bid, h, brand, model, stem, text in rows:
            conn.execute(
                "INSERT INTO blobs(blob_id,content_hash,kind,title,comp_readable,text,n_occ) "
                "VALUES (?,?,?,?,?,?,1)", (bid, h, 'repair', text, 'Brakes', text))
            conn.execute(
                "INSERT INTO occurrences(blob_id,car_stem,brand,model,variant,year,"
                "node_id,title,title_path,system_tags,href) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (bid, stem, brand, model, '', 2025, f'n{bid}', text,
                 f'Root › Brakes › {text}', 'Brakes', f'{bid}.html'))
            conn.execute(
                "INSERT INTO vec_blobs(rowid, embedding) VALUES (?, vec_quantize_int8(vec_f32(?), 'unit'))",
                (bid, store.pack_f32(_basis(0))))
            conn.execute(
                "INSERT INTO blobs_fts(rowid,text,title,comp) VALUES (?,?,?,?)",
                (bid, text, text, 'Brakes'))
        conn.commit()
        conn.close()

    def tearDown(self):
        store.reset_index_ro()
        (config.RAG_DIR, config.INDEX_DB, config.FEEDBACK_DB,
         config.FEEDBACK_BOOST, config.LOG_QUERIES, embed.encode) = self._orig
        self._tmp.cleanup()

    def test_in_scope_blob_outranks_identical_cross_brand_blob(self):
        res = retrieve.assist('brake fluid', brand='Toyota', model='Corolla',
                              car_stem='Corolla')
        ids = [h['blob_id'] for h in res['hits']]
        self.assertEqual(ids[0], 1, f"expected in-car blob 1 first, got {ids}")
        # the cross-brand blob carries the explicit scope penalty in its explain
        foreign = next((h for h in res['hits'] if h['blob_id'] == 4), None)
        self.assertIsNotNone(foreign)
        self.assertLess(foreign['explain']['boosts']['scope'], 1.0)

    def test_unscoped_query_applies_no_scope_penalty(self):
        res = retrieve.assist('brake fluid')        # site-wide, no scope
        for h in res['hits']:
            self.assertEqual(h['explain']['boosts']['scope'], 1.0)


if __name__ == '__main__':
    unittest.main()
