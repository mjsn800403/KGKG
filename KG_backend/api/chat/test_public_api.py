"""Anonymous visitor API: create a thread, post, poll, contact, rate."""
import hashlib
import json
from unittest import mock

from django.test import Client, TestCase

from api import ratelimit
from api.models import Event

from .models import ChatMessage, ChatThread

CREATE = '/api/chat/threads/'


def _msgs(tid):
    return f'/api/chat/threads/{tid}/messages/'


def _hdr(token):
    return {'HTTP_X_CHAT_TOKEN': token} if token else {}


class PublicBase(TestCase):
    def setUp(self):
        ratelimit._HITS.clear()
        self.c = Client()
        p = mock.patch('api.chat.views_public._verify_turnstile', return_value=True)
        self.turnstile = p.start()
        self.addCleanup(p.stop)

    def post(self, url, body, token=None, method='post'):
        return getattr(self.c, method)(url, json.dumps(body), content_type='application/json',
                                       **_hdr(token))

    def create(self, message='سلام، قیمت اشتراک چند است؟', **extra):
        body = dict(message=message, client_id='c-first', intent='sales')
        body.update(extra)
        r = self.post(CREATE, body)
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        return d['thread_id'], d['token'], d


class CreateTests(PublicBase):
    def test_create_returns_token_once_and_stores_only_hash(self):
        tid, token, d = self.create()
        t = ChatThread.objects.get(pk=tid)
        self.assertEqual(t.token_hash, hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, json.dumps(
            {'hash': t.token_hash, 'contact': t.contact_name}))
        self.assertEqual(t.intent, 'sales')
        self.assertEqual(t.status, 'waiting_staff')
        self.assertEqual(d['mode'], 'async')
        self.assertEqual(d['message']['body'], 'سلام، قیمت اشتراک چند است؟')
        self.assertEqual(t.messages.count(), 1)

    def test_unknown_intent_falls_back_to_other(self):
        tid, _, _ = self.create(intent='hack')
        self.assertEqual(ChatThread.objects.get(pk=tid).intent, 'other')

    def test_honeypot_filled_stores_nothing(self):
        r = self.post(CREATE, {'message': 'buy pills', 'website': 'http://spam'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(ChatThread.objects.count(), 0)

    def test_turnstile_enforced_on_create(self):
        self.turnstile.return_value = False
        r = self.post(CREATE, {'message': 'hi'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ChatThread.objects.count(), 0)
        self.turnstile.assert_called_with(mock.ANY, None, 'chat')

    def test_empty_and_zero_width_only_bodies_rejected(self):
        for body in ('', '   \n ', '​‏‮', '​ ‌'):
            self.assertEqual(self.post(CREATE, {'message': body}).status_code, 400, repr(body))
        self.assertEqual(ChatThread.objects.count(), 0)

    def test_body_over_2000_chars_rejected_400(self):
        self.assertEqual(self.post(CREATE, {'message': 'ا' * 2001}).status_code, 400)

    def test_rtl_emoji_body_at_cap_roundtrips_intact(self):
        text = ('سلام \U0001F600 hello ' * 200)[:2000]
        tid, token, _ = self.create(message=text, client_id='c-big')
        got = self.c.get(_msgs(tid), **_hdr(token)).json()['messages'][0]['body']
        self.assertEqual(got, text.strip())

    def test_create_with_contact_normalises_persian_digit_phone(self):
        tid, _, _ = self.create(contact={'name': 'علی', 'phone': '۰۹۱۲-۳۴۵ ۶۷۸۹',
                                         'email': 'a@example.com'})
        t = ChatThread.objects.get(pk=tid)
        self.assertEqual((t.contact_name, t.contact_phone, t.contact_email),
                         ('علی', '09123456789', 'a@example.com'))

    def test_invalid_contact_rejected_without_creating_a_thread(self):
        for contact in ({'email': 'nope'}, {'phone': '12'}, {'phone': 'abc'}):
            r = self.post(CREATE, {'message': 'hi', 'contact': contact})
            self.assertEqual(r.status_code, 400, contact)
        self.assertEqual(ChatThread.objects.count(), 0)

    def test_create_is_rate_limited_per_ip(self):
        codes = [self.post(CREATE, {'message': f'm{i}', 'client_id': f'c{i}'}).status_code
                 for i in range(7)]
        self.assertEqual(codes[:5], [201] * 5)
        self.assertIn(429, codes[5:])


class MessageTests(PublicBase):
    def test_wrong_token_and_other_threads_token_both_404(self):
        tid, token, _ = self.create()
        _, other_token, _ = self.create(message='second', client_id='c-2')
        for tok in ('wrong', other_token, None):
            self.assertEqual(self.c.get(_msgs(tid), **_hdr(tok)).status_code, 404)
            self.assertEqual(self.post(_msgs(tid), {'message': 'x'}, tok).status_code, 404)
        self.assertEqual(self.c.get(_msgs('not-a-uuid'), **_hdr(token)).status_code, 404)

    def test_poll_returns_only_after_cursor_and_hides_internal_notes(self):
        tid, token, d = self.create()
        t = ChatThread.objects.get(pk=tid)
        ChatMessage.objects.create(thread=t, author_kind='admin', body='internal note',
                                   internal=True)
        ChatMessage.objects.create(thread=t, author_kind='admin', body='public reply')
        everything = self.c.get(_msgs(tid), **_hdr(token)).json()
        self.assertEqual([m['body'] for m in everything['messages']],
                         ['سلام، قیمت اشتراک چند است؟', 'public reply'])
        self.assertNotIn('internal', json.dumps(everything))
        first_id = d['message']['id']
        after = self.c.get(_msgs(tid) + f'?after={first_id}', **_hdr(token)).json()
        self.assertEqual([m['body'] for m in after['messages']], ['public reply'])
        self.assertEqual(self.c.get(_msgs(tid) + '?after=junk', **_hdr(token)).status_code, 200)

    def test_double_submit_same_client_id_stores_one_message(self):
        tid, token, _ = self.create()
        a = self.post(_msgs(tid), {'message': 'again', 'client_id': 'c-dup'}, token)
        b = self.post(_msgs(tid), {'message': 'again', 'client_id': 'c-dup'}, token)
        self.assertEqual((a.status_code, b.status_code), (201, 200))
        self.assertEqual(a.json()['id'], b.json()['id'])
        self.assertEqual(ChatMessage.objects.filter(client_id='c-dup').count(), 1)

    def test_31st_message_in_an_hour_rate_limited_429(self):
        tid, token, _ = self.create()
        t = ChatThread.objects.get(pk=tid)
        ChatMessage.objects.bulk_create(
            [ChatMessage(thread=t, author_kind='visitor', body='x') for _ in range(28)])
        self.assertEqual(self.post(_msgs(tid), {'message': 'thirtieth'}, token).status_code, 201)
        self.assertEqual(self.post(_msgs(tid), {'message': 'one too many'}, token).status_code, 429)

    def test_visitor_message_sets_waiting_staff_and_emits_admin_event_without_contact(self):
        tid, token, _ = self.create(contact={'phone': '09123456789'})
        ChatThread.objects.filter(pk=tid).update(status='waiting_customer')
        Event.objects.all().delete()
        self.post(_msgs(tid), {'message': 'follow-up question'}, token)
        self.assertEqual(ChatThread.objects.get(pk=tid).status, 'waiting_staff')
        ev = Event.objects.get(type='chat.message')
        self.assertEqual(ev.audience, 'admin')
        self.assertEqual(ev.payload['thread_id'], tid)
        self.assertNotIn('09123456789', json.dumps(ev.payload))

    def test_closed_thread_rejects_new_messages_409(self):
        tid, token, _ = self.create()
        ChatThread.objects.filter(pk=tid).update(status='closed')
        self.assertEqual(self.post(_msgs(tid), {'message': 'hello?'}, token).status_code, 409)

    def test_spam_thread_looks_missing_to_the_visitor(self):
        tid, token, _ = self.create()
        ChatThread.objects.filter(pk=tid).update(status='spam')
        self.assertEqual(self.c.get(_msgs(tid), **_hdr(token)).status_code, 404)


class ContactAndCsatTests(PublicBase):
    def test_persian_digit_phone_normalised_on_contact_patch(self):
        tid, token, _ = self.create()
        r = self.post(f'/api/chat/threads/{tid}/contact/',
                      {'name': 'سارا', 'phone': '۰۹۱۲۳۴۵۶۷۸۹'}, token, method='patch')
        self.assertEqual(r.status_code, 200)
        t = ChatThread.objects.get(pk=tid)
        self.assertEqual((t.contact_name, t.contact_phone), ('سارا', '09123456789'))

    def test_invalid_email_and_short_phone_rejected_on_patch(self):
        tid, token, _ = self.create()
        url = f'/api/chat/threads/{tid}/contact/'
        self.assertEqual(self.post(url, {'email': 'x'}, token, method='patch').status_code, 400)
        self.assertEqual(self.post(url, {'phone': '123'}, token, method='patch').status_code, 400)
        self.assertEqual(self.post(url, {'phone': '09123456789'}, None, method='patch').status_code, 404)

    def test_csat_rejected_while_open_then_accepted_once_closed(self):
        tid, token, _ = self.create()
        url = f'/api/chat/threads/{tid}/csat/'
        self.assertEqual(self.post(url, {'score': 5}, token).status_code, 409)
        ChatThread.objects.filter(pk=tid).update(status='closed')
        self.assertEqual(self.post(url, {'score': 9}, token).status_code, 400)
        self.assertEqual(self.post(url, {'score': 4}, token).status_code, 200)
        self.assertEqual(ChatThread.objects.get(pk=tid).csat_score, 4)
        self.assertEqual(self.post(url, {'score': 5}, token).status_code, 409)
