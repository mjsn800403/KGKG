"""Concurrency and stream load for the support chat, on real threads and real transactions.

Needs a real database (these skip on in-memory SQLite): CI runs them on its PostgreSQL service.
Nothing leaves the process: the test client calls the WSGI handler directly, rate limits are
switched off for the run (they would measure the limiter), and no alert or notification runs.
Each test prints one LOAD line for the CI log and asserts correctness first (no errors, no lost
or duplicated message), then only generous latency ceilings, so a gross regression fails but
runner noise does not. These are handler-level numbers: no network, TLS, proxy or gunicorn.
"""
import random
import threading
import time
from unittest import mock

from django.db import connection
from django.db.backends.base.base import BaseDatabaseWrapper
from django.test import Client

from api import events

from .helpers import SupportTxCase, run_parallel
from .models import SupportMessage, SupportThread

VISITORS = 30
STAFF = 4
SENDS = 3
POLLS = 4
STAFF_ROUNDS = 12


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))] if values else 0.0


class MixedLoad(SupportTxCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict('os.environ', {'KG_RL_DISABLE': '1', 'KG_SC_POLL': '0/0', 'KG_SC_SEND_HOUR': '0/0',
                                             'KG_ADMIN_TOKEN': 'load-loopback'})
        env.start()
        self.addCleanup(env.stop)
        self.samples = []
        self.lock = threading.Lock()

    def timed(self, label, call):
        t0 = time.perf_counter()
        r = call()
        ms = (time.perf_counter() - t0) * 1000
        with self.lock:
            self.samples.append((label, ms, r.status_code))
        return r

    def test_visitors_and_staff_together_lose_nothing(self):
        thread_ids = []

        def visitor(i):
            c = Client()
            r = self.timed('create', lambda: c.post(
                '/api/support-chat/threads/',
                '{"message": "hello %d", "client_id": "v%d-0", "intent": "sales"}' % (i, i),
                content_type='application/json'))
            d = r.json()
            tid, token = d['thread_id'], d['token']
            with self.lock:
                thread_ids.append(tid)
            hdr = {'HTTP_X_SUPPORT_CHAT_TOKEN': token}
            for k in range(1, SENDS + 1):
                for _ in range(POLLS // SENDS or 1):
                    self.timed('poll', lambda: c.get(f'/api/support-chat/threads/{tid}/messages/', **hdr))
                self.timed('send', lambda k=k: c.post(
                    f'/api/support-chat/threads/{tid}/messages/',
                    '{"message": "m%d", "client_id": "v%d-%d"}' % (k, i, k),
                    content_type='application/json', **hdr))
            return tid

        def staff(i):
            c = Client()
            rnd = random.Random(i)
            for _ in range(STAFF_ROUNDS):
                self.timed('staff list', lambda: c.get('/api/admin/support-chat/threads/', **self.h))
                with self.lock:
                    pick = rnd.choice(thread_ids) if thread_ids else None
                if pick:
                    self.timed('staff detail', lambda: c.get(f'/api/admin/support-chat/threads/{pick}/', **self.h))
                time.sleep(0.05)

        t0 = time.perf_counter()
        run_parallel(VISITORS + STAFF, lambda i: visitor(i) if i < VISITORS else staff(i))
        wall = time.perf_counter() - t0

        bad = [(label, status) for label, _, status in self.samples if status not in (200, 201)]
        self.assertEqual(bad, [], 'every request must succeed under concurrency')
        self.assertEqual(SupportThread.objects.count(), VISITORS)
        self.assertEqual(SupportMessage.objects.filter(author_kind='visitor').count(),
                         VISITORS * (1 + SENDS), 'no message lost or duplicated')
        by = {}
        for label, ms, _ in self.samples:
            by.setdefault(label, []).append(ms)
        total = len(self.samples)
        for label in ('create', 'poll', 'send', 'staff list', 'staff detail'):
            v = by[label]
            print(f'LOAD {label:<12} vendor={connection.vendor} n={len(v)} p50_ms={pct(v, .5):.1f} '
                  f'p95_ms={pct(v, .95):.1f} max_ms={max(v):.1f}', flush=True)
            self.assertLess(pct(v, .95), 3000, f'{label} p95')
        print(f'LOAD total        vendor={connection.vendor} visitors={VISITORS} staff={STAFF} requests={total} '
              f'seconds={wall:.1f} req_per_s={total / wall:.0f} errors=0', flush=True)


class StreamLoad(SupportTxCase):
    STREAMS = 12
    SECONDS = 4

    def test_database_cost_of_open_streams(self):
        """Opened-and-held streams cost one events_since per second each; count how many
        database connections that takes, because a connection per second per stream is churn."""
        connects = []
        polls = []
        real_connect = BaseDatabaseWrapper.connect
        real_since = events.events_since

        def counting_connect(self_):
            connects.append(1)
            return real_connect(self_)

        def counting_since(*a, **k):
            polls.append(1)
            return real_since(*a, **k)

        def hold(i):
            resp = Client().get('/api/events/stream/', **self.h)
            assert resp.status_code == 200, resp.status_code
            deadline = time.monotonic() + self.SECONDS
            for _ in resp.streaming_content:
                if time.monotonic() > deadline:
                    break
            resp.close()

        # a ping every loop iteration so the client side regains control each second
        with mock.patch.object(events, '_HEARTBEAT_S', 0.5), \
                mock.patch.object(BaseDatabaseWrapper, 'connect', counting_connect), \
                mock.patch.object(events, 'events_since', counting_since):
            t0 = time.perf_counter()
            run_parallel(self.STREAMS, hold)
            wall = time.perf_counter() - t0
        per_stream_s = len(polls) / (self.STREAMS * self.SECONDS)
        print(f'LOAD sse          vendor={connection.vendor} streams={self.STREAMS} seconds={self.SECONDS} '
              f'wall_s={wall:.1f} events_since_calls={len(polls)} per_stream_per_s={per_stream_s:.2f} '
              f'db_connects={len(connects)} connects_per_stream_per_s={len(connects) / (self.STREAMS * self.SECONDS):.2f}',
              flush=True)
        self.assertGreater(len(polls), self.STREAMS * (self.SECONDS - 1), 'every stream kept polling')
        if connection.vendor != 'sqlite':
            # One connection per stream thread, held between polls. Before the fix this equalled the
            # number of polls (a new server process per stream per second).
            self.assertLessEqual(len(connects), self.STREAMS * 2,
                                 f'{len(connects)} connects for {len(polls)} polls')
