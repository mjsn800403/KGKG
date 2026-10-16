"""api/hostjobs.py (container -> host bridge) and its host daemon's allow-list."""
import importlib.util
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from api import hostjobs

DAEMON = Path(settings.BASE_DIR).parent / 'ops' / 'hostjobs' / 'hostjobs_daemon.py'


def load_daemon(spool):
    env = {'KG_BACKEND_DIR': str(settings.BASE_DIR), 'KG_HOSTJOBS_DIR': spool}
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location('hostjobs_daemon', DAEMON)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class LocalModeTests(SimpleTestCase):
    def test_local_pgrep_finds_this_process_but_not_itself(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('KG_HOSTJOBS_DIR', None)
            self.assertFalse(hostjobs.enabled())
            self.assertNotIn(os.getpid(), hostjobs.pgrep(r'manage\.py'))
            self.assertTrue(hostjobs.pid_alive(os.getpid()))


class BridgeTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.spool = self.tmp.name
        self.daemon = load_daemon(self.spool)
        for d in ('req', 'resp'):
            Path(self.spool, d).mkdir()
        self.stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()
        self.env = mock.patch.dict(os.environ, {'KG_HOSTJOBS_DIR': self.spool})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.stop.set()
        self.tmp.cleanup()

    def _serve(self):
        while not self.stop.is_set():
            for f in Path(self.spool, 'req').glob('*.json'):
                self.daemon.handle(f)
            time.sleep(0.02)

    def test_procs_round_trip(self):
        self.assertTrue(hostjobs.enabled())
        self.assertTrue(hostjobs.pid_alive(os.getpid()))

    def test_unknown_action_is_refused(self):
        with self.assertRaises(hostjobs.HostJobError):
            hostjobs.call('shell', timeout=5, cmd='id')

    def test_unit_stop_only_pipeline_units(self):
        with self.assertRaisesRegex(hostjobs.HostJobError, 'unit not allowed'):
            hostjobs.call('unit_stop', timeout=5, unit='ssh.service')

    def test_crawl_start_only_crawl_units(self):
        with self.assertRaisesRegex(hostjobs.HostJobError, 'unit not allowed'):
            hostjobs.call('tis_crawl_start', timeout=5, unit='kgkg-tis-crawl-1; reboot')

    def test_term_refuses_unrelated_process(self):
        with self.assertRaisesRegex(hostjobs.HostJobError, 'process not allowed'):
            hostjobs.terminate(os.getpid(), 'pipeline')

    def test_pipeline_launch_rejects_foreign_env_and_plan(self):
        base = dict(job_id=1, attempt=1, nice=15, cpu_weight=25, io_class='idle')
        with self.assertRaisesRegex(hostjobs.HostJobError, 'environment LD_PRELOAD'):
            hostjobs.call('pipeline_launch', timeout=5, env={'LD_PRELOAD': '/x.so'}, **base)
        with self.assertRaisesRegex(hostjobs.HostJobError, 'environment OMP_NUM_THREADS'):
            hostjobs.call('pipeline_launch', timeout=5, env={'OMP_NUM_THREADS': '1 --x'}, **base)
        with self.assertRaisesRegex(hostjobs.HostJobError, 'CPU plan'):
            hostjobs.call('pipeline_launch', timeout=5, **{**base, 'io_class': 'realtime'})

    def test_pipeline_launch_builds_host_command(self):
        ran = {}

        def fake_run(cmd, **kw):
            ran['cmd'] = cmd
            return mock.Mock(returncode=0, stderr='')
        with mock.patch.object(self.daemon.subprocess, 'run', fake_run):
            unit = hostjobs.call('pipeline_launch', timeout=5, job_id=7, attempt=2, nice=15,
                                 cpu_weight=25, io_class='idle', env={'OMP_NUM_THREADS': '12'})
        self.assertEqual(unit, 'kgkg-pipeline-job7-a2')
        self.assertEqual(ran['cmd'][-5:], [str(self.daemon.HOST_PYTHON), 'manage.py',
                                           'run_pipeline', '--job', '7'])
        self.assertIn('--setenv=OMP_NUM_THREADS=12', ran['cmd'])
