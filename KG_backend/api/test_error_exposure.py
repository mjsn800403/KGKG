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
import types
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase
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


class WalCheckpointFailureTests(AdminCase):
    """remediate() has a ``log`` callback parameter; the module logger must not be named ``log``
    or a failed checkpoint raises AttributeError and the whole audit is lost (Codex P2 on PR #98)."""

    def _vehicle(self):
        return {'stem': 'x', 'size_mb': 0.0, 'integrity': 'ok', 'error': None, 'total_nodes': 0,
                'content_leaves': 0, 'empty_leaves': 0, 'content_mb': 0.0, 'sections': [],
                'fingerprint': None}

    def _broken_sqlite(self):
        return types.SimpleNamespace(
            connect=mock.Mock(side_effect=sqlite3.OperationalError('unable to open /srv/secret/x.db-wal')),
            Error=sqlite3.Error, DatabaseError=sqlite3.DatabaseError)

    def test_remediate_records_a_failed_checkpoint_with_and_without_a_log_callback(self):
        from . import dataquality
        from .rag import config
        with tempfile.TemporaryDirectory() as tmp:
            wh = Path(tmp)
            (wh / 'x.db').write_bytes(b'')
            (wh / 'x.db-wal').write_bytes(b'')
            vehicles = [dict(self._vehicle(), status='complete')]
            want = [{'action': 'wal_checkpoint_failed', 'stem': 'x', 'detail': 'OperationalError'}]
            for callback in (None, [].append):        # the default lambda and a real callback
                with mock.patch.object(config, 'WAREHOUSE_DIR', wh), \
                     mock.patch('api.dataquality.sqlite3', self._broken_sqlite()), \
                     self.assertLogs('kgkg.dataquality', 'WARNING') as logs:
                    actions = dataquality.remediate(vehicles, [], log=callback)
                self.assertEqual(actions, want)
                self.assertNotIn('/srv/secret/x.db-wal', ' '.join(r.getMessage() for r in logs.records))

    def test_a_failed_checkpoint_does_not_fail_the_audit_and_stays_clean_in_the_api(self):
        from . import dataquality
        from .rag import config
        with tempfile.TemporaryDirectory() as tmp:
            wh = Path(tmp)
            (wh / 'x.db').write_bytes(b'')
            (wh / 'x.db-wal').write_bytes(b'')
            with mock.patch.object(config, 'WAREHOUSE_DIR', wh), \
                 mock.patch.object(config, 'DIAG_DIR', wh / 'diag'), \
                 mock.patch.object(config, 'car_db_files', return_value=[wh / 'x.db']), \
                 mock.patch('api.dataquality.audit_vehicle_db', return_value=self._vehicle()), \
                 mock.patch('api.dataquality._rag_indexed_stems', return_value=set()), \
                 mock.patch('api.dataquality._static_dirs', return_value=set()), \
                 mock.patch('api.dataquality.sqlite3', self._broken_sqlite()), \
                 self.assertLogs('kgkg.dataquality', 'WARNING'):
                run = dataquality.run_audit_to_db(fix=True)
        self.assertEqual((run.status, run.error), ('done', ''))
        self.assertEqual(run.actions, [{'action': 'wal_checkpoint_failed', 'stem': 'x',
                                        'detail': 'OperationalError'}])
        r = self.get('/api/admin/data-quality/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('/srv/secret', r.content.decode())
        self.assertEqual(r.json()['report']['actions'][0]['detail'], 'OperationalError')


class FailClosedErrorTextTests(AdminCase):
    """Stored error text that has no suspicious punctuation is still not returned."""

    PLAIN_SECRETS = ('password for admin is hunter2', 'connection refused by host db internal',
                     'Alice Smith alice smith', 'رمز عبور کاربر رضا ۱۲۳۴', 'FooBarError',
                     'parse; rag; password hunter2', 'could not connect to server', 'x' * 200)

    def test_public_error_returns_only_known_phrases_stage_keys_and_known_exception_classes(self):
        from .safepath import public_error
        for raw in self.PLAIN_SECRETS:
            self.assertEqual(public_error(raw), 'error', raw)
        cases = {
            '': '', None: None, 'OSError': 'OSError', 'skipped by admin': 'skipped by admin',
            'parse; rag': 'parse; rag', 'rag': 'rag',
            'به دلیل خطا در مرحله RAG اجرا نشد': 'به دلیل خطا در مرحله RAG اجرا نشد',
            'OSError: [Errno 2] No such file: /srv/x': 'OSError',
            'ValueError: password hunter2': 'ValueError',
            'cannot open: unable to open database file': 'error',
            'a/b': 'error', 'C:\\x': 'error', "it's": 'error',
            OLD_TRACEBACK: 'OperationalError',
            'worker: ValueError: a | s: sqlite3.OperationalError: b': 'ValueError, OperationalError',
        }
        for raw, want in cases.items():
            self.assertEqual(public_error(raw), want, raw)

    def test_scrub_errors_reduces_error_keys_integrity_and_log_tail_only(self):
        from .safepath import scrub_errors
        got = scrub_errors({
            'error': 'X: /a', 'integrity': '*** in database main *** Page 5 is never used',
            'n': [{'db_error': 'Y: /b', 'integrity': 'ok', 'detail': '/keep'}], 'ok': 1,
            'log_tail': '[10:00:00] !! diag failed for A: boom password=hunter2'})
        self.assertEqual(got, {
            'error': 'error', 'integrity': 'error',
            'n': [{'db_error': 'error', 'integrity': 'ok', 'detail': '/keep'}], 'ok': 1,
            'log_tail': '[10:00:00] !! diag failed for A'})

    def test_plain_historical_errors_do_not_reach_any_admin_response(self):
        DataQualityRun.objects.create(
            status='failed', finished_at=timezone.now(), error='password for admin is hunter2',
            vehicles=[{'stem': 'a', 'error': 'could not connect to host db internal',
                       'integrity': 'wrong number of entries in index sqlite_autoindex_x'}])
        ZipPackage.objects.create(path='/inbox/p.zip', zip_name='p.zip', status='failed',
                                  error='Wrong credentials for ftp user bob')
        ProcessingJob.objects.create(status='failed', error='database password is hunter2',
                                     stages=[{'key': 'rag', 'error': 'token for bob expired'}])
        SystemAlert.objects.create(key='k', message='m', context={'error': 'bob forgot the password'})
        bodies = [self.get(u).content.decode() for u in
                  ('/api/admin/data-quality/', PIPELINE, '/api/admin/system/')]
        for body in bodies:
            for secret in ('hunter2', 'bob', 'ftp', 'credentials', 'internal', 'sqlite_autoindex'):
                self.assertNotIn(secret, body, secret)


class WorkerLogTailTests(AdminCase):
    TAIL = '\n'.join([
        '[10:00:01] worker started (pid 12, attempt 1)',
        '[10:00:02] !! stage rag failed: OSError: [Errno 2] No such file: /srv/secret/x.db',
        '[10:00:03] !! diag failed for Camry: unable to open /srv/secret/diag.db',
        'Traceback (most recent call last):',
        '  File "/srv/secret/a.py", line 3, in f',
        'sqlite3.OperationalError: unable to open /srv/secret/x',
        '[10:00:04] connecting postgres://kgkg:hunter2@db-internal/kgkg',
        '[10:00:05] request failed password=hunter2 token: abc123',
        '[10:00:06] parse stage: 3 parsed, 0 failed, 0 skipped/remaining',
    ])

    def test_job_dict_removes_messages_frames_and_credentials_from_the_log_tail(self):
        from . import pipeline
        job = ProcessingJob.objects.create(status='failed', log_tail=self.TAIL)
        tail = pipeline.job_dict(job)['log_tail']
        for secret in ('/srv/secret', 'hunter2', 'abc123', 'File "', 'Traceback'):
            self.assertNotIn(secret, tail, secret)
        lines = tail.split('\n')
        self.assertEqual(lines[0], '[10:00:01] worker started (pid 12, attempt 1)')
        self.assertEqual(lines[1], '[10:00:02] !! stage rag failed: OSError')
        self.assertEqual(lines[2], '[10:00:03] !! diag failed for Camry')
        self.assertEqual(lines[5], 'sqlite3.OperationalError')
        self.assertEqual(lines[-1], '[10:00:06] parse stage: 3 parsed, 0 failed, 0 skipped/remaining')
        self.assertIn('[redacted]', tail)

    def test_the_admin_pipeline_view_and_crawler_status_serve_the_same_redaction(self):
        ProcessingJob.objects.create(status='failed', log_tail=self.TAIL)
        crawl = {'running': False, 'log_tail': self.TAIL}
        with mock.patch('api.adminops.tis_crawler.status', return_value=dict(crawl)), \
             mock.patch('api.adminops.partsouq_crawler.status', return_value=dict(crawl)):
            r = self.get(PIPELINE)
        body = r.content.decode()
        for secret in ('/srv/secret', 'hunter2', 'abc123', 'Traceback'):
            self.assertNotIn(secret, body, secret)

    def test_a_failing_stage_writes_only_the_class_into_the_job_and_its_log(self):
        from .management.commands import run_pipeline
        job = ProcessingJob.objects.create(
            status='running', stages=[{'key': 'rag', 'label': 'rag', 'status': 'pending',
                                       'items_total': 2, 'items_done': 0, 'error': ''}])
        runner = run_pipeline.Runner(job)

        def boom(stage):
            raise OSError('/srv/secret/x.db unreadable for password=hunter2')

        with self.assertLogs('kgkg.run_pipeline', 'WARNING'):
            self.assertFalse(runner.run_stage('rag', boom))
        job.refresh_from_db()
        self.assertEqual(job.stages[0]['error'], 'OSError')
        self.assertNotIn('/srv/secret', runner._log_tail())
        self.assertNotIn('hunter2', runner._log_tail())
        self.assertIn('!! stage rag failed: OSError', runner._log_tail())


class PartsouqStartTests(AdminCase):
    URL = ('https://partsouq.com/en/catalog/toyota/vehicle/gcc/2020/corolla/zre/'
           'category/groups/vin/JTDKBRFU5J3000000')

    def test_a_failed_partsouq_start_returns_a_fixed_message(self):
        from . import partsouq_crawler
        with mock.patch('api.partsouq_crawler.hostjobs.enabled', return_value=True), \
             mock.patch('api.partsouq_crawler._pids', return_value=[]), \
             mock.patch('api.partsouq_crawler.tis_crawler._pids', return_value=[]), \
             mock.patch('api.partsouq_crawler.tis_crawler._chrome', return_value={'reachable': True}), \
             mock.patch('api.partsouq_crawler.hostjobs.call', side_effect=OSError('/srv/secret/spool')), \
             self.assertLogs('kgkg.partsouq_crawler', 'WARNING'):
            pid, err = partsouq_crawler.start(self.URL)
            r = self.post(PIPELINE, {'action': 'ps_start', 'url': self.URL})
        self.assertIsNone(pid)
        self.assertNotIn('/srv/secret', err)
        self.assertEqual(r.status_code, 409)
        self.assertNotIn('/srv/secret', r.content.decode())
        self.assertIn('جزئیات در لاگ سرور', r.json()['error'])


class PartsouqBuildErrorTests(AdminCase):
    """CodeQL alert #38 (ps_build): a BuildError reaches the operator as fixed text chosen
    by its code, never as the exception's own message."""
    PREFIX = 'ساخت پایگاه داده ناموفق بود: '
    FOLDER = 'LandCruiser_2019_GRJ200L-GNTAKV_JTMHU01J6L5165492'

    def _patched(self, exc):
        """build_and_register past its input checks, with build_db raising ``exc``."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / 'pages').mkdir()
        (Path(tmp.name) / 'pages' / 'groups.html').write_text('x')
        stack = mock.patch.multiple(
            'api.partsouq_build', parse_folder=mock.Mock(return_value={'year': '2020'}),
            safe_join=mock.Mock(return_value=Path(tmp.name)), build_db=mock.Mock(side_effect=exc))
        status = mock.patch('api.partsouq_build.partsouq_crawler.status', return_value={'running': False})
        return stack, status

    def _build(self, exc):
        from . import partsouq_build
        stack, status = self._patched(exc)
        with stack, status:
            return partsouq_build.build_and_register('f', 'Corolla 2020', '')

    def test_each_code_keeps_the_text_the_operator_saw_before(self):
        from .partsouq_build import BUILD_ERRORS, BuildError
        expected = {
            'folder': 'folder name is not <Model>_<year>_<frame>_<VIN>',
            'car_name': 'car name is not a plain file name',
            'no_diagrams': 'no usable diagrams in this crawl',
        }
        self.assertEqual(BUILD_ERRORS, expected)           # the wording is part of the API contract
        for code, text in expected.items():
            res, err = self._build(BuildError(code))
            self.assertIsNone(res)
            self.assertEqual(err, self.PREFIX + text, code)

    def test_an_exception_message_is_never_echoed(self):
        from .partsouq_build import BUILD_ERROR_FALLBACK, BuildError
        for bad in ('/srv/secret/x.db', 'unable to open /srv/secret/x.db password=hunter2', ''):
            res, err = self._build(BuildError(bad))
            self.assertIsNone(res)
            self.assertEqual(err, self.PREFIX + BUILD_ERROR_FALLBACK)
            self.assertNotIn('secret', err)
            self.assertNotIn('hunter2', err)

    def test_the_admin_endpoint_returns_the_fixed_text_with_409(self):
        from .partsouq_build import BuildError
        stack, status = self._patched(BuildError('/srv/secret/x.db'))
        with stack, status:
            r = self.post(PIPELINE, {'action': 'ps_build', 'folder': 'f', 'car_name': 'Corolla 2020'})
        self.assertEqual(r.status_code, 409)
        self.assertNotIn('/srv/secret', r.content.decode())
        self.assertIn(self.PREFIX, r.json()['error'])

    def test_every_raise_site_uses_a_known_code_and_every_code_is_used(self):
        import inspect
        import re
        from . import partsouq_build
        used = set(re.findall(r"raise BuildError\('(\w+)'", inspect.getsource(partsouq_build)))
        self.assertEqual(used, set(partsouq_build.BUILD_ERRORS))

    def test_build_db_raises_the_codes_for_a_bad_folder_and_a_bad_car_name(self):
        from . import partsouq_build
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(partsouq_build.BuildError) as cm:
                partsouq_build.build_db(Path(tmp) / 'not-a-crawl', 'Corolla 2020', '', backend=tmp)
            self.assertEqual(cm.exception.code, 'folder')
            with self.assertRaises(partsouq_build.BuildError) as cm:
                partsouq_build.build_db(Path(tmp) / self.FOLDER, '../x', '', backend=tmp)
            self.assertEqual(cm.exception.code, 'car_name')


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


# --- sensitive data in server logs, GlitchTip and the worker log tail (KGTEC-14) ------------
# Synthetic values only: nothing below is a real credential or a real person's number.
FAKE_PW = 'SyntheticPw9'
FAKE_SECRET = 'SyntheticSecret1'
FAKE_PHONE = '09120000000'


class LogScrubberTests(SimpleTestCase):
    """KG_backend.jsonlog._scrub_text: what reaches app.jsonl, Loki and GlitchTip messages."""

    def scrub(self, text):
        from KG_backend.jsonlog import _scrub_text
        return _scrub_text(text)

    def test_a_password_in_a_connection_string_is_masked_but_user_and_host_stay(self):
        out = self.scrub(f'could not connect: postgresql://kguser:{FAKE_PW}@db.internal:5432/kgkg')
        self.assertNotIn(FAKE_PW, out)
        self.assertIn('kguser', out)
        self.assertIn('db.internal:5432', out)

    def test_a_quoted_libpq_password_is_masked_as_a_whole(self):
        out = self.scrub("host=db user=kgkg password='Synthetic Pass 9' dbname=kgkg_vec")
        self.assertNotIn('Synthetic', out)
        self.assertNotIn('Pass 9', out)
        self.assertIn('dbname=kgkg_vec', out)

    def test_row_data_in_postgres_error_detail_is_masked_but_the_column_stays(self):
        out = self.scrub(f'DETAIL:  Key (phone)=({FAKE_PHONE}) already exists.')
        self.assertNotIn(FAKE_PHONE, out)
        self.assertIn('Key (phone)=', out)
        out = self.scrub(f'DETAIL:  Failing row contains (5, {FAKE_PHONE}, ali).')
        self.assertNotIn(FAKE_PHONE, out)
        self.assertNotIn('ali', out.split('contains', 1)[1])

    def test_ordinary_messages_and_a_public_key_dsn_are_left_alone(self):
        for text in ('FATAL: password authentication failed for user "kgkg"',
                     'unable to open /srv/x/y.db', 'parse stage: 4 parsed, 0 failed',
                     'dsn=https://abc123@glitch.local/1'):
            self.assertEqual(self.scrub(text), text)

    def test_adversarial_long_input_is_processed_in_linear_time(self):
        import time
        for text in ('a' * 200000, 'a.b-' * 50000, 'a://' * 50000, 'Key (' * 40000,
                     "password='" * 20000, 'Failing row contains (' * 9000):
            t0 = time.monotonic()
            self.scrub(text)
            self.assertLess(time.monotonic() - t0, 2.0, text[:14])

    def test_the_json_formatter_masks_a_secret_in_the_message_and_in_the_traceback(self):
        import json
        import logging
        import sys
        from KG_backend.jsonlog import JsonFormatter
        try:
            raise RuntimeError(f'connect failed: postgresql://u:{FAKE_PW}@h/db')
        except RuntimeError:
            record = logging.LogRecord('kgkg.x', logging.WARNING, __file__, 1,
                                       f'start failed password={FAKE_SECRET}', None, sys.exc_info())
        line = JsonFormatter().format(record)
        self.assertNotIn(FAKE_PW, line)
        self.assertNotIn(FAKE_SECRET, line)
        self.assertIn('RuntimeError', json.loads(line)['error']['type'])


class LogTailCredentialTests(SimpleTestCase):
    """safepath.public_log_tail: credential-looking values, including keys that only CONTAIN
    the word (DB_PASSWORD, client_secret) and quoted values."""

    def tail(self, text):
        from .safepath import public_log_tail
        return public_log_tail(text)

    def test_keys_that_contain_a_credential_word_are_masked(self):
        for line in (f'DB_PASSWORD={FAKE_PW}', f'client_secret={FAKE_SECRET}',
                     f'AWS_SECRET_ACCESS_KEY={FAKE_SECRET}', f'KG_PG_PASSWORD: {FAKE_PW}',
                     f'api_key={FAKE_SECRET}', f'Authorization: Bearer {FAKE_SECRET}'):
            out = self.tail(f'[12:00:01] starting {line} now')
            self.assertNotIn(FAKE_PW, out, line)
            self.assertNotIn(FAKE_SECRET, out, line)
            self.assertIn('[redacted]', out, line)

    def test_a_quoted_value_with_spaces_is_masked_as_a_whole(self):
        out = self.tail("connecting with password='Synthetic Pass 9' to db")
        self.assertNotIn('Synthetic', out)
        self.assertNotIn('Pass 9', out)
        self.assertTrue(out.endswith('to db'))

    def test_a_connection_string_password_is_masked(self):
        out = self.tail(f'using postgresql://u:{FAKE_PW}@h:5432/db')
        self.assertNotIn(FAKE_PW, out)

    def test_ordinary_progress_lines_are_unchanged(self):
        for line in ('[12:00:02] parse stage: 4 parsed in 12s: ok', 'scanned x_2021', 'max_tokens limit not used'):
            self.assertEqual(self.tail(line), line)

    def test_a_very_long_line_is_processed_in_linear_time(self):
        import time
        for text in ('a' * 200000, 'a.b-' * 50000, ('password ' * 20000)):
            t0 = time.monotonic()
            self.tail(text)
            self.assertLess(time.monotonic() - t0, 2.0, text[:12])


class SentryLocalVariablesTests(SimpleTestCase):
    """GlitchTip must not receive stack-frame local variables: the SDK scrubs them by variable
    NAME only, so a `dsn`/`conninfo` holding a password would pass."""

    def test_sentry_init_turns_frame_variables_off(self):
        import importlib
        import os
        import sys
        try:
            import sentry_sdk  # noqa: F401
        except ImportError:
            self.skipTest('sentry-sdk is not installed here (CI installs it)')
        import KG_backend.settings as settings_module
        seen = {}
        with mock.patch.dict(os.environ, {'SENTRY_DSN': 'http://public@localhost:9/1'}), \
             mock.patch('sentry_sdk.init', side_effect=lambda **kw: seen.update(kw)):
            try:
                importlib.reload(settings_module)
            finally:
                os.environ.pop('SENTRY_DSN', None)
                importlib.reload(sys.modules['KG_backend.settings'])
        self.assertIs(seen.get('include_local_variables'), False)
        self.assertIs(seen.get('send_default_pii'), False)

