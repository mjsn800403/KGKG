"""Per-vehicle CSV exports: Labor Times (api/labortimes.py) and SST special
tools (api/sst.py). Both are paid manual content, so the views must apply the
same login + per-car gate as the manual pages; the builders must flatten the
manual's trees into the documented report shape.

The car DB here is a real SQLite file with the crawler's ``nodes`` schema and
a handful of leaves shaped like the fleet's (verified shapes are described in
the module docstrings).
"""
import csv
import io
import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.test import Client, TestCase

from . import cardb, labortimes, sst
from .models import ActivityLog, AuthToken, Car, Company, CompanyCarAccess, PortalUser, UserCarAccess

STEM = 'Camry LE'
LT_TABLE = ('<table><thead><tr><th>Applies To</th><th>Note</th><th>Standard Hours</th>'
            '<th>Warranty Hours</th><th>Skill Level</th></tr></thead><tbody>'
            '<tr><td>All</td><td>-</td><td>1.2</td><td>1.0</td><td>B</td></tr>'
            '<tr><td>AWD</td><td>w/ skid plate</td><td>1.5</td><td>1.3</td><td>B</td></tr>'
            '</tbody></table>')


def sst_table(*rows):
    body = ''.join(f'<tr><td><img src="../images/{img}"></td><td>{num}</td><td>{name}</td><td>-</td></tr>'
                   for img, num, name in rows)
    return f'<table>{body}</table>'


