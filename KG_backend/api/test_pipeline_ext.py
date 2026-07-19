"""Tests for the pipeline's download/parse/schema extension: inbox scanning,
ZIP normalization + registration, the duplicate guard, queue-aware pending
work, and legacy-job stage tolerance."""
import os
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from . import ingest, pipeline
from .models import Car, DownloadRequest, ProcessingJob, ZipPackage
from .rag import config


def _make_zip(dirpath, zip_name, inner_dir, payload=b'x' * 64):
    path = Path(dirpath) / zip_name
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr(f'{inner_dir}/index.html', payload)
        zf.writestr(f'{inner_dir}/images/a.png', payload)
    return path


class ZipInnerMetaTest(TestCase):
    def test_reads_year_brand_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            zp = _make_zip(tmp, 'whatever.zip', '2023 Toyota Corolla Cross LE, FWD')
            self.assertEqual(ingest.zip_inner_meta(zp),
                             ('Toyota', 2023, 'Corolla Cross LE, FWD'))

    def test_unrecognizable(self):
        with tempfile.TemporaryDirectory() as tmp:
            zp = _make_zip(tmp, 'junk.zip', 'no-year-here')
            self.assertIsNone(ingest.zip_inner_meta(zp))
            bad = Path(tmp) / 'not_a_zip.zip'
            bad.write_bytes(b'garbage')
            self.assertIsNone(ingest.zip_inner_meta(bad))


