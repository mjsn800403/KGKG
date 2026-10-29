"""QA audit: api/ratelimit.py — sliding-window limiter, shared sqlite store,
fallback, decorator contract (429 + Retry-After), proxy-header trust.

Under `manage.py test` the module sets ``_STORE = None`` (in-process window
only). These tests deliberately re-enable the shared store against a temp
sqlite file so the production code path is exercised, and drive time through a
fake clock injected as ``ratelimit.time`` (no sleeps).
"""
import json
import os
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
from unittest import mock

from django.http import JsonResponse
from django.test import RequestFactory, TestCase

from api import portal, ratelimit
from api.models import Company, PortalUser


class _Clock:
    def __init__(self, t=1_000_000.5):
        self.t = t

    def __call__(self):
        return self.t


class _RLBase(TestCase):
    def setUp(self):
        ratelimit._HITS.clear()
        ratelimit._LAST_SWEEP = 0.0
        self.clock = _Clock()
        p = mock.patch.object(ratelimit, 'time',
                              SimpleNamespace(time=self.clock, monotonic=self.clock))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(ratelimit._HITS.clear)
        env = mock.patch.dict(os.environ, {'KG_RL_DISABLE': ''})
        env.start()
        self.addCleanup(env.stop)


# ---------------------------------------------------------------------------
# rule parsing
# ---------------------------------------------------------------------------
class ParseRuleTests(TestCase):
    D = (7, 30.0)

    def test_valid_rule(self):
        self.assertEqual(ratelimit._parse_rule('30/60', self.D), (30, 60.0))
        self.assertEqual(ratelimit._parse_rule('1/0.5', self.D), (1, 0.5))

    def test_garbage_falls_back_to_default(self):
        for raw in ('abc', '10', '10/60/5', 'x/60', '10/y', '', None, 42):
            self.assertEqual(ratelimit._parse_rule(raw, self.D), self.D, raw)

    def test_non_positive_values_fall_back(self):
        for raw in ('0/60', '-1/60', '10/0', '10/-5'):
            self.assertEqual(ratelimit._parse_rule(raw, self.D), self.D, raw)


# ---------------------------------------------------------------------------
# client IP / proxy trust
# ---------------------------------------------------------------------------
class ClientIpTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_proxy_headers_ignored_by_default(self):
        with mock.patch.object(ratelimit, '_TRUST_PROXY', False):
            req = self.rf.get('/', REMOTE_ADDR='198.51.100.1',
                              HTTP_X_REAL_IP='1.1.1.1', HTTP_X_FORWARDED_FOR='2.2.2.2')
            self.assertEqual(ratelimit._client_ip(req), '198.51.100.1')

    def test_trusted_proxy_prefers_x_real_ip(self):
        with mock.patch.object(ratelimit, '_TRUST_PROXY', True):
            req = self.rf.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP=' 203.0.113.5 ',
                              HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.5')
            self.assertEqual(ratelimit._client_ip(req), '203.0.113.5')

    def test_trusted_proxy_uses_last_xff_hop_not_spoofable_first(self):
        with mock.patch.object(ratelimit, '_TRUST_PROXY', True):
            req = self.rf.get('/', REMOTE_ADDR='127.0.0.1',
                              HTTP_X_FORWARDED_FOR='6.6.6.6, 7.7.7.7, 203.0.113.5')
            self.assertEqual(ratelimit._client_ip(req), '203.0.113.5')

    def test_trusted_proxy_without_headers_uses_remote_addr(self):
        with mock.patch.object(ratelimit, '_TRUST_PROXY', True):
            self.assertEqual(ratelimit._client_ip(self.rf.get('/', REMOTE_ADDR='10.1.1.1')), '10.1.1.1')

    def test_missing_remote_addr_is_unknown(self):
        req = SimpleNamespace(META={})
        with mock.patch.object(ratelimit, '_TRUST_PROXY', False):
            self.assertEqual(ratelimit._client_ip(req), 'unknown')