def build_db(path, labor=True, tools=True):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER, path TEXT,
        title TEXT, node_type TEXT, file_type TEXT, href TEXT, sort_order INTEGER,
        depth INTEGER, content TEXT, source_file TEXT)""")
    n = [0]

    def add(p, node_type='section', content=None):
        n[0] += 1
        con.execute('INSERT INTO nodes (id, path, title, node_type, content) VALUES (?,?,?,?,?)',
                    (n[0], p, p.rsplit('/', 1)[-1], node_type, content))

    add(STEM, 'car')
    if labor:
        add(f'{STEM}/Labor Times')
        add(f'{STEM}/Labor Times/Engine/Lubrication/Oil Pan/Replace', 'leaf', LT_TABLE)
        # inherited from a sibling trim: the wrapper must not become a category
        add(f'{STEM}/Labor Times/Other Variant/Brakes/Front/Pad ⁄ Rotor/Replace', 'leaf', LT_TABLE)
        add(f'{STEM}/Labor Times/Body/Hood/Hood/Adjust', 'leaf', '<p>known missing</p>')
    if tools:
        root = f'{STEM}/Repair and Diagnosis'
        # The same tool on two systems, and a kit with a component.
        add(f'{root}/Brakes/Brake Caliper/SST [11⁄2021 - ]/SST [11⁄2021 - ]', 'leaf',
            sst_table(('t1.png', '09023-00101', 'Union Nut Wrench'),
                      ('k1.svg', '09890-47010', 'Anti-Static Mat Set'),
                      ('k2.png', '(09891-04020)', 'Wrist Band')))
        # same system, later date window: must not list the system twice
        add(f'{root}/Brakes/Brake Caliper/SST [03⁄2023 - ]/SST [03⁄2023 - ]', 'leaf',
            sst_table(('t1.png', '09023-00101', 'Union Nut Wrench')))
        add(f'{root}/Engine/Engine Mechanical (Preparation)/SST [11⁄2021 - ]', 'leaf',
            sst_table(('t1.png', '09023-00101', 'Union Nut Wrench'),
                      ('x.png', 'not-a-number', 'Unparseable row')))
    con.commit()
    con.close()


def rows(text):
    assert text.startswith('﻿'), 'BOM for Excel'
    return list(csv.reader(io.StringIO(text[1:])))


class BuilderTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp(prefix='kg_exports_'))
        cls.db = cls.tmp / 'car.db'
        build_db(cls.db)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()

    def conn(self):
        c = sqlite3.connect(self.db)
        self.addCleanup(c.close)
        return c

    def test_labor_times_flatten_to_one_row_per_table_row(self):
        out = rows(labortimes.build_csv(self.conn(), 'Camry LE', 'Toyota', 2021))
        self.assertEqual(out[0], labortimes.CSV_HEADER)
        body = out[1:]
        self.assertEqual(len(body), 5)                     # 2 + 2 table rows + 1 known-missing
        self.assertIn(['Toyota', 'Camry LE', '2021', 'Engine', 'Lubrication', 'Oil Pan', 'Replace',
                       'AWD', 'w/ skid plate', '1.5', '1.3', 'B'], body)
        brakes = [r for r in body if r[3] == 'Brakes']
        self.assertEqual(brakes[0][3:7], ['Brakes', 'Front', 'Pad / Rotor', 'Replace'])
        missing = [r for r in body if r[3] == 'Body']
        self.assertEqual(missing, [['Toyota', 'Camry LE', '2021', 'Body', 'Hood', 'Hood', 'Adjust',
                                    '', '', '', '', '']])

    def test_car_without_labor_times_yields_nothing(self):
        db = self.tmp / 'nolabor.db'
        build_db(db, labor=False)
        with sqlite3.connect(db) as c:
            self.assertIsNone(next(labortimes.iter_report_rows(c, 'X', 'Toyota', 2021), None))

    def test_sst_merges_tools_across_systems_and_keeps_kits_together(self):
        out = rows(sst.build_csv(self.conn(), 'Camry LE', 'Toyota', 2021,
                                 media_base='https://kg.example/kg-api/media/Camry LE/'))
        self.assertEqual(out[0], sst.CSV_HEADER)
        by_num = {r[3]: r for r in out[1:]}
        self.assertEqual(set(by_num), {'09023-00101', '09890-47010', '09891-04020'})
        wrench = by_num['09023-00101']
        self.assertEqual(wrench[7], '2')                   # used by two systems
        self.assertEqual(wrench[8], 'Brakes › Brake Caliper | Engine › Engine Mechanical')
        self.assertEqual(wrench[10], 'https://kg.example/kg-api/media/Camry LE/t1.png')
        self.assertEqual(by_num['09891-04020'][5], '09890-47010')   # component -> its kit
        self.assertTrue(by_num['09890-47010'][10].endswith('/k1.svg'))
        order = [r[3] for r in out[1:]]
        self.assertEqual(order.index('09891-04020'), order.index('09890-47010') + 1)
        self.assertCountEqual(wrench[9].split(' | '), ['11/2021 -', '03/2023 -'])  # each once

    def test_has_sst(self):
        self.assertTrue(sst.has_sst(self.conn()))
        db = self.tmp / 'nosst.db'
        build_db(db, tools=False)
        with sqlite3.connect(db) as c:
            self.assertFalse(sst.has_sst(c))
            self.assertEqual(sst.collect_tools(c), [])

    def test_download_filenames_are_safe(self):
        self.assertEqual(labortimes._sanitize_filename('Toyota_Camry LE (2024)/../x'),
                         'Toyota_Camry_LE__2024_____x')
        self.assertEqual(labortimes._sanitize_filename('///'), '___')
        self.assertEqual(labortimes._sanitize_filename(''), 'car')


class ExportViewTests(TestCase):
    """The views: same gate as manual pages, then the CSV."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp(prefix='kg_exports_view_'))
        build_db(cls.tmp / 'camry.db')
        build_db(cls.tmp / 'bare.db', labor=False, tools=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cardb.invalidate_ready_cache()
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        cardb.invalidate_ready_cache()
        self.c = Client()
        self.camry = Car.objects.create(brand_name='Toyota', car_name='Camry LE', year=2021,
                                        db_address=str(self.tmp / 'camry.db'))
        self.bare = Car.objects.create(brand_name='Toyota', car_name='Mirai', year=2021,
                                       db_address=str(self.tmp / 'bare.db'))
        self.ghost = Car.objects.create(brand_name='Toyota', car_name='Ghost', year=2021,
                                        db_address=str(self.tmp / 'missing.db'))
        co = Company.objects.create(name='Exports Co', active=True)
        other = Company.objects.create(name='Other Co', active=True)
        for car in (self.camry, self.bare, self.ghost):
            CompanyCarAccess.objects.create(company=co, car=car, documents=[])
        self.alice = PortalUser.objects.create(company=co, username='alice', password_hash='x',
                                               role='after_sales_specialist', active=True)
        for car in (self.camry, self.bare, self.ghost):
            UserCarAccess.objects.create(user=self.alice, car=car, documents=[])
        self.mallory = PortalUser.objects.create(company=other, username='mallory', password_hash='x',
                                                 role='after_sales_specialist', active=True)

    def get(self, kind, car, user=None, **params):
        h = {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(user).key}'} if user else {}
        return self.c.get(f'/api/{kind}/{car.brand_name}/{car.year}/{car.car_name}/', params, **h)

    def test_anonymous_is_401_even_for_unknown_cars(self):
        for kind in ('labor-times', 'sst'):
            self.assertEqual(self.get(kind, self.camry).status_code, 401)
            r = self.c.get(f'/api/{kind}/Nope/1999/Nothing/')
            self.assertEqual(r.status_code, 401)          # no existence oracle

    def test_another_company_is_403(self):
        for kind in ('labor-times', 'sst'):
            self.assertEqual(self.get(kind, self.camry, self.mallory).status_code, 403)

    def test_entitled_user_gets_csv_and_download_is_logged(self):
        r = self.get('labor-times', self.camry, self.alice)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Type'].startswith('text/csv'))
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn('Replace', r.content.decode('utf-8'))
        self.assertTrue(ActivityLog.objects.filter(user=self.alice, action='download_csv').exists())
        r = self.get('sst', self.camry, self.alice)
        self.assertEqual(r.status_code, 200)
        self.assertIn('09023-00101', r.content.decode('utf-8'))

    def test_sst_probe_answers_availability(self):
        self.assertEqual(self.get('sst', self.camry, self.alice, probe=1).json(), {'available': True})
        self.assertEqual(self.get('sst', self.bare, self.alice, probe=1).json(), {'available': False})

    def test_car_without_data_is_404_with_a_message_not_an_empty_csv(self):
        r = self.get('labor-times', self.bare, self.alice)
        self.assertEqual(r.status_code, 404)
        self.assertIn('Labor Times', r.content.decode('utf-8'))

    def test_unbuilt_and_unknown_cars_are_404(self):
        self.assertEqual(self.get('labor-times', self.ghost, self.alice).status_code, 404)
        h = {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(self.alice).key}'}
        self.assertEqual(self.c.get('/api/sst/Toyota/2021/Nothing/', **h).status_code, 404)

    def test_stale_year_segment_falls_back_to_the_car(self):
        h = {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(self.alice).key}'}
        for year in ('1999', 'latest'):
            r = self.c.get(f'/api/labor-times/toyota/{year}/camry le/', **h)
            self.assertEqual(r.status_code, 200, year)
