"""Hit decoration in retrieve.py (#22, step 4): related pages over graph edges,
"same procedure in other vehicles", expert-pinned hits and the per-vehicle
title check behind the scope guard.

The occurrence lookups are replaced by small fakes and the index is an
in-memory SQLite with only the tables these helpers read, so each rule is
pinned on its own: authorization filtering, ordering, de-duplication, caps.
"""
import sqlite3
import unittest
from unittest import mock

from api.rag import config, retrieve


def occ(stem, brand='Toyota', model='Corolla', variant='', title='Brake Pad'):
    return {'car_stem': stem, 'brand': brand, 'model': model, 'variant': variant, 'year': 2025,
            'title': title, 'title_path': f'Brakes / {title}', 'system_tags': ''}


class Fakes(unittest.TestCase):
    def setUp(self):
        self.idx = sqlite3.connect(':memory:')
        self.idx.row_factory = sqlite3.Row
        self.idx.executescript("""
            CREATE TABLE edges (src_blob INTEGER, dst_blob INTEGER, relation TEXT, weight REAL);
            CREATE TABLE blobs (blob_id INTEGER, title TEXT);
            CREATE TABLE occurrences (blob_id INTEGER, car_stem TEXT);
        """)
        self.occs = {}
        for target, fn in (('_occurrences', lambda index, b: list(self.occs.get(b, []))),
                           ('_app_url', lambda o: (f"/app/{o['car_stem']}", ['s'])),
                           ('_blob_text', lambda index, b, max_chars=3000: f'text {b}'),
                           ('_pick_occurrence', lambda occs, brand, model, stem: (
                               next((o for o in occs if o['car_stem'] == stem), occs[0]), 0))):
            p = mock.patch.object(retrieve, target, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)


class ExpandTests(Fakes):
    def test_relations_in_priority_order_capped_and_deduplicated(self):
        self.idx.executemany('INSERT INTO edges VALUES (1, ?, ?, ?)', [
            (2, 'semantic', 0.9), (3, 'labor_time', 0.1), (4, 'crosslink', 0.5),
            (4, 'semantic', 0.8), (5, 'semantic', 0.95), (6, 'semantic', 0.2), (7, 'other', 1.0)])
        for b in range(2, 8):
            self.occs[b] = [occ('car_a', title=f'T{b}')]
        out = retrieve._expand(self.idx, 1, 'Toyota', 'Corolla', 'car_a')
        self.assertEqual([r['relation'] for r in out], ['labor_time', 'crosslink', 'semantic', 'semantic'])
        self.assertEqual([r['title'] for r in out], ['T3', 'T4', 'T5', 'T2'])
        self.assertEqual(len(out), config.GRAPH_EXPAND)
        self.assertEqual(out[0]['snippet'], 'text 3')

    def test_never_links_a_vehicle_the_caller_cannot_open(self):
        self.idx.executemany('INSERT INTO edges VALUES (1, ?, ?, 1.0)', [(2, 'semantic'), (3, 'semantic')])
        self.occs[2] = [occ('car_b')]
        self.occs[3] = [occ('car_a'), occ('car_b')]
        out = retrieve._expand(self.idx, 1, 'Toyota', 'Corolla', 'car_a', allowed_cars={'car_a'})
        self.assertEqual([r['app_url'] for r in out], ['/app/car_a'])

    def test_no_edges(self):
        self.assertEqual(retrieve._expand(self.idx, 1, 'Toyota', 'Corolla', 'car_a'), [])


class CrossVehicleTests(Fakes):
    def test_scopes_order_dedup_and_skip_the_shown_vehicle(self):
        shown = occ('cc_2025', model='Corolla Cross')
        occs = [shown,
                occ('lexus', brand='Lexus', model='NX'),
                occ('cam', model='Camry'),
                occ('cc_2024', model='Corolla Cross'),
                occ('cc_2024b', model='Corolla Cross')]           # same (model, variant): dropped
        out = retrieve._cross_vehicle(shown, occs)
        self.assertEqual([(c['car_stem'], c['scope']) for c in out],
                         [('cc_2024', 'same_model'), ('cam', 'same_brand'), ('lexus', 'cross_brand')])

    def test_capped(self):
        shown = occ('x0')
        occs = [shown] + [occ(f'x{i}', model=f'M{i}') for i in range(1, 10)]
        self.assertEqual(len(retrieve._cross_vehicle(shown, occs)), config.CROSS_VEHICLE_MAX)


class PinnedHitTests(Fakes):
    def test_expert_pin_becomes_a_high_confidence_hit_on_the_selected_vehicle(self):
        self.occs[9] = [occ('car_b'), occ('car_a')]
        h = retrieve._pinned_hit(self.idx, {'blob_id': 9, 'note': 'checked by Ali'},
                                 'Toyota', 'Corolla', 'car_a')
        self.assertEqual((h['car_stem'], h['matched_via'], h['confidence_band'], h['score']),
                         ('car_a', 'expert_verified', 'high', 1.0))
        self.assertEqual(h['explain']['note'], 'checked by Ali')
        self.assertEqual(h['text'], 'text 9')
        self.assertEqual([c['car_stem'] for c in h['cross_vehicle']], ['car_b'])

    def test_pin_outside_the_callers_vehicles_or_unknown_is_dropped(self):
        self.occs[9] = [occ('car_b')]
        self.assertIsNone(retrieve._pinned_hit(self.idx, {'blob_id': 9}, 'Toyota', 'Corolla', 'car_a',
                                               allowed_cars={'car_a'}))
        self.assertIsNone(retrieve._pinned_hit(self.idx, {'blob_id': 404}, 'Toyota', 'Corolla', 'car_a'))


class VehicleHasTitleTests(Fakes):
    def test_answers_from_the_vehicles_own_pages(self):
        self.idx.executemany('INSERT INTO blobs VALUES (?, ?)', [(1, 'Propeller Shaft'), (2, 'Brake Pad')])
        self.idx.executemany('INSERT INTO occurrences VALUES (?, ?)', [(1, 'awd'), (2, 'awd'), (2, 'fwd')])
        self.assertTrue(retrieve._vehicle_has_title(self.idx, ' Propeller Shaft ', 'awd'))
        self.assertFalse(retrieve._vehicle_has_title(self.idx, 'Propeller Shaft', 'fwd'))
        self.assertIsNone(retrieve._vehicle_has_title(self.idx, '', 'fwd'))
        self.assertIsNone(retrieve._vehicle_has_title(self.idx, 'Brake Pad', ''))
