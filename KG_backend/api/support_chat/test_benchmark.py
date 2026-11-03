"""Handler-level latency baseline for the support chat, with a realistic queue behind it.

Measures the request path through Django (URL routing, middleware, view, database) with the
test client, so network and TLS are excluded; it is a baseline for regressions and for
spotting the slow query, not a capacity claim. It prints one BENCH line per endpoint for the
CI log (PostgreSQL there) and asserts only generous ceilings, so a gross regression fails
but ordinary runner noise does not. Limits are off for the run (they would measure the
limiter), and nothing is sent anywhere.
"""
import time
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from .helpers import SupportCase, bearer
from .models import SupportMessage, SupportThread

QUEUE = 500          # threads already in the system
SAMPLES = 60


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


class Baseline(SupportCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict('os.environ', {'KG_RL_DISABLE': '1', 'KG_SC_SEND': '0/0', 'KG_SC_CREATE_IP': '0/0',
                                             'KG_SC_POLL': '0/0', 'KG_SC_SEND_HOUR': '0/0', 'KG_ADMIN_TOKEN': 'bench-loopback'})
        env.start()
        self.addCleanup(env.stop)
        threads = SupportThread.objects.bulk_create(
            [SupportThread(token_hash=f'{i:064d}', intent=('sales', 'technical', 'demo', 'other')[i % 4],
                           status='waiting_staff') for i in range(QUEUE)])
        SupportMessage.objects.bulk_create(
            [SupportMessage(thread=t, author_kind='visitor', body='سلام، یک سؤال دارم') for t in threads for _ in range(3)])

    def measure(self, label, fn, ceiling_ms):
        fn()                                              # warm-up (plan cache, imports)
        times, queries = [], []
        for _ in range(SAMPLES):
            with CaptureQueriesContext(connection) as q:
                t0 = time.perf_counter()
                fn()
                times.append((time.perf_counter() - t0) * 1000)
            queries.append(len(q))
        p50, p95 = pct(times, 0.5), pct(times, 0.95)
        print(f'BENCH {label:<22} vendor={connection.vendor} queue={QUEUE} n={SAMPLES} '
              f'p50_ms={p50:.1f} p95_ms={p95:.1f} max_ms={max(times):.1f} queries_max={max(queries)}', flush=True)
        self.assertLess(p95, ceiling_ms, f'{label} p95 {p95:.0f} ms')
        return max(queries)

    def test_endpoints_with_a_realistic_queue(self):
        n = [0]

        def create():
            n[0] += 1
            r = self.send('/api/support-chat/threads/',
                          {'message': 'سلام', 'client_id': f'b-{n[0]}', 'intent': 'sales'})
            assert r.status_code == 201, r.content
            return r.json()

        made = create()
        tid, token = made['thread_id'], made['token']
        self.measure('visitor create', create, 600)
        self.measure('visitor poll', lambda: self.poll(tid, token), 300)
        sent = [0]

        def send():
            sent[0] += 1
            r = self.send(f'/api/support-chat/threads/{tid}/messages/',
                          {'message': 'پیام', 'client_id': f's-{sent[0]}'}, token)
            assert r.status_code == 201, r.content
        self.measure('visitor send', send, 400)
        admin = self.h or bearer('x')
        staff_list_q = self.measure('staff list (500 live)',
                                    lambda: self.c.get('/api/admin/support-chat/threads/', **admin), 800)
        from . import views_admin_inbox as inbox
        self.measure('  list rows (page of 30)', lambda: list(inbox._annotated().filter(
            inbox.Q(status__in=inbox.ACTIVE)).order_by('-last_activity_at', '-pk')[:31]), 800)
        self.measure('  list counts', lambda: inbox._counts(self.admin), 800)
        self.measure('staff thread detail',
                     lambda: self.c.get(f'/api/admin/support-chat/threads/{tid}/', **admin), 400)
        from . import health
        self.measure('support_health report', health.report, 800)
        # The list is the hottest staff request: its query count must not grow with the queue.
        self.assertLess(staff_list_q, 20)
