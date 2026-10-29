"""Behavioural tests for the deterministic diagnostic rule engine (api/rag/diag.py).

A tiny synthetic sidecar (.diag.db, created with diag_build's OWN
init_diag_schema) and a tiny unified index (store.init_index_schema) are built in
a temp dir per test class. config.DIAG_DIR / RAG_DIR / INDEX_DB are patched to it
for each test and restored afterwards.

Stubs (and only these):
  * api.rag.embed.encode   -> deterministic keyword->basis-vector fake, so the
    symptom path runs without the bge-m3 model. Sidecar vectors are written with
    the same basis so cosine similarities are known by construction.
  * api.rag.feedback.blob_boost_map -> fixed map (it reads the feedback DB /
    process cache; it is a collaborator, not the engine under test).

    cd KG_backend
    DJANGO_DEBUG=true python manage.py test api.rag.test_diag_engine -v 2
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from api.rag import config, diag, embed, feedback, store
from api.rag.diag_build import init_diag_schema, open_diag

DIM = config.EMBED_DIM


def _vec(**w):
    """Unit vector from {'e<i>': weight} components."""
    v = np.zeros(DIM, dtype=np.float32)
    for k, x in w.items():
        v[int(k[1:])] = x
    return v / np.linalg.norm(v)


# Query keyword -> basis direction used by the fake encoder.
_KEYWORDS = (
    ('misfire', 'e0'), ('ریپ', 'e0'),
    ('hesitat', 'e1'),
    ('airbag', 'e2'),
    ('communication', 'e4'),
    ('catalyst', 'e6'),
)


def _fake_encode(texts, batch_size=32, is_query=False, progress=False):
    # STUB of the embedding model only (deterministic; no torch / no network).
    out = []
    for t in texts:
        low = (t or '').lower()
        axis = next((ax for kw, ax in _KEYWORDS if kw in low), 'e9')   # e9 = junk
        out.append(_vec(**{axis: 1.0}))
    return np.vstack(out).astype(np.float32)


def _put_vec(conn, table, rowid, v):
    conn.execute(f"INSERT INTO {table}(rowid, embedding) "
                 f"VALUES (?, vec_quantize_int8(vec_f32(?), 'unit'))",
                 (rowid, store.pack_f32(v)))


SPARK_URL = '/Toyota/2021/CarA/Engine/Spark%20Plug%20Inspection'
LONG_DESC = 'The ECM monitors crankshaft speed. ' + 'x' * 900


def _build_car_a(path):
    c = open_diag(path)
    init_diag_schema(c)
    dtcs = [
        # did, code, name, system, subsystem, component, node, url, desc, trig, sym, circ, proc, wir
        (1, 'P0300-00', 'Random/Multiple Cylinder Misfire Detected', 'Engine', 'Engine Control',
         'Misfire', 'a-p0300', '/u/p0300', LONG_DESC, 'DTC sets when misfire > 2%.', 1, 1, 1, 1),
        (2, 'P0301-00', 'Cylinder 1 Misfire Detected', 'Engine', 'Engine Control', 'Misfire',
         'a-p0301', '/u/p0301', 'Cyl 1.', '', 1, 0, 0, 0),
        (3, 'P0171', 'System Too Lean', 'Engine', 'Engine Control', 'Fuel Trim',
         'a-p0171', '/u/p0171', 'Lean.', '', 0, 0, 0, 0),
        (4, 'B1234', 'Driver Airbag Circuit', 'Body', 'SRS', 'Airbag',
         'a-b1234', '/u/b1234', 'Airbag.', '', 0, 1, 0, 0),
        (5, 'U0100-87', 'Lost Communication With ECM', 'Network', '', 'CAN',
         'a-u0100', '/u/u0100', None, '', 0, 0, 0, 0),
        (6, 'P0607-94', 'Control Module Performance', 'Engine', 'ECM', 'ECM',
         'a-p0607', '/u/p0607', 'ECM.', '', 0, 0, 0, 0),
    ]
    c.executemany("INSERT INTO dtc VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", dtcs)
    # steps inserted OUT of order on purpose: the engine must ORDER BY step_order
    c.executemany("INSERT INTO dtc_step(code,step_order,aspect,node_id,app_url) VALUES (?,?,?,?,?)", [
        ('P0300-00', 3, 'Procedure', 'a-p0300-p', '/u/p0300/proc'),
        ('P0300-00', 0, 'Description', 'a-p0300-d', '/u/p0300/desc'),
        ('P0300-00', 2, 'Circuit Tests', 'a-p0300-c', '/u/p0300/circ'),
        ('P0300-00', 1, 'Symptom Tests', 'a-p0300-s', '/u/p0300/sym'),
        ('P0300-00', 4, 'Wiring Diagram', 'a-p0300-w', '/u/p0300/wir'),
        ('P0171', 0, 'Description', 'a-p0171-d', '/u/p0171/desc'),
    ])
    syms = [
        (1, 'Engine misfire or rough idle', 'Spark plug', 'Engine', 'Engine Control', 'Misfire', 't1', '/u/t1'),
        (2, 'Engine hesitates on acceleration', 'Fuel pump', 'Engine', 'Engine Control', 'Fuel', 't1', '/u/t1'),
        (3, 'Airbag warning light stays on', 'Airbag module', 'Body', 'SRS', 'Airbag', 't2', '/u/t2'),
        # same text as #1 modulo case/whitespace (duplicated PST page); longer
        # suspected list -> lower bm25, so #1 is unambiguously the best symptom
        (4, 'engine misfire or rough idle ', 'Fuel injector fuel pressure intake leak EGR valve PCV hose '
         'vacuum line throttle body', 'Engine', 'Engine Control', 'Misfire', 't3', '/u/t3'),
    ]
    c.executemany("INSERT INTO symptom VALUES (?,?,?,?,?,?,?,?)", syms)
    c.executemany("INSERT INTO symptom_link(symptom_id,target_kind,target_code,target_node_id,"
                  "target_title,target_app_url,weight,source) VALUES (?,?,?,?,?,?,?,?)", [
                      (1, 'dtc', 'P0300-00', 'a-p0300', 'DTC P0300-00', None, 1.0, 'symptom_table'),
                      (1, 'dtc', 'P0301-00', None, None, None, 0.45, 'inheritance'),
                      (1, 'dtc', 'P0171', None, None, None, 0.45, 'inheritance'),
                      (1, 'page', None, 'a-spark', 'Spark Plug Inspection', SPARK_URL, 1.0, 'symptom_table'),
                      (2, 'dtc', 'P0171', 'a-p0171', 'DTC P0171', None, 1.0, 'symptom_table'),
                      (2, 'dtc', 'U0100-87', None, None, None, 0.45, 'inheritance'),
                      (3, 'dtc', 'B1234', 'a-b1234', 'DTC B1234', None, 1.0, 'symptom_table'),
                  ])
    c.executemany("INSERT INTO diag_fts(text,kind,ref) VALUES (?,?,?)",
                  [(f"{s[1]} {s[2]}", 'symptom', str(s[0])) for s in syms] +
                  [(f"{d[2]} {d[8] or ''}", 'dtc', d[1]) for d in dtcs])
    _put_vec(c, 'sym_vec', 1, _vec(e0=1.0))
    _put_vec(c, 'sym_vec', 2, _vec(e1=1.0))
    _put_vec(c, 'sym_vec', 3, _vec(e2=1.0))
    _put_vec(c, 'sym_vec', 4, _vec(e0=0.2, e5=0.98))
    _put_vec(c, 'dtc_vec', 1, _vec(e0=0.7, e3=0.714))      # cos(misfire) ~0.70 > floor
    _put_vec(c, 'dtc_vec', 2, _vec(e0=0.5, e3=0.866))      # cos(misfire) ~0.50 < floor
    _put_vec(c, 'dtc_vec', 3, _vec(e1=0.3, e3=0.954))
    _put_vec(c, 'dtc_vec', 4, _vec(e7=1.0))
    _put_vec(c, 'dtc_vec', 5, _vec(e4=1.0))                # cos(communication) = 1
    _put_vec(c, 'dtc_vec', 6, _vec(e8=1.0))
    c.execute("INSERT INTO meta(k,v) VALUES ('embed_model', ?)", (config.EMBED_MODEL,))
    c.commit()
    c.close()


def _build_car_b(path):
    """Second car: only P0420, no symptom tables, and NO meta row."""
    c = open_diag(path)
    init_diag_schema(c)
    c.execute("INSERT INTO dtc VALUES (1,'P0420','Catalyst Efficiency Below Threshold','Engine',"
              "'Emission','Catalyst','b-p0420','/u/b/p0420','Cat.','',0,0,0,0)")
    _put_vec(c, 'dtc_vec', 1, _vec(e6=0.7, e10=0.714))    # cos(catalyst) ~0.70
    c.commit()
    c.close()


def _build_car_old(path):
    c = open_diag(path)
    init_diag_schema(c)
    c.execute("INSERT INTO meta(k,v) VALUES ('embed_model','some-other-model')")
    c.commit()
    c.close()


def _build_index(path):
    c = store.open_index(path=path)
    store.init_index_schema(c)
    occ = [
        # blob, car, brand, model, variant, year, node, title, title_path
        (10, 'CarA', 'Toyota', 'CarA', 'v1', 2021, 'a-p0300-d', 'P0300 Description', 'CarA › Engine › P0300'),
        (10, 'CarB', 'Toyota', 'ModelB', 'vb', 2020, 'b-x', 'P0300 Description B', 'CarB › Engine › P0300'),
        (10, 'CarB2', 'Toyota', 'ModelB', 'vb', 2020, 'b2-x', 'P0300 Description B2', 'CarB2 › Engine › P0300'),
        (10, 'CarC', 'Toyota', 'ModelC', 'vc', 2019, 'c-x', 'P0300 Description C', 'CarC › Engine › P0300'),
        (20, 'CarA', 'Toyota', 'CarA', 'v1', 2021, 'a-p0300-p', 'P0300 Procedure', 'CarA › Engine › Proc'),
        (30, 'CarC', 'Toyota', 'ModelC', 'vc', 2019, 'c-lab', 'Labor: Spark plugs C', 'CarC › Labor › Spark'),
        (30, 'CarB', 'Toyota', 'ModelB', 'vb', 2020, 'b-lab', 'Labor: Spark plugs B', 'CarB › Labor › Spark'),
        (40, 'CarA', 'Toyota', 'CarA', 'v1', 2021, 'a-p0171-d', 'P0171 Description', 'CarA › Engine › P0171'),
    ]
    c.executemany("INSERT INTO occurrences(blob_id,car_stem,brand,model,variant,year,node_id,title,"
                  "title_path) VALUES (?,?,?,?,?,?,?,?,?)", occ)
    c.executemany("INSERT INTO edges(src_blob,dst_blob,relation,weight) VALUES (?,?,?,?)",
                  [(20, 30, 'labor_time', 1.0), (20, 10, 'semantic', 0.9)])
    c.commit()
    c.close()


class _DiagFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = Path(tempfile.mkdtemp(prefix='kg_diag_test_'))
        ddir = cls._tmp / 'diag'
        with mock.patch.object(config, 'DIAG_DIR', ddir), \
                mock.patch.object(config, 'RAG_DIR', cls._tmp):
            _build_car_a(ddir / 'CarA.diag.db')
            _build_car_b(ddir / 'CarB.diag.db')
            _build_car_old(ddir / 'CarOld.diag.db')
            _build_index(cls._tmp / 'index.rag.db')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        for attr, val in (('DIAG_DIR', self._tmp / 'diag'), ('RAG_DIR', self._tmp),
                          ('INDEX_DB', self._tmp / 'index.rag.db')):
            p = mock.patch.object(config, attr, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(embed, 'encode', side_effect=_fake_encode)
        self.encode = p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(feedback, 'blob_boost_map', return_value={})
        self.boost = p.start()
        self.addCleanup(p.stop)

    def codes(self, res):
        return [c['code'] for c in res['candidates']]


# ---------------------------------------------------------------------------
class CodeIntentTest(_DiagFixture):
    """Exact DTC lookup: detection variants, payload, precedence, isolation."""

    def assertExact(self, query, code, car='CarA'):
        res = diag.diagnose(query, car_stem=car)
        self.assertEqual(res['intent'], 'dtc', query)
        self.assertTrue(res['known'], query)
        self.assertEqual(self.codes(res), [code], query)
        return res

    def test_code_variants_resolve_to_the_stored_code(self):
        for q, code in [
            ('P0171', 'P0171'),
            ('p0171', 'P0171'),                         # lowercase
            ('my scanner shows P0171 since monday', 'P0171'),   # surrounding text
            ('P0300', 'P0300-00'),                      # base code -> sub-coded row
            ('p0300-00', 'P0300-00'),
            ('U0100:87', 'U0100-87'),                   # ':' separator
            ('u0100', 'U0100-87'),
            ('P060794', 'P0607-94'),                    # run-together scan-tool form
            ('P ۰۱۷۱', 'P0171'),                        # Persian digits + split letter
            ('کد P٠١٧١ روشن شد', 'P0171'),             # Arabic-Indic digits in Persian text
            ('b1234', 'B1234'),
        ]:
            with self.subTest(q=q):
                self.assertExact(q, code)
        self.encode.assert_not_called()                 # code path never embeds

    def test_exact_hit_is_fully_grounded_high_band(self):
        res = self.assertExact('P0300', 'P0300-00')
        self.assertTrue(res['grounded'])
        self.assertEqual(res['top_similarity'], 1.0)
        self.assertEqual(res['confidence_band']['band'], 'high')
        c = res['candidates'][0]
        self.assertEqual(c['confidence'], 1.0)
        self.assertEqual(c['matched_via'], 'exact_code')
        self.assertEqual(c['reason'], 'direct_code')
        self.assertEqual(c['confidence_band'], 'high')
        self.assertEqual(c['explain'], {'matched_via': 'exact_code', 'source': 'direct_code'})

    def test_payload_steps_ordered_procedure_siblings_and_truncation(self):
        c = self.assertExact('P0300-00', 'P0300-00')['candidates'][0]
        self.assertEqual([s['aspect'] for s in c['steps']],
                         ['Description', 'Symptom Tests', 'Circuit Tests', 'Procedure',
                          'Wiring Diagram'])
        self.assertEqual(c['procedure'], {'title': 'Procedure', 'app_url': '/u/p0300/proc'})
        self.assertEqual(c['sibling_dtcs'], ['P0301-00'])        # same component, not self
        self.assertEqual(c['inheritance_path'], 'Engine › Engine Control › Misfire')
        self.assertEqual(len(c['description']), 700)
        self.assertEqual(c['trigger'], 'DTC sets when misfire > 2%.')
        self.assertIs(c['has_symptom_test'], True)
        self.assertIs(c['has_circuit_test'], True)

    def test_steps_capped_by_diag_steps_max(self):
        with mock.patch.object(config, 'DIAG_STEPS_MAX', 2):
            c = self.assertExact('P0300', 'P0300-00')['candidates'][0]
        self.assertEqual([s['aspect'] for s in c['steps']], ['Description', 'Symptom Tests'])
        self.assertIsNone(c['procedure'])        # procedure step lies beyond the cap

    def test_sparse_row_empty_levels_and_null_desc(self):
        c = self.assertExact('U0100-87', 'U0100-87')['candidates'][0]
        self.assertEqual(c['inheritance_path'], 'Network › CAN')   # '' subsystem skipped
        self.assertEqual(c['description'], '')
        self.assertEqual(c['steps'], [])
        self.assertIsNone(c['procedure'])
        self.assertEqual(c['labor_time'], [])
        self.assertIsNone(c['blob_id'])

    def test_unknown_code_for_this_car_is_not_in_data(self):
        res = diag.diagnose('P0420', car_stem='CarA')     # exists only in CarB
        self.assertEqual(res['intent'], 'dtc')
        self.assertFalse(res['known'])
        self.assertFalse(res['grounded'])
        self.assertEqual(res['code'], 'P0420')
        self.assertEqual(res['candidates'], [])
        self.assertEqual(res['top_similarity'], 0.0)
        self.assertEqual(res['confidence_band']['band'], 'low')
        self.assertIn('not found', res['message'])
        self.encode.assert_not_called()

    def test_code_of_another_car_is_never_returned(self):
        self.assertExact('P0420', 'P0420', car='CarB')
        res = diag.diagnose('P0300', car_stem='CarB')
        self.assertFalse(res['known'])
        self.assertEqual(res['candidates'], [])

    def test_first_known_code_wins_among_multiple(self):
        self.assertExact('P0171 and also P0300', 'P0171')
        self.assertExact('P0300 then P0171', 'P0300-00')

    def test_known_code_not_masked_by_earlier_unknown_code(self):
        # Regression (fixed in this change): _detect_code returns on the first code-shaped miss (diag.py:302-303), so a
        # pasted "P0420 P0171" answers "P0420 not found" although P0171 is in this car.
        self.assertExact('P0420 P0171', 'P0171')

    def test_unknown_subcode_is_reported_not_found(self):
        # Regression (fixed in this change): the code-shape guard ^[A-Z]\d{4}$ (diag.py:302) rejects sub-coded keys,
        # so an unknown "P0300-27" silently falls into embedding symptom search.
        res = diag.diagnose('P0300-27', car_stem='CarA')
        self.assertEqual(res['intent'], 'dtc')
        self.assertFalse(res['known'])

    def test_code_beats_repair_marker(self):
        self.assertExact('how to replace the sensor for P0171', 'P0171')

    def test_non_code_words_are_not_codes(self):
        for q in ('P030', 'P03000000', 'idle', 'lean rough'):   # wrong length / plain words
            with self.subTest(q=q):
                self.assertNotEqual(diag.diagnose(q, car_stem='CarA')['intent'], 'dtc')


class LaborAndCrossVehicleTest(_DiagFixture):
    """Unified-index bridges must honour allowed_cars."""

    def payload(self, allowed):
        res = diag.diagnose('P0300', car_stem='CarA', allowed_cars=allowed)
        return res['candidates'][0]

    def test_unrestricted_caller_sees_dedup_cross_vehicle(self):
        c = self.payload(None)
        self.assertEqual(c['blob_id'], 10)
        stems = [x['car_stem'] for x in c['cross_vehicle']]
        self.assertNotIn('CarA', stems)
        self.assertIn('CarC', stems)
        # CarB and CarB2 share (model, variant) -> only one corroboration
        self.assertEqual(len([s for s in stems if s.startswith('CarB')]), 1)
        self.assertEqual(len(c['labor_time']), 1)
        self.assertTrue(c['labor_time'][0]['title'].startswith('Labor: Spark plugs'))

    def test_allow_list_filters_cross_vehicle_and_labor(self):
        c = self.payload({'CarA', 'CarB'})
        self.assertEqual([x['car_stem'] for x in c['cross_vehicle']], ['CarB'])
        self.assertEqual(c['cross_vehicle'][0]['app_url'], '/Toyota/2020/CarB/Engine/P0300')
        self.assertEqual(c['labor_time'], [{'title': 'Labor: Spark plugs B',
                                            'app_url': '/Toyota/2020/CarB/Labor/Spark'}])

    def test_only_own_car_allowed_hides_everything_foreign(self):
        c = self.payload({'CarA'})
        self.assertEqual(c['cross_vehicle'], [])
        self.assertEqual(c['labor_time'], [])     # labor page exists only in foreign cars

    def test_cross_vehicle_capped(self):
        with mock.patch.object(config, 'CROSS_VEHICLE_MAX', 1):
            self.assertEqual(len(self.payload(None)['cross_vehicle']), 1)

    def test_missing_index_degrades_without_error(self):
        with mock.patch.object(config, 'INDEX_DB', self._tmp / 'absent' / 'nope.db'):
            c = self.payload(None)
        self.assertEqual(c['code'], 'P0300-00')
        self.assertEqual((c['cross_vehicle'], c['labor_time'], c['blob_id']), ([], [], None))


class CarResolutionTest(_DiagFixture):
    def test_car_stem_takes_precedence_over_model(self):
        self.assertEqual(diag._resolve_stem(None, 'CarA', 'CarB'), 'CarB')
        self.assertEqual(diag._resolve_stem(None, 'CarA', 'NoSuchCar'), 'CarA')
        self.assertEqual(diag._resolve_stem(None, 'CarA', None), 'CarA')

    def test_allow_list_honoured(self):
        self.assertIsNone(diag._resolve_stem(None, None, 'CarA', allowed_cars=set()))
        self.assertIsNone(diag._resolve_stem(None, None, 'CarA', allowed_cars={'CarB2'}))
        # car_stem forbidden, model allowed -> falls back to model
        self.assertEqual(diag._resolve_stem(None, 'CarB', 'CarA', allowed_cars={'CarB'}), 'CarB')

    def test_forbidden_car_resolves_to_nothing_end_to_end(self):
        res = diag.diagnose('P0300', car_stem='CarA', allowed_cars={'CarB'})
        self.assertEqual(res['error'], 'no_diag_index')
        self.assertEqual(res['candidates'], [])

    def test_hostile_names_rejected_without_error(self):
        (self._tmp / 'diag' / 'sub').mkdir(exist_ok=True)
        for name in ('../diag/CarA', 'sub/../CarA', '..', '.', 'a\\CarA', 'CarA\x00',
                     'A' * 201, '', None):
            with self.subTest(name=repr(name)[:30]):
                self.assertIsNone(diag._resolve_stem(None, name, name))
                res = diag.diagnose('P0300', model=name, car_stem=name)
                self.assertEqual(res['intent'], 'unknown')
                self.assertEqual(res['error'], 'no_diag_index')

    def test_available_cars_lists_built_sidecars(self):
        self.assertEqual(diag.available_cars(), ['CarA', 'CarB', 'CarOld'])
        with mock.patch.object(config, 'DIAG_DIR', self._tmp / 'missing'):
            self.assertEqual(diag.available_cars(), [])

    def test_embed_model_mismatch_refuses(self):
        with self.assertRaises(RuntimeError) as cm:
            diag.diagnose('P0300', car_stem='CarOld')
        self.assertIn('some-other-model', str(cm.exception))


class RepairIntentTest(_DiagFixture):
    def test_how_to_questions_route_to_repair(self):
        for q in ('how to replace spark plugs', 'Torque spec for wheel nuts',
                  'چطور شمع را تعویض کنم', 'ظرفیت روغن موتور'):
            with self.subTest(q=q):
                res = diag.diagnose(q, car_stem='CarA')
                self.assertEqual(res['intent'], 'repair')
                self.assertEqual(res['candidates'], [])
        self.encode.assert_not_called()

    def test_symptom_marker_overrides_repair_marker(self):
        for q in ('engine noise, how to fix', 'صدا می‌دهد، چطور درستش کنم'):
            with self.subTest(q=q):
                self.assertEqual(diag.diagnose(q, car_stem='CarA')['intent'], 'symptom')


class SymptomRankingTest(_DiagFixture):
    def test_table_link_ranks_first_and_related_fills_after_strong(self):
        res = diag.diagnose('engine misfire', car_stem='CarA')
        self.assertEqual(res['intent'], 'symptom')
        codes = self.codes(res)
        top = res['candidates'][0]
        self.assertEqual(top['code'], 'P0300-00')
        self.assertEqual(top['confidence'], 0.9)
        self.assertEqual(top['confidence_band'], 'high')
        self.assertEqual(top['explain']['source'], 'symptom_table')
        self.assertEqual(top['matched_via'], 'diagnostic')
        self.assertEqual(top['reason']['matched_symptom'], 'Engine misfire or rough idle')
        self.assertGreater(top['explain']['direct'], 0.6)   # also a confident dense match
        # P0301-00: inheritance-only (dense 0.5 < floor) -> weak "related", ranked last
        self.assertEqual(codes[-1], 'P0301-00')
        rel = res['candidates'][-1]
        self.assertEqual((rel['confidence'], rel['explain']['source'],
                          rel['confidence_band']), (0.35, 'related', 'low'))
        for c in res['candidates'][:-1]:
            self.assertGreater(c['explain']['table'] + c['explain']['direct'], 0)
        # inheritance is taken only from the BEST symptom: s2's U0100-87 must not leak
        self.assertNotIn('U0100-87', codes)
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(res['grounded'])
        self.assertEqual(res['confidence_band']['band'], 'high')

    def test_k_limits(self):
        full = self.codes(diag.diagnose('engine misfire', car_stem='CarA'))
        for k in (1, 2, len(full), len(full) + 5):
            with self.subTest(k=k):
                got = self.codes(diag.diagnose('engine misfire', car_stem='CarA', k=k))
                self.assertEqual(got, full[:k])          # prefix of the same ranking

    def test_ranking_is_deterministic(self):
        a = diag.diagnose('engine misfire', car_stem='CarA')
        b = diag.diagnose('engine misfire', car_stem='CarA')
        self.assertEqual(self.codes(a), self.codes(b))

    def test_symptoms_and_procedures(self):
        res = diag.diagnose('engine misfire', car_stem='CarA')
        texts = [s['text'].strip().lower() for s in res['symptoms']]
        self.assertEqual(texts[0], 'engine misfire or rough idle')
        self.assertEqual(len(texts), len(set(texts)))          # case/space duplicates merged
        self.assertLessEqual(len(texts), 5)
        self.assertEqual(res['procedures'][0], {'title': 'Spark Plug Inspection',
                                                'app_url': SPARK_URL,
                                                'matched_symptom': 'Engine misfire or rough idle'})

    def test_persian_symptom(self):
        res = diag.diagnose('موتور ریپ میزند', car_stem='CarA')
        self.assertEqual(res['intent'], 'symptom')
        self.assertEqual(res['kind'], 'semantic')
        self.assertEqual(self.codes(res)[0], 'P0300-00')
        self.encode.assert_called()
        self.assertTrue(self.encode.call_args.kwargs.get('is_query'))

    def test_direct_semantic_match_without_table_link(self):
        res = diag.diagnose('lost communication', car_stem='CarA')
        c = next(c for c in res['candidates'] if c['code'] == 'U0100-87')
        self.assertEqual(c['explain']['source'], 'direct')
        self.assertEqual(c['matched_via'], 'semantic')
        self.assertGreaterEqual(c['confidence'], 0.95)

    def test_direct_floor_and_grounding_floor_boundaries(self):
        # CarB: no symptom tables; P0420's cosine to the query is ~0.70 by construction
        q = 'catalyst efficiency'
        with mock.patch.object(config, 'DIAG_DIRECT_SIM_FLOOR', 0.75):
            res = diag.diagnose(q, car_stem='CarB')
        self.assertEqual(res['candidates'], [])
        self.assertFalse(res['grounded'])
        with mock.patch.object(config, 'DIAG_DIRECT_SIM_FLOOR', 0.65), \
                mock.patch.object(config, 'GROUND_SIM_FLOOR', 0.65):
            res = diag.diagnose(q, car_stem='CarB')
        self.assertEqual(self.codes(res), ['P0420'])
        self.assertAlmostEqual(res['candidates'][0]['confidence'], 0.70, delta=0.02)
        self.assertEqual(res['candidates'][0]['confidence_band'], 'medium')
        self.assertTrue(res['grounded'])
        self.assertAlmostEqual(res['top_similarity'], 0.70, delta=0.02)
        self.assertEqual(res['confidence_band']['band'], 'medium')
        # candidate exists but evidence below the grounding floor -> refuse
        with mock.patch.object(config, 'DIAG_DIRECT_SIM_FLOOR', 0.65), \
                mock.patch.object(config, 'GROUND_SIM_FLOOR', 0.75):
            res = diag.diagnose(q, car_stem='CarB')
        self.assertEqual(self.codes(res), ['P0420'])
        self.assertFalse(res['grounded'])
        self.assertEqual(res['confidence_band']['band'], 'low')

    def test_junk_query_without_symptom_tables_is_ungrounded(self):
        res = diag.diagnose('qwertyuiop zxcvbnmasd', car_stem='CarB')
        self.assertEqual(res['intent'], 'symptom')
        self.assertEqual(res['candidates'], [])
        self.assertFalse(res['grounded'])
        self.assertEqual(res['confidence_band']['band'], 'low')

    def test_junk_query_with_symptom_tables_is_ungrounded(self):
        # Regression (fixed in this change): sym_vec KNN always returns the top-K symptoms regardless of similarity
        # and any symptom_table link sets has_table (diag.py:347-351,399-403,512-513), so
        # unrelated text on a car with symptom tables gets 0.9-confidence, grounded, high band.
        res = diag.diagnose('qwertyuiop zxcvbnmasd', car_stem='CarA')
        self.assertFalse(res['grounded'])
        self.assertEqual(res['candidates'], [])

    def test_feedback_boost_reorders_and_is_explained(self):
        base = self.codes(diag.diagnose('engine misfire', car_stem='CarA'))
        self.assertEqual(base[0], 'P0300-00')
        # blob 10 = P0300-00's Description; a (deliberately extreme) demotion multiplier
        self.boost.return_value = {10: 0.01}
        res = diag.diagnose('engine misfire', car_stem='CarA')
        c = next(c for c in res['candidates'] if c['code'] == 'P0300-00')
        self.assertEqual(c['explain']['boosts']['feedback'], 0.01)
        self.assertEqual(c['blob_id'], 10)
        self.assertNotEqual(self.codes(res)[0], 'P0300-00')
        other = next(c for c in res['candidates'] if c['code'] != 'P0300-00')
        self.assertEqual(other['explain']['boosts']['feedback'], 1.0)

    def test_no_index_means_no_feedback_lookup(self):
        with mock.patch.object(diag.store, 'open_index', side_effect=OSError('no index')):
            res = diag.diagnose('engine misfire', car_stem='CarA')
        self.boost.assert_not_called()
        self.assertEqual(self.codes(res)[0], 'P0300-00')


class PureHelpersTest(unittest.TestCase):
    def test_band_boundaries(self):
        self.assertEqual(diag._band(1.0)['band'], 'high')
        self.assertEqual(diag._band(config.CONF_HIGH_SIM)['band'], 'high')
        self.assertEqual(diag._band(config.CONF_HIGH_SIM - 1e-6)['band'], 'medium')
        self.assertEqual(diag._band(config.CONF_LOW_SIM)['band'], 'medium')
        self.assertEqual(diag._band(config.CONF_LOW_SIM - 1e-6)['band'], 'low')
        self.assertEqual(diag._band(0.9, margin=0.0)['band'], 'medium')   # no clear winner
        self.assertTrue(diag._band(0.0)['label_fa'])

    def test_fts_match(self):
        self.assertIsNone(diag._fts_match(None))
        self.assertIsNone(diag._fts_match(''))
        self.assertIsNone(diag._fts_match('a " ! ?'))
        self.assertEqual(diag._fts_match('rough "idle" a'), 'rough OR idle')

    def test_normalize_code_text(self):
        self.assertEqual(diag.normalize_code_text('P ۰۳۰۱'), 'P0301')
        self.assertEqual(diag.normalize_code_text('p  0a80'), 'p0a80')
        self.assertEqual(diag.normalize_code_text(None), '')
        self.assertEqual(diag.normalize_code_text('Step 1234'), 'Step 1234')  # not a lone letter

    def test_looks_like_repair(self):
        self.assertTrue(diag._looks_like_repair('How do I bleed the brakes'))
        self.assertFalse(diag._looks_like_repair('brake pedal noise'))
        self.assertFalse(diag._looks_like_repair(''))
