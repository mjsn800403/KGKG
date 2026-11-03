"""Concurrent staff actions on one thread serialise on its row lock.

Skipped on in-memory SQLite (threads cannot share it); runs on PostgreSQL in CI
and on file-backed SQLite locally.
"""
import json

from django.test import Client

from api.models import AuditLog, PlatformAdmin

from .helpers import SupportTxCase, admin_url, run_parallel
from .models import SupportMessage, SupportThread


class ConcurrentActionTests(SupportTxCase):
    def act(self, tid, action, body=None):
        return Client().post(admin_url(tid, action), json.dumps(body or {}),
                             content_type='application/json', **self.h)

    def test_two_closes_write_one_closure(self):
        tid, _ = self.new_thread()
        codes = run_parallel(2, lambda i: self.act(tid, 'close').status_code)
        self.assertEqual(sorted(codes), [200, 409])
        self.assertEqual(SupportMessage.objects.filter(thread_id=tid, author_kind='system').count(), 1)
        self.assertEqual(AuditLog.objects.filter(action='support_chat.close').count(), 1)

    def test_assign_and_close_both_apply_without_losing_either(self):
        tid, _ = self.new_thread()
        PlatformAdmin.objects.create(username='bob', password_hash='x', active=True)
        run_parallel(2, lambda i: (self.act(tid, 'assign', {'admin': 'me'}) if i == 0
                                   else self.act(tid, 'close')).status_code)
        t = SupportThread.objects.get(pk=tid)
        self.assertEqual((t.status, t.assignee_id), ('closed', self.admin.id))

    def test_competing_assignments_end_with_exactly_one_assignee_and_two_audits(self):
        tid, _ = self.new_thread()
        bob = PlatformAdmin.objects.create(username='bob', password_hash='x', active=True)
        run_parallel(2, lambda i: self.act(tid, 'assign', {'admin': bob.id if i else 'me'}).status_code)
        t = SupportThread.objects.get(pk=tid)
        self.assertIn(t.assignee_id, (self.admin.id, bob.id))
        self.assertEqual(AuditLog.objects.filter(action='support_chat.assign').count(), 2)
