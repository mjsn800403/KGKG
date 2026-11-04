"""KGTEC-14 (CodeQL py/stack-trace-exposure): no exception text, traceback or path may
leave the server through an admin endpoint, including text that an older version
already stored in the database (DataQualityRun, ZipPackage, ProcessingJob,
SystemAlert). Also pins the input handling of the admin access view (#44).

The tests mock the failing dependency with a recognisable marker (a /srv/secret
path, a private address, a traceback) and assert the marker never appears in a
response or in a stored error field. Background work is mocked; nothing is started.
"""
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from .models import (
    Car, Company, DataQualityRun, PortalUser, ProcessingJob, SystemAlert, UserCarAccess, ZipPackage,
)
from .test_adminops import AdminCase

LEAK_MARKERS = ('/srv/secret', 'Traceback', 'File "', '10.0.0.5', '.py"', 'password=')
OLD_TRACEBACK = (
    'Traceback (most recent call last):\n'
    '  File "/srv/secret/KGKG/api/dataquality.py", line 9, in run_audit\n'
    '    boom()\n'
    'sqlite3.OperationalError: unable to open /srv/secret/warehouse/x.db')
PIPELINE = '/api/admin/pipeline/'


class ErrorExposureTests(AdminCase):
    def assertClean(self, response):
        body = response.content.decode()
        for marker in LEAK_MARKERS:
            self.assertNotIn(marker, body, marker)

    def test_stored_traceback_in_a_data_quality_run_is_not_served(self):
        DataQualityRun.objects.create(
            status='failed', finished_at=timezone.now(), error=OLD_TRACEBACK,
            vehicles=[{'stem': 'a', 'error': 'cannot open: unable to open /srv/secret/a.db'}],
            actions=[{'action': 'wal_checkpoint_failed', 'stem': 'a',
                      'detail': 'database is locked: /srv/secret/a.db-wal'},
                     {'action': 'wal_checkpoint', 'stem': 'b'}])
        r = self.get('/api/admin/data-quality/')
        self.assertEqual(r.status_code, 200)
        self.assertClean(r)
        rep = r.json()['report']
        self.assertEqual(rep['error'], 'OperationalError')
        self.assertEqual(rep['vehicles'][0]['error'], 'error')
        self.assertEqual(rep['actions'][0]['detail'], 'error')
        self.assertEqual(rep['actions'][1], {'action': 'wal_checkpoint', 'stem': 'b'})

    def test_a_failing_audit_stores_and_logs_only_what_is_safe(self):
        from . import dataquality
        with mock.patch('api.dataquality.run_audit', side_effect=RuntimeError('/srv/secret/x')), \
             self.assertLogs('kgkg.dataquality', 'ERROR'):
            run = dataquality.run_audit_to_db()
        self.assertEqual((run.status, run.error), ('failed', 'RuntimeError'))

    def test_stored_alert_context_and_snapshot_errors_are_not_served(self):
        SystemAlert.objects.create(
            key='db_down', message='db',
            context={'error': 'OperationalError: connection to server at "10.0.0.5", port 5432 failed',
                     'used_pct': 91})
        snap = {'db_ok': False, 'db_error': 'could not connect to 10.0.0.5 password=hunter2'}
        with mock.patch('api.adminops.monitoring.system_snapshot', return_value=snap):
            r = self.get('/api/admin/system/')
        self.assertClean(r)
        d = r.json()
        self.assertEqual(d['alerts_open'][0]['context'], {'error': 'OperationalError', 'used_pct': 91})
        self.assertEqual(d['snapshot']['db_error'], 'error')

    def test_snapshot_keeps_only_the_class_of_a_database_error(self):
        from . import monitoring
        with mock.patch('api.models.Car.objects.count', side_effect=RuntimeError('conn to 10.0.0.5')), \
             self.assertLogs('kgkg.monitoring', 'WARNING'):
            snap = monitoring.system_snapshot()
        self.assertEqual(snap['db_error'], 'RuntimeError')

    def test_stored_pipeline_and_zip_errors_are_not_served(self):
        ZipPackage.objects.create(path='/inbox/f.zip', zip_name='f.zip', status='failed',
                                  error=OLD_TRACEBACK)
        ZipPackage.objects.create(path='/inbox/g.zip', zip_name='g.zip', status='skipped_duplicate',
                                  error='skipped by admin')
        ProcessingJob.objects.create(status='failed', error=OLD_TRACEBACK)
        ProcessingJob.objects.create(
            status='failed', error='parse; rag',
            stages=[{'key': 'parse', 'error': 'a.zip: OSError: [Errno 2] No such file: /srv/secret/a.zip'}],
            progress={'overall_pct': 40, 'error': 'worker: ValueError: bad /srv/secret/x'})
        with mock.patch('api.adminops.tis_crawler.status',
                        return_value={'running': False, 'error': 'URLError: <urlopen error 10.0.0.5>'}):
            r = self.get(PIPELINE)
        self.assertClean(r)
        d = r.json()
        rows = {z['zip_name']: z['error'] for z in d['zip_queue']['rows']}
        self.assertEqual(rows, {'f.zip': 'OperationalError', 'g.zip': 'skipped by admin'})
        self.assertEqual(d['tis']['error'], 'URLError')
        self.assertEqual({h['error'] for h in d['history']}, {'OperationalError', 'parse; rag'})
        self.assertEqual(ProcessingJob.objects.filter(error='parse; rag').count(), 1)
        self.assertTrue(ProcessingJob.objects.filter(error=OLD_TRACEBACK).exists())   # data not rewritten
        shown = [j for j in (d['job'], d['last_job']) if j]
        self.assertTrue(shown)
        for j in shown:
            self.assertEqual([s['error'] for s in j['stages']], ['OSError'] * len(j['stages']))
            self.assertIn(j['error'], ('OperationalError', 'parse; rag'))
        with_stages = [j for j in shown if j['stages']]
        if with_stages:
            self.assertEqual(with_stages[0]['progress'], {'overall_pct': 40, 'error': 'ValueError'})

    def test_job_dict_scrubs_stage_and_progress_errors(self):
        from . import pipeline
        job = ProcessingJob.objects.create(
            status='failed', error=OLD_TRACEBACK,
            stages=[{'key': 'parse', 'error': 'a.zip: OSError: [Errno 2] No such file: /srv/secret/a.zip'},
                    {'key': 'rag', 'status': 'done', 'error': ''}],
            progress={'overall_pct': 40, 'error': 'worker: ValueError: bad /srv/secret/x'})
        d = pipeline.job_dict(job)
        self.assertEqual([s['error'] for s in d['stages']], ['OSError', ''])
        self.assertEqual(d['progress'], {'overall_pct': 40, 'error': 'ValueError'})
        self.assertEqual(d['error'], 'OperationalError')

    def test_a_failed_chrome_start_returns_a_fixed_message(self):
        with mock.patch('api.tis_crawler.hostjobs.enabled', return_value=True), \
             mock.patch('api.tis_crawler.hostjobs.call', side_effect=OSError('/srv/secret/spool')), \
             self.assertLogs('kgkg.tis_crawler', 'WARNING'):
            r = self.post(PIPELINE, {'action': 'tis_chrome'})
        self.assertEqual(r.status_code, 409)
        self.assertClean(r)
        self.assertIn('اجرای Chrome روی سرور ناموفق بود', r.json()['error'])

    def test_a_failed_tis_crawler_start_returns_a_fixed_message(self):
        from . import tis_crawler
        script = mock.Mock()
        script.is_file.return_value = True
        with mock.patch.object(tis_crawler, 'SCRIPT', script), \
             mock.patch('api.tis_crawler.hostjobs.enabled', return_value=True), \
             mock.patch('api.tis_crawler.hostjobs.pgrep', return_value=[]), \
             mock.patch('api.tis_crawler._pids', return_value=[]), \
             mock.patch('api.tis_crawler._chrome', return_value={'reachable': True, 'logged_in': True}), \
             mock.patch('api.tis_crawler.hostjobs.call', side_effect=OSError('/srv/secret/spool')), \
             self.assertLogs('kgkg.tis_crawler', 'WARNING'):
            pid, err = tis_crawler.start()
        self.assertIsNone(pid)
        self.assertNotIn('/srv/secret', err)

    def test_a_failed_parts_build_returns_a_fixed_message(self):
        from . import partsouq_build
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'pages').mkdir()
            (Path(tmp) / 'pages' / 'groups.html').write_text('x')
            with mock.patch('api.partsouq_build.parse_folder', return_value={'year': '2020'}), \
                 mock.patch('api.partsouq_build.safe_join', return_value=Path(tmp)), \
                 mock.patch('api.partsouq_build.partsouq_crawler.status', return_value={'running': False}), \
                 mock.patch('api.partsouq_build.build_db',
                            side_effect=sqlite3.OperationalError('unable to open /srv/secret/x.db')), \
                 self.assertLogs('kgkg.partsouq_build', 'WARNING'):
                res, err = partsouq_build.build_and_register('f', 'Corolla 2020', '')
        self.assertIsNone(res)
        self.assertNotIn('/srv/secret', err)
        # our own validation messages are still shown to the operator
        with mock.patch('api.partsouq_build.parse_folder', return_value=None):
            self.assertEqual(partsouq_build.build_and_register('f', 'Corolla 2020', '')[1],
                             'پوشهٔ خزش نامعتبر است.')

    def test_a_failed_zip_parse_stores_only_the_exception_class(self):
        from . import ingest
        pkg = ZipPackage.objects.create(path='/inbox/t', zip_name='t', status='pending', stem='t')
        tis = mock.Mock()
        tis.process_vehicle.side_effect = ValueError('bad member /srv/secret/t/x.html')
        with mock.patch('api.ingest.tis_module', return_value=tis), \
             mock.patch('api.ingest.parser_module', return_value=mock.Mock()), \
             self.assertLogs('kgkg.ingest', 'WARNING'):
            self.assertEqual(ingest._parse_tis_package(pkg), 'failed')
        pkg.refresh_from_db()
        self.assertEqual((pkg.status, pkg.error), ('failed', 'ValueError'))


