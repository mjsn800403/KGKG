"""Retention enforcement is built but disabled: nothing is deleted unless the
owner has approved a policy (KG_SUPPORT_RETENTION_ENABLED=1) AND the operator
passes --apply. The day counts below are the PROPOSED values, used for
reporting until they are approved."""
import io
import os
from datetime import timedelta
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from api.models import Company, CompanyRequest

from .models import SupportMessage, SupportRating, SupportThread


def _thread(n, idle_days, **kw):
    t = SupportThread.objects.create(token_hash=f'{n:064d}', **kw)
    SupportThread.objects.filter(pk=t.pk).update(
        last_activity_at=timezone.now() - timedelta(days=idle_days))
    return t.pk


def _run(*args, enabled=False):
    out = io.StringIO()
    env = {'KG_SUPPORT_RETENTION_ENABLED': '1'} if enabled else {}
    with mock.patch.dict(os.environ, env):
        if not enabled:
            os.environ.pop('KG_SUPPORT_RETENTION_ENABLED', None)
        call_command('purge_support_chat', *args, stdout=out)
    return out.getvalue()


def _exists(pk):
    return SupportThread.objects.filter(pk=pk).exists()


class DisabledByDefaultTests(TestCase):
    def setUp(self):
        self.old = _thread(1, 4000)

    def test_a_plain_run_only_reports(self):
        text = _run()
        self.assertTrue(_exists(self.old))
        self.assertIn('would delete 1', text)
        self.assertIn('retention is DISABLED', text)

    def test_apply_is_refused_while_retention_is_not_enabled(self):
        with self.assertRaises(CommandError):
            _run('--apply')
        self.assertTrue(_exists(self.old))

    def test_the_enabled_flag_alone_does_not_delete_without_apply(self):
        _run(enabled=True)
        self.assertTrue(_exists(self.old))


class ProposedPolicyTests(TestCase):
    """What enforcement would do, once approved (exercised with both switches on)."""

    def test_no_contact_30_days(self):
        old, recent = _thread(2, 31), _thread(3, 29)
        _run('--apply', enabled=True)
        self.assertFalse(_exists(old))
        self.assertTrue(_exists(recent))

    def test_contact_180_days(self):
        kept = _thread(4, 179, contact_phone='09123456789')
        gone = _thread(5, 181, contact_email='a@example.com')
        _run('--apply', enabled=True)
        self.assertTrue(_exists(kept))
        self.assertFalse(_exists(gone))

    def test_spam_7_days(self):
        gone, kept = _thread(6, 8, status='spam', contact_phone='09123456789'), _thread(7, 6, status='spam')
        _run('--apply', enabled=True)
        self.assertFalse(_exists(gone))
        self.assertTrue(_exists(kept))

    def test_promoted_threads_30_days(self):
        co = Company.objects.create(name='Acme')
        req = CompanyRequest.objects.create(company=co, subject='s')
        gone = _thread(8, 31, promoted_request=req, contact_phone='09123456789')
        kept = _thread(9, 29, promoted_request=req, contact_phone='09123456789')
        _run('--apply', enabled=True)
        self.assertFalse(_exists(gone))
        self.assertTrue(_exists(kept))

    def test_messages_and_ratings_go_with_their_thread(self):
        pk = _thread(10, 90)
        t = SupportThread.objects.get(pk=pk)
        t.messages.create(author_kind='visitor', body='x')
        SupportRating.objects.create(thread=t, score=4)
        _run('--apply', enabled=True)
        self.assertEqual((SupportMessage.objects.count(), SupportRating.objects.count()), (0, 0))

    def test_the_periods_are_configurable(self):
        pk = _thread(11, 40)
        with mock.patch.dict(os.environ, {'KG_SUPPORT_RETENTION_NO_CONTACT_DAYS': '60'}):
            _run('--apply', enabled=True)
        self.assertTrue(_exists(pk))
