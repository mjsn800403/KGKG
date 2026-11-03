"""C1: customer content and contact details must not persist in audit or event
logs, while staff actions stay traceable by id."""
import json

from api.models import AuditLog, Event

from .helpers import SupportCase
from .models import SupportThread

SECRETS = ('please call me about pricing', '09121112222', 'visitor@example.com', '5.6.7.8')


def _dump_audit():
    return json.dumps([[a.path, a.ip, a.user_agent, a.actor_label, a.detail]
                       for a in AuditLog.objects.all()], ensure_ascii=False, default=str)


class AuditPrivacyTests(SupportCase):
    def test_visitor_calls_leave_no_content_contact_or_ip_in_the_audit_log(self):
        tid, token, _ = self.create(message='please call me about pricing',
                                    contact={'phone': '09121112222', 'email': 'visitor@example.com'},
                                    HTTP_CF_CONNECTING_IP='5.6.7.8')
        self.send(f'/api/support-chat/threads/{tid}/messages/',
                  {'message': 'please call me about pricing', 'client_id': 'c-2'}, token,
                  HTTP_CF_CONNECTING_IP='5.6.7.8')
        self.send(f'/api/support-chat/threads/{tid}/contact/',
                  {'phone': '09121112222', 'email': 'visitor@example.com'}, token, method='patch',
                  HTTP_CF_CONNECTING_IP='5.6.7.8')
        dump = _dump_audit()
        for secret in SECRETS:
            self.assertNotIn(secret, dump)
        self.assertEqual(AuditLog.objects.filter(path__startswith='/api/support-chat/').count(), 0)

    def test_event_payloads_carry_ids_only(self):
        tid, _, _ = self.create(message='please call me about pricing',
                                contact={'phone': '09121112222'})
        ev = Event.objects.get(type='support_chat.message')
        self.assertEqual(set(ev.payload), {'thread_id', 'intent'})
        for secret in SECRETS:
            self.assertNotIn(secret, json.dumps(ev.payload))
        self.assertEqual(ev.payload['thread_id'], tid)

    def test_staff_actions_are_audited_with_actor_and_ids_but_no_content(self):
        tid, _, _ = self.create()
        self.staff(tid, 'reply', {'message': 'a confidential reply body'})
        self.staff(tid, 'close')
        self.staff(tid, 'reopen')
        rows = {a.action: a for a in AuditLog.objects.filter(action__startswith='support_chat.')}
        self.assertEqual(set(rows), {'support_chat.reply', 'support_chat.close',
                                     'support_chat.reopen'})
        for row in rows.values():
            self.assertEqual((row.actor_type, row.actor_id, row.actor_label),
                             (AuditLog.ADMIN, self.admin.id, 'ann'))
            self.assertEqual((row.target_type, row.target_id), ('support_thread', tid))
            self.assertNotIn('confidential', json.dumps(row.detail))
        self.assertNotIn('confidential', _dump_audit())

    def test_visitor_reopen_is_audited_without_ip_or_content(self):
        tid, token, _ = self.create(HTTP_CF_CONNECTING_IP='5.6.7.8')
        self.staff(tid, 'close')
        self.send(f'/api/support-chat/threads/{tid}/reopen/', {}, token,
                  HTTP_CF_CONNECTING_IP='5.6.7.8')
        row = AuditLog.objects.get(action='support_chat.visitor_reopen')
        self.assertEqual((row.actor_type, row.ip, row.target_id), (AuditLog.ANONYMOUS, '', tid))


class StoredUrlTests(SupportCase):
    def test_source_page_and_referrer_lose_query_and_fragment(self):
        tid, _, _ = self.create(page='/purchase?plan=pro&phone=09121112222#top',
                                referrer='https://www.google.com/search?q=my+secret#x')
        t = SupportThread.objects.get(pk=tid)
        self.assertEqual(t.source_page, '/purchase')
        self.assertEqual(t.referrer, 'https://www.google.com/search')

    def test_non_http_referrer_and_junk_are_dropped(self):
        tid, _, _ = self.create(page='javascript:alert(1)', referrer='data:text/html,<b>')
        t = SupportThread.objects.get(pk=tid)
        self.assertEqual((t.source_page, t.referrer), ('', ''))