class SafeErrorTextTests(TestCase):
    def test_public_error_reduces_anything_that_can_carry_details(self):
        from .safepath import public_error, scrub_errors
        cases = {
            '': '', None: None, 'OSError': 'OSError', 'skipped by admin': 'skipped by admin',
            'parse; rag': 'parse; rag',
            'به دلیل خطا در مرحله RAG اجرا نشد': 'به دلیل خطا در مرحله RAG اجرا نشد',
            'OSError: [Errno 2] No such file: /srv/x': 'OSError',
            'cannot open: unable to open database file': 'error',
            'a/b': 'error', 'C:\\x': 'error', "it's": 'error',
            'x' * 200: 'error',
            OLD_TRACEBACK: 'OperationalError',
            'worker: ValueError: a | s: sqlite3.OperationalError: b': 'ValueError, OperationalError',
        }
        for raw, want in cases.items():
            self.assertEqual(public_error(raw), want, raw)
        self.assertEqual(
            scrub_errors({'error': 'X: /a', 'n': [{'db_error': 'Y: /b', 'detail': '/keep'}], 'ok': 1}),
            {'error': 'error', 'n': [{'db_error': 'error', 'detail': '/keep'}], 'ok': 1})


class AdminUserAccessInputTests(AdminCase):
    """portal.admin_user_access_view: a ValueError from the ORM used to be echoed back (#44)."""

    def setUp(self):
        super().setUp()
        self.co = Company.objects.create(name='A', active=True)
        self.u = PortalUser.objects.create(company=self.co, username='emp', password_hash='x',
                                           role='after_sales_specialist', active=True)
        self.url = f'/api/admin/users/{self.u.id}/access/'

    def test_malformed_entries_get_a_fixed_400(self):
        for bad in ([{'car_id': 'abc'}], [{'car_id': "5'; DROP"}], ['x'], [None], [{'car_id': [1]}],
                    [{'car_id': True}], [{'car_id': 1, 'documents': 'manual'}],
                    [{'car_id': 1, 'documents': [['x']]}], {'car_id': 1}):
            r = self.post(self.url, {'accesses': bad})
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.json(), {'error': 'invalid accesses payload'}, bad)

    def test_a_refused_payload_leaves_the_existing_grants_alone(self):
        car = Car.objects.create(brand_name='Toyota', car_name='X', year=2020, db_address='')
        UserCarAccess.objects.create(user=self.u, car=car, documents=['manual'], admin_granted=True)
        self.post(self.url, {'accesses': [{'car_id': 'abc'}]})
        self.assertEqual(UserCarAccess.objects.filter(user=self.u).count(), 1)

    def test_well_formed_payloads_still_work_and_the_gate_still_applies(self):
        car = Car.objects.create(brand_name='Toyota', car_name='Y', year=2020, db_address='')
        ok = self.post(self.url, {'accesses': [{'car_id': car.id, 'documents': ['manual'],
                                                'admin_granted': True}]})
        self.assertEqual(ok.status_code, 200, ok.content)
        as_text = self.post(self.url, {'accesses': [{'car_id': str(car.id), 'admin_granted': True}]})
        self.assertEqual(as_text.status_code, 200, as_text.content)
        self.assertEqual(self.post(self.url, {'accesses': []}).status_code, 200)
        r = self.c.post(self.url, '{"accesses": []}', content_type='application/json',
                        HTTP_AUTHORIZATION='Bearer nope')
        self.assertEqual(r.status_code, 401)
