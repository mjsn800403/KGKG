"""Assign, priority, intent, spam/restore and the admin-feed update events."""
import os
import uuid
from unittest import mock

from django.test import Client

from api.models import AdminAuthToken, AuditLog, Event, PlatformAdmin

from .helpers import SupportCase, bearer
from .models import SupportMessage, SupportThread


class ActionBase(SupportCase):
    def make(self, message='secret words', **extra):
        tid, tok, _ = self.create(message=message, **extra)
        return tid, tok

    def thread(self, tid):
        return SupportThread.objects.get(pk=tid)

    def updates(self, tid):
        return [e for e in Event.objects.filter(type='support_chat.updated')
                if e.payload.get('thread_id') == tid]


class AssignTests(ActionBase):
    def test_assign_to_self_by_shorthand_and_by_id(self):
        tid, _ = self.make()
        self.assertEqual(self.staff(tid, 'assign', {'admin': 'me'}).status_code, 200)
        self.assertEqual(self.thread(tid).assignee_id, self.admin.id)
        bob = PlatformAdmin.objects.create(username='bob', password_hash='x', active=True)
        r = self.staff(tid, 'assign', {'admin': bob.id})
        self.assertEqual(r.json()['assignee'], {'id': bob.id, 'username': 'bob'})
        self.assertEqual(self.thread(tid).assignee_id, bob.id)

    def test_unassign_with_null(self):
        tid, _ = self.make()
        self.staff(tid, 'assign', {'admin': 'me'})
        self.assertEqual(self.staff(tid, 'assign', {'admin': None}).status_code, 200)
        self.assertIsNone(self.thread(tid).assignee_id)

    def test_cannot_assign_to_an_unknown_inactive_or_malformed_admin(self):
        tid, _ = self.make()
        gone = PlatformAdmin.objects.create(username='gone', password_hash='x', active=False)
        for bad in (99999, gone.id, 'bob', True, 1.5, [1]):
            self.assertEqual(self.staff(tid, 'assign', {'admin': bad}).status_code, 400, bad)
        self.assertIsNone(self.thread(tid).assignee_id)

    def test_assign_requires_the_field(self):
        tid, _ = self.make()
        self.assertEqual(self.staff(tid, 'assign', {}).status_code, 400)

    def test_assign_does_not_change_status_or_activity(self):
        tid, _ = self.make()
        before = self.thread(tid)
        self.staff(tid, 'assign', {'admin': 'me'})
        after = self.thread(tid)
        self.assertEqual((after.status, after.last_activity_at),
                         (before.status, before.last_activity_at))

    def test_assign_writes_no_visitor_visible_message(self):
        tid, tok = self.make()
        self.staff(tid, 'assign', {'admin': 'me'})
        self.assertEqual(len(self.poll(tid, tok).json()['messages']), 1)


class PriorityIntentTests(ActionBase):
    def test_priority_values(self):
        tid, _ = self.make()
        for p in ('low', 'high', 'urgent', 'normal'):
            self.assertEqual(self.staff(tid, 'priority', {'priority': p}).status_code, 200)
            self.assertEqual(self.thread(tid).priority, p)
        for bad in ('', 'critical', None, 3):
            self.assertEqual(self.staff(tid, 'priority', {'priority': bad}).status_code, 400)

    def test_intent_values(self):
        tid, _ = self.make(intent='sales')
        self.assertEqual(self.staff(tid, 'intent', {'intent': 'technical'}).status_code, 200)
        self.assertEqual(self.thread(tid).intent, 'technical')
        self.assertEqual(self.staff(tid, 'intent', {'intent': 'bogus'}).status_code, 400)
        self.assertEqual(self.thread(tid).intent, 'technical')


class SpamTests(ActionBase):
    def test_spam_hides_the_thread_from_the_visitor_and_restore_returns_it(self):
        tid, tok = self.make()
        self.assertEqual(self.staff(tid, 'spam').status_code, 200)
        self.assertEqual(self.thread(tid).status, 'spam')
        self.assertEqual(self.poll(tid, tok).status_code, 404)
        self.assertEqual(self.staff(tid, 'restore').status_code, 200)
        self.assertEqual(self.thread(tid).status, 'waiting_staff')
        self.assertEqual(self.poll(tid, tok).status_code, 200)

    def test_spam_leaves_no_message_for_the_visitor_and_double_spam_is_409(self):
        tid, _ = self.make()
        self.staff(tid, 'spam')
        self.assertEqual(SupportMessage.objects.filter(thread_id=tid, author_kind='system').count(), 0)
        self.assertEqual(self.staff(tid, 'spam').status_code, 409)

    def test_restore_only_applies_to_spam(self):
        tid, _ = self.make()
        self.assertEqual(self.staff(tid, 'restore').status_code, 409)