# ---------------------------------------------------------------------------
# in-process sliding window
# ---------------------------------------------------------------------------
class InProcessWindowTests(_RLBase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(ratelimit, '_STORE', None)
        p.start()
        self.addCleanup(p.stop)

    def test_allows_exactly_limit_then_denies(self):
        results = [ratelimit._allow('k', 3, 10)[0] for _ in range(3)]
        self.assertEqual(results, [True, True, True])
        ok, retry = ratelimit._allow('k', 3, 10)
        self.assertFalse(ok)
        self.assertEqual(retry, 11)          # int(t0 + 10 - t0) + 1

    def test_retry_after_counts_down_to_oldest_hit_expiry(self):
        t0 = self.clock.t
        for dt in (0, 1, 2):
            self.clock.t = t0 + dt
            ratelimit._allow('k', 3, 10)
        self.clock.t = t0 + 5
        ok, retry = ratelimit._allow('k', 3, 10)
        self.assertFalse(ok)
        self.assertEqual(retry, 6)

    def test_denied_requests_do_not_extend_the_window(self):
        for _ in range(2):
            ratelimit._allow('k', 2, 10)
        for _ in range(5):
            self.assertFalse(ratelimit._allow('k', 2, 10)[0])
        self.assertEqual(len(ratelimit._HITS['k']), 2)

    def test_window_slides(self):
        t0 = self.clock.t
        ratelimit._allow('k', 2, 10)
        self.clock.t = t0 + 6
        ratelimit._allow('k', 2, 10)
        self.clock.t = t0 + 9.99
        self.assertFalse(ratelimit._allow('k', 2, 10)[0])
        self.clock.t = t0 + 10.01            # first hit has left the window
        self.assertTrue(ratelimit._allow('k', 2, 10)[0])
        self.clock.t = t0 + 10.02            # second hit (t0+6) still inside
        self.assertFalse(ratelimit._allow('k', 2, 10)[0])

    def test_hit_exactly_at_cutoff_still_counts(self):
        t0 = self.clock.t
        ratelimit._allow('k', 1, 10)
        self.clock.t = t0 + 10               # dq[0] == cutoff -> not popped
        self.assertFalse(ratelimit._allow('k', 1, 10)[0])

    def test_keys_are_isolated(self):
        self.assertTrue(ratelimit._allow('login:1.1.1.1', 1, 60)[0])
        self.assertFalse(ratelimit._allow('login:1.1.1.1', 1, 60)[0])
        self.assertTrue(ratelimit._allow('login:2.2.2.2', 1, 60)[0])
        self.assertTrue(ratelimit._allow('verify_otp:1.1.1.1', 1, 60)[0])

    def test_sweep_evicts_stale_buckets_at_most_once_a_minute(self):
        t0 = self.clock.t
        ratelimit._allow('old-ip', 5, 10)
        self.clock.t = t0 + 3601
        ratelimit._allow('new-ip', 5, 10)    # sweep runs: old-ip bucket gone
        self.assertNotIn('old-ip', ratelimit._HITS)
        self.assertIn('new-ip', ratelimit._HITS)
        # inject a stale bucket; a sweep within 60s must not run
        ratelimit._HITS['stale'].append(t0)
        self.clock.t = t0 + 3601 + 30
        ratelimit._allow('new-ip', 5, 10)
        self.assertIn('stale', ratelimit._HITS)
        self.clock.t = t0 + 3601 + 61
        ratelimit._allow('new-ip', 5, 10)
        self.assertNotIn('stale', ratelimit._HITS)

    def test_sweep_keeps_buckets_with_recent_hits(self):
        t0 = self.clock.t
        ratelimit._HITS['mixed'].extend([t0 - 4000, t0 - 10])
        ratelimit._allow('trigger', 5, 10)
        self.assertEqual(list(ratelimit._HITS['mixed']), [t0 - 10])

    def test_thread_safety_never_over_grants(self):
        granted = []

        def worker():
            for _ in range(50):
                if ratelimit._allow('race', 25, 60)[0]:
                    granted.append(1)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(granted), 25)


