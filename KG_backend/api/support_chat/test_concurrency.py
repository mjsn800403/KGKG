"""C5: real threads against the real database. These prove ordering and
integrity on whichever database runs them; PostgreSQL (CI) is the authority
for row locking, so a green SQLite run is a smoke test, not proof."""
import os
import secrets
from unittest import mock

from django.db import connection

from .helpers import CREATE, SupportTxCase, admin_url, msgs_url, run_parallel
from .models import SupportMessage, SupportRating, SupportThread

N = 8


def _token():
    return secrets.token_urlsafe(32)


class ConcurrentCreateTests(SupportTxCase):
    def test_simultaneous_creates_with_one_client_token_make_one_thread(self):
        tok = _token()
        results = run_parallel(N, lambda i: self.post(
            CREATE, {'message': 'hello', 'client_id': 'c1', 'token': tok}).status_code)
        self.assertEqual(sorted(results).count(201), 1, results)
        self.assertEqual(set(results) - {201, 200}, set())
        self.assertEqual(SupportThread.objects.count(), 1)
        self.assertEqual(SupportMessage.objects.count(), 1)


class ConcurrentSendTests(SupportTxCase):
    def test_simultaneous_sends_with_one_client_id_store_one_message(self):
        tid, tok = self.new_thread()
        results = run_parallel(N, lambda i: self.post(
            msgs_url(tid), {'message': 'again', 'client_id': 'dup'}, tok).status_code)
        self.assertEqual(sorted(results).count(201), 1, results)
        self.assertEqual(SupportMessage.objects.filter(client_id='dup').count(), 1)

    def test_the_hourly_message_cap_holds_under_concurrent_load(self):
        tid, tok = self.new_thread()
        with mock.patch.dict(os.environ, {'KG_SC_SEND_HOUR': '5/3600'}):
            results = run_parallel(12, lambda i: self.post(
                msgs_url(tid), {'message': f'm{i}', 'client_id': f'k{i}'}, tok).status_code)
        stored = SupportMessage.objects.filter(thread_id=tid, author_kind='visitor').count()
        self.assertLessEqual(stored, 5, results)
        self.assertEqual(results.count(201), stored - 1)      # the first message was the create
        self.assertEqual(set(results) - {201, 429}, set())

    def test_visitor_send_and_staff_reply_leave_a_status_that_matches_the_last_message(self):
        for rnd in range(6):
            tid, tok = self.new_thread(client_id=f'r{rnd}')

            def act(i):
                if i == 0:
                    return self.post(msgs_url(tid), {'message': 'question', 'client_id': 'q'},
                                     tok).status_code
                return self.post(admin_url(tid, 'reply'), {'message': 'answer'},
                                 hdr=self.h).status_code
            run_parallel(2, act)
            last = SupportMessage.objects.filter(thread_id=tid).order_by('-id').first()
            expected = 'waiting_staff' if last.author_kind == 'visitor' else 'waiting_customer'
            self.assertEqual(SupportThread.objects.get(pk=tid).status, expected, rnd)


class ConcurrentTransitionTests(SupportTxCase):
    def test_simultaneous_closes_succeed_once(self):
        tid, _ = self.new_thread()
        results = run_parallel(N, lambda i: self.post(admin_url(tid, 'close'), {},
                                                      hdr=self.h).status_code)
        self.assertEqual(sorted(results).count(200), 1, results)
        self.assertEqual(SupportMessage.objects.filter(author_kind='system').count(), 1)

    def test_simultaneous_reopens_count_once(self):
        tid, _ = self.new_thread()
        self.post(admin_url(tid, 'close'), {}, hdr=self.h)
        results = run_parallel(N, lambda i: self.post(admin_url(tid, 'reopen'), {},
                                                      hdr=self.h).status_code)
        self.assertEqual(sorted(results).count(200), 1, results)
        self.assertEqual(SupportThread.objects.get(pk=tid).reopen_count, 1)

    def test_simultaneous_ratings_for_one_closure_store_one(self):
        tid, tok = self.new_thread()
        self.post(admin_url(tid, 'close'), {}, hdr=self.h)
        results = run_parallel(N, lambda i: self.post(
            f'/api/support-chat/threads/{tid}/csat/', {'score': 1 + i % 5}, tok).status_code)
        self.assertEqual(sorted(results).count(201), 1, results)
        self.assertEqual(SupportRating.objects.filter(thread_id=tid).count(), 1)


class BackendNoteTests(SupportTxCase):
    def test_report_which_database_ran_these(self):
        # Not an assertion about behaviour: it makes the evidence label explicit.
        print(f'\n[support_chat concurrency ran on: {connection.vendor}]')
        self.assertIn(connection.vendor, ('sqlite', 'postgresql'))
