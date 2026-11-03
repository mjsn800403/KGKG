"""C2: conversation-scoped limits that leave visitors sharing an IP alone."""
import os
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from . import throttle
from .helpers import CREATE, SupportCase, msgs_url, visitor_hdr


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class PollLimitTests(SupportCase):
    def setUp(self):
        super().setUp()
        self.clock = Clock()
        p = mock.patch('api.support_chat.throttle._now', self.clock)
        p.start()
        self.addCleanup(p.stop)

    def test_one_thread_over_its_poll_limit_is_throttled_but_a_neighbour_on_the_same_ip_is_not(self):
        a_id, a_tok, _ = self.create(client_id='ca')
        b_id, b_tok, _ = self.create(client_id='cb')
        codes = [self.poll(a_id, a_tok).status_code for _ in range(31)]
        self.assertEqual(codes[:30], [200] * 30)
        self.assertEqual(codes[30], 429)
        self.assertEqual(self.poll(b_id, b_tok).status_code, 200)

    def test_twelve_visitors_behind_one_nat_poll_every_three_seconds_for_a_minute(self):
        threads = [self.create(client_id=f'c{i}')[:2] for i in range(12)]
        codes = []
        for _ in range(20):
            for tid, tok in threads:
                codes.append(self.poll(tid, tok).status_code)
            self.clock.t += 3
        self.assertEqual(set(codes), {200})

    def test_poll_window_slides_so_a_visitor_recovers(self):
        tid, tok, _ = self.create()
        for _ in range(30):
            self.poll(tid, tok)
        self.assertEqual(self.poll(tid, tok).status_code, 429)
        self.clock.t += 61
        self.assertEqual(self.poll(tid, tok).status_code, 200)

    def test_limits_are_configurable_and_zero_disables(self):
        tid, tok, _ = self.create()
        with mock.patch.dict(os.environ, {'KG_SC_POLL': '2/60'}):
            self.assertEqual([self.poll(tid, tok).status_code for _ in range(3)], [200, 200, 429])
        self.clock.t += 61
        with mock.patch.dict(os.environ, {'KG_SC_POLL': '0/0'}):
            self.assertEqual({self.poll(tid, tok).status_code for _ in range(40)}, {200})

    def test_the_429_tells_the_client_when_to_retry(self):
        tid, tok, _ = self.create()
        with mock.patch.dict(os.environ, {'KG_SC_POLL': '1/60'}):
            self.poll(tid, tok)
            r = self.poll(tid, tok)
        self.assertEqual(r.status_code, 429)
        self.assertTrue(int(r['Retry-After']) >= 1)


class WriteLimitTests(SupportCase):
    def test_send_is_limited_per_thread_not_per_ip(self):
        a_id, a_tok, _ = self.create(client_id='ca')
        b_id, b_tok, _ = self.create(client_id='cb')
        codes = [self.send(msgs_url(a_id), {'message': f'm{i}', 'client_id': f's{i}'}, a_tok).status_code
                 for i in range(21)]
        self.assertEqual(codes[:20], [201] * 20)
        self.assertEqual(codes[20], 429)
        self.assertEqual(self.send(msgs_url(b_id), {'message': 'hi', 'client_id': 'sb'},
                                   b_tok).status_code, 201)

    def test_contact_and_csat_have_limits(self):
        tid, tok, _ = self.create()
        url = f'/api/support-chat/threads/{tid}/contact/'
        codes = [self.send(url, {'name': f'n{i}'}, tok, method='patch').status_code for i in range(11)]
        self.assertEqual(codes[:10], [200] * 10)
        self.assertEqual(codes[10], 429)
        csat = f'/api/support-chat/threads/{tid}/csat/'
        codes = [self.send(csat, {'score': 3}, tok).status_code for _ in range(6)]
        self.assertEqual(codes[5], 429)

    def test_thread_creation_per_ip_allows_an_office_and_stops_a_flood(self):
        codes = [self.send(CREATE, {'message': f'hello {i}', 'client_id': f'c{i}'},
                           REMOTE_ADDR='10.1.1.1').status_code for i in range(21)]
        self.assertEqual(codes[:20], [201] * 20)
        self.assertEqual(codes[20], 429)
        other = self.send(CREATE, {'message': 'hello', 'client_id': 'z'}, REMOTE_ADDR='10.2.2.2')
        self.assertEqual(other.status_code, 201)

    def test_creation_limit_is_configurable(self):
        with mock.patch.dict(os.environ, {'KG_SC_CREATE_IP': '2/600'}):
            codes = [self.send(CREATE, {'message': f'hi {i}'}, REMOTE_ADDR='10.3.3.3').status_code
                     for i in range(3)]
        self.assertEqual(codes, [201, 201, 429])


class InvalidTokenTests(SupportCase):
    WRONG = 'A' * 43

    def test_malformed_token_is_rejected_without_touching_the_database(self):
        tid, _, _ = self.create()
        with CaptureQueriesContext(connection) as q:
            for bad in ('short', 'x' * 500, 'has spaces ' * 4, '<script>'):
                self.assertEqual(self.c.get(msgs_url(tid), **visitor_hdr(bad)).status_code, 404)
            self.assertEqual(self.c.get(msgs_url('not-a-uuid'),
                                        **visitor_hdr(self.WRONG)).status_code, 404)
            self.assertEqual(self.c.get(msgs_url(tid)).status_code, 404)
        self.assertEqual(len(q), 0)

    def test_repeated_wrong_tokens_from_one_ip_are_eventually_throttled(self):
        tid, _, _ = self.create()
        codes = [self.c.get(msgs_url(tid), **visitor_hdr(self.WRONG),
                            REMOTE_ADDR='10.9.9.9').status_code for _ in range(35)]
        self.assertEqual(codes[:30], [404] * 30)
        self.assertEqual(set(codes[30:]), {429})

    def test_a_valid_visitor_on_the_same_ip_is_not_blocked_by_someone_elses_bad_tokens(self):
        tid, tok, _ = self.create(REMOTE_ADDR='10.8.8.8')
        for _ in range(40):
            self.c.get(msgs_url(tid), **visitor_hdr(self.WRONG), REMOTE_ADDR='10.8.8.8')
        self.assertEqual(self.c.get(msgs_url(tid), **visitor_hdr(tok),
                                    REMOTE_ADDR='10.8.8.8').status_code, 200)
        self.assertEqual(self.send(msgs_url(tid), {'message': 'still here', 'client_id': 'k'}, tok,
                                   REMOTE_ADDR='10.8.8.8').status_code, 201)

    def test_bad_tokens_from_other_ips_do_not_count_against_this_one(self):
        tid, _, _ = self.create()
        for _ in range(40):
            self.c.get(msgs_url(tid), **visitor_hdr(self.WRONG), REMOTE_ADDR='10.7.7.7')
        r = self.c.get(msgs_url(tid), **visitor_hdr(self.WRONG), REMOTE_ADDR='10.6.6.6')
        self.assertEqual(r.status_code, 404)


class ThrottleUnitTests(SupportCase):
    def test_poll_buckets_stay_bounded_in_memory(self):
        for i in range(throttle.MAX_BUCKETS + 50):
            throttle.poll_ok(f'thread-{i}')
        self.assertLessEqual(len(throttle._buckets), throttle.MAX_BUCKETS)