class CommonRulesTests(ActionBase):
    ACTIONS = (('assign', {'admin': 'me'}), ('priority', {'priority': 'high'}),
               ('intent', {'intent': 'other'}), ('spam', {}), ('restore', {}))

    def test_every_action_needs_a_staff_person(self):
        tid, _ = self.make()
        for name, body in self.ACTIONS:
            self.assertEqual(self.staff(tid, name, body, hdr={}).status_code, 401, name)
            with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'loop-secret'}):
                r = Client(REMOTE_ADDR='127.0.0.1').post(
                    f'/api/admin/support-chat/threads/{tid}/{name}/', '{}',
                    content_type='application/json', **bearer('loop-secret'))
            self.assertEqual(r.status_code, 403, name)

    def test_post_only_and_junk_ids(self):
        tid, _ = self.make()
        for name, body in self.ACTIONS:
            self.assertEqual(self.c.get(f'/api/admin/support-chat/threads/{tid}/{name}/',
                                        **self.h).status_code, 405, name)
            self.assertEqual(self.staff(str(uuid.uuid4()), name, body).status_code, 404, name)
            self.assertEqual(self.staff('junk', name, body).status_code, 404, name)

    def test_audit_rows_carry_ids_and_enums_only_never_content_or_contact(self):
        tid, _ = self.make('very private message', contact={'phone': '09123456789',
                                                              'email': 'z@example.com'})
        self.staff(tid, 'assign', {'admin': 'me'})
        self.staff(tid, 'priority', {'priority': 'high'})
        self.staff(tid, 'intent', {'intent': 'technical'})
        self.staff(tid, 'spam')
        self.staff(tid, 'restore')
        rows = AuditLog.objects.filter(action__startswith='support_chat.').order_by('id')
        self.assertEqual([r.action for r in rows],
                         ['support_chat.assign', 'support_chat.priority', 'support_chat.intent',
                          'support_chat.spam', 'support_chat.restore'])
        for r in rows:
            self.assertEqual((r.actor_id, r.target_id), (self.admin.id, tid))
            flat = f'{r.detail} {r.actor_label} {r.target_id}'
            for leak in ('very private', '0912', 'example.com'):
                self.assertNotIn(leak, flat)
        self.assertEqual(rows[0].detail, {'assignee_id': self.admin.id})
        self.assertEqual(rows[1].detail, {'from': 'normal', 'to': 'high'})
        self.assertEqual(rows[2].detail, {'from': 'sales', 'to': 'technical'})

    def test_every_change_emits_one_admin_feed_update_with_ids_only(self):
        tid, _ = self.make()
        Event.objects.all().delete()
        self.staff(tid, 'assign', {'admin': 'me'})
        self.staff(tid, 'priority', {'priority': 'high'})
        self.staff(tid, 'reply', {'message': 'text must not travel in events'})
        self.staff(tid, 'close')
        self.staff(tid, 'reopen')
        evs = self.updates(tid)
        self.assertEqual(len(evs), 5)
        for e in evs:
            self.assertEqual(e.audience, 'admin')
            self.assertEqual(set(e.payload), {'thread_id', 'kind'})
            self.assertNotIn('text must not travel', str(e.payload))
        self.assertEqual([e.payload['kind'] for e in evs],
                         ['assign', 'priority', 'reply', 'close', 'reopen'])

    def test_rejected_actions_emit_and_audit_nothing(self):
        tid, _ = self.make()
        Event.objects.all().delete()
        audits = AuditLog.objects.count()
        self.staff(tid, 'priority', {'priority': 'bogus'})
        self.staff(tid, 'restore')
        self.assertEqual(self.updates(tid), [])
        self.assertEqual(AuditLog.objects.count(), audits)

    def test_a_noop_change_is_not_audited_or_announced(self):
        tid, _ = self.make()
        self.staff(tid, 'priority', {'priority': 'high'})
        Event.objects.all().delete()
        audits = AuditLog.objects.count()
        self.assertEqual(self.staff(tid, 'priority', {'priority': 'high'}).status_code, 200)
        self.assertEqual(self.updates(tid), [])
        self.assertEqual(AuditLog.objects.count(), audits)
