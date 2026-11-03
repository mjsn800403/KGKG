"""Staff inbox: list, detail, contact masking and the unread rule."""
import os
import uuid
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from api.models import AdminAuthToken, AuditLog, PlatformAdmin

from .helpers import SupportCase, bearer
from .models import SupportMessage, SupportRating, SupportThread

LIST = '/api/admin/support-chat/threads/'


def detail_url(tid):
    return f'/api/admin/support-chat/threads/{tid}/'


class InboxBase(SupportCase):
    def get(self, url, hdr=None, **params):
        return self.c.get(url, params, **(self.h if hdr is None else hdr))

    def make(self, message='hello', **extra):
        tid, tok, _ = self.create(message=message, client_id=f'c-{uuid.uuid4().hex[:8]}', **extra)
        return tid, tok

    def ids(self, **params):
        return [t['id'] for t in self.get(LIST, **params).json()['threads']]


class AuthTests(InboxBase):
    def test_list_and_detail_need_a_staff_session(self):
        tid, _ = self.make()
        self.assertEqual(self.get(LIST, hdr={}).status_code, 401)
        self.assertEqual(self.get(detail_url(tid), hdr={}).status_code, 401)
        self.assertEqual(self.get(LIST, hdr=bearer('junk')).status_code, 401)

    def test_a_portal_style_or_visitor_token_is_not_staff(self):
        tid, tok = self.make()
        hdr = {'HTTP_X_SUPPORT_CHAT_TOKEN': tok}
        self.assertEqual(self.get(LIST, hdr=hdr).status_code, 401)

    def test_loopback_script_token_is_not_a_person(self):
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'loop-secret'}):
            r = Client(REMOTE_ADDR='127.0.0.1').get(LIST, **bearer('loop-secret'))
        self.assertEqual(r.status_code, 403)

    def test_get_only(self):
        self.assertEqual(self.c.post(LIST, '{}', content_type='application/json',
                                     **self.h).status_code, 405)

    def test_junk_thread_ids_are_404(self):
        self.assertEqual(self.get(detail_url('junk')).status_code, 404)
        self.assertEqual(self.get(detail_url(uuid.uuid4())).status_code, 404)


