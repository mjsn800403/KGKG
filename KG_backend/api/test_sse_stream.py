"""Regression tests for the SSE stream's HTTP contract and session behaviour.

The existing stream tests call ``stream_view`` directly, so they never saw what a
WSGI server does with the response. These pin two defects found 2026-11-03:
a hop-by-hop ``Connection`` header (500 under wsgiref/runserver) and the stream
sliding the admin idle window on every (re)connect.
"""
import types
from datetime import timedelta
from unittest import mock
from wsgiref.util import is_hop_by_hop

from django.test import RequestFactory, TestCase
from django.utils import timezone

from api import events
from api.models import AdminAuthToken, Event, PlatformAdmin


class _Clock:
    """monotonic: start, first loop check, then past the lifetime so the stream ends."""
    def __init__(self):
        self._ticks = [0, 0, 10 ** 6]

    def monotonic(self):
        return self._ticks.pop(0)

    def sleep(self, _s):
        pass


class StreamContractTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.admin = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True)
        self.token = AdminAuthToken.issue(self.admin)
        for p in (mock.patch.object(events, 'connection'),
                  mock.patch.object(events, 'time', types.SimpleNamespace(
                      monotonic=_Clock().monotonic, sleep=lambda s: None))):
            p.start()
            self.addCleanup(p.stop)

    def open(self, key=None):
        hdr = {'HTTP_AUTHORIZATION': f'Bearer {key or self.token.key}'}
        return events.stream_view(self.rf.get('/api/events/stream/', **hdr))

    def test_no_hop_by_hop_header_is_set(self):
        """wsgiref asserts exactly this for every response header; a violation is a 500."""
        resp = self.open()
        self.assertEqual(resp.status_code, 200)
        bad = [name for name, _ in resp.items() if is_hop_by_hop(name)]
        self.assertEqual(bad, [])

    def test_stream_is_served_by_a_real_wsgi_handler_without_error(self):
        """Run the actual wsgiref handler's header validation on the response."""
        from wsgiref.handlers import BaseHandler
        resp = self.open()
        handler = BaseHandler()
        handler.origin_server = True
        handler.http_version = '1.1'
        handler.server_software = 'test'
        handler.headers = None
        handler.status = None
        # start_response is where wsgiref raises AssertionError for hop-by-hop headers.
        handler.start_response('200 OK', [(k, v) for k, v in resp.items()])

    def test_first_frames_are_connected_then_ready(self):
        body = b''.join(resp_chunk if isinstance(resp_chunk, bytes) else resp_chunk.encode()
                        for resp_chunk in self.open().streaming_content).decode()
        self.assertTrue(body.startswith(': connected\nretry: 3000\n\n'))
        self.assertIn('event: ready', body)

    def test_a_scoped_event_is_delivered(self):
        # after=0 means "fresh subscriber, start at the live edge", so anchor on a real id.
        after = events.emit('support_chat.updated', {'thread_id': 'sentinel'}, audience='admin').id
        ev = events.emit('support_chat.message', {'thread_id': 'abc'}, audience='admin')
        resp = events.stream_view(self.rf.get(
            f'/api/events/stream/?after={after}', HTTP_AUTHORIZATION=f'Bearer {self.token.key}'))
        body = ''.join(c.decode() if isinstance(c, bytes) else c for c in resp.streaming_content)
        self.assertIn(f'id: {ev.id}', body)
        self.assertIn('support_chat.message', body)

    def test_opening_the_stream_does_not_extend_the_admin_session(self):
        stale = timezone.now() - timedelta(hours=3)
        AdminAuthToken.objects.filter(pk=self.token.pk).update(
            last_used_at=stale, expires_at=timezone.now() + timedelta(hours=9))
        before = AdminAuthToken.objects.get(pk=self.token.pk)
        self.open()
        after = AdminAuthToken.objects.get(pk=self.token.pk)
        self.assertEqual((after.last_used_at, after.expires_at),
                         (before.last_used_at, before.expires_at))

    def test_control_a_normal_admin_request_still_extends_it(self):
        from api.admin_auth import _admin_session
        stale = timezone.now() - timedelta(hours=3)
        AdminAuthToken.objects.filter(pk=self.token.pk).update(last_used_at=stale)
        _admin_session(self.token.key)
        self.assertGreater(AdminAuthToken.objects.get(pk=self.token.pk).last_used_at, stale)

    def test_expired_or_inactive_sessions_cannot_open_the_stream(self):
        AdminAuthToken.objects.filter(pk=self.token.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.open().status_code, 401)
        AdminAuthToken.objects.filter(pk=self.token.pk).update(
            expires_at=timezone.now() + timedelta(hours=1))
        self.admin.active = False
        self.admin.save()
        self.assertEqual(self.open().status_code, 401)


class StreamConnectionHandlingTests(TestCase):
    """The stream polls once a second per open stream; how it treats its database connection
    decides what that costs (60 new PostgreSQL connections for 60 polls before this)."""

    def setUp(self):
        self.rf = RequestFactory()
        self.admin = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True)
        self.token = AdminAuthToken.issue(self.admin)
        self.conn = mock.MagicMock()
        for p in (mock.patch.object(events, 'connection', self.conn),
                  mock.patch.object(events, 'time', types.SimpleNamespace(
                      monotonic=self._clock([0, 0, 1, 2, 10 ** 6]), sleep=lambda s: None))):
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def _clock(ticks):
        ticks = list(ticks)
        return lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0]

    def run_stream(self, after=None):
        url = '/api/events/stream/' + (f'?after={after}' if after is not None else '')
        resp = events.stream_view(self.rf.get(url, HTTP_AUTHORIZATION=f'Bearer {self.token.key}'))
        return ''.join(c.decode() if isinstance(c, bytes) else c for c in resp.streaming_content)

    def test_postgresql_keeps_its_connection_between_polls(self):
        self.conn.vendor = 'postgresql'
        self.run_stream(after=events.emit('x', {}, audience='admin').id)
        self.assertEqual(self.conn.close.call_count, 0, 'no close per poll; Django recycles it at request end')

    def test_sqlite_still_closes_between_polls(self):
        self.conn.vendor = 'sqlite'
        self.run_stream(after=events.emit('x', {}, audience='admin').id)
        self.assertGreaterEqual(self.conn.close.call_count, 2)       # once per poll

    def test_a_failed_poll_drops_the_connection_and_the_next_poll_recovers(self):
        self.conn.vendor = 'postgresql'
        after = events.emit('x', {}, audience='admin').id
        ev = events.emit('support_chat.message', {'thread_id': 't'}, audience='admin')
        real = events.events_since
        calls = {'n': 0}

        def flaky(*a, **k):
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('server closed the connection unexpectedly')
            return real(*a, **k)

        with mock.patch.object(events, 'events_since', side_effect=flaky):
            body = self.run_stream(after=after)
        self.assertIn(f'id: {ev.id}', body, 'the stream survived the failure and delivered the event')
        self.assertGreaterEqual(self.conn.close.call_count, 1, 'closed after the failed poll so the next reconnects')
