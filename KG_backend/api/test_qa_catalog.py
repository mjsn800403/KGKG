"""QA integration tests for the content-serving API.

Covers api/views.py (public catalog, per-car manual tree, title search,
entitlement gating, orphan-page / href resolution, search fallback, AI entry
guards), api/parts.py (parts catalog serving) and api/mediaauth.py (nginx
auth_request gate for paid media).

Every test drives the real HTTP stack (URLconf + middleware + view) against a
real per-car SQLite DB built in a temp dir, with real grants and real portal
tokens. Nothing in the code under test is mocked; the only patch is the RAG
semantic index (an external, heavyweight dependency) forced "absent" so the
documented SQL LIKE fallback runs deterministically.

Tests marked ``@unittest.expectedFailure`` pin a real defect (see the
``# DEFECT:`` line on each); they flip to "unexpected success" once fixed.

Run:  python manage.py test api.test_qa_catalog
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from . import cardb, contentguard
from .models import (AdminAuthToken, AuthToken, Car, Company, CompanyCarAccess,
                     PlatformAdmin, PortalUser, PurchaseRequest, UserCarAccess,
                     VehicleSpec)

CAMRY = 'Camry LE'
SUPRA = 'Supra GR'
GHOST = 'NX Ghost'
CAMRY_PARTS = 'Camry LE (Parts 2021)'

OIL_TITLE = 'Oil 50% Change_Guide'
TORQUE_TITLE = 'O\'Brien "Torque" Spec'
SLASH_TITLE = 'Service Data [11/2022 - ]'
N_BOLTS = 60

_ENV_KEYS = ('KG_RL_DISABLE',)
_saved_env = {}
TMP = None
_CG_PATCH = mock.patch.dict(contentguard._LIMITS,
                            {'page': (10 ** 9, 10 ** 9), 'media': (10 ** 9, 10 ** 9)})


def setUpModule():
    global TMP
    # Rate limiting has its own tests; here it would only add order coupling.
    for k in _ENV_KEYS:
        _saved_env[k] = os.environ.get(k)
    os.environ['KG_RL_DISABLE'] = '1'
    # The per-user hourly scrape guard counts in a store shared across runs;
    # lift its ceiling so repeated runs within an hour stay deterministic.
    _CG_PATCH.start()
    TMP = Path(tempfile.mkdtemp(prefix='kg_qa_catalog_'))


def tearDownModule():
    _CG_PATCH.stop()
    for k, v in _saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    cardb.invalidate_ready_cache()
    shutil.rmtree(TMP, ignore_errors=True)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def build_manual_db(db_path, car_name, src_dir):
    """A per-car manual DB with the same ``nodes`` schema the crawler emits.

    Tree (depth in brackets):
      [0] <car>                         car root, source_file -> src_dir
      [1] Repair Manual                 root
          [2] Engine
              [3] Oil 50% Change_Guide          leaf, href pages/100.html
              [3] O'Brien "Torque" Spec         leaf, href pages/101.html
          [2] Service Data [11/2022 - ]         leaf (literal '/' in title)
          [2] Abbreviations
              [3] Abbreviations: "D"            leaf (prefixed index page)
          [2] Dead End                          placeholder: must be hidden
          [2] External Pages                    only dead children: hidden
              [3] Different car
          [2] Fasteners
              [3] Bolt 00 .. Bolt 59            60 leaves
      [1] Download .zip for offline use  href 404.html: must be hidden
      [1] Body
          [2] Panel                             leaf
      [1] Ghost Root                     placeholder root: must be hidden
    """
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE nodes (
        id INTEGER PRIMARY KEY, parent_id INTEGER, path TEXT, title TEXT,
        node_type TEXT, file_type TEXT, href TEXT, sort_order INTEGER,
        depth INTEGER, content TEXT, source_file TEXT)""")
    paths = {}

    def add(nid, parent, title, depth, sort, node_type='section', content=None,
            href=None, file_type=None, source_file=None):
        seg = title.replace('/', '⁄')
        p = seg if parent is None else f'{paths[parent]}/{seg}'
        paths[nid] = p
        con.execute('INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (nid, parent, p, title, node_type, file_type, href, sort,
                     depth, content, source_file))

    add(1, None, car_name, 0, 0, node_type='car', file_type='root_path',
        source_file=str(Path(src_dir) / 'index.html'))
    add(2, 1, 'Repair Manual', 1, 1, node_type='root')
    add(3, 2, 'Engine', 2, 1)
    add(4, 3, OIL_TITLE, 3, 1,
        content='<p>Drain the oil.</p><img src="../images/A1.png">',
        href='pages/100.html')
    add(5, 3, TORQUE_TITLE, 3, 2, content='<p>Tighten to 25 Nm</p>',
        href='pages/101.html')
    add(6, 2, SLASH_TITLE, 2, 2,
        content='<object data="/api/Image/SVGImage/W1"></object>',
        href='pages/102.html')
    add(7, 2, 'Abbreviations', 2, 3)
    add(8, 7, 'Abbreviations: "D"', 3, 1, content='<p>DTC: Diagnostic Trouble Code</p>',
        href='pages/103.html')
    add(9, 2, 'Dead End', 2, 4)
    add(10, 2, 'External Pages', 2, 5)
    add(11, 10, 'Different car', 3, 1)
    add(12, 2, 'Fasteners', 2, 6)
    for i in range(N_BOLTS):
        add(100 + i, 12, f'Bolt {i:02d}', 3, i,
            content=f'<p>bolt spec {i}</p><img src="images/B{i}.png">',
            href=f'pages/b{i}.html')
    add(20, 1, 'Download .zip for offline use', 1, 2, node_type='root', href='404.html')
    add(21, 1, 'Body', 1, 3, node_type='root')
    add(22, 21, 'Panel', 2, 1, content='<p>panel</p>', href='pages/200.html')
    add(23, 1, 'Ghost Root', 1, 4, node_type='root')
    con.commit()
    con.close()