class ListTests(InboxBase):
    def test_empty_inbox_is_an_empty_list_with_null_not_zero_ready_counts(self):
        d = self.get(LIST).json()
        self.assertEqual(d['threads'], [])
        self.assertIsNone(d['next_cursor'])
        self.assertEqual(d['counts']['all'], 0)

    def test_default_view_hides_closed_and_spam(self):
        a, _ = self.make('open one')
        b, _ = self.make('closed one')
        c, _ = self.make('spam one')
        self.staff(b, 'close')
        SupportThread.objects.filter(pk=c).update(status='spam')
        self.assertEqual(self.ids(), [a])
        self.assertEqual(set(self.ids(status='closed')), {b})
        self.assertEqual(set(self.ids(status='all')), {a, b})          # spam only when asked for
        self.assertEqual(set(self.ids(status='spam')), {c})

    def test_item_shape_and_last_message_preview(self):
        tid, _ = self.make('سلام وقت بخیر', intent='technical')
        self.staff(tid, 'reply', {'message': 'سلام، بفرمایید'})
        item = self.get(LIST).json()['threads'][0]
        self.assertEqual(item['id'], tid)
        self.assertEqual(item['intent'], 'technical')
        self.assertEqual(item['status'], 'waiting_customer')
        self.assertEqual(item['last_message']['author_kind'], 'admin')
        self.assertEqual(item['last_message']['snippet'], 'سلام، بفرمایید')
        self.assertEqual(item['message_count'], 2)
        self.assertIsNone(item['assignee'])
        self.assertNotIn('token_hash', item)
        self.assertNotIn('ua_hash', item)

    def test_an_internal_note_can_be_the_staff_preview_and_is_flagged(self):
        tid, _ = self.make('hello')
        self.staff(tid, 'reply', {'message': 'private note', 'internal': True})
        item = self.get(LIST).json()['threads'][0]
        self.assertEqual(item['last_message']['snippet'], 'private note')
        self.assertTrue(item['last_message']['internal'])

    def test_filters_intent_priority_assignee(self):
        a, _ = self.make('x', intent='sales')
        b, _ = self.make('y', intent='technical')
        SupportThread.objects.filter(pk=b).update(priority='high', assignee=self.admin)
        self.assertEqual(self.ids(intent='sales'), [a])
        self.assertEqual(self.ids(priority='high'), [b])
        self.assertEqual(self.ids(assignee='me'), [b])
        self.assertEqual(self.ids(assignee='none'), [a])
        self.assertEqual(self.ids(assignee=str(self.admin.id)), [b])
        self.assertEqual(self.get(LIST, intent='bogus').status_code, 400)
        self.assertEqual(self.get(LIST, assignee='x').status_code, 400)

    def test_unread_rule_newest_visitor_message_after_staff_seen(self):
        a, tok = self.make('first')
        b, _ = self.make('second')
        self.assertEqual(set(self.ids(unread='1')), {a, b})
        self.staff(a, 'seen')
        self.assertEqual(self.ids(unread='1'), [b])
        # a staff reply does not make it unread; a newer visitor message does
        self.staff(a, 'reply', {'message': 'hi'})
        self.assertEqual(self.ids(unread='1'), [b])
        self.send(f'/api/support-chat/threads/{a}/messages/',
                  {'message': 'more', 'client_id': 'c-more'}, token=tok)
        self.assertEqual(set(self.ids(unread='1')), {a, b})
        flags = {t['id']: t['unread'] for t in self.get(LIST).json()['threads']}
        self.assertTrue(flags[a] and flags[b])

    def test_search_by_id_prefix_and_contact_without_leaking_it_in_the_response(self):
        a, _ = self.make('x')
        b, _ = self.make('y', contact={'name': 'Zahra', 'phone': '09123456789'})
        stored = SupportThread.objects.get(pk=b).contact_phone
        self.assertEqual(self.ids(q=a[:8]), [a])
        self.assertEqual(self.ids(q=stored), [b])
        self.assertEqual(self.ids(q='Zahra'), [b])
        self.assertEqual(self.ids(q='no-such'), [])

    def test_search_never_matches_message_text(self):
        a, _ = self.make('a very private sentence')
        self.assertEqual(self.ids(q='private sentence'), [])

    def test_counts_are_global_to_the_filters_not_the_page(self):
        for i in range(3):
            self.make(f'm{i}')
        c = self.make('closed')[0]
        self.staff(c, 'close')
        d = self.get(LIST, limit=1).json()
        self.assertEqual(len(d['threads']), 1)
        self.assertEqual(d['counts']['active'], 3)
        self.assertEqual(d['counts']['closed'], 1)
        self.assertEqual(d['counts']['unassigned'], 3)
        self.assertEqual(d['counts']['unread'], 3)

    def test_cursor_paging_is_stable_and_complete(self):
        made = [self.make(f'm{i}')[0] for i in range(7)]
        base = timezone.now()
        for i, tid in enumerate(made):                          # distinct, known order
            SupportThread.objects.filter(pk=tid).update(last_activity_at=base - timedelta(minutes=i))
        # two share an identical timestamp: the tie-break must not drop or repeat one
        SupportThread.objects.filter(pk=made[4]).update(
            last_activity_at=base - timedelta(minutes=3))
        seen, cursor = [], None
        for _ in range(10):
            params = {'limit': 3}
            if cursor:
                params['cursor'] = cursor
            d = self.get(LIST, **params).json()
            seen += [t['id'] for t in d['threads']]
            cursor = d['next_cursor']
            if not cursor:
                break
        self.assertEqual(sorted(seen), sorted(made))
        self.assertEqual(len(seen), len(set(seen)))

    def test_bad_cursor_and_limit(self):
        self.assertEqual(self.get(LIST, cursor='garbage').status_code, 400)
        for bad in ('x', '0', '101', '-1'):
            self.assertEqual(self.get(LIST, limit=bad).status_code, 400, bad)

    def test_query_count_does_not_grow_with_the_number_of_threads(self):
        for i in range(2):
            self.make(f'm{i}')
        with CaptureQueriesContext(connection) as small:
            self.get(LIST)
        for i in range(8):
            t, _ = self.make(f'n{i}')
            self.staff(t, 'reply', {'message': 'r'})
        with CaptureQueriesContext(connection) as big:
            self.get(LIST)
        self.assertLessEqual(len(big), len(small) + 1)