# ---------------------------------------------------------------------------
# shared sqlite store (production path)
# ---------------------------------------------------------------------------
class SharedStoreTests(_RLBase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'rl.sqlite3')
        self._use_store(self.path)

    def _use_store(self, path):
        p = mock.patch.object(ratelimit, '_STORE', path)
        p.start()
        self.addCleanup(p.stop)
        self._reset_conn()
        self.addCleanup(self._reset_conn)

    @staticmethod
    def _reset_conn():
        conn = getattr(ratelimit._STORE_LOCAL, 'conn', None)
        if conn is not None:
            conn.close()
            ratelimit._STORE_LOCAL.conn = None

    def _rows(self, key=None):
        c = sqlite3.connect(self.path)
        try:
            if key:
                return c.execute('SELECT COUNT(*) FROM hits WHERE k=?', (key,)).fetchone()[0]
            return c.execute('SELECT COUNT(*) FROM hits').fetchone()[0]
        finally:
            c.close()

    def test_store_enforces_limit_and_does_not_touch_memory(self):
        self.assertEqual([ratelimit._allow('k', 2, 60)[0] for _ in range(3)],
                         [True, True, False])
        self.assertEqual(self._rows('k'), 2)
        self.assertEqual(len(ratelimit._HITS), 0)

    def test_retry_after_from_store(self):
        t0 = self.clock.t
        ratelimit._allow('k', 1, 60)
        self.clock.t = t0 + 20
        ok, retry = ratelimit._allow('k', 1, 60)
        self.assertFalse(ok)
        self.assertEqual(retry, int(t0 + 60 - (t0 + 20)) + 1)

    def test_retry_after_is_at_least_one_second(self):
        t0 = self.clock.t
        ratelimit._allow('k', 1, 60)
        self.clock.t = t0 + 59.9999
        self.assertEqual(ratelimit._allow('k', 1, 60), (False, 1))

    def test_window_expiry_in_store(self):
        t0 = self.clock.t
        ratelimit._allow('k', 1, 60)
        self.clock.t = t0 + 61
        self.assertTrue(ratelimit._allow('k', 1, 60)[0])

    def test_counters_are_shared_across_workers(self):
        # Each thread gets its own sqlite connection (threading.local), like
        # separate gunicorn workers sharing one file.
        ratelimit._allow('shared', 2, 60)
        out = []

        def other_worker():
            out.append(ratelimit._allow('shared', 2, 60)[0])
            out.append(ratelimit._allow('shared', 2, 60)[0])
            ratelimit._STORE_LOCAL.conn.close()

        t = threading.Thread(target=other_worker)
        t.start()
        t.join()
        self.assertEqual(out, [True, False])
        self.assertFalse(ratelimit._allow('shared', 2, 60)[0])

    def test_hourly_prune_on_minute_boundary(self):
        t0 = 1_000_020.0
        self.clock.t = t0
        ratelimit._allow('ancient', 100, 60)
        self.clock.t = t0 + 3700             # not a multiple of 60 -> no prune
        self.assertNotEqual(int(self.clock.t) % 60, 0)
        ratelimit._allow('x', 100, 60)
        self.assertEqual(self._rows('ancient'), 1)
        self.clock.t = 1_003_740.0           # int % 60 == 0 -> prune >1h old rows
        self.assertEqual(int(self.clock.t) % 60, 0)
        ratelimit._allow('x', 100, 60)
        self.assertEqual(self._rows('ancient'), 0)
        self.assertEqual(self._rows('x'), 2)

    def test_unusable_store_falls_back_to_in_process_window(self):
        self._use_store(os.path.join(self.tmp.name, 'missing-dir', 'rl.sqlite3'))
        self.assertEqual([ratelimit._allow('fb', 2, 60)[0] for _ in range(3)],
                         [True, True, False])
        self.assertEqual(len(ratelimit._HITS['fb']), 2)

    def test_failed_write_rolls_back_and_falls_back(self):
        # A trigger makes the INSERT fail inside the transaction: the store
        # must roll back (no dangling BEGIN IMMEDIATE lock) and the limiter
        # must still enforce via the in-process window.
        c = sqlite3.connect(self.path)
        c.execute('CREATE TABLE hits (k TEXT, ts REAL)')
        c.execute("CREATE TRIGGER boom BEFORE INSERT ON hits BEGIN SELECT RAISE(ABORT, 'boom'); END")
        c.commit()
        c.close()
        self.assertEqual([ratelimit._allow('rb', 1, 60)[0] for _ in range(2)], [True, False])
        self.assertEqual(len(ratelimit._HITS['rb']), 1)
        conn = ratelimit._STORE_LOCAL.conn
        self.assertFalse(conn.in_transaction)
        # the lock was released: another connection can write immediately
        c = sqlite3.connect(self.path, timeout=0)
        c.execute('DROP TRIGGER boom')
        c.commit()
        c.close()
        self.assertTrue(ratelimit._allow('after', 1, 60)[0])
        self.assertEqual(self._rows('after'), 1)

    def test_store_uses_wal_and_index(self):
        ratelimit._allow('k', 1, 60)
        conn = ratelimit._STORE_LOCAL.conn
        self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0].lower(), 'wal')
        idx = [r[1] for r in conn.execute("PRAGMA index_list('hits')")]
        self.assertIn('hits_k_ts', idx)


# ---------------------------------------------------------------------------
# decorator contract
# ---------------------------------------------------------------------------
_calls = []


@ratelimit.rate_limited('qa_probe', 2, 60)
def _probe(request):
    _calls.append(1)
    return JsonResponse({'ok': True})


