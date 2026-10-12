"""Tests for the operational layer: data quality, monitoring, cardb pooling."""
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from . import cardb, dataquality, monitoring
from .models import (
    Car, Company, CompanyCarAccess, DataQualityRun, PortalUser, SystemAlert,
    TrafficStat, UserCarAccess, VisitorSeen,
)


def make_car_db(path, stem, sections=('Brakes', 'Steering'), empty_sections=(),
                content='<p>procedure</p>'):
    """Minimal but schema-faithful per-car DB for tests."""
    con = sqlite3.connect(str(path))
    con.execute("""CREATE TABLE nodes (
        id TEXT PRIMARY KEY, parent_id TEXT, path TEXT NOT NULL,
        title TEXT NOT NULL, node_type TEXT, file_type TEXT, href TEXT,
        source_file TEXT, sort_order INTEGER NOT NULL DEFAULT 0,
        depth INTEGER NOT NULL DEFAULT 0, root_order INTEGER,
        content TEXT, updated_at TEXT)""")
    rows = [('r0', None, stem, stem, None, None, 0, 0, None),
            ('r1', 'r0', f'{stem}/Repair and Diagnosis', 'Repair and Diagnosis',
             'root', None, 0, 1, None)]
    for i, sec in enumerate(tuple(sections) + tuple(empty_sections)):
        sid = f's{i}'
        rows.append((sid, 'r1', f'{stem}/Repair and Diagnosis/{sec}', sec,
                     'root', None, i, 2, None))
        if sec not in empty_sections:
            rows.append((f'l{i}', sid, f'{stem}/Repair and Diagnosis/{sec}/Page',
                         'Page', 'leaf', 'end_path', 0, 3, content))
    con.executemany(
        'INSERT INTO nodes (id, parent_id, path, title, node_type, file_type,'
        ' sort_order, depth, content) VALUES (?,?,?,?,?,?,?,?,?)', rows)
    con.commit()
    con.close()