class MaskingTests(InboxBase):
    def test_list_and_detail_mask_phone_and_email_by_default(self):
        tid, _ = self.make('x', contact={'name': 'Zahra', 'phone': '09123456789',
                                          'email': 'zahra.k@example.com'})
        phone = SupportThread.objects.get(pk=tid).contact_phone
        item = self.get(LIST).json()['threads'][0]['contact']
        self.assertEqual(item['name'], 'Zahra')
        for raw in (phone, 'zahra.k@example.com'):
            self.assertNotIn(raw, str(item))
        self.assertEqual(item['phone'][-2:], phone[-2:])
        self.assertIn('•', item['phone'])
        self.assertTrue(item['email'].endswith('@example.com'))
        self.assertTrue(item['has_phone'] and item['has_email'])
        d = self.get(detail_url(tid)).json()['thread']['contact']
        self.assertNotIn(phone, str(d))

    def test_reveal_returns_full_contact_and_leaves_an_audit_row_without_contact(self):
        tid, _ = self.make('x', contact={'phone': '09123456789', 'email': 'z@example.com'})
        phone = SupportThread.objects.get(pk=tid).contact_phone
        d = self.get(detail_url(tid), reveal_contact='1').json()['thread']['contact']
        self.assertEqual((d['phone'], d['email']), (phone, 'z@example.com'))
        row = AuditLog.objects.get(action='support_chat.reveal_contact')
        self.assertEqual((row.actor_id, row.target_id), (self.admin.id, tid))
        self.assertNotIn(phone[-6:], str(row.detail))
        self.assertNotIn('example.com', str(row.detail))

    def test_a_thread_without_contact_reveals_nothing_and_logs_nothing(self):
        tid, _ = self.make('x')
        self.get(detail_url(tid), reveal_contact='1')
        self.assertFalse(AuditLog.objects.filter(action='support_chat.reveal_contact').exists())


class DetailTests(InboxBase):
    def test_detail_has_all_messages_including_internal_and_authors(self):
        tid, tok = self.make('hello')
        self.staff(tid, 'reply', {'message': 'public answer'})
        self.staff(tid, 'reply', {'message': 'note to self', 'internal': True})
        d = self.get(detail_url(tid)).json()
        rows = [(m['author_kind'], m['body'], m['internal']) for m in d['messages']]
        self.assertEqual(rows, [('visitor', 'hello', False), ('admin', 'public answer', False),
                                ('admin', 'note to self', True)])
        self.assertEqual(d['messages'][1]['author'], {'id': self.admin.id, 'username': 'ann'})
        self.assertIsNone(d['messages'][0]['author'])

    def test_after_param_returns_only_newer_messages(self):
        tid, _ = self.make('hello')
        first = self.get(detail_url(tid)).json()['messages'][0]['id']
        self.staff(tid, 'reply', {'message': 'more'})
        d = self.get(detail_url(tid), after=first).json()
        self.assertEqual([m['body'] for m in d['messages']], ['more'])

    def test_detail_exposes_thread_facts_and_rating_history_but_no_secrets(self):
        tid, tok = self.make('hello', page='/pricing?utm=1', referrer='https://x.test/a?b=1')
        self.staff(tid, 'close')
        SupportRating.objects.create(thread_id=tid, score=4, closure=0)
        self.staff(tid, 'reopen')
        self.staff(tid, 'close')
        SupportRating.objects.create(thread_id=tid, score=2, closure=1)
        t = self.get(detail_url(tid)).json()
        th = t['thread']
        self.assertEqual((th['status'], th['reopen_count'], th['intent']), ('closed', 1, 'sales'))
        self.assertEqual(th['source_page'], '/pricing')
        self.assertEqual([(r['closure'], r['score']) for r in t['ratings']], [(0, 4), (1, 2)])
        flat = str(t)
        self.assertNotIn('token_hash', flat)
        self.assertNotIn('ua_hash', flat)
        self.assertNotIn(tok, flat)

    def test_detail_does_not_mark_seen(self):
        tid, _ = self.make('hello')
        self.get(detail_url(tid))
        self.assertIsNone(SupportThread.objects.get(pk=tid).staff_seen_at)

    def test_detail_of_a_spam_thread_is_still_available_to_staff(self):
        tid, _ = self.make('buy now')
        SupportThread.objects.filter(pk=tid).update(status='spam')
        self.assertEqual(self.get(detail_url(tid)).status_code, 200)

    def test_assignee_is_a_username_and_id_only(self):
        tid, _ = self.make('x')
        SupportThread.objects.filter(pk=tid).update(assignee=self.admin)
        a = self.get(detail_url(tid)).json()['thread']['assignee']
        self.assertEqual(a, {'id': self.admin.id, 'username': 'ann'})


class NoSideEffectsTests(InboxBase):
    def test_reading_the_inbox_writes_nothing_and_does_not_audit_content(self):
        tid, _ = self.make('secret words', contact={'phone': '09123456789'})
        audits = AuditLog.objects.count()
        msgs = SupportMessage.objects.count()
        self.get(LIST)
        self.get(detail_url(tid))
        self.assertEqual(AuditLog.objects.count(), audits)
        self.assertEqual(SupportMessage.objects.count(), msgs)