class DecoratorTests(_RLBase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(ratelimit, '_STORE', None)
        p.start()
        self.addCleanup(p.stop)
        _calls.clear()
        self.rf = RequestFactory()

    def hit(self, ip='198.51.100.10'):
        return _probe(self.rf.get('/', REMOTE_ADDR=ip))

    def test_over_limit_returns_429_with_retry_after_and_skips_view(self):
        self.assertEqual([self.hit().status_code for _ in range(2)], [200, 200])
        r = self.hit()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(json.loads(r.content)['error'], 'rate_limited')
        self.assertEqual(r['Retry-After'], '61')
        self.assertEqual(len(_calls), 2)

    def test_other_ip_unaffected(self):
        for _ in range(3):
            self.hit()
        self.assertEqual(self.hit(ip='198.51.100.11').status_code, 200)

    def test_bucket_is_namespaced_by_endpoint(self):
        self.hit()
        self.assertIn('qa_probe:198.51.100.10', ratelimit._HITS)

    def test_env_override_tightens_limit(self):
        with mock.patch.dict(os.environ, {'KG_RL_QA_PROBE': '1/30'}):
            self.assertEqual(self.hit().status_code, 200)
            r = self.hit()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r['Retry-After'], '31')

    def test_garbage_env_override_keeps_default(self):
        with mock.patch.dict(os.environ, {'KG_RL_QA_PROBE': 'lots'}):
            codes = [self.hit().status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_global_disable_switch(self):
        with mock.patch.dict(os.environ, {'KG_RL_DISABLE': '1'}):
            codes = [self.hit().status_code for _ in range(5)]
        self.assertEqual(codes, [200] * 5)
        self.assertEqual(len(ratelimit._HITS), 0)

    def test_non_positive_default_limit_disables(self):
        @ratelimit.rate_limited('qa_off', 0, 60)
        def off(request):
            return JsonResponse({'ok': True})
        codes = [off(self.rf.get('/')).status_code for _ in range(5)]
        self.assertEqual(codes, [200] * 5)

    def test_documented_zero_override_turns_endpoint_off(self):
        # Regression (fixed in this change): ratelimit.py:155 documents KG_RL_<NAME>="0/0" as "turn off", but
        # _parse_rule (ratelimit.py:67) rejects n<=0 and returns the default limit,
        # so the endpoint stays rate-limited.
        with mock.patch.dict(os.environ, {'KG_RL_QA_PROBE': '0/0'}):
            codes = [self.hit().status_code for _ in range(5)]
        self.assertEqual(codes, [200] * 5)

    def test_guard_bug_fails_open(self):
        # A request object whose META is unusable makes the IP lookup itself
        # raise inside the guard; the view must still be served.
        broken = SimpleNamespace(META=None, method='GET')
        r = _probe(broken)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(_calls), 1)

    def test_wraps_preserves_view_identity(self):
        self.assertEqual(_probe.__name__, '_probe')


# ---------------------------------------------------------------------------
# end-to-end through the real login endpoint
# ---------------------------------------------------------------------------
class LoginEndpointRateLimitTests(_RLBase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(ratelimit, '_STORE', None)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(portal, '_verify_turnstile', return_value=True)
        p.start()
        self.addCleanup(p.stop)
        co = Company.objects.create(name='RL-Co')
        u = PortalUser(company=co, username='rl_user', role='after_sales_specialist')
        u.set_password('right-password')
        u.save()

    def _login(self, ip, password='wrong-password'):
        return self.client.post('/api/auth/login/',
                                json.dumps({'username': 'rl_user', 'password': password,
                                            'turnstile_token': 't'}),
                                content_type='application/json', REMOTE_ADDR=ip)

    def test_password_guessing_capped_at_15_per_minute_per_ip(self):
        codes = [self._login('203.0.113.50').status_code for _ in range(15)]
        self.assertEqual(set(codes), {401})
        r = self._login('203.0.113.50', password='right-password')
        self.assertEqual(r.status_code, 429)        # even the right password
        self.assertTrue(r.has_header('Retry-After'))
        self.assertEqual(self._login('203.0.113.51', 'right-password').status_code, 200)

    def test_limit_lifts_after_window(self):
        for _ in range(15):
            self._login('203.0.113.60')
        self.clock.t += 61
        self.assertEqual(self._login('203.0.113.60', 'right-password').status_code, 200)

    def test_spoofed_xff_does_not_dodge_limit_without_trusted_proxy(self):
        with mock.patch.object(ratelimit, '_TRUST_PROXY', False):
            for i in range(15):
                self.client.post('/api/auth/login/', json.dumps({'username': 'rl_user',
                                 'password': 'x', 'turnstile_token': 't'}),
                                 content_type='application/json', REMOTE_ADDR='203.0.113.70',
                                 HTTP_X_FORWARDED_FOR=f'10.0.0.{i}')
            r = self.client.post('/api/auth/login/', json.dumps({'username': 'rl_user',
                                 'password': 'x', 'turnstile_token': 't'}),
                                 content_type='application/json', REMOTE_ADDR='203.0.113.70',
                                 HTTP_X_FORWARDED_FOR='10.0.0.99')
        self.assertEqual(r.status_code, 429)

    def test_resend_otp_capped_at_3_per_minute(self):
        codes = [self.client.post('/api/auth/resend-otp/', json.dumps({'otp_session': 'x'}),
                                  content_type='application/json',
                                  REMOTE_ADDR='203.0.113.80').status_code for _ in range(4)]
        self.assertEqual(codes, [400, 400, 400, 429])
