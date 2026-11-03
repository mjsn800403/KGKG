"""Anonymous visitor API: create (idempotently), poll, send, contact."""
import hashlib
import json
import secrets
from unittest import mock

from api.models import Event

from .helpers import CREATE, SupportCase, msgs_url
from .models import SupportMessage, SupportThread

WRONG = 'W' * 43


class CreateTests(SupportCase):
    def test_create_returns_token_once_and_stores_only_hash(self):
        tid, token, d = self.create()
        t = SupportThread.objects.get(pk=tid)
        self.assertEqual(t.token_hash, hashlib.sha256(token.encode()).hexdigest())
        self.assertEqual((t.intent, t.status), ('sales', 'waiting_staff'))
        self.assertEqual(d['mode'], 'async')
        self.assertEqual(d['message']['body'], 'سلام، قیمت اشتراک چند است؟')
        self.assertEqual(t.messages.count(), 1)

    def test_unknown_intent_falls_back_to_other(self):
        tid, _, _ = self.create(intent='hack')
        self.assertEqual(SupportThread.objects.get(pk=tid).intent, 'other')

    def test_honeypot_filled_stores_nothing(self):
        r = self.send(CREATE, {'message': 'buy pills', 'website': 'http://spam'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(SupportThread.objects.count(), 0)

    def test_turnstile_enforced_on_create(self):
        self.turnstile.return_value = False
        r = self.send(CREATE, {'message': 'hi'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(SupportThread.objects.count(), 0)
        self.turnstile.assert_called_with(mock.ANY, None, 'support_chat')

    def test_empty_and_zero_width_only_bodies_rejected(self):
        for body in ('', '   \n ', '​‏‮', '​ ‌'):
            self.assertEqual(self.send(CREATE, {'message': body}).status_code, 400, repr(body))
        self.assertEqual(SupportThread.objects.count(), 0)

    def test_body_over_2000_chars_rejected_400(self):
        self.assertEqual(self.send(CREATE, {'message': 'ا' * 2001}).status_code, 400)

    def test_rtl_emoji_body_at_cap_roundtrips_intact(self):
        text = ('سلام \U0001F600 hello ' * 200)[:2000]
        tid, token, _ = self.create(message=text, client_id='c-big')
        got = self.poll(tid, token).json()['messages'][0]['body']
        self.assertEqual(got, text.strip())

    def test_create_with_contact_normalises_persian_digit_phone(self):
        tid, _, _ = self.create(contact={'name': 'علی', 'phone': '۰۹۱۲-۳۴۵ ۶۷۸۹',
                                         'email': 'a@example.com'})
        t = SupportThread.objects.get(pk=tid)
        self.assertEqual((t.contact_name, t.contact_phone, t.contact_email),
                         ('علی', '09123456789', 'a@example.com'))

    def test_invalid_contact_rejected_without_creating_a_thread(self):
        for contact in ({'email': 'nope'}, {'phone': '12'}, {'phone': 'abc'}):
            self.assertEqual(self.send(CREATE, {'message': 'hi', 'contact': contact}).status_code,
                             400, contact)
        self.assertEqual(SupportThread.objects.count(), 0)


class IdempotentCreateTests(SupportCase):
    """A visitor who retries 'start conversation' must not get a second thread:
    a duplicate would split their history and alert staff twice."""

    def test_a_client_supplied_token_makes_the_create_idempotent(self):
        tok = secrets.token_urlsafe(32)
        first = self.send(CREATE, {'message': 'hello', 'client_id': 'c1', 'token': tok})
        self.turnstile.return_value = False        # Turnstile tokens are single-use
        second = self.send(CREATE, {'message': 'hello', 'client_id': 'c1', 'token': tok})
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(first.json()['thread_id'], second.json()['thread_id'])
        self.assertEqual(SupportThread.objects.count(), 1)
        self.assertEqual(SupportMessage.objects.count(), 1)

    def test_a_supplied_token_is_never_echoed_back(self):
        tok = secrets.token_urlsafe(32)
        body = self.send(CREATE, {'message': 'hello', 'token': tok}).json()
        self.assertNotIn('token', body)
        self.assertEqual(self.poll(body['thread_id'], tok).status_code, 200)

    def test_malformed_client_tokens_are_rejected(self):
        for bad in ('short', 'A' * 44, 'A' * 42 + '!', 12345, ['x']):
            r = self.send(CREATE, {'message': 'hello', 'token': bad})
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(SupportThread.objects.count(), 0)

    def test_the_retry_does_not_need_turnstile_or_a_new_message(self):
        tok = secrets.token_urlsafe(32)
        self.send(CREATE, {'message': 'hello', 'client_id': 'c1', 'token': tok})
        self.turnstile.reset_mock()
        r = self.send(CREATE, {'message': 'different text', 'client_id': 'c9', 'token': tok})
        self.assertEqual(r.status_code, 200)
        self.turnstile.assert_not_called()
        self.assertEqual(SupportMessage.objects.count(), 1)

    def test_a_spam_marked_thread_does_not_come_back_through_create(self):
        tok = secrets.token_urlsafe(32)
        tid = self.send(CREATE, {'message': 'hello', 'token': tok}).json()['thread_id']
        SupportThread.objects.filter(pk=tid).update(status='spam')
        self.assertEqual(self.send(CREATE, {'message': 'hello', 'token': tok}).status_code, 404)

    def test_without_a_token_the_server_generates_one(self):
        tid, token, _ = self.create()
        self.assertEqual(len(token), 43)


class MessageTests(SupportCase):
    def test_wrong_token_and_other_threads_token_both_404(self):
        tid, token, _ = self.create()
        _, other_token, _ = self.create(message='second', client_id='c-2')
        for tok in (WRONG, other_token, None):
            self.assertEqual(self.c.get(msgs_url(tid), **({'HTTP_X_SUPPORT_CHAT_TOKEN': tok}
                                                           if tok else {})).status_code, 404)
            self.assertEqual(self.send(msgs_url(tid), {'message': 'x'}, tok).status_code, 404)
        self.assertEqual(self.poll('not-a-uuid', token).status_code, 404)

    def test_poll_returns_only_after_cursor_and_hides_internal_notes(self):
        tid, token, d = self.create()
        t = SupportThread.objects.get(pk=tid)
        SupportMessage.objects.create(thread=t, author_kind='admin', body='internal note',
                                      internal=True)
        SupportMessage.objects.create(thread=t, author_kind='admin', body='public reply')
        everything = self.poll(tid, token).json()
        self.assertEqual([m['body'] for m in everything['messages']],
                         ['سلام، قیمت اشتراک چند است؟', 'public reply'])
        self.assertNotIn('internal', json.dumps(everything))
        after = self.poll(tid, token, after=d['message']['id']).json()
        self.assertEqual([m['body'] for m in after['messages']], ['public reply'])
        self.assertEqual(self.poll(tid, token, after='junk').status_code, 200)

    def test_double_submit_same_client_id_stores_one_message(self):
        tid, token, _ = self.create()
        a = self.send(msgs_url(tid), {'message': 'again', 'client_id': 'c-dup'}, token)
        b = self.send(msgs_url(tid), {'message': 'again', 'client_id': 'c-dup'}, token)
        self.assertEqual((a.status_code, b.status_code), (201, 200))
        self.assertEqual(a.json()['id'], b.json()['id'])
        self.assertEqual(SupportMessage.objects.filter(client_id='c-dup').count(), 1)

    def test_31st_message_in_an_hour_rate_limited_429(self):
        tid, token, _ = self.create()
        t = SupportThread.objects.get(pk=tid)
        SupportMessage.objects.bulk_create(
            [SupportMessage(thread=t, author_kind='visitor', body='x') for _ in range(28)])
        self.assertEqual(self.send(msgs_url(tid), {'message': 'thirtieth'}, token).status_code, 201)
        self.assertEqual(self.send(msgs_url(tid), {'message': 'one too many'}, token).status_code, 429)

    def test_visitor_message_sets_waiting_staff_and_emits_an_id_only_admin_event(self):
        tid, token, _ = self.create(contact={'phone': '09123456789'})
        SupportThread.objects.filter(pk=tid).update(status='waiting_customer')
        Event.objects.all().delete()
        self.send(msgs_url(tid), {'message': 'follow-up question'}, token)
        self.assertEqual(SupportThread.objects.get(pk=tid).status, 'waiting_staff')
        ev = Event.objects.get(type='support_chat.message')
        self.assertEqual((ev.audience, ev.payload['thread_id']), ('admin', tid))
        self.assertNotIn('09123456789', json.dumps(ev.payload))

    def test_spam_thread_looks_missing_to_the_visitor(self):
        tid, token, _ = self.create()
        SupportThread.objects.filter(pk=tid).update(status='spam')
        self.assertEqual(self.poll(tid, token).status_code, 404)

    def test_poll_payload_shape(self):
        tid, token, _ = self.create()
        body = self.poll(tid, token).json()
        self.assertEqual(set(body), {'messages', 'status', 'mode', 'staff_seen_at', 'can_reopen'})
        self.assertEqual(set(body['messages'][0]),
                         {'id', 'author_kind', 'author_label', 'body', 'created_at'})


class ContactTests(SupportCase):
    def test_persian_digit_phone_normalised_on_contact_patch(self):
        tid, token, _ = self.create()
        r = self.send(f'/api/support-chat/threads/{tid}/contact/',
                      {'name': 'سارا', 'phone': '۰۹۱۲۳۴۵۶۷۸۹'}, token, method='patch')
        self.assertEqual(r.status_code, 200)
        t = SupportThread.objects.get(pk=tid)
        self.assertEqual((t.contact_name, t.contact_phone), ('سارا', '09123456789'))

    def test_invalid_email_and_short_phone_rejected_on_patch(self):
        tid, token, _ = self.create()
        url = f'/api/support-chat/threads/{tid}/contact/'
        self.assertEqual(self.send(url, {'email': 'x'}, token, method='patch').status_code, 400)
        self.assertEqual(self.send(url, {'phone': '123'}, token, method='patch').status_code, 400)
        self.assertEqual(self.send(url, {'phone': '09123456789'}, None, method='patch').status_code, 404)