class DataQualityUnitTests(TestCase):
    def test_normalize_section(self):
        self.assertEqual(dataquality.normalize_section('Drivelines and Axles'),
                         'drivelines & axles')
        self.assertEqual(dataquality.normalize_section('  Drivelines  &  Axles '),
                         'drivelines & axles')

    def test_expected_sections_powertrain_aware(self):
        gas = dataquality.expected_sections('4Runner SR5, 4WD')
        self.assertIn('engine mechanical', gas)
        self.assertNotIn('hybrid/electric powertrain', gas)
        hybrid = dataquality.expected_sections('Corolla Cross Hybrid SE')
        self.assertIn('hybrid/electric powertrain', hybrid)
        self.assertIn('engine mechanical', hybrid)     # hybrids have engines
        lexus_hybrid = dataquality.expected_sections('NX 350h')
        self.assertIn('hybrid/electric powertrain', lexus_hybrid)
        ev = dataquality.expected_sections('bZ4X Nightshade')
        self.assertNotIn('engine mechanical', ev)
        self.assertIn('hybrid/electric powertrain', ev)

    def test_audit_vehicle_db_sections_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            p1 = Path(td) / 'Car A.db'
            p2 = Path(td) / 'Car A (1).db'
            p3 = Path(td) / 'Car B.db'
            # The real duplicate pattern: the FILE gets "(1)" appended on a
            # double upload, but the tree inside still carries the original
            # root path. Fingerprints must match anyway.
            make_car_db(p1, 'Car A')
            make_car_db(p2, 'Car A')
            make_car_db(p3, 'Car B', sections=('Brakes',))  # different
            a, a1, b = (dataquality.audit_vehicle_db(p) for p in (p1, p2, p3))
            self.assertEqual(a['integrity'], 'ok')
            self.assertEqual([s['normalized'] for s in a['sections']],
                             ['brakes', 'steering'])
            self.assertEqual(a['fingerprint'], a1['fingerprint'])   # stem-independent
            self.assertNotEqual(a['fingerprint'], b['fingerprint'])

    def test_audit_vehicle_db_flags_corrupt(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'Broken.db'
            p.write_bytes(b'SQLite format 3\x00' + b'\x00' * 64)  # truncated garbage
            info = dataquality.audit_vehicle_db(p)
            self.assertIsNotNone(info['error'])


class DataQualityFleetTests(TestCase):
    """run_audit + remediate against a temp warehouse."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.wh = Path(self._td.name) / 'warehouse'
        self.media = Path(self._td.name) / 'media'
        self.wh.mkdir()
        self.media.mkdir()
        make_car_db(self.wh / 'NX Test FWD.db', 'NX Test FWD')
        make_car_db(self.wh / 'NX Test FWD (1).db', 'NX Test FWD (1)')
        (self.media / 'NX Test FWD').mkdir()
        (self.media / 'NX Test FWD (1)').mkdir()
        (self.wh / 'Broken Car.db').write_bytes(b'\x00' * 128)

        self.keep = Car.objects.create(brand_name='Lexus', car_name='NX Test FWD',
                                       year=2025, db_address='./Database_warehouse/NX Test FWD.db')
        self.dup = Car.objects.create(brand_name='Lexus', car_name='NX Test FWD (1)',
                                      year=2025, db_address='./Database_warehouse/NX Test FWD (1).db')
        company = Company.objects.create(name='co')
        self.user = PortalUser.objects.create(company=company, username='u1',
                                              role='after_sales_specialist',
                                              password_hash='x')
        # A grant on the duplicate AND one on the original (tests both the
        # repoint and the collision-skip path).
        UserCarAccess.objects.create(user=self.user, car=self.dup)
        CompanyCarAccess.objects.create(company=company, car=self.dup)
        CompanyCarAccess.objects.create(company=company, car=self.keep)

        patches = [
            mock.patch.object(dataquality.config, 'WAREHOUSE_DIR', self.wh),
            mock.patch.object(dataquality.config, 'INDEX_DB', self.wh / '_rag' / 'none.db'),
            mock.patch.object(dataquality.config, 'DIAG_DIR', self.wh / '_rag' / 'diag'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self._settings = override_settings(MEDIA_ROOT=self.media)
        self._settings.enable()
        self.addCleanup(self._settings.disable)
        self.addCleanup(self._td.cleanup)

    def test_audit_detects_duplicate_and_corrupt(self):
        summary, vehicles, _ = dataquality.run_audit(fix=False)
        self.assertEqual(summary['total_dbs'], 3)
        self.assertEqual(len(summary['duplicates']), 1)
        self.assertEqual(summary['duplicates'][0]['keep'], 'NX Test FWD')
        self.assertEqual(summary['duplicates'][0]['remove'], ['NX Test FWD (1)'])
        by_stem = {v['stem']: v for v in vehicles}
        self.assertEqual(by_stem['Broken Car']['status'], 'corrupt')
        self.assertEqual(by_stem['NX Test FWD (1)']['status'], 'duplicate')

    def test_remediate_merges_duplicate_and_quarantines(self):
        summary, vehicles, actions = dataquality.run_audit(fix=True)
        # Duplicate catalog row is gone; grants moved to the original.
        self.assertFalse(Car.objects.filter(car_name='NX Test FWD (1)').exists())
        self.assertTrue(UserCarAccess.objects.filter(
            user=self.user, car=self.keep).exists())
        # Company already had the original -> duplicate grant dropped, one row left.
        self.assertEqual(CompanyCarAccess.objects.filter(car=self.keep).count(), 1)
        # Files moved to quarantine, not deleted.
        q = self.wh / '_quarantine'
        self.assertTrue((q / 'NX Test FWD (1).db').exists())
        self.assertTrue((q / 'Broken Car.db').exists())
        self.assertFalse((self.wh / 'NX Test FWD (1).db').exists())
        # Original untouched and still cataloged.
        self.assertTrue((self.wh / 'NX Test FWD.db').exists())
        self.assertTrue(Car.objects.filter(car_name='NX Test FWD').exists())


class CardbTests(TestCase):
    def test_pooling_and_reopen_on_replace(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'x.db'
            make_car_db(p, 'X')
            c1 = cardb.connect(p)
            c2 = cardb.connect(p)
            self.assertIs(c1, c2)
            time.sleep(0.01)
            make_car_db(Path(td) / 'tmp.db', 'X2', sections=('Brakes',))
            os.replace(Path(td) / 'tmp.db', p)   # file swapped underneath
            c3 = cardb.connect(p)
            self.assertIsNot(c1, c3)

    def test_breadcrumbs_match_old_walk(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'x.db'
            make_car_db(p, 'X', sections=('Brakes',))
            conn = cardb.connect(p)
            row = conn.execute("SELECT id FROM nodes WHERE title='Page'").fetchone()
            self.assertEqual(cardb.breadcrumbs(conn, row['id']),
                             ['Repair and Diagnosis', 'Brakes', 'Page'])


class MonitoringTests(TestCase):
    def test_endpoint_grouping(self):
        cases = {
            '/api/assist/': 'assist',
            '/api/admin/users/3/': 'admin',
            '/media/Car/img.svg': 'media',
            '/': 'brands',
            '/Toyota/2025/Camry LE/': 'catalog',
            '/api/health/': 'health',
        }
        for path, expected in cases.items():
            self.assertEqual(monitoring.endpoint_group(path), expected, path)

    def test_flush_writes_rollups(self):
        rf = mock.Mock(path='/api/assist/', method='POST',
                       META={'REMOTE_ADDR': '10.0.0.9'})
        # Keep the periodic background flush quiescent — this test flushes
        # explicitly (a daemon thread would race the in-memory test DB) —
        # and start from empty aggregates (other tests' Client requests feed
        # the same module-level state through the middleware).
        monitoring._LAST_FLUSH = time.time()
        with monitoring._LOCK:
            monitoring._AGG.clear()
            monitoring._VISITORS.clear()
        monitoring.record_request(rf, 200, 12.5)
        monitoring.record_request(rf, 500, 30.0)
        monitoring.flush_metrics()
        stat = TrafficStat.objects.get(endpoint='assist', method='POST')
        self.assertEqual(stat.requests, 2)
        self.assertEqual(stat.errors_5xx, 1)
        self.assertEqual(VisitorSeen.objects.count(), 1)

    def test_alert_opens_and_resolves(self):
        with mock.patch.object(monitoring, 'DISK_WARN_PCT', 0.0), \
             mock.patch.object(monitoring, 'DISK_CRIT_PCT', 0.0):
            result = monitoring.evaluate_alerts()
        self.assertIn('disk_high', result['open'])
        self.assertTrue(SystemAlert.objects.filter(key='disk_high', is_open=True).exists())
        # Second run with sane thresholds resolves it.
        with mock.patch.object(monitoring, 'DISK_WARN_PCT', 101.0), \
             mock.patch.object(monitoring, 'DISK_CRIT_PCT', 102.0):
            result = monitoring.evaluate_alerts()
        self.assertIn('disk_high', result['resolved'])
        self.assertFalse(SystemAlert.objects.filter(key='disk_high', is_open=True).exists())


class OpsEndpointTests(TestCase):
    def setUp(self):
        self.c = Client()

    def test_health_public(self):
        r = self.c.get('/api/health/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertTrue(body['db'])

    def test_admin_ops_endpoints_are_gated(self):
        for url in ('/api/admin/data-quality/', '/api/admin/system/',
                    '/api/admin/traffic/'):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 401, url)

    def _admin_headers(self):
        from .models import PlatformAdmin, AdminAuthToken
        admin = PlatformAdmin.objects.create(username='boss')
        admin.set_password('pw')
        admin.save()
        token = AdminAuthToken.issue(admin)
        return {'HTTP_AUTHORIZATION': f'Bearer {token.key}'}

    def test_data_quality_report_roundtrip(self):
        headers = self._admin_headers()
        r = self.c.get('/api/admin/data-quality/', **headers)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()['report'])
        DataQualityRun.objects.create(
            status='done', summary={'complete': 1}, vehicles=[{'stem': 'X'}],
            finished_at=timezone.now())
        r = self.c.get('/api/admin/data-quality/', **headers)
        self.assertEqual(r.json()['report']['summary']['complete'], 1)

    def test_system_and_traffic_views(self):
        headers = self._admin_headers()
        r = self.c.get('/api/admin/system/', **headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn('snapshot', r.json())
        r = self.c.get('/api/admin/traffic/?range=7', **headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn('totals', r.json())
