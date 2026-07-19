"""Tests for the data-processing pipeline (api/pipeline.py + worker/tick)."""
import tempfile
from pathlib import Path
from unittest import mock

from django.test import Client, TestCase
from django.utils import timezone

from . import pipeline
from .models import Car, PipelineSettings, ProcessingJob, SystemAlert
from .test_ops import make_car_db


class PendingWorkTests(TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.wh = Path(self._td.name)
        make_car_db(self.wh / 'Car A.db', 'Car A')
        make_car_db(self.wh / 'Car B.db', 'Car B')
        Car.objects.create(brand_name='Toyota', car_name='Car A', year=2025,
                           db_address='./Database_warehouse/Car A.db')
        patches = [
            mock.patch.object(pipeline.config, 'WAREHOUSE_DIR', self.wh),
            mock.patch.object(pipeline.config, 'INDEX_DB', self.wh / '_rag' / 'index.rag.db'),
            mock.patch.object(pipeline.config, 'DIAG_DIR', self.wh / '_rag' / 'diag'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._td.cleanup)

    def test_pending_work_detects_all_gaps(self):
        work = pipeline.pending_work()
        self.assertEqual(work['vehicles_on_disk'], 2)
        self.assertEqual(work['need_catalog'], ['Car B'])
        self.assertEqual(work['need_rag_ingest'], ['Car A', 'Car B'])  # no index at all
        self.assertEqual(work['need_diag'], ['Car A', 'Car B'])
        self.assertTrue(work['has_work'])

    def test_no_work_when_everything_done(self):
        import sqlite3
        Car.objects.create(brand_name='Toyota', car_name='Car B', year=2025,
                           db_address='x')
        rag_dir = self.wh / '_rag'
        (rag_dir / 'diag').mkdir(parents=True)
        con = sqlite3.connect(str(rag_dir / 'index.rag.db'))
        con.execute('CREATE TABLE blobs (id INTEGER PRIMARY KEY)')
        # The pipeline counts the vec0 SHADOW table (readable without the
        # sqlite-vec extension), so the fixture mirrors that table name.
        con.execute('CREATE TABLE vec_blobs_rowids (rowid INTEGER PRIMARY KEY)')
        con.execute('CREATE TABLE occurrences (car_stem TEXT)')
        con.execute('CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)')
        con.executemany('INSERT INTO occurrences VALUES (?)',
                        [('Car A',), ('Car B',)])
        con.execute('INSERT INTO blobs VALUES (1)')
        con.execute('INSERT INTO vec_blobs_rowids VALUES (1)')
        # Graph in sync with the 1 stored vector.
        con.execute("INSERT INTO meta VALUES ('graph_synced_vectors', '1')")
        con.commit()
        con.close()
        for stem in ('Car A', 'Car B'):
            (rag_dir / 'diag' / f'{stem}.diag.db').touch()
        # Vehicle specs are their own stage now; "everything done" includes
        # them (built here via the real builder so staleness math runs too).
        from . import vehicleschema
        for stem in ('Car A', 'Car B'):
            vehicleschema.build_for_stem(stem)
        work = pipeline.pending_work()
        self.assertEqual(work['need_schema'], [])
        self.assertFalse(work['has_work'])
        self.assertEqual(work['pages_to_embed'], 0)

    def test_graph_pending_when_marker_stale(self):
        import sqlite3
        rag_dir = self.wh / '_rag'
        rag_dir.mkdir()
        con = sqlite3.connect(str(rag_dir / 'index.rag.db'))
        con.execute('CREATE TABLE blobs (id INTEGER PRIMARY KEY)')
        con.execute('CREATE TABLE vec_blobs_rowids (rowid INTEGER PRIMARY KEY)')
        con.execute('CREATE TABLE occurrences (car_stem TEXT)')
        con.execute('CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)')
        con.execute('INSERT INTO blobs VALUES (1)')
        con.execute('INSERT INTO vec_blobs_rowids VALUES (1)')
        # No graph_synced_vectors marker -> an embed ran but the graph never
        # caught up (e.g. interrupted between phases) -> work remains.
        con.commit()
        con.close()
        work = pipeline.pending_work()
        self.assertTrue(work['graph_pending'])
        self.assertTrue(work['has_work'])

    def test_estimate_scales_with_work(self):
        st = PipelineSettings.get()
        st.embed_rate_pps = 2.0
        work = {'pages_to_embed': 7200, 'need_rag_ingest': [],
                'need_diag': ['X'], 'need_catalog': []}
        est = pipeline.estimate_duration_s(work, st)
        self.assertGreaterEqual(est, 3600)          # 7200 pages / 2pps = 3600s
        self.assertLess(est, 3600 + 600)


class JobLifecycleTests(TestCase):
    def _fake_work(self, has=True):
        return {'vehicles_on_disk': 2, 'need_catalog': ['B'] if has else [],
                'need_rag_ingest': [], 'pages_to_embed': 100 if has else 0,
                'embed_total': 100, 'embed_done': 0,
                'need_diag': ['B'] if has else [], 'has_work': has}

    def test_start_job_single_flight(self):
        with mock.patch.object(pipeline, 'pending_work', return_value=self._fake_work()), \
             mock.patch.object(pipeline, 'launch_worker') as launch, \
             mock.patch.object(pipeline, '_foreign_build_running', return_value=None):
            job, err = pipeline.start_job()
            self.assertIsNone(err)
            self.assertEqual(job.status, 'pending')
            self.assertEqual([s['key'] for s in job.stages],
                             ['download', 'parse', 'catalog', 'schema',
                              'rag', 'diag', 'audit'])
            launch.assert_called_once()
            # Second start while one is active must refuse.
            job2, err2 = pipeline.start_job()
            self.assertIsNone(job2)
            self.assertIn('در جریان است', err2)

    def test_start_refuses_on_foreign_process(self):
        with mock.patch.object(pipeline, 'pending_work', return_value=self._fake_work()), \
             mock.patch.object(pipeline, '_foreign_build_running',
                               return_value={'pid': 1, 'cmd': 'manage.py build_rag'}):
            job, err = pipeline.start_job()
            self.assertIsNone(job)
            self.assertIn('خارج از سامانه', err)

    def test_start_refuses_without_work(self):
        with mock.patch.object(pipeline, 'pending_work',
                               return_value=self._fake_work(has=False)), \
             mock.patch.object(pipeline, '_foreign_build_running', return_value=None):
            job, err = pipeline.start_job()
            self.assertIsNone(job)
            self.assertIn('همه پردازش‌ها انجام شده', err)

    def test_scheduled_job_not_launched_immediately(self):
        at = timezone.now() + timezone.timedelta(hours=3)
        with mock.patch.object(pipeline, 'pending_work', return_value=self._fake_work()), \
             mock.patch.object(pipeline, 'launch_worker') as launch, \
             mock.patch.object(pipeline, '_foreign_build_running', return_value=None):
            job, err = pipeline.start_job(trigger='schedule', scheduled_for=at)
            self.assertIsNone(err)
            self.assertEqual(job.status, 'scheduled')
            launch.assert_not_called()

    def test_tick_marks_stalled_and_resumes(self):
        job = ProcessingJob.objects.create(
            status='running', pid=999999983,   # nonexistent pid
            heartbeat_at=timezone.now() - timezone.timedelta(minutes=10),
            stages=[], progress={})
        with mock.patch.object(pipeline, 'launch_worker') as launch, \
             mock.patch.object(pipeline, '_foreign_build_running', return_value=None):
            did = pipeline.tick()
        self.assertIn(job.id, did['stalled'])
        self.assertIn(job.id, did['resumed'])
        job.refresh_from_db()
        self.assertEqual(job.status, 'pending')     # reclaimed for relaunch
        launch.assert_called_once()
        self.assertTrue(SystemAlert.objects.filter(key='pipeline_stalled').exists())

    def test_tick_respects_attempt_budget(self):
        job = ProcessingJob.objects.create(
            status='stalled', pid=None, attempts=pipeline.MAX_AUTO_ATTEMPTS,
            stages=[], progress={})
        with mock.patch.object(pipeline, 'launch_worker') as launch, \
             mock.patch.object(pipeline, '_foreign_build_running', return_value=None), \
             mock.patch.object(pipeline, 'pending_work',
                               return_value=self._fake_work(has=False)):
            did = pipeline.tick()
        self.assertEqual(did['resumed'], [])
        launch.assert_not_called()

    def test_tick_autostarts_only_on_low_load(self):
        PipelineSettings.get()   # ensure defaults (auto_enabled=True)
        with mock.patch.object(pipeline, 'pending_work', return_value=self._fake_work()), \
             mock.patch.object(pipeline, 'launch_worker'), \
             mock.patch.object(pipeline, '_foreign_build_running', return_value=None):
            with mock.patch.object(pipeline, 'load_snapshot',
                                   return_value={'ratio': 0.9, 'level': 'high',
                                                 'load1': 14, 'cores': 16}):
                did = pipeline.tick()
                self.assertFalse(did['auto_started'])
            with mock.patch.object(pipeline, 'load_snapshot',
                                   return_value={'ratio': 0.1, 'level': 'low',
                                                 'load1': 1.6, 'cores': 16}):
                did = pipeline.tick()
                self.assertTrue(did['auto_started'])

    def test_cancel_pending_job(self):
        job = ProcessingJob.objects.create(status='pending', stages=[], progress={})
        ok, err = pipeline.cancel_job(job)
        self.assertTrue(ok)
        job.refresh_from_db()
        self.assertEqual(job.status, 'canceled')

    def test_resume_requires_resumable_state(self):
        job = ProcessingJob.objects.create(status='done', stages=[], progress={})
        ok, err = pipeline.resume_job(job)
        self.assertFalse(ok)
        job2 = ProcessingJob.objects.create(status='paused', stages=[], progress={})
        with mock.patch.object(pipeline, 'launch_worker') as launch, \
             mock.patch.object(pipeline, '_foreign_build_running', return_value=None):
            ok, err = pipeline.resume_job(job2)
        self.assertTrue(ok)
        launch.assert_called_once()


class PipelineEndpointTests(TestCase):
    def setUp(self):
        self.c = Client()

    def _admin_headers(self):
        from .models import PlatformAdmin, AdminAuthToken
        admin = PlatformAdmin.objects.create(username='boss2')
        admin.set_password('pw')
        admin.save()
        return {'HTTP_AUTHORIZATION': f'Bearer {AdminAuthToken.issue(admin).key}'}

    def test_gated(self):
        self.assertEqual(self.c.get('/api/admin/pipeline/').status_code, 401)

    def test_get_shape(self):
        r = self.c.get('/api/admin/pipeline/', **self._admin_headers())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in ('pending', 'load', 'estimate_s', 'recommendation',
                    'job', 'history', 'settings'):
            self.assertIn(key, body)

    def test_post_start_and_conflict(self):
        headers = self._admin_headers()
        fake = {'vehicles_on_disk': 1, 'need_catalog': [], 'need_rag_ingest': [],
                'pages_to_embed': 10, 'embed_total': 10, 'embed_done': 0,
                'need_diag': [], 'has_work': True}
        with mock.patch.object(pipeline, 'pending_work', return_value=fake), \
             mock.patch.object(pipeline, 'launch_worker'), \
             mock.patch.object(pipeline, '_foreign_build_running', return_value=None):
            r = self.c.post('/api/admin/pipeline/', {'action': 'start'},
                            content_type='application/json', **headers)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()['job']['status'], 'pending')
            r = self.c.post('/api/admin/pipeline/', {'action': 'start'},
                            content_type='application/json', **headers)
            self.assertEqual(r.status_code, 409)

    def test_settings_update(self):
        headers = self._admin_headers()
        r = self.c.post('/api/admin/pipeline/',
                        {'action': 'settings', 'auto_enabled': False,
                         'load_threshold': 0.4},
                        content_type='application/json', **headers)
        self.assertEqual(r.status_code, 200)
        st = PipelineSettings.get()
        self.assertFalse(st.auto_enabled)
        self.assertEqual(st.load_threshold, 0.4)