def build_parts_db(db_path, *, labels=True, meta='{"groups": 2, "parts": 4}',
                   frames=True, broken=False):
    """A per-vehicle parts DB matching the schema api/parts.py reads."""
    con = sqlite3.connect(db_path)
    if broken:
        # A DB with no `frames` table: the open succeeds, the first query fails.
        con.execute('CREATE TABLE meta (k TEXT, v TEXT)')
        con.commit()
        con.close()
        return
    con.executescript("""
        CREATE TABLE frames (code TEXT, engine TEXT, transmission TEXT,
            steering TEXT, destination TEXT, grade TEXT, region TEXT,
            date_from TEXT, date_to TEXT, is_default INTEGER, n_groups INTEGER,
            n_parts INTEGER, sort_order INTEGER);
        CREATE TABLE meta (k TEXT, v TEXT);
        CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER,
            path TEXT, title TEXT, node_type TEXT, file_type TEXT, href TEXT,
            sort_order INTEGER, depth INTEGER, content TEXT, frame TEXT,
            group_id INTEGER);
        CREATE TABLE groups (id INTEGER PRIMARY KEY, label TEXT, gid INTEGER,
            frame TEXT, category TEXT, category_fa TEXT, node_id INTEGER);
        CREATE TABLE sections (id INTEGER PRIMARY KEY, group_id INTEGER,
            section_index INTEGER, figure_code TEXT, image_url TEXT, caption TEXT);
        CREATE TABLE part_rows (id INTEGER PRIMARY KEY, section_id INTEGER,
            row_index INTEGER, callout TEXT, pn TEXT, pn_display TEXT,
            name_en TEXT, name_fa TEXT, qty INTEGER, qty_display TEXT,
            note TEXT, date_range TEXT, is_xref INTEGER);
    """)
    if labels:
        con.execute('CREATE TABLE section_labels (id INTEGER PRIMARY KEY, '
                    'section_id INTEGER, code TEXT, x REAL, y REAL, w REAL, '
                    'h REAL, title TEXT)')
    if meta is not None:
        con.execute("INSERT INTO meta VALUES ('counts', ?)", (meta,))
    if frames:
        con.executemany('INSERT INTO frames VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', [
            ('F1', 'M20A', 'CVT', 'LHD', 'US', 'LE', 'US', '202001', '202212',
             0, 2, 3, 1),
            ('F2', 'A25A', 'AT', 'LHD', 'GCC', 'XLE', 'ME', '202101', '202312',
             1, 1, 1, 2),
        ])
        nodes = [
            # F1 tree: root(0) -> Engine(1) -> {Oil Filter leaf, Belt / Set leaf}
            (1, None, 'F1', 'F1', 'frame', None, None, 0, 0, None, 'F1', None),
            (2, 1, 'F1/Engine', 'Engine', 'section', None, None, 1, 1, None, 'F1', None),
            (3, 2, 'F1/Engine/Oil Filter', 'Oil Filter', 'group', None, None, 1, 2,
             None, 'F1', 10),
            (4, 2, 'F1/Engine/Belt _ Set', 'Belt / Set', 'group', None, None, 2, 2,
             None, 'F1', 11),
            (5, 1, 'F1/Orphan', 'Orphan', 'group', None, None, 2, 1, None, 'F1', 999),
            # F2 tree: root -> Body leaf
            (6, None, 'F2', 'F2', 'frame', None, None, 0, 0, None, 'F2', None),
            (7, 6, 'F2/Body', 'Body Panel', 'group', None, None, 1, 1, None, 'F2', 20),
        ]
        con.executemany('INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', nodes)
        con.executemany('INSERT INTO groups VALUES (?,?,?,?,?,?,?)', [
            (10, 'Oil Filter', 2, 'F1', 'Engine/Fuel', 'موتور', 3),
            (11, 'Belt / Set', 11, 'F1', 'Engine/Fuel', 'موتور', 4),
            (20, 'Body Panel', 30, 'F2', 'Body', 'بدنه', 7),
        ])
        con.executemany('INSERT INTO sections VALUES (?,?,?,?,?,?)', [
            (100, 10, 1, '15600', '/media/_parts_assets/oil.gif', 'OIL FILTER'),
            (101, 11, 1, '90916', '/media/_parts_assets/belt.gif', 'BELT'),
            (200, 20, 1, '61111', '/media/_parts_assets/body.gif', 'PANEL'),
        ])
        con.executemany('INSERT INTO part_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', [
            (1, 100, 1, '15600', '90915-YZZD1', '90915-YZZD1', 'OIL FILTER',
             'فیلتر روغن', 1, '1', '', '', 0),
            (2, 100, 2, '90915YZZD1', '90915-YZZD1', '90915-YZZD1', 'OIL FILTER',
             'فیلتر روغن', 1, '1', 'dup row', '', 0),
            (3, 100, 3, '0888680000', '0888680000', '08886-80000', '', None,
             None, '', '', '', 1),
            (4, 101, 1, '90916', '9091602680', '90916-02680', 'BELT, V-RIBBED',
             None, 8, '8', '12V', '', 0),
            (5, 200, 1, '61111', '6111142170', '61111-42170', 'PANEL, SIDE',
             None, 1, '1', '', '', 0),
        ])
        if labels:
            con.execute("INSERT INTO section_labels VALUES "
                        "(1, 100, '15600', 0.1, 0.2, 0.05, 0.03, 'OIL FILTER')")
    con.commit()
    con.close()


class QAUsersMixin:
    """Shared world: a ready car (Camry), a second ready car (Supra), a car whose
    DB is missing (Ghost), three companies and users with distinct grants."""

    @classmethod
    def make_world(cls):
        root = TMP / cls.__name__
        root.mkdir(parents=True, exist_ok=True)
        cls.src = root / 'crawl' / 'camry'
        (cls.src / 'pages').mkdir(parents=True, exist_ok=True)
        (cls.src / 'pages' / 'orphan.html').write_text(
            '<html><body><div class="main"><h1>Orphan Variant Labor</h1>'
            '<img src="../images/Z9.png"><p>0.4 h</p></div></body></html>',
            encoding='utf-8')
        (cls.src / 'notitle.html').write_text(
            '<html><body><a class="breadcrumb-part">Crumb A</a>'
            '<a class="breadcrumb-part">Crumb B</a><p>body</p></body></html>',
            encoding='utf-8')
        # A file OUTSIDE the car's source folder that traversal must never reach.
        (root / 'crawl' / 'secret.html').write_text(
            '<div class="main"><h1>TOP SECRET</h1></div>', encoding='utf-8')
        cls.camry_db = root / 'camry_le.db'
        cls.supra_db = root / 'supra_gr.db'
        build_manual_db(cls.camry_db, CAMRY, cls.src)
        build_manual_db(cls.supra_db, SUPRA, root / 'crawl' / 'supra')

    def make_rows(self):
        cache.clear()
        cardb.invalidate_ready_cache()
        self.camry = Car.objects.create(brand_name='Toyota', car_name=CAMRY, year=2021,
                                        db_address=str(self.camry_db))
        self.supra = Car.objects.create(brand_name='Toyota', car_name=SUPRA, year=2020,
                                        db_address=str(self.supra_db))
        self.ghost = Car.objects.create(brand_name='Lexus', car_name=GHOST, year=2022,
                                        db_address=str(TMP / 'does-not-exist.db'))
        self.co_a = Company.objects.create(name='QA Garage A')
        self.co_b = Company.objects.create(name='QA Garage B')
        for car in (self.camry, self.ghost):
            CompanyCarAccess.objects.create(company=self.co_a, car=car, documents=[])
        CompanyCarAccess.objects.create(company=self.co_b, car=self.supra, documents=[])
        # alice: company A, may open Camry (+ the unbuilt Ghost)
        self.alice = PortalUser.objects.create(company=self.co_a, username='qa_alice',
                                               role='after_sales_specialist')
        UserCarAccess.objects.create(user=self.alice, car=self.camry, documents=[])
        UserCarAccess.objects.create(user=self.alice, car=self.ghost, documents=[])
        # carol: company A, but no per-user car grant at all
        self.carol = PortalUser.objects.create(company=self.co_a, username='qa_carol',
                                               role='after_sales_specialist')
        # bob: company B, may open Supra only
        self.bob = PortalUser.objects.create(company=self.co_b, username='qa_bob',
                                             role='after_sales_specialist')
        UserCarAccess.objects.create(user=self.bob, car=self.supra, documents=[])

    @staticmethod
    def auth(user):
        return {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(user).key}'}

    @staticmethod
    def car_url(car):
        return f'/{quote(car.brand_name)}/{car.year}/{quote(car.car_name)}/'


