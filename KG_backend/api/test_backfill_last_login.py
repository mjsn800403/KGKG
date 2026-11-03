"""backfill_last_login (#49): fills only null values, from the newest login row."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from api.models import ActivityLog, Company, PortalUser


class BackfillLastLoginTests(TestCase):
    def setUp(self):
        co = Company.objects.create(name='BF-Co')
        self.old = PortalUser.objects.create(company=co, username='bf_old')
        self.recent = PortalUser.objects.create(company=co, username='bf_recent')
        self.never = PortalUser.objects.create(company=co, username='bf_never')
        self.t1 = timezone.now() - timedelta(days=90)
        self.t2 = timezone.now() - timedelta(days=80)
        for at in (self.t1, self.t2):
            a = ActivityLog.objects.create(user=self.old, action='login')
            ActivityLog.objects.filter(pk=a.pk).update(created_at=at)
        ActivityLog.objects.create(user=self.never, action='view_car')
        self.now = timezone.now()
        self.recent.last_login_at = self.now
        self.recent.save(update_fields=['last_login_at'])
        ActivityLog.objects.create(user=self.recent, action='login')

    def _run(self, *args):
        out = StringIO()
        call_command('backfill_last_login', *args, stdout=out)
        return out.getvalue()

    def test_fills_null_from_newest_login_and_leaves_the_rest(self):
        self.assertIn('backfilled 1 account', self._run())
        for u in (self.old, self.recent, self.never):
            u.refresh_from_db()
        self.assertEqual(self.old.last_login_at, self.t2)
        self.assertEqual(self.recent.last_login_at, self.now)
        self.assertIsNone(self.never.last_login_at)
        self.assertIn('backfilled 0 account', self._run())

    def test_dry_run_writes_nothing(self):
        self.assertIn('would backfill 1 account', self._run('--dry-run'))
        self.old.refresh_from_db()
        self.assertIsNone(self.old.last_login_at)
