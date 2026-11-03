"""Shared fixtures for the support-chat tests (not a test module itself)."""
import json
from unittest import mock

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase

from api import ratelimit
from api.models import AdminAuthToken, PlatformAdmin

from . import throttle

CREATE = '/api/support-chat/threads/'


def bearer(key):
    return {'HTTP_AUTHORIZATION': f'Bearer {key}'}


def visitor_hdr(token):
    return {'HTTP_X_SUPPORT_CHAT_TOKEN': token} if token else {}


def msgs_url(tid):
    return f'/api/support-chat/threads/{tid}/messages/'


def admin_url(tid, action):
    return f'/api/admin/support-chat/threads/{tid}/{action}/'


class SupportCase(TestCase):
    """Clean rate-limit state, Turnstile accepted, one signed-in staff member."""

    def setUp(self):
        ratelimit._HITS.clear()
        throttle.reset()
        on = mock.patch.dict('os.environ', {'KG_SUPPORT_CHAT_ENABLED': '1'})
        on.start()
        self.addCleanup(on.stop)
        self.c = Client()
        p = mock.patch('api.support_chat.views_public._verify_turnstile', return_value=True)
        self.turnstile = p.start()
        self.addCleanup(p.stop)
        self.admin = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True)
        self.h = bearer(AdminAuthToken.issue(self.admin).key)

    def send(self, url, body=None, token=None, method='post', hdr=None, **extra):
        extra.update(hdr or {})
        return getattr(self.c, method)(url, json.dumps(body if body is not None else {}),
                                       content_type='application/json',
                                       **visitor_hdr(token), **extra)

    def create(self, message='سلام، قیمت اشتراک چند است؟', **extra):
        body = dict(message=message, client_id='c-first', intent='sales')
        body.update(extra)
        r = self.send(CREATE, body)
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        return d['thread_id'], d['token'], d

    def poll(self, tid, token, **params):
        qs = ('?' + '&'.join(f'{k}={v}' for k, v in params.items())) if params else ''
        return self.c.get(msgs_url(tid) + qs, **visitor_hdr(token))

    def staff(self, tid, action, body=None, hdr=None):
        return self.c.post(admin_url(tid, action), json.dumps(body or {}),
                           content_type='application/json', **(self.h if hdr is None else hdr))


class SupportTxCase(TransactionTestCase):
    """For real-thread concurrency tests: same fixtures, committed transactions."""

    def setUp(self):
        if connection.vendor == 'sqlite' and connection.is_in_memory_db():
            self.skipTest('threads need a real database: PostgreSQL, or file-backed SQLite')
        ratelimit._HITS.clear()
        throttle.reset()
        env = mock.patch.dict('os.environ', {'KG_SC_SEND': '0/0', 'KG_SC_CREATE_IP': '0/0',
                                             'KG_SC_CSAT': '0/0',
                                             'KG_SUPPORT_CHAT_ENABLED': '1'})
        env.start()
        self.addCleanup(env.stop)
        p = mock.patch('api.support_chat.views_public._verify_turnstile', return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.admin = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True)
        self.h = bearer(AdminAuthToken.issue(self.admin).key)

    def post(self, url, body, token=None, hdr=None):
        return Client().post(url, json.dumps(body), content_type='application/json',
                             **visitor_hdr(token), **(hdr or {}))

    def new_thread(self, message='hello', client_id='c-first'):
        d = self.post(CREATE, {'message': message, 'client_id': client_id}).json()
        return d['thread_id'], d['token']


def run_parallel(n, fn):
    """Run `fn(i)` in `n` threads released together; returns their results."""
    import threading

    from django.db import connections
    barrier = threading.Barrier(n)
    results, errors = [None] * n, []

    def work(i):
        try:
            barrier.wait(timeout=15)
            results[i] = fn(i)
        except Exception as exc:                       # surfaced by the caller's assertion
            errors.append(repr(exc))
        finally:
            connections.close_all()
    threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    return results