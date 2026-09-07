"""Tests for the parts-catalog ingest (partsingest) + serving (api/parts.py).

A synthetic mini-crawl (one frame, five groups) exercises the real pipeline
end-to-end into a temp warehouse; serving tests then hit the built artifact
through the HTTP layer with real grants. Run with the suite:
    KG_RL_DISABLE=1 python manage.py test api
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from django.core.cache import cache
from django.test import Client, TestCase

from . import cardb, partsingest
from .models import (AuthToken, Car, Company, CompanyCarAccess, PortalUser,
                     UserCarAccess)

FRAME = 'FR1'
PARTS_CAR = 'Corolla Cross LE (Parts 2022)'

TREEGRID = """<html><head><title>Groups | Toyota COROLLA CROSS FR1 | PartSouq</title></head>
<body><table>
<tr class="treegrid-1 treegrid-collapsed"><td><b>Service parts</b></td></tr>
<tr class="treegrid-2 treegrid-parent-1"><td><a href="https://x/vehicle?gid=2&amp;vid=0">Oil Filter</a></td></tr>
<tr class="treegrid-3 treegrid-parent-1"><td><a href="https://x/vehicle?gid=11">V-Ribbed Belt / Set</a></td></tr>
<tr class="treegrid-4"><td><a href="https://x/vehicle?gid=20">Alternator</a></td></tr>
<tr class="treegrid-5"><td><a href="https://x/vehicle?gid=30">Control Unit</a></td></tr>
<tr class="treegrid-6"><td><a href="https://x/vehicle?gid=31">Empty Group</a></td></tr>
</table></body></html>"""


def group_page(category, gid, sections):
    """sections: list of (figure_gif, caption, rows); rows = list of 6-tuples."""
    body = []
    for gif, caption, rows in sections:
        cid = f'zoom_container_{gid}{len(body)}'
        body.append(f'<h2>{caption}</h2>')
        body.append(f'<div id="{cid}"><img class="drag" data-container="{cid}" '
                    f'alt="TOYOTA COROLLA CROSS {FRAME} {caption}" '
                    f'src="../../../_assets/{gif}"/></div>')
        trs = []
        for (pn, name, code, note, qty, rng) in rows:
            trs.append(
                f'<tr class="part-search-tr"><td class="oem">'
                f'<a href="https://partsouq.com/en/search/all?q={pn}&amp;qty=1">{pn}</a></td>'
                f'<td>{name}</td><td class="codeonimage">{code}</td>'
                f'<td>{note}</td><td>{qty}</td><td>{rng}</td></tr>')
        body.append(
            '<table><thead><tr><th>Number</th><th>Name</th><th>Code</th>'
            '<th>Note</th><th>Quantity</th><th>Range</th></tr></thead>'
            '<tbody>' + ''.join(trs) + '</tbody></table>')
    return (f'<html><head><title>{category} | Toyota COROLLA CROSS {FRAME} | '
            f'Parts Catalogs | PartSouq</title>'
            f'<meta property="og:url" content="https://partsouq.com/en/catalog/'
            f'genuine/parts?c=Toyota&amp;vid=0&amp;gid={gid}"/></head>'
            f'<body>{"".join(body)}</body></html>')


CF_PAGE = '<html><head><title>Just a moment...</title></head><body>x</body></html>'


def make_crawl(root):
    """Synthetic crawl tree under ``root``. Returns the src dir path."""
    src = Path(root)
    dl = src / 'downloads'
    (dl / '_assets').mkdir(parents=True)
    for gif in ('aabbccdd_1502A.gif', 'e1e1e1e1_ALT1.gif', 'f1f1f1f1_VRB1.gif'):
        (dl / '_assets' / gif).write_bytes(b'GIF89a-test')
    fdir = dl / FRAME
    (fdir / '_groups').mkdir(parents=True)
    (fdir / 'index.html').write_text(
        f'<html><head><title>Engine/Fuel/Tool | Toyota COROLLA CROSS {FRAME} '
        f'| PartSouq</title></head><body></body></html>', encoding='utf-8')
    (fdir / '_groups' / 'index.html').write_text(TREEGRID, encoding='utf-8')

    pages = {
        'Oil Filter': group_page('Engine/Fuel/Tool', 2, [
            ('aabbccdd_1502A.gif', 'OIL FILTER', [
                ('9091503001', 'OIL FILTER', '15600', 'M20AFKS..FR1', '01', '10.2023 - ...'),
                # xref row: no name, callout == pn, no qty
                ('9091530002', '', '9091530002', '', '', ''),
                # EPC "as required" quantity — legitimate, must be published
                ('0888680000', 'SEALANT, FIPG', '15690', '', 'X', ''),
            ])]),
        'V-Ribbed Belt _ Set': group_page('Engine/Fuel/Tool', 11, [
            ('f1f1f1f1_VRB1.gif', 'V-RIBBED BELT', [
                ('9091602680', 'BELT, V-RIBBED', '90916', '１２Ｖ', 'X8', ''),
            ])]),
        'Alternator': group_page('Engine/Fuel/Tool', 20, [
            ('e1e1e1e1_ALT1.gif', 'ALTERNATOR ASSY', [
                ('2706024080', 'ALTERNATOR ASSY', '27020', 'M20AFKS..FR1', '01', '10.2023 - ...'),
                ('9982700100', 'BOLT NO QTY', '27021', '', '', ''),   # excluded: missing qty
            ]),
            ('99999999_MISSING.gif', 'ALTERNATOR BRACKET', [
                ('2711111111', 'BRACKET', '27111', '', '02', ''),     # pruned: image missing
            ])]),
        'Control Unit': CF_PAGE,
        'Empty Group': group_page('Electrical', 31, []),
    }
    for d, html in pages.items():
        (fdir / '_groups' / d).mkdir()
        (fdir / '_groups' / d / 'index.html').write_text(html, encoding='utf-8')

    (src / 'toyotaepc_frames.csv').write_text(
        'frame,region,model_dir,model_name,year_seen,date_from,date_to,'
        'engine,transmission,steering,destination,grade\n'
        f'{FRAME},US,552410,Corolla Cross (US),2022,202109,202211,'
        'M20AF,CVT,LHD,,LE\n', encoding='utf-8')
    return src


def run_pipeline(src, backend_dir, report_dir):
    conn = partsingest.staging_conn(Path(report_dir) / 'staging.db')
    partsingest.stage_scan(conn, src, report_dir, log=lambda *a: None)
    partsingest.stage_parse(conn, src, jobs=1, log=lambda *a: None)
    stats = partsingest.stage_validate(conn, src, report_dir, log=lambda *a: None)
    partsingest.stage_build(conn, src, backend_dir, report_dir, log=lambda *a: None)
    summary = partsingest.stage_audit(conn, backend_dir, report_dir, log=lambda *a: None)
    return conn, stats, summary


class PartsParserUnitTests(unittest.TestCase):
    def test_sanitize_label_matches_crawler(self):
        self.assertEqual(partsingest.sanitize_label('V-Ribbed Belt / Set'),
                         'V-Ribbed Belt _ Set')
        self.assertEqual(partsingest.sanitize_label('Thermostat/ Gasket'),
                         'Thermostat_ Gasket')
        self.assertEqual(partsingest.sanitize_label('  a   b  '), 'a b')

    def test_classify_row(self):
        base = {'pn': '123', 'pn_display': '123', 'name_en': 'X',
                'callout': '9', 'qty_raw': '01', 'note': '', 'date_range': ''}
        qty, qd, xref, valid, reason = partsingest.classify_row(base)
        self.assertEqual((qty, qd, xref, valid), (1, '1', False, True))
        qty, qd, xref, valid, _ = partsingest.classify_row({**base, 'qty_raw': 'X8'})
        self.assertEqual((qty, qd, valid), (8, '8', True))
        # 'X' alone = EPC "as required" — a published quantity, not missing
        qty, qd, xref, valid, reason = partsingest.classify_row({**base, 'qty_raw': 'X'})
        self.assertEqual((qty, qd, valid, reason), (None, 'X', True, None))
        _, _, xref, valid, reason = partsingest.classify_row(
            {**base, 'name_en': '', 'qty_raw': '', 'callout': '123'})
        self.assertTrue(xref)
        self.assertTrue(valid)
        _, _, xref, valid, reason = partsingest.classify_row({**base, 'qty_raw': ''})
        self.assertFalse(valid)
        self.assertEqual(reason, 'missing_qty')
        _, _, _, valid, reason = partsingest.classify_row({**base, 'name_en': ''})
        self.assertFalse(valid)
        self.assertEqual(reason, 'missing_name')

    def test_treegrid_parse(self):
        nodes = partsingest.parse_treegrid(TREEGRID)
        self.assertEqual(len(nodes), 6)
        byid = {n['tree_id']: n for n in nodes}
        self.assertFalse(byid[1]['is_leaf'])
        self.assertEqual(byid[2]['parent'], 1)
        self.assertEqual(byid[3]['label'], 'V-Ribbed Belt / Set')
        self.assertEqual(byid[3]['gid'], 11)
        self.assertTrue(all(byid[i]['is_leaf'] for i in (2, 3, 4, 5, 6)))

    def test_match_dirs_gid_collision(self):
        leaves = [
            {'tree_id': 1, 'label': 'Alarm System', 'gid': 100, 'is_leaf': True},
            {'tree_id': 2, 'label': 'Alarm System', 'gid': 1060, 'is_leaf': True},
        ]
        match = partsingest._match_dirs_to_leaves(
            leaves, ['Alarm System', 'Alarm System (gid 1060)'])
        self.assertEqual(match['Alarm System (gid 1060)'], 2)
        self.assertEqual(match['Alarm System'], 1)

    def test_load_fa_terms_reads_the_generated_envelope(self):
        """The generated store is {version, generated_at, count, entries,
        fa_terms} with entries as [en, fa] pairs — walking it as a flat mapping
        silently yields one junk entry and loses the whole dictionary."""
        with tempfile.TemporaryDirectory() as td:
            backend = Path(td) / 'backend'
            (backend / 'Database_warehouse' / '_rag').mkdir(parents=True)
            (backend / 'Database_warehouse' / '_rag' / 'terms_en_fa.json').write_text(
                json.dumps({'version': 1, 'generated_at': '2026-07-19T05:06:56+00:00',
                            'count': 2,
                            'entries': [['OIL FILTER', 'فیلتر روغن'],
                                        ['AIR CLEANER', 'فیلتر هوا']],
                            'fa_terms': ['فیلتر روغن']}, ensure_ascii=False),
                encoding='utf-8')
            terms = partsingest.load_fa_terms(backend)
        self.assertEqual(terms.get('oil filter'), 'فیلتر روغن')
        self.assertEqual(terms.get('air cleaner'), 'فیلتر هوا')
        self.assertNotIn('generated_at', terms)
        self.assertEqual(len(terms), 2)

    def test_page_with_no_catalog_body_is_not_ok(self):
        """A page truncated after </head> has 0 sections AND 0 tables; treating
        that as 'ok' would count it as imported and then drop it silently."""
        html = ('<html><head><title>Electrical | Toyota COROLLA CROSS FR1 | x'
                '</title><meta property="og:url" content="https://p/?gid=9"/>'
                '</head><body></body></html>')
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'x.html'
            p.write_text(html, encoding='utf-8')
            self.assertEqual(partsingest.parse_group_page(p)['status'], 'no_content')

    def test_group_page_mismatch_and_cf(self):
        bad = ('<html><head><title>Electrical | Toyota COROLLA CROSS FR1 | x'
               '</title></head><body>'
               '<table><thead><tr><th>Number</th><th>Name</th><th>Code</th>'
               '<th>Note</th><th>Quantity</th><th>Range</th></tr></thead>'
               '<tbody></tbody></table></body></html>')
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'x.html'
            p.write_text(bad, encoding='utf-8')
            out = partsingest.parse_group_page(p)
            self.assertEqual(out['status'], 'parse_error')  # 1 table, 0 sections
            p.write_text(CF_PAGE, encoding='utf-8')
            self.assertEqual(partsingest.parse_group_page(p)['status'], 'cloudflare')


class PartsPipelineTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp(prefix='kgparts_test_'))
        cls.src = make_crawl(cls.tmp / 'crawl')
        cls.backend = cls.tmp / 'backend'
        cls.backend.mkdir()
        cls.reports = cls.tmp / 'reports'
        cls.conn, cls.stats, cls.summary = run_pipeline(
            cls.src, cls.backend, cls.reports)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()

    def test_validate_stats(self):
        s = self.stats
        self.assertEqual(s['frames'], 1)
        self.assertEqual(s['tree_leaves'], 5)
        self.assertEqual(s['pages_cloudflare'], 1)
        self.assertEqual(s['rows_xref'], 1)
        self.assertEqual(s['rows_excluded'], 1)        # the missing-qty bolt
        self.assertEqual(s['sections_missing_image'], 1)

    def test_build_output_and_audit(self):
        vname = PARTS_CAR
        db = self.backend / 'Database_warehouse' / '_parts' / f'{vname}.db'
        self.assertTrue(db.is_file())
        self.assertTrue(self.summary['ok'], self.summary)
        v = self.summary['vehicles'][vname]
        # Control Unit (CF), Empty Group (no sections), Alternator sec2 (no
        # image) are pruned; 3 groups and 3 sections survive.
        self.assertEqual(v['groups'], 3)
        self.assertEqual(v['sections'], 3)
        self.assertEqual(v['rows'], 5)                 # 4 valid (incl. qty 'X') + 1 xref
        self.assertEqual(v['xref_rows'], 1)
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        roots = con.execute(
            "SELECT title FROM nodes WHERE depth=1 ORDER BY sort_order").fetchall()
        self.assertEqual([r['title'] for r in roots], ['Service parts', 'Alternator'])
        fa = con.execute(
            "SELECT name_fa FROM part_rows WHERE pn='9091503001'").fetchone()
        self.assertIsNotNone(fa)                        # column exists (value may be NULL)
        # NFKC applied to notes (fullwidth 12V -> ASCII)
        note = con.execute(
            "SELECT note FROM part_rows WHERE pn='9091602680'").fetchone()['note']
        self.assertEqual(note, '12V')
        con.close()
        # images copied for surviving sections only
        assets = {p.name for p in
                  (self.backend / 'static_warehouse' / '_parts_assets').glob('*.gif')}
        self.assertIn('aabbccdd_1502A.gif', assets)
        self.assertNotIn('99999999_MISSING.gif', assets)

    def test_catalog_stage_creates_hidden_car(self):
        created = partsingest.stage_catalog(self.conn, self.backend,
                                            log=lambda *a: None)
        self.assertEqual(len(created), 1)
        car = Car.objects.get(car_name=PARTS_CAR)
        self.assertEqual((car.brand_name, car.year, car.db_address),
                         ('Toyota', 2022, ''))
        # idempotent
        again = partsingest.stage_catalog(self.conn, self.backend,
                                          log=lambda *a: None)
        self.assertFalse(any(c['created'] for c in again))


class PartsServingTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp(prefix='kgparts_serve_'))
        cls.src = make_crawl(cls.tmp / 'crawl')
        cls.backend = cls.tmp / 'backend'
        cls.backend.mkdir()
        conn, _, _ = run_pipeline(cls.src, cls.backend, cls.tmp / 'reports')
        conn.close()
        os.environ['KG_PARTS_DIR'] = str(
            cls.backend / 'Database_warehouse' / '_parts')
        # a stand-in manual DB file for the "normal" car
        cls.manual_db = cls.tmp / 'manual.db'
        con = sqlite3.connect(cls.manual_db)
        con.execute('CREATE TABLE nodes (id TEXT, parent_id TEXT, path TEXT,'
                    'title TEXT, node_type TEXT, file_type TEXT, href TEXT,'
                    'sort_order INT, depth INT, content TEXT)')
        con.commit()
        con.close()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop('KG_PARTS_DIR', None)
        cardb.invalidate_ready_cache()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        cardb.invalidate_ready_cache()
        self.c = Client()
        self.parts_car = Car.objects.create(
            brand_name='Toyota', car_name=PARTS_CAR, year=2022, db_address='')
        self.manual_car = Car.objects.create(
            brand_name='Toyota', car_name='Corolla Cross LE',
            year=2023, db_address=str(self.manual_db))
        self.test_co = Company.objects.create(name='شرکت تست قطعات', is_demo=True)
        self.other_co = Company.objects.create(name='شرکت اصلی')
        CompanyCarAccess.objects.create(
            company=self.test_co, car=self.parts_car, documents=['parts'])
        CompanyCarAccess.objects.create(
            company=self.other_co, car=self.manual_car, documents=[])
        self.tester = PortalUser.objects.create(
            company=self.test_co, username='parts_tester',
            role='after_sales_manager')
        UserCarAccess.objects.create(
            user=self.tester, car=self.parts_car, documents=['parts'])
        self.other = PortalUser.objects.create(
            company=self.other_co, username='other_user',
            role='after_sales_specialist')
        UserCarAccess.objects.create(
            user=self.other, car=self.manual_car, documents=[])
        self.tok = AuthToken.issue(self.tester).key
        self.other_tok = AuthToken.issue(self.other).key

    def _url(self, car=None, **params):
        car = car or self.parts_car
        u = f'/api/parts/Toyota/{car.year}/{quote(car.car_name)}/'
        return u

    def test_parts_requires_auth_401(self):
        self.assertEqual(self.c.get(self._url()).status_code, 401)

    def test_anonymous_cannot_probe_which_parts_vehicles_exist(self):
        """Auth must be checked BEFORE the car is resolved, otherwise 401-vs-404
        tells an anonymous caller which hidden parts vehicles are real."""
        real = self.c.get(self._url())
        fake = self.c.get('/api/parts/Toyota/2022/No%20Such%20Vehicle%20(Parts)/')
        self.assertEqual(real.status_code, 401)
        self.assertEqual(fake.status_code, 401)
        self.assertEqual(real.json(), fake.json())

    def test_fleet_hides_parts_chip_without_the_parts_layer(self):
        ua = self.tester.car_accesses.get(car=self.parts_car)
        ua.documents = ['manual']
        ua.save()
        r = self.c.get('/api/auth/fleet/', HTTP_AUTHORIZATION=f'Bearer {self.tok}')
        rows = [i for i in r.json()['items'] if i['car_name'] == PARTS_CAR]
        # no parts layer -> no parts entry point advertised (and no manual DB
        # either, so the vehicle drops out of the fleet entirely)
        self.assertTrue(all(not i['has_parts'] for i in rows))

    def test_other_company_user_403(self):
        r = self.c.get(self._url(), HTTP_AUTHORIZATION=f'Bearer {self.other_tok}')
        self.assertEqual(r.status_code, 403)

    def test_forbidden_without_parts_layer(self):
        # granted the car, but only the manual layer -> parts endpoint stays 403
        ua = self.tester.car_accesses.get(car=self.parts_car)
        ua.documents = ['manual']
        ua.save()
        r = self.c.get(self._url(), HTTP_AUTHORIZATION=f'Bearer {self.tok}')
        self.assertEqual(r.status_code, 403)

    def test_root_frames_payload(self):
        r = self.c.get(self._url(), HTTP_AUTHORIZATION=f'Bearer {self.tok}')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['default_frame'], FRAME)
        self.assertEqual(len(data['frames']), 1)
        f = data['frames'][0]
        self.assertEqual((f['code'], f['grade'], f['region']), (FRAME, 'LE', 'US'))
        self.assertEqual(f['n_groups'], 3)

    def test_walk_and_leaf_shape(self):
        auth = {'HTTP_AUTHORIZATION': f'Bearer {self.tok}'}
        r = self.c.get(self._url(), {'cfg': FRAME}, **auth)
        self.assertEqual(r.status_code, 200)
        tops = r.json()
        self.assertEqual([n['title'] for n in tops], ['Service parts', 'Alternator'])
        self.assertFalse(tops[0]['is_leaf'])
        r = self.c.get(self._url(), {'cfg': FRAME, 'seg': 'Service parts'}, **auth)
        kids = r.json()
        self.assertEqual([n['title'] for n in kids],
                         ['Oil Filter', 'V-Ribbed Belt / Set'])
        r = self.c.get(self._url(),
                       {'cfg': FRAME, 'seg': ['Service parts', 'Oil Filter']}, **auth)
        leaf = r.json()
        self.assertTrue(leaf['leaf'])
        self.assertEqual(leaf['group']['category'], 'Engine/Fuel/Tool')
        self.assertEqual(len(leaf['sections']), 1)
        parts = leaf['sections'][0]['parts']
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0]['pn'], '9091503001')
        self.assertEqual(parts[0]['qty'], 1)
        self.assertEqual(parts[0]['qty_display'], '1')
        self.assertTrue(parts[1]['is_xref'])
        self.assertEqual(parts[2]['qty_display'], 'X')   # as-required quantity
        self.assertTrue(leaf['sections'][0]['image'].startswith('/media/_parts_assets/'))
        # slash-bearing title walks fine via ?seg=
        r = self.c.get(self._url(),
                       {'cfg': FRAME, 'seg': ['Service parts', 'V-Ribbed Belt / Set']},
                       **auth)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['leaf'])

    def test_unknown_cfg_404(self):
        r = self.c.get(self._url(), {'cfg': 'NOPE'},
                       HTTP_AUTHORIZATION=f'Bearer {self.tok}')
        self.assertEqual(r.status_code, 404)

    def test_public_catalog_hides_parts_car(self):
        brands = self.c.get('/').json()
        self.assertIn('Toyota', brands)                # the manual car is public
        names = [c['car_name'] for c in self.c.get('/Toyota/').json()]
        self.assertNotIn(PARTS_CAR, names)
        names_2022 = [c['car_name'] for c in self.c.get('/Toyota/2022/').json()]
        self.assertEqual(names_2022, [])

    def test_fleet_flags_and_backward_compat(self):
        r = self.c.get('/api/auth/fleet/', HTTP_AUTHORIZATION=f'Bearer {self.tok}')
        items = r.json()['items']
        self.assertEqual(len(items), 1)
        row = items[0]
        self.assertEqual(row['car_name'], PARTS_CAR)
        self.assertFalse(row['has_manual'])
        self.assertTrue(row['has_parts'])
        for k in ('brand_name', 'car_name', 'year'):
            self.assertIn(k, row)
        r = self.c.get('/api/auth/fleet/',
                       HTTP_AUTHORIZATION=f'Bearer {self.other_tok}')
        row = r.json()['items'][0]
        self.assertTrue(row['has_manual'])
        self.assertFalse(row['has_parts'])

    def test_manual_endpoint_404_for_parts_only_car(self):
        r = self.c.get(f'/Toyota/2022/{quote(PARTS_CAR)}/',
                       HTTP_AUTHORIZATION=f'Bearer {self.tok}')
        self.assertEqual(r.status_code, 404)

    def test_admin_parts_summary(self):
        os.environ['KG_ADMIN_TOKEN'] = 'test-admin-token'
        try:
            r = self.c.get('/api/admin/parts/',
                           HTTP_X_ADMIN_TOKEN='test-admin-token')
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertTrue(data['available'])
            self.assertIn(PARTS_CAR, data['vehicles'])
        finally:
            os.environ.pop('KG_ADMIN_TOKEN', None)