class ScanInboxTest(TestCase):
    def _scan_env(self, tmp):
        """Patches so the scanner sees only the temp inbox + temp warehouse."""
        inbox = Path(tmp) / 'inbox'
        wh = Path(tmp) / 'warehouse'
        inbox.mkdir()
        wh.mkdir()
        return inbox, wh, mock.patch.dict(
            os.environ, {'KG_ZIP_INBOX': str(inbox)}), mock.patch.object(
            ingest, 'MIN_ZIP_BYTES', 0), mock.patch.object(
            config, 'WAREHOUSE_DIR', wh)

    def test_normalize_renames_and_registers(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox, wh, envp, minp, whp = self._scan_env(tmp)
            _make_zip(inbox, 'Corolla Cross LE, FWD.zip',
                      '2023 Toyota Corolla Cross LE, FWD')
            with envp, minp, whp:
                summary = ingest.scan_inbox(normalize=True)
            self.assertEqual(summary['registered'], 1)
            self.assertEqual(summary['renamed'], 1)
            pkg = ZipPackage.objects.get()
            self.assertEqual(pkg.zip_name, 'LEMON 2023 Toyota Corolla Cross LE, FWD.zip')
            self.assertTrue(Path(pkg.path).exists())
            self.assertEqual(pkg.stem, 'Corolla Cross LE, FWD (2023)')
            self.assertEqual(pkg.year, 2023)
            self.assertEqual(pkg.status, 'pending')

    def test_default_year_keeps_plain_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox, wh, envp, minp, whp = self._scan_env(tmp)
            _make_zip(inbox, 'RAV4 LE.zip', '2025 Toyota RAV4 LE')
            with envp, minp, whp:
                ingest.scan_inbox(normalize=True)
            pkg = ZipPackage.objects.get()
            self.assertEqual(pkg.stem, 'RAV4 LE')

    def test_duplicate_guard_warehouse(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox, wh, envp, minp, whp = self._scan_env(tmp)
            _make_zip(inbox, 'RAV4 LE.zip', '2025 Toyota RAV4 LE')
            (wh / 'RAV4 LE.db').write_bytes(b'')          # already ingested
            with envp, minp, whp:
                summary = ingest.scan_inbox(normalize=True)
            self.assertEqual(summary['duplicates'], 1)
            self.assertEqual(ZipPackage.objects.get().status, 'skipped_duplicate')

    def test_duplicate_guard_second_copy_in_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox, wh, envp, minp, whp = self._scan_env(tmp)
            sub1 = inbox / 'Toyota_2025'
            sub2 = inbox / 'Downloads'
            sub1.mkdir()
            sub2.mkdir()
            _make_zip(sub1, 'RAV4 LE.zip', '2025 Toyota RAV4 LE')
            _make_zip(sub2, 'LEMON 2025 Toyota RAV4 LE.zip', '2025 Toyota RAV4 LE')
            with envp, minp, whp:
                ingest.scan_inbox(normalize=True)
            statuses = sorted(ZipPackage.objects.values_list('status', flat=True))
            self.assertEqual(statuses, ['pending', 'skipped_duplicate'])

    def test_dry_run_touches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox, wh, envp, minp, whp = self._scan_env(tmp)
            zp = _make_zip(inbox, 'RAV4 LE.zip', '2025 Toyota RAV4 LE')
            with envp, minp, whp:
                summary = ingest.scan_inbox(normalize=True, dry_run=True)
            self.assertEqual(summary['registered'], 1)
            self.assertTrue(zp.exists())                  # not renamed
            self.assertEqual(ZipPackage.objects.count(), 0)


class PendingWorkQueueTest(TestCase):
    def test_queues_feed_pending_work_and_has_work(self):
        with mock.patch.object(pipeline, '_schema_stale_stems', return_value=[]):
            base = pipeline.pending_work()
            self.assertEqual(base['need_download'], 0)
            self.assertEqual(base['need_parse'], 0)

            DownloadRequest.objects.create(url='https://lemon-manuals.org.ua/Toyota/2024/')
            ZipPackage.objects.create(path='/tmp/x.zip', zip_name='x.zip',
                                      stem='X', status='pending')
            work = pipeline.pending_work()
        self.assertEqual(work['need_download'], 1)   # listing not fetched -> 1
        self.assertEqual(work['need_parse'], 1)
        self.assertTrue(work['has_work'])

    def test_download_remaining_counts_vehicles(self):
        DownloadRequest.objects.create(
            url='u', status='running', vehicles_total=19, vehicles_done=4)
        with mock.patch.object(pipeline, '_schema_stale_stems', return_value=[]):
            work = pipeline.pending_work()
        self.assertEqual(work['need_download'], 15)

    def test_stage_definitions_order_and_plans(self):
        keys = [d['key'] for d in pipeline.stage_definitions()]
        self.assertEqual(keys, ['download', 'parse', 'catalog', 'schema',
                                'rag', 'diag', 'audit'])
        work = {'need_download': 3, 'need_parse': 7, 'need_catalog': ['a'],
                'need_schema': ['a', 'b'], 'need_rag_ingest': [],
                'pages_to_embed': 0, 'graph_pending': False, 'need_diag': []}
        plans = {d['key']: d['plan'](work) for d in pipeline.stage_definitions()}
        self.assertEqual(plans['download'], 3)
        self.assertEqual(plans['parse'], 7)
        self.assertEqual(plans['schema'], 2)
        self.assertEqual(plans['audit'], 1)

    def test_estimate_includes_queue_terms(self):
        from .models import PipelineSettings
        st = PipelineSettings.get()
        work = {'need_download': 2, 'need_parse': 3, 'need_schema': [],
                'need_catalog': [], 'need_rag_ingest': [], 'pages_to_embed': 0,
                'graph_pending': False, 'need_diag': []}
        est = pipeline.estimate_duration_s(work, st)
        self.assertGreaterEqual(
            est, 2 * st.download_secs_per_vehicle + 3 * st.parse_secs_per_zip)


class LegacyJobToleranceTest(TestCase):
    def test_runner_stage_lookup_tolerates_missing_stages(self):
        from .management.commands.run_pipeline import Runner
        job = ProcessingJob.objects.create(stages=[
            {'key': 'catalog', 'label': 'x', 'status': 'pending',
             'items_total': 0, 'items_done': 0, 'error': ''}])
        runner = Runner(job)
        self.assertIsNone(runner.stage('download'))
        # run_stage on a stage the job predates is a no-op success
        self.assertTrue(runner.run_stage('download', lambda s: None))

    def test_start_job_plans_new_stages(self):
        ZipPackage.objects.create(path='/tmp/y.zip', zip_name='y.zip',
                                  stem='Y', status='pending')
        with mock.patch.object(pipeline, '_schema_stale_stems', return_value=[]), \
             mock.patch.object(pipeline, '_foreign_build_running', return_value=None), \
             mock.patch.object(pipeline, 'launch_worker', return_value='test'):
            job, err = pipeline.start_job(trigger='manual')
        self.assertIsNone(err)
        keys = [s['key'] for s in job.stages]
        self.assertIn('download', keys)
        self.assertIn('parse', keys)
        self.assertIn('schema', keys)
        parse_stage = next(s for s in job.stages if s['key'] == 'parse')
        self.assertEqual(parse_stage['items_total'], 1)


class ParseZipPackageTest(TestCase):
    def test_missing_file_fails_cleanly(self):
        pkg = ZipPackage.objects.create(path='/nonexistent/z.zip',
                                        zip_name='z.zip', stem='Z',
                                        status='pending')
        self.assertEqual(ingest.parse_zip_package(pkg), 'failed')
        pkg.refresh_from_db()
        self.assertEqual(pkg.status, 'failed')
        self.assertIn('missing', pkg.error)

    def test_existing_stem_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            wh = Path(tmp)
            (wh / 'Z.db').write_bytes(b'')
            zp = _make_zip(tmp, 'LEMON 2025 Toyota Z.zip', '2025 Toyota Z')
            pkg = ZipPackage.objects.create(path=str(zp),
                                            zip_name=zp.name, stem='Z',
                                            status='pending')
            with mock.patch.object(config, 'WAREHOUSE_DIR', wh):
                self.assertEqual(ingest.parse_zip_package(pkg), 'skipped')
            pkg.refresh_from_db()
            self.assertEqual(pkg.status, 'skipped_duplicate')