# ---------------------------------------------------------------------------
# Public catalog: brand list + brand/year listings
# ---------------------------------------------------------------------------

class PublicCatalogTests(QAUsersMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.make_world()

    def setUp(self):
        self.make_rows()
        self.c = Client()

    def test_brand_list_only_lists_brands_with_a_built_db(self):
        r = self.c.get('/')
        self.assertEqual(r.status_code, 200)
        # Lexus' only car has no DB on disk -> must not be advertised.
        self.assertEqual(r.json(), ['Toyota'])

    def test_brand_list_is_cached_until_ttl(self):
        self.assertEqual(self.c.get('/').json(), ['Toyota'])
        Car.objects.create(brand_name='Acura', car_name='MDX', year=2020,
                           db_address=str(self.camry_db))
        # Served from the 60s cache: the new brand is not visible yet ...
        self.assertEqual(self.c.get('/').json(), ['Toyota'])
        cache.clear()
        # ... and appears once the cache is dropped (sorted).
        self.assertEqual(self.c.get('/').json(), ['Acura', 'Toyota'])

    def test_brand_listing_is_case_insensitive_and_hides_internal_fields(self):
        r = self.c.get('/toyota/')
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        self.assertEqual([x['car_name'] for x in rows], [CAMRY, SUPRA])
        for row in rows:
            self.assertEqual(set(row), {'brand_name', 'car_name', 'display_name', 'year'})
            self.assertNotIn(str(TMP), json.dumps(row))

    def test_brand_listing_excludes_unbuilt_vehicle(self):
        self.assertEqual(self.c.get('/Lexus/').json(), [])

    def test_year_listing_filters_by_year(self):
        self.assertEqual([x['car_name'] for x in self.c.get('/Toyota/2021/').json()], [CAMRY])
        self.assertEqual(self.c.get('/Toyota/1999/').json(), [])

    def test_non_numeric_year_is_an_empty_listing_not_a_500(self):
        for year in ('unknown', 'abc', '20x1'):
            with self.subTest(year=year):
                r = self.c.get(f'/Toyota/{year}/')
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json(), [])

    def test_brand_lookup_treats_sql_wildcards_as_literals(self):
        # `%` / `_` must not turn the iexact brand match into "every brand".
        for brand in ('%25', '_', '%25%25', 'T_yota', "Toyota'%20OR%20'1'='1"):
            with self.subTest(brand=brand):
                r = self.c.get(f'/{brand}/')
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json(), [])

    def test_public_listing_spec_exposes_identity_subset_only(self):
        VehicleSpec.objects.create(car=self.camry, data={
            '@type': 'Car', 'name': 'Camry LE', 'fuelType': 'Gasoline',
            'engineOilCapacity': '4.8 L', 'torqueSpec': '25 Nm'})
        row = next(x for x in self.c.get('/Toyota/').json() if x['car_name'] == CAMRY)
        self.assertEqual(row['spec']['name'], 'Camry LE')
        self.assertEqual(row['spec']['fuelType'], 'Gasoline')
        # licensed service data must never reach the public catalog
        self.assertNotIn('engineOilCapacity', row['spec'])
        self.assertNotIn('torqueSpec', row['spec'])

    def test_unmatched_api_path_is_404_not_a_brand(self):
        r = self.c.get('/api/definitely-not-an-endpoint/')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {'error': 'not found'})


# ---------------------------------------------------------------------------
# Per-car manual content: entitlement gating
# ---------------------------------------------------------------------------

class CarContentAccessTests(QAUsersMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.make_world()

    def setUp(self):
        self.make_rows()
        self.c = Client()

    def test_signed_out_gets_401(self):
        r = self.c.get(self.car_url(self.camry))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {'error': 'unauthorized'})

    def test_bogus_bearer_token_gets_401(self):
        r = self.c.get(self.car_url(self.camry), HTTP_AUTHORIZATION='Bearer not-a-token')
        self.assertEqual(r.status_code, 401)

    def test_user_without_any_grant_gets_403(self):
        r = self.c.get(self.car_url(self.camry), **self.auth(self.carol))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['error'], 'forbidden')

    def test_other_company_user_cannot_open_car(self):
        r = self.c.get(self.car_url(self.camry), **self.auth(self.bob))
        self.assertEqual(r.status_code, 403)
        # every content variant stays closed, not just the root listing
        for params in ({'seg': 'Repair Manual'}, {'q': 'oil'}, {'href': 'pages/100.html'},
                       {'page': 'pages/orphan.html'}, {'spec': '1'},
                       {'seg': 'Repair Manual', 'subtree': '1'}):
            with self.subTest(params=params):
                r = self.c.get(self.car_url(self.camry), params, **self.auth(self.bob))
                self.assertEqual(r.status_code, 403)
                self.assertNotIn('Drain', r.content.decode())

    def test_owner_gets_200(self):
        r = self.c.get(self.car_url(self.camry), **self.auth(self.alice))
        self.assertEqual(r.status_code, 200)

    def test_purchase_grant_is_revoked_when_company_loses_the_car(self):
        CompanyCarAccess.objects.filter(company=self.co_a, car=self.camry).delete()
        r = self.c.get(self.car_url(self.camry), **self.auth(self.alice))
        self.assertEqual(r.status_code, 403)

    def test_admin_grant_survives_company_rescope(self):
        CompanyCarAccess.objects.filter(company=self.co_a, car=self.camry).delete()
        UserCarAccess.objects.filter(user=self.alice, car=self.camry).update(admin_granted=True)
        r = self.c.get(self.car_url(self.camry), **self.auth(self.alice))
        self.assertEqual(r.status_code, 200)

    def test_locked_user_is_signed_out(self):
        hdr = self.auth(self.alice)
        PortalUser.objects.filter(pk=self.alice.pk).update(locked=True)
        self.assertEqual(self.c.get(self.car_url(self.camry), **hdr).status_code, 401)

    def test_deactivated_company_is_signed_out(self):
        hdr = self.auth(self.alice)
        Company.objects.filter(pk=self.co_a.pk).update(active=False)
        self.assertEqual(self.c.get(self.car_url(self.camry), **hdr).status_code, 401)

    def test_unknown_car_for_signed_in_user_is_404(self):
        r = self.c.get('/Toyota/2021/No%20Such%20Car/', **self.auth(self.alice))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()['error'], 'Car not found')

    def test_granted_but_unbuilt_vehicle_is_404(self):
        r = self.c.get(self.car_url(self.ghost), **self.auth(self.alice))
        self.assertEqual(r.status_code, 404)
        self.assertIn('not available', r.json()['error'])

    def test_unbuilt_vehicle_is_403_not_404_for_ungranted_user(self):
        # Readiness must not be revealed to someone without the grant.
        r = self.c.get(self.car_url(self.ghost), **self.auth(self.bob))
        self.assertEqual(r.status_code, 403)

    def test_anonymous_cannot_probe_which_vehicles_exist(self):
        # Regression (fixed in this change): views.car_view resolves the Car (views.py:776-783) BEFORE the
        # auth check (views.py:790-792), so anonymous callers get 404 for a
        # made-up car but 401 for a real one -> catalog existence oracle (incl.
        # hidden/unbuilt vehicles). parts_view fixed the same issue.
        real = self.c.get(self.car_url(self.camry))
        fake = self.c.get('/Toyota/2021/No%20Such%20Car/')
        self.assertEqual(real.status_code, 401)
        self.assertEqual(fake.status_code, 401)

    def test_placeholder_year_resolves_by_name(self):
        r = self.c.get(f'/Toyota/unknown/{quote(CAMRY)}/', **self.auth(self.alice))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([n['title'] for n in r.json()], ['Repair Manual', 'Body'])

    def test_wrong_year_falls_back_to_name_and_is_still_gated(self):
        r = self.c.get(f'/Toyota/1999/{quote(CAMRY)}/', **self.auth(self.bob))
        self.assertEqual(r.status_code, 403)
        r = self.c.get(f'/toyota/1999/{quote(CAMRY.lower())}/', **self.auth(self.alice))
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# Per-car manual content: tree walking, search, href/page resolution
# ---------------------------------------------------------------------------

