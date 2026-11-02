"""The QA fixture seeder must refuse to run anywhere but the QA stack."""
import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from api.management.commands import seed_qa_fixtures as seed
from api.models import Car, PortalUser, UserCarAccess

PW = 'x' * 20


class SeedGuardTest(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        p = mock.patch.object(seed, 'db_dir', return_value=self.dir)
        p.start()
        self.addCleanup(p.stop)
        # The test database itself is whatever CI runs (SQLite or PostgreSQL
        # test_kgkg); the target check is exercised explicitly below.
        t = mock.patch.object(seed, 'db_target', return_value=('sqlite', 'qa.sqlite3'))
        self.target = t.start()
        self.addCleanup(t.stop)
        Car.objects.create(brand_name='Toyota', car_name='Corolla Cross Hybrid S', year=2025,
                           db_address='/nonexistent.db')

    def run_seed(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            for k in ('KG_QA_STACK', 'KG_QA_PASSWORD'):
                if k not in env:
                    os.environ.pop(k, None)
            out = StringIO()
            call_command('seed_qa_fixtures', stdout=out)
            return out.getvalue()

    def test_refuses_without_the_env_flag(self):
        (self.dir / seed.MARKER).write_text('')
        with self.assertRaisesRegex(CommandError, 'KG_QA_STACK'):
            self.run_seed({'KG_QA_PASSWORD': PW})
        self.assertFalse(PortalUser.objects.filter(username__startswith='qa_e2e_').exists())

    def test_refuses_on_a_database_without_the_marker(self):
        # The production database directory never holds the marker.
        with self.assertRaisesRegex(CommandError, 'missing'):
            self.run_seed({'KG_QA_STACK': '1', 'KG_QA_PASSWORD': PW})
        self.assertFalse(PortalUser.objects.filter(username__startswith='qa_e2e_').exists())

    def test_refuses_a_weak_password(self):
        (self.dir / seed.MARKER).write_text('')
        with self.assertRaisesRegex(CommandError, '16'):
            self.run_seed({'KG_QA_STACK': '1', 'KG_QA_PASSWORD': 'short'})

    def test_seeds_password_only_accounts_idempotently(self):
        (self.dir / seed.MARKER).write_text('')
        env = {'KG_QA_STACK': '1', 'KG_QA_PASSWORD': PW}
        self.run_seed(env)
        out = json.loads(self.run_seed(env))   # second run updates, never duplicates
        users = PortalUser.objects.filter(username__startswith='qa_e2e_')
        self.assertEqual(users.count(), 4)
        mgr = users.get(username='qa_e2e_manager')
        self.assertTrue(mgr.check_password(PW))
        self.assertEqual(mgr.phone, '')                 # password-only: no SMS
        self.assertTrue(users.get(username='qa_e2e_locked').locked)
        self.assertNotEqual(users.get(username='qa_e2e_other').company_id, mgr.company_id)
        self.assertEqual(UserCarAccess.objects.filter(user=mgr).count(), 1)
        self.assertFalse(UserCarAccess.objects.filter(
            user=users.get(username='qa_e2e_specialist')).exists())
        # Each printed token is a working session for its own account.
        # `desk_admin` was added on 2026-10-31: a platform-side session, so an
        # E2E can exercise the support desk's two-sided behaviour. A customer
        # cannot create their own unread, so without it the unread test could
        # not assert anything real.
        self.assertEqual(set(out['tokens']),
                         {'manager', 'specialist', 'other', 'manager_logout', 'desk_admin'})
        me = self.client.get('/api/auth/me/', HTTP_AUTHORIZATION=f"Bearer {out['tokens']['other']}")
        self.assertEqual(me.status_code, 200, me.content)
        self.assertIn('qa_e2e_other', me.content.decode())
        # The desk account is a PlatformAdmin, not a fifth portal seat: the
        # count above must stay at four, and its token must not pass as one.
        self.assertEqual(users.count(), 4)
        seat = self.client.get('/api/auth/me/',
                               HTTP_AUTHORIZATION=f"Bearer {out['tokens']['desk_admin']}")
        self.assertIn(seat.status_code, (401, 403))

    def test_refuses_a_postgres_database_that_is_not_a_qa_copy(self):
        # Since the PostgreSQL cutover the QA backend reads .env.prod, whose
        # connection points at production's `kgkg`. The marker sits in the QA
        # data directory either way, so the guard must judge the database itself.
        (self.dir / seed.MARKER).write_text('')
        env = {'KG_QA_STACK': '1', 'KG_QA_PASSWORD': PW}
        for name in ('kgkg', 'kgkg_staging', 'qa_kgkg', ''):
            self.target.return_value = ('postgres', name)
            with self.assertRaisesRegex(CommandError, '_qa'):
                self.run_seed(env)
        self.assertFalse(PortalUser.objects.filter(username__startswith='qa_e2e_').exists())

    def test_accepts_the_qa_postgres_copy(self):
        (self.dir / seed.MARKER).write_text('')
        self.target.return_value = ('postgres', 'kgkg_qa')
        out = json.loads(self.run_seed({'KG_QA_STACK': '1', 'KG_QA_PASSWORD': PW}))
        self.assertIn('manager', out['tokens'])
