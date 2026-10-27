"""The QA fixture seeder must refuse to run anywhere but the QA stack."""
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
        Car.objects.create(brand_name='Toyota', car_name='Corolla Cross', year=2025,
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
        self.run_seed(env)   # second run updates, never duplicates
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
