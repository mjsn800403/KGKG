"""Retention: anonymous threads do not live forever."""
import io
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from api.models import Company, CompanyRequest

from .models import ChatThread


def _thread(n, idle_days, **kw):
    t = ChatThread.objects.create(token_hash=f'{n:064d}', **kw)
    ChatThread.objects.filter(pk=t.pk).update(
        last_activity_at=timezone.now() - timedelta(days=idle_days))
    return t.pk


def _run(*args):
    out = io.StringIO()
    call_command('purge_chat', *args, stdout=out)
    return out.getvalue()


class PurgeTests(TestCase):
    def test_purges_idle_anonymous_but_not_recent(self):
        old, recent = _thread(1, 31), _thread(2, 29)
        _run()
        self.assertFalse(ChatThread.objects.filter(pk=old).exists())
        self.assertTrue(ChatThread.objects.filter(pk=recent).exists())

    def test_contact_threads_kept_until_12_months(self):
        kept = _thread(3, 200, contact_phone='09123456789')
        gone = _thread(4, 366, contact_email='a@example.com')
        _run()
        self.assertTrue(ChatThread.objects.filter(pk=kept).exists())
        self.assertFalse(ChatThread.objects.filter(pk=gone).exists())

    def test_promoted_threads_never_purged(self):
        co = Company.objects.create(name='Acme')
        req = CompanyRequest.objects.create(company=co, subject='s')
        pk = _thread(5, 900, promoted_request=req)
        _run()
        self.assertTrue(ChatThread.objects.filter(pk=pk).exists())

    def test_dry_run_deletes_nothing_and_reports(self):
        pk = _thread(6, 90)
        text = _run('--dry-run')
        self.assertTrue(ChatThread.objects.filter(pk=pk).exists())
        self.assertIn('would delete 1', text)

    def test_messages_go_with_their_thread(self):
        pk = _thread(7, 90)
        ChatThread.objects.get(pk=pk).messages.create(author_kind='visitor', body='x')
        _run()
        from .models import ChatMessage
        self.assertEqual(ChatMessage.objects.count(), 0)