class CarTreeTests(QAUsersMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.make_world()

    def setUp(self):
        self.make_rows()
        self.c = Client()
        self.hdr = self.auth(self.alice)
        self.url = self.car_url(self.camry)

    def get(self, params=None, raw=None):
        url = self.url + raw if raw else self.url
        return self.c.get(url, params or {}, **self.hdr)

    # -- root + walking ----------------------------------------------------
    def test_root_hides_404_artifacts_and_dead_placeholders(self):
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual([n['title'] for n in r.json()], ['Repair Manual', 'Body'])

    def test_children_hide_dead_ends_and_sections_of_only_dead_ends(self):
        r = self.get({'seg': 'Repair Manual'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([n['title'] for n in r.json()],
                         ['Engine', SLASH_TITLE, 'Abbreviations', 'Fasteners'])

    def test_walk_to_leaf_returns_node_with_rewritten_images(self):
        r = self.get({'seg': ['Repair Manual', 'Engine', OIL_TITLE]})
        self.assertEqual(r.status_code, 200)
        nodes = r.json()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]['title'], OIL_TITLE)
        self.assertIn('src="/media/Camry%20LE/A1.png"', nodes[0]['content'])
        self.assertNotIn('../images/', nodes[0]['content'])

    def test_title_with_literal_slash_walks_via_seg(self):
        r = self.get({'seg': ['Repair Manual', SLASH_TITLE]})
        self.assertEqual(r.status_code, 200)
        self.assertIn('data="/media/Camry%20LE/W1.svg"', r.json()[0]['content'])

    def test_prefixless_index_segment_resolves(self):
        # '.../Abbreviations/"D"' must resolve to 'Abbreviations: "D"'
        r = self.get({'seg': ['Repair Manual', 'Abbreviations', '"D"']})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]['title'], 'Abbreviations: "D"')

    def test_unknown_segment_is_404_naming_the_walked_path(self):
        r = self.get({'seg': ['Repair Manual', 'Nope', 'Deeper']})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()['error'], f'Path not found: {CAMRY}/Repair Manual/Nope')

    def test_dot_dot_segments_cannot_escape_the_tree(self):
        for segs in (['..'], ['Repair Manual', '..', 'Body'], ['../Body'],
                     ['%2e%2e'], ['Repair Manual/Engine']):
            with self.subTest(segs=segs):
                r = self.get({'seg': segs})
                self.assertEqual(r.status_code, 404)

    def test_url_encoded_dot_dot_in_query_is_still_404(self):
        r = self.get(raw='?seg=%2e%2e&seg=Body')
        self.assertEqual(r.status_code, 404)

    def test_sql_metacharacters_in_segment_are_literal(self):
        for seg in ("' OR '1'='1", 'Repair%', 'Repair_Manual', '"; DROP TABLE nodes; --'):
            with self.subTest(seg=seg):
                self.assertEqual(self.get({'seg': seg}).status_code, 404)
        # and the DB is intact afterwards
        self.assertEqual(self.get().status_code, 200)

    def test_nav_mode_strips_bodies_but_flags_content(self):
        r = self.get({'seg': ['Repair Manual', 'Engine'], 'nav': '1'})
        nodes = r.json()
        self.assertEqual([n['title'] for n in nodes], [OIL_TITLE, TORQUE_TITLE])
        self.assertTrue(all(n['content'] is None for n in nodes))
        self.assertTrue(all(n['has_content'] for n in nodes))
        sec = self.get({'seg': 'Repair Manual', 'nav': '1'}).json()
        self.assertFalse(next(n for n in sec if n['title'] == 'Engine')['has_content'])

    # -- subtree flattening ------------------------------------------------
    def test_subtree_stacks_every_leaf_in_tree_order(self):
        r = self.get({'seg': ['Repair Manual', 'Fasteners'], 'subtree': '1'})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['mode'], 'stack')
        self.assertEqual(body['count'], N_BOLTS)
        self.assertFalse(body['truncated'])
        self.assertEqual([i['title'] for i in body['items']],
                         [f'Bolt {i:02d}' for i in range(N_BOLTS)])
        first = body['items'][0]
        self.assertEqual(first['segments'], ['Bolt 00'])
        self.assertIn('<img loading="lazy" src="/media/Camry%20LE/B0.png"', first['content'])
        self.assertEqual(body['root']['segments'], ['Repair Manual', 'Fasteners'])

    def test_subtree_over_cap_switches_to_cards(self):
        r = self.get({'seg': ['Repair Manual', 'Fasteners'], 'subtree': '1', 'max': '10'})
        body = r.json()
        self.assertEqual(body['mode'], 'cards')
        self.assertEqual(body['items'], [])
        self.assertEqual(body['count'], N_BOLTS)
        self.assertTrue(body['truncated'])

    def test_subtree_cap_boundaries(self):
        seg = ['Repair Manual', 'Fasteners']
        # exactly at the cap -> still a stack
        self.assertEqual(self.get({'seg': seg, 'subtree': '1', 'max': str(N_BOLTS)})
                         .json()['mode'], 'stack')
        # one below -> cards
        self.assertEqual(self.get({'seg': seg, 'subtree': '1', 'max': str(N_BOLTS - 1)})
                         .json()['mode'], 'cards')
        # junk / zero / negative / huge all clamp into [1, 600] without error
        for mx, mode in (('abc', 'stack'), ('0', 'cards'), ('-5', 'cards'),
                         ('999999', 'stack')):
            with self.subTest(max=mx):
                r = self.get({'seg': seg, 'subtree': '1', 'max': mx})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()['mode'], mode)

    def test_subtree_restores_slash_in_relative_segments(self):
        body = self.get({'seg': 'Repair Manual', 'subtree': '1'}).json()
        self.assertEqual(body['mode'], 'stack')
        by_title = {i['title']: i for i in body['items']}
        self.assertEqual(by_title[SLASH_TITLE]['segments'], [SLASH_TITLE])
        self.assertEqual(by_title[OIL_TITLE]['segments'], ['Engine', OIL_TITLE])
        # 2 engine leaves + slash leaf + abbreviation leaf + 60 bolts
        self.assertEqual(body['count'], 4 + N_BOLTS)

    def test_subtree_of_a_leaf_contains_the_leaf_itself(self):
        body = self.get({'seg': ['Repair Manual', 'Engine', OIL_TITLE],
                         'subtree': '1'}).json()
        self.assertEqual([i['title'] for i in body['items']], [OIL_TITLE])
        self.assertEqual(body['items'][0]['segments'], [])

    # -- per-car title/content search (?q=) -------------------------------
    def test_search_ranks_title_matches_before_content_matches(self):
        r = self.get({'q': 'spec', 'limit': '3'})
        self.assertEqual(r.status_code, 200)
        res = r.json()
        self.assertEqual(len(res), 3)
        self.assertEqual(res[0]['title'], TORQUE_TITLE)          # title hit
        self.assertTrue(res[1]['title'].startswith('Bolt'))       # content hit
        self.assertEqual(res[0]['segments'], ['Repair Manual', 'Engine', TORQUE_TITLE])
        self.assertTrue(res[0]['is_leaf'])

    def test_search_is_case_insensitive_and_matches_content(self):
        res = self.get({'q': 'TIGHTEN'}).json()
        self.assertEqual([x['title'] for x in res], [TORQUE_TITLE])

    def test_blank_search_returns_empty_list(self):
        for q in ('', '   '):
            with self.subTest(q=q):
                r = self.get({'q': q})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json(), [])

    def test_search_limit_is_clamped(self):
        cases = {'1000': 50, '50': 50, '51': 50, '7': 7, '0': 1, '-3': 1,
                 'abc': 30, '': 30}
        for limit, expected in cases.items():
            with self.subTest(limit=limit):
                r = self.get({'q': 'Bolt', 'limit': limit})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(len(r.json()), expected)

    def test_search_quotes_and_injection_payloads_are_literal(self):
        self.assertEqual([x['title'] for x in self.get({'q': "O'Brien"}).json()],
                         [TORQUE_TITLE])
        self.assertEqual([x['title'] for x in self.get({'q': '"Torque"'}).json()],
                         [TORQUE_TITLE])
        for q in ("' OR '1'='1", '"; DROP TABLE nodes; --', "x'); DELETE FROM nodes; --"):
            with self.subTest(q=q):
                r = self.get({'q': q})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json(), [])
        # table still there and intact
        self.assertEqual(len(self.get({'q': 'Bolt', 'limit': '50'}).json()), 50)

    def test_search_excludes_404_artifacts(self):
        self.assertEqual(self.get({'q': 'Download .zip'}).json(), [])

    def test_search_percent_is_a_literal_not_a_wildcard(self):
        # Regression (fixed in this change): views.py:840 builds LIKE '%{q}%' without escaping, so a user
        # '%' matches every node (returns 30 arbitrary rows) instead of only the
        # one title containing a literal '%'. Same pattern at views.py:505.
        res = self.get({'q': '%'}).json()
        self.assertEqual([x['title'] for x in res], [OIL_TITLE])

    def test_search_underscore_is_a_literal_not_a_wildcard(self):
        # Regression (fixed in this change): views.py:840 — unescaped '_' in LIKE matches any single char,
        # so q='_' returns every node instead of only 'Oil 50% Change_Guide'.
        res = self.get({'q': '_'}).json()
        self.assertEqual([x['title'] for x in res], [OIL_TITLE])

    # -- href (cross-link) resolution ---------------------------------------
    def test_href_resolves_to_breadcrumb_segments(self):
        r = self.get({'href': '../pages/100.html'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'brand': 'Toyota', 'year': 2021, 'model': CAMRY,
                                    'segments': ['Repair Manual', 'Engine', OIL_TITLE]})

    def test_href_unknown_file_is_404(self):
        r = self.get({'href': 'pages/999.html'})
        self.assertEqual(r.status_code, 404)

    def test_href_lookup_is_scoped_to_this_car(self):
        # pages/100.html also exists in Supra's DB; Bob must not resolve it via Camry
        r = self.c.get(self.url, {'href': 'pages/100.html'}, **self.auth(self.bob))
        self.assertEqual(r.status_code, 403)

    def test_href_wildcards_do_not_match_other_pages(self):
        # Regression (fixed in this change): views.py:892-894 matches href LIKE '%/'+filename unescaped, so
        # '_00.html' resolves to pages/100.html and '%' to an arbitrary page
        # instead of 404.
        got = [self.get({'href': h}).status_code for h in ('_00.html', '%')]
        self.assertEqual(got, [404, 404])

    # -- orphan page (?page=) ---------------------------------------------
    def test_orphan_page_is_read_from_the_car_source_folder(self):
        r = self.get({'page': 'pages/orphan.html'})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['title'], 'Orphan Variant Labor')
        self.assertIn('/media/Camry%20LE/Z9.png', body['content'])
        self.assertIn('0.4 h', body['content'])

    def test_orphan_page_without_h1_uses_last_breadcrumb(self):
        r = self.get({'page': 'notitle.html'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['title'], 'Crumb B')

    def test_orphan_page_missing_is_404(self):
        self.assertEqual(self.get({'page': 'pages/nope.html'}).status_code, 404)

    def test_orphan_page_traversal_cannot_leave_source_folder(self):
        for page in ('../secret.html', '../../secret.html', 'pages/../../secret.html',
                     '/etc/passwd', '../../../../../../etc/passwd'):
            with self.subTest(page=page):
                r = self.get({'page': page})
                self.assertEqual(r.status_code, 404)
                self.assertNotIn('TOP SECRET', r.content.decode())
        r = self.get(raw='?page=%2e%2e%2fsecret.html')
        self.assertEqual(r.status_code, 404)
        self.assertNotIn('TOP SECRET', r.content.decode())

    def test_orphan_page_dot_dot_is_404_not_500(self):
        # Regression (fixed in this change): ?page=.. -> filename '..' -> views.py:689-693 picks
        # <src>/pages/.. (an existing directory) and read_text() raises
        # IsADirectoryError -> generic 500 instead of 404. No data leaks.
        self.assertEqual(self.get({'page': '..'}).status_code, 404)

    # -- structured spec --------------------------------------------------
    def test_spec_absent_is_null(self):
        r = self.get({'spec': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'spec': None})

    def test_spec_present_returns_full_data_to_entitled_user(self):
        VehicleSpec.objects.create(car=self.camry, builder_version='v3',
                                   data={'@type': 'Car', 'name': CAMRY,
                                         'engineOilCapacity': '4.8 L'},
                                   provenance={'engineOilCapacity': 'Repair Manual/Engine'})
        spec = self.get({'spec': '1'}).json()['spec']
        self.assertEqual(spec['data']['engineOilCapacity'], '4.8 L')
        self.assertEqual(spec['jsonld']['@context'], 'https://schema.org')
        self.assertEqual(spec['builder_version'], 'v3')
        self.assertIn('engineOilCapacity', spec['provenance'])


# ---------------------------------------------------------------------------
# /api/search/ (semantic search; LIKE fallback) + AI entry-point guards
# ---------------------------------------------------------------------------

class SearchAndAssistGuardTests(QAUsersMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.make_world()

    def setUp(self):
        self.make_rows()
        self.c = Client()

    def _no_index(self):
        # The semantic index is an external heavyweight artifact; force the
        # documented "index not built" path so the view's own LIKE fallback runs.
        from .rag import service
        return mock.patch.object(service, 'search', side_effect=FileNotFoundError('no index'))

    def test_empty_query_short_circuits_without_auth(self):
        r = self.c.get('/api/search/', {'q': '  '})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_signed_out_search_is_401(self):
        self.assertEqual(self.c.get('/api/search/', {'q': 'oil', 'car': CAMRY}).status_code, 401)

    def test_search_on_ungranted_car_is_403(self):
        r = self.c.get('/api/search/', {'q': 'oil', 'car': CAMRY, 'brand': 'Toyota'},
                       **self.auth(self.bob))
        self.assertEqual(r.status_code, 403)

    def test_like_fallback_returns_car_results_with_segments(self):
        with self._no_index():
            r = self.c.get('/api/search/', {'q': 'tighten', 'car': CAMRY},
                           **self.auth(self.alice))
        self.assertEqual(r.status_code, 200)
        res = r.json()
        self.assertEqual([x['title'] for x in res], [TORQUE_TITLE])
        self.assertEqual(res[0]['segments'], ['Repair Manual', 'Engine', TORQUE_TITLE])

    def test_like_fallback_limit_clamped(self):
        with self._no_index():
            for limit, n in (('500', 50), ('0', 1), ('x', 30)):
                with self.subTest(limit=limit):
                    r = self.c.get('/api/search/', {'q': 'Bolt', 'car': CAMRY, 'limit': limit},
                                   **self.auth(self.alice))
                    self.assertEqual(len(r.json()), n)

    def test_like_fallback_without_car_returns_nothing(self):
        with self._no_index():
            r = self.c.get('/api/search/', {'q': 'Bolt'}, **self.auth(self.alice))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_like_fallback_injection_payload_is_literal(self):
        with self._no_index():
            r = self.c.get('/api/search/', {'q': "' OR 1=1 --", 'car': CAMRY},
                           **self.auth(self.alice))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_assist_and_diagnose_validate_then_gate(self):
        for ep in ('/api/assist/', '/api/diagnose/'):
            with self.subTest(ep=ep):
                # missing query -> 400 (GET and POST, incl. malformed JSON body)
                self.assertEqual(self.c.get(ep).status_code, 400)
                self.assertEqual(self.c.post(ep, 'not json',
                                             content_type='application/json').status_code, 400)
                self.assertEqual(self.c.post(ep, '[1,2]',
                                             content_type='application/json').status_code, 400)
                # signed out -> 401
                self.assertEqual(self.c.get(ep, {'q': 'oil'}).status_code, 401)
                # another company's vehicle -> 403 before any retrieval runs
                r = self.c.post(ep, json.dumps({'query': 'oil', 'car': CAMRY}),
                                content_type='application/json', **self.auth(self.bob))
                self.assertEqual(r.status_code, 403)
                r = self.c.get(ep, {'q': 'oil', 'model': CAMRY, 'brand': 'Toyota'},
                               **self.auth(self.bob))
                self.assertEqual(r.status_code, 403)

    def test_feedback_endpoints_require_post_and_login(self):
        for ep in ('/api/assist/feedback/', '/api/feedback/rate/'):
            with self.subTest(ep=ep):
                self.assertEqual(self.c.get(ep).status_code, 405)
                self.assertEqual(self.c.post(ep, '{}', content_type='application/json')
                                 .status_code, 401)

    def test_admin_feedback_endpoints_reject_portal_users(self):
        hdr = self.auth(self.alice)
        self.assertEqual(self.c.get('/api/feedback/recent/').status_code, 401)
        self.assertEqual(self.c.get('/api/feedback/recent/', **hdr).status_code, 401)
        self.assertEqual(self.c.post('/api/feedback/pin/', '{}',
                                     content_type='application/json', **hdr).status_code, 401)


# ---------------------------------------------------------------------------
# /api/purchase-request/ input validation (public, unauthenticated endpoint)
# ---------------------------------------------------------------------------

class PurchaseRequestValidationTests(TestCase):
    URL = '/api/purchase-request/'
    PLAN = [{'role': 'after_sales_manager', 'department': 'گارانتی', 'count': 2}]

    def base(self, **kw):
        d = dict(brand='Toyota', model='Camry', year='2021', documents=['manual', 'bogus'],
                 company='QA Co', landline='021-1', mobile='۰۹۱۲ ۱۲۳-۴۵۶۷', reg_no='۱۲-۳۴',
                 employees_count=10, seat_plan=self.PLAN)
        d.update(kw)
        return d

    def post(self, body, raw=False):
        return self.client.post(self.URL, body if raw else json.dumps(body),
                                content_type='application/json')

    def test_method_and_body_shape(self):
        self.assertEqual(self.client.get(self.URL).status_code, 405)
        self.assertEqual(self.post('{bad', raw=True).status_code, 400)
        self.assertEqual(self.post('[]', raw=True).status_code, 400)

    def test_valid_request_normalises_mobile_and_filters_documents(self):
        r = self.post(self.base())
        self.assertEqual(r.status_code, 200, r.content)
        pr = PurchaseRequest.objects.get(id=r.json()['id'])
        self.assertEqual(pr.mobile, '09121234567')
        self.assertEqual(pr.documents, ['manual'])
        self.assertEqual(pr.seats_count, 2)

    def test_rejections(self):
        cases = {
            'bad mobile': self.base(mobile='12345'),
            'no documents': self.base(documents=['bogus']),
            'missing model': self.base(model='  '),
            'seats mismatch': self.base(seats_count=5),
            'demo multi-seat': self.base(year='demo'),
            'no employees': self.base(employees_count=0),
            'missing company': self.base(company=''),
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.post(body).status_code, 400)
        self.assertFalse(PurchaseRequest.objects.exists())

    def test_one_live_request_per_registration_number(self):
        self.assertEqual(self.post(self.base()).status_code, 200)
        # same reg no written with ASCII digits and other separators -> duplicate
        r = self.post(self.base(reg_no='12 34'))
        self.assertEqual(r.status_code, 409)
        # a rejected request no longer blocks
        PurchaseRequest.objects.update(status='rejected')
        self.assertEqual(self.post(self.base(reg_no='1234')).status_code, 200)

    def test_existing_customer_reg_no_is_refused(self):
        Company.objects.create(name='Existing', reg_no='5566')
        self.assertEqual(self.post(self.base(reg_no='55-66')).status_code, 409)


# ---------------------------------------------------------------------------
# nginx auth_request gate for paid media
# ---------------------------------------------------------------------------

class MediaAuthTests(QAUsersMixin, TestCase):
    URL = '/api/media-auth/'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.make_world()

    def setUp(self):
        self.make_rows()
        self.c = Client()

    def ask(self, uri, user=None):
        hdr = self.auth(user) if user else {}
        return self.c.get(self.URL, HTTP_X_ORIGINAL_URI=uri, **hdr).status_code

    def test_signed_out_is_401(self):
        self.assertEqual(self.ask(f'/kg-api/media/{quote(CAMRY)}/A1.png'), 401)
        self.assertEqual(self.ask('/kg-api/media/_parts_assets/x.gif'), 401)

    def test_entitled_user_gets_204_by_car_name(self):
        self.assertEqual(self.ask(f'/kg-api/media/{quote(CAMRY)}/A1.png', self.alice), 204)
        # query string must not confuse the folder parse
        self.assertEqual(self.ask(f'/kg-api/media/{quote(CAMRY)}/A1.png?v=2', self.alice), 204)

    def test_other_company_gets_403_by_car_name(self):
        self.assertEqual(self.ask(f'/kg-api/media/{quote(CAMRY)}/A1.png', self.bob), 403)
        self.assertEqual(self.ask(f'/kg-api/media/{quote(SUPRA)}/A1.png', self.alice), 403)

    def test_car_is_also_recognised_by_db_stem(self):
        stem = self.camry_db.stem            # 'camry_le'
        self.assertEqual(self.ask(f'/kg-api/media/{stem}/A1.png', self.bob), 403)
        self.assertEqual(self.ask(f'/kg-api/media/{stem}/A1.png', self.alice), 204)

    def test_partial_stem_does_not_match_a_car(self):
        # 'camry' is a substring of the db path but not the stem: no car -> login only
        self.assertEqual(self.ask('/kg-api/media/camry/A1.png', self.bob), 204)

    def test_shared_underscore_folders_need_login_only(self):
        self.assertEqual(self.ask('/kg-api/media/_parts_assets/x.gif', self.carol), 204)

    def test_foreign_prefix_is_refused(self):
        # Only /kg-api/media/ URIs carry a car folder; anything else is not a
        # media request the gate can judge, so it fails closed.
        self.assertEqual(self.ask(f'/media/{quote(CAMRY)}/A1.png', self.bob), 403)
        self.assertEqual(self.ask('/kg-api/media/../api/health/', self.alice), 403)

    def test_dot_segments_cannot_bypass_the_car_check(self):
        # Regression (fixed in this change): mediaauth._folder (mediaauth.py:19-23) takes the first segment
        # of the RAW X-Original-URI ($request_uri, ops/nginx/kgkg.conf:120)
        # without resolving dot-segments. nginx normalises '/_x/../CAR/' to
        # '/CAR/' before `alias` serves the file, but the gate sees folder '_x'
        # (or an unknown folder / empty segment) and answers 204 -> any logged-in
        # user can fetch another company's paid images.
        cam = quote(CAMRY)
        uris = (f'/kg-api/media/_parts_assets/../{cam}/A1.png',
                f'/kg-api/media/_parts_assets/%2e%2e/{cam}/A1.png',
                f'/kg-api/media/nonexistent/../{cam}/A1.png',
                f'/kg-api/media//{cam}/A1.png')
        self.assertEqual([self.ask(u, self.bob) for u in uris], [403] * len(uris))


# ---------------------------------------------------------------------------
# Parts catalog (/api/parts/<brand>/<year>/<model>/)
# ---------------------------------------------------------------------------

class PartsCatalogTests(QAUsersMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.make_world()
        cls.parts_dir = TMP / 'parts_wh'
        cls.parts_dir.mkdir(exist_ok=True)
        build_parts_db(cls.parts_dir / f'{CAMRY_PARTS}.db')
        build_parts_db(cls.parts_dir / 'Supra GR (Parts 2020).db', labels=False,
                       meta='{not json')
        build_parts_db(cls.parts_dir / 'Empty (Parts 2021).db', frames=False)
        build_parts_db(cls.parts_dir / 'Broken (Parts 2021).db', broken=True)
        cls._ovr = override_settings(KG_PARTS_DIR=str(cls.parts_dir))
        cls._ovr.enable()

    @classmethod
    def tearDownClass(cls):
        cls._ovr.disable()
        super().tearDownClass()

    def setUp(self):
        self.make_rows()
        self.c = Client()
        mk = lambda name, year=2021: Car.objects.create(  # noqa: E731
            brand_name='Toyota', car_name=name, year=year, db_address='')
        self.pcar = mk(CAMRY_PARTS)
        self.legacy = mk('Supra GR (Parts 2020)', 2020)
        self.empty = mk('Empty (Parts 2021)')
        self.broken = mk('Broken (Parts 2021)')
        self.unbuilt = mk('Prius (Parts 2021)')
        # decoys for related-catalog matching: shorter trim and a different trim
        self.decoy_short = mk('Camry (Parts 2021)')
        self.decoy_lex = mk('Camry LEX (Parts 2021)')
        for car in (self.pcar, self.legacy, self.empty, self.broken, self.unbuilt,
                    self.decoy_short):
            CompanyCarAccess.objects.create(company=self.co_a, car=car, documents=['parts'])
            UserCarAccess.objects.create(user=self.alice, car=car, documents=['parts'])
        self.hdr = self.auth(self.alice)

    def url(self, car):
        return f'/api/parts/{quote(car.brand_name)}/{car.year}/{quote(car.car_name)}/'

    def get(self, car, params=None, user=None):
        hdr = self.auth(user) if user else self.hdr
        return self.c.get(self.url(car), params or {}, **hdr)

    # -- gating -----------------------------------------------------------
    def test_anonymous_is_401_for_real_and_fake_vehicle_alike(self):
        real = self.c.get(self.url(self.pcar))
        fake = self.c.get('/api/parts/Toyota/2021/Nope%20(Parts%202021)/')
        self.assertEqual((real.status_code, fake.status_code), (401, 401))
        self.assertEqual(real.json(), fake.json())

    def test_unknown_vehicle_for_signed_in_user_is_404(self):
        r = self.c.get('/api/parts/Toyota/2021/Nope%20(Parts%202021)/', **self.hdr)
        self.assertEqual(r.status_code, 404)

    def test_other_company_is_403(self):
        self.assertEqual(self.get(self.pcar, user=self.bob).status_code, 403)

    def test_manual_only_layer_is_403(self):
        UserCarAccess.objects.filter(user=self.alice, car=self.pcar).update(documents=['manual'])
        self.assertEqual(self.get(self.pcar).status_code, 403)

    def test_company_scope_caps_user_layers(self):
        # user row says parts, but the company bought only the manual layer
        CompanyCarAccess.objects.filter(company=self.co_a, car=self.pcar).update(
            documents=['manual'])
        self.assertEqual(self.get(self.pcar).status_code, 403)

    def test_manual_vehicle_points_at_matching_catalog_only(self):
        r = self.get(self.camry)
        self.assertEqual(r.status_code, 404)
        body = r.json()
        self.assertEqual(body['error'], 'no_parts_catalog')
        # exact trim wins; 'Camry' (shorter) and 'Camry LEX' (other trim) do not
        self.assertEqual(body['related'],
                         [{'brand': 'Toyota', 'model': CAMRY_PARTS, 'year': 2021}])

    def test_related_catalogs_hide_ungranted_ones(self):
        UserCarAccess.objects.filter(user=self.alice, car=self.pcar).delete()
        r = self.get(self.camry)
        self.assertEqual(r.json()['related'], [])

    def test_granted_but_unbuilt_parts_vehicle_is_404(self):
        r = self.get(self.unbuilt)
        self.assertEqual(r.status_code, 404)
        self.assertIn('not available', r.json()['error'])

    def test_empty_catalog_is_404(self):
        r = self.get(self.empty)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()['error'], 'parts catalog empty')

    def test_corrupt_catalog_is_503_not_500(self):
        r = self.get(self.broken)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()['error'], 'parts catalog unavailable')

    # -- root / frames ----------------------------------------------------
    def test_root_lists_frames_with_flagged_default(self):
        r = self.get(self.pcar)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([f['code'] for f in body['frames']], ['F1', 'F2'])
        self.assertEqual(body['default_frame'], 'F2')          # is_default, not first
        self.assertEqual(body['counts'], {'groups': 2, 'parts': 4})
        self.assertEqual(body['car'], {'brand': 'Toyota', 'model': CAMRY_PARTS, 'year': 2021})
        self.assertIs(body['frames'][1]['is_default'], True)

    def test_root_with_unparseable_meta_counts_is_empty(self):
        r = self.get(self.legacy)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['counts'], {})

    # -- walking ----------------------------------------------------------
    def test_unknown_cfg_is_404(self):
        for cfg in ('NOPE', "F1' OR '1'='1", 'f1'):
            with self.subTest(cfg=cfg):
                self.assertEqual(self.get(self.pcar, {'cfg': cfg}).status_code, 404)

    def test_top_level_groups_of_a_frame(self):
        nodes = self.get(self.pcar, {'cfg': 'F1'}).json()
        self.assertEqual([n['title'] for n in nodes], ['Engine', 'Orphan'])
        self.assertFalse(nodes[0]['is_leaf'])
        self.assertTrue(all(n['content'] is None and n['href'] is None for n in nodes))

    def test_walk_to_leaf_payload(self):
        r = self.get(self.pcar, {'cfg': 'F1', 'seg': ['Engine', 'Oil Filter']})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Cache-Control'], 'private, max-age=300')
        body = r.json()
        self.assertTrue(body['leaf'])
        self.assertEqual(body['group']['path_titles'], ['Engine', 'Oil Filter'])
        self.assertEqual(body['group']['category_fa'], 'موتور')
        sec = body['sections'][0]
        self.assertEqual([p['pn'] for p in sec['parts']],
                         ['90915-YZZD1', '90915-YZZD1', '0888680000'])
        self.assertTrue(sec['parts'][2]['is_xref'])
        self.assertEqual(sec['labels'], [{'code': '15600', 'x': 0.1, 'y': 0.2,
                                          'w': 0.05, 'h': 0.03, 'title': 'OIL FILTER'}])

    def test_leaf_on_db_without_label_table_has_no_hotspots(self):
        body = self.get(self.legacy, {'cfg': 'F1', 'seg': ['Engine', 'Oil Filter']}).json()
        self.assertTrue(body['leaf'])
        self.assertEqual(body['sections'][0]['labels'], [])

    def test_slash_title_and_intermediate_level(self):
        kids = self.get(self.pcar, {'cfg': 'F1', 'seg': 'Engine'}).json()
        self.assertEqual([k['title'] for k in kids], ['Oil Filter', 'Belt / Set'])
        self.assertTrue(all(k['is_leaf'] for k in kids))
        r = self.get(self.pcar, {'cfg': 'F1', 'seg': ['Engine', 'Belt / Set']})
        self.assertEqual(r.json()['sections'][0]['parts'][0]['qty_display'], '8')

    def test_walk_is_scoped_to_the_selected_frame(self):
        # 'Body Panel' exists only in F2
        self.assertEqual(self.get(self.pcar, {'cfg': 'F1', 'seg': 'Body Panel'}).status_code, 404)
        self.assertTrue(self.get(self.pcar, {'cfg': 'F2', 'seg': 'Body Panel'}).json()['leaf'])

    def test_bad_segments_are_404(self):
        for segs in (['Nope'], ['Engine', '..'], ['..', 'Engine'], ['Engine/Oil Filter'],
                     ["' OR 1=1 --"]):
            with self.subTest(segs=segs):
                r = self.get(self.pcar, {'cfg': 'F1', 'seg': segs})
                self.assertEqual(r.status_code, 404)

    # -- search -----------------------------------------------------------
    def test_search_by_part_number_ignores_dashes_and_spaces(self):
        for q in ('90915-YZZD1', '90915 yzzd1', '90915YZZD1', '90915'):
            with self.subTest(q=q):
                res = self.get(self.pcar, {'cfg': 'F1', 'q': q}).json()['results']
                # the duplicate row of the same pn in the same group collapses
                self.assertEqual([h['pn'] for h in res], ['90915-YZZD1'])
                self.assertEqual(res[0]['path_titles'], ['Engine', 'Oil Filter'])

    def test_search_by_english_and_persian_name(self):
        res = self.get(self.pcar, {'cfg': 'F1', 'q': 'v-ribbed'}).json()['results']
        self.assertEqual([h['pn'] for h in res], ['9091602680'])
        res = self.get(self.pcar, {'cfg': 'F1', 'q': 'فیلتر'}).json()['results']
        self.assertEqual([h['pn'] for h in res], ['90915-YZZD1'])

    def test_search_is_scoped_to_frame(self):
        self.assertEqual(self.get(self.pcar, {'cfg': 'F1', 'q': 'PANEL'}).json()['results'], [])
        self.assertEqual(len(self.get(self.pcar, {'cfg': 'F2', 'q': 'PANEL'})
                             .json()['results']), 1)

    def test_search_length_boundaries(self):
        body = self.get(self.pcar, {'cfg': 'F1', 'q': 'b'}).json()
        self.assertEqual(body, {'query': 'b', 'results': []})        # < 2 chars
        body = self.get(self.pcar, {'cfg': 'F1', 'q': 'x' * 200}).json()
        self.assertEqual(len(body['query']), 80)                     # clamped to 80
        self.assertEqual(body['results'], [])

    def test_search_quotes_and_injection_are_literal(self):
        for q in ("' OR '1'='1", '"; DROP TABLE part_rows; --'):
            with self.subTest(q=q):
                r = self.get(self.pcar, {'cfg': 'F1', 'q': q})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()['results'], [])
        self.assertEqual(len(self.get(self.pcar, {'cfg': 'F1', 'q': 'filter'})
                             .json()['results']), 1)

    def test_search_wildcards_are_literal(self):
        # Regression (fixed in this change): parts.py:258-270 interpolates q into LIKE without escaping:
        # q='%%' (or '__') matches every part row of the frame.
        got = [self.get(self.pcar, {'cfg': 'F1', 'q': q}).json()['results']
               for q in ('%%', '__')]
        self.assertEqual(got, [[], []])

    # -- admin summary ----------------------------------------------------
    def _admin(self):
        admin = PlatformAdmin.objects.create(username='qa_boss')
        admin.set_password('pw')
        admin.save()
        return {'HTTP_AUTHORIZATION': f'Bearer {AdminAuthToken.issue(admin).key}'}

    def test_admin_summary_gated(self):
        self.assertEqual(self.c.get('/api/admin/parts/').status_code, 401)
        self.assertEqual(self.c.get('/api/admin/parts/', **self.hdr).status_code, 401)

    def test_admin_summary_states(self):
        hdr = self._admin()
        summary = self.parts_dir / 'report_summary.json'
        try:
            self.assertEqual(self.c.get('/api/admin/parts/', **hdr).json(),
                             {'available': False, 'vehicles': {}})
            summary.write_text('{oops', encoding='utf-8')
            self.assertFalse(self.c.get('/api/admin/parts/', **hdr).json()['available'])
            summary.write_text(json.dumps({'ok': True, 'vehicles': {
                CAMRY_PARTS: {'groups': 3}, 'Gone (Parts 1999)': {'groups': 1}}}),
                encoding='utf-8')
            body = self.c.get('/api/admin/parts/', **hdr).json()
            self.assertTrue(body['available'])
            self.assertEqual(body['vehicles'][CAMRY_PARTS]['car'],
                             {'id': self.pcar.id, 'year': 2021})
            self.assertIsNone(body['vehicles']['Gone (Parts 1999)']['car'])
        finally:
            summary.unlink(missing_ok=True)
