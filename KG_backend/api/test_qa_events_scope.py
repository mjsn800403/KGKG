"""QA audit: real-time event backbone (api/events.py) — delivery scoping.

The existing test_events.py checks ``events_since`` scoping at the function
level. This suite drives the two HTTP surfaces a browser actually uses
(``/api/events/recent/`` and ``/api/events/stream/``) with real credentials and
asserts that every viewer receives exactly the events of its own scope:

  * admin    -> 'admin' + 'all' (never a company's or user's private events);
  * manager  -> own company's 'company' events + own 'user' events + 'all';
  * specialist (no team/analytics flag) -> own 'user' events + 'all' only;
  * another tenant never sees anything of the first one.

Also covered: cursor/limit parsing (junk must not 500), ordering, the wire
shape (no audience/tenant ids leak), log retention (``_trim``), the change
detector's event typing, and the SSE generator's frames.

No long-lived stream is held: the SSE generator runs against a fake ``time``
(monotonic clock + no-op sleep) so each loop iteration is explicit.
"""
import json
import os
import types
import unittest
from unittest import mock

from django.db import transaction
from django.test import Client, RequestFactory, TestCase

from api import events
from api.models import (
    AdminAuthToken, AuthToken, Company, Event, PlatformAdmin, PortalUser, SystemState,
)

STATIC_ADMIN = 'qa-static-admin-secret-0123456789'


def _user(company, username, *, manager=False, analytics=False, **kw):
    u = PortalUser(company=company, username=username,
                   role='after_sales_manager' if manager else 'after_sales_specialist',
                   can_manage_team=manager, can_view_analytics=analytics, **kw)
    u.set_password('pw-qa-events')
    u.save()
    return u


class _World(TestCase):
    """Two tenants, a manager / analytics-viewer / specialist in tenant 1, a
    manager in tenant 2, a platform admin session, and one event of every
    audience so each test can check exactly what a viewer receives."""

    def setUp(self):
        env = mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': STATIC_ADMIN,
                                           'KG_RL_DISABLE': '1'})
        env.start()
        self.addCleanup(env.stop)
        self.co1 = Company.objects.create(name='QA-Ev-Tenant-1')
        self.co2 = Company.objects.create(name='QA-Ev-Tenant-2')
        self.mgr1 = _user(self.co1, 'qa_ev_mgr1', manager=True)
        self.ana1 = _user(self.co1, 'qa_ev_ana1', analytics=True)
        self.spec1 = _user(self.co1, 'qa_ev_spec1')
        self.mgr2 = _user(self.co2, 'qa_ev_mgr2', manager=True)
        self.admin = PlatformAdmin.objects.create(username='qa-ev-admin')
        self.admin_session = AdminAuthToken.issue(self.admin).key

        # Invisible to every viewer (user audience, no user): a resume cursor
        # that precedes all the visible events below.
        self.sentinel = events.emit('x.sentinel', audience='user')
        self.e_admin = events.emit('data.detected', {'k': 'admin'}, audience='admin')
        self.e_all = events.emit('maintenance', {'k': 'all'}, audience='all')
        self.e_co1 = events.emit_company('activity', self.co1.id, {'k': 'co1'})
        self.e_co2 = events.emit_company('activity', self.co2.id, {'k': 'co2'})
        self.e_spec1 = events.emit_user('rec.updated', self.spec1.id, {'k': 'spec1'},
                                        company_id=self.co1.id)
        self.e_mgr1 = events.emit_user('rec.updated', self.mgr1.id, {'k': 'mgr1'},
                                       company_id=self.co1.id)
        self.e_mgr2 = events.emit_user('rec.updated', self.mgr2.id, {'k': 'mgr2'},
                                       company_id=self.co2.id)
        self.client = Client(raise_request_exception=False)

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def bearer(user):
        return {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(user).key}'}

    def admin_auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.admin_session}'}

    def recent(self, query='', **auth):
        return self.client.get('/api/events/recent/' + query, **auth)

    def recent_ids(self, query='', **auth):
        r = self.recent(query, **auth)
        self.assertEqual(r.status_code, 200, r.content)
        return [e['id'] for e in r.json()['events']]

    @staticmethod
    def ids(*evs):
        return [e.id for e in evs]


# ---------------------------------------------------------------------------
# /api/events/recent/ — who receives what
# ---------------------------------------------------------------------------
class RecentScopeTests(_World):

    def test_manager_gets_own_company_own_user_and_broadcast_only(self):
        got = self.recent_ids(**self.bearer(self.mgr1))
        self.assertEqual(got, self.ids(self.e_all, self.e_co1, self.e_mgr1))

    def test_analytics_viewer_without_team_flag_also_gets_company_events(self):
        got = self.recent_ids(**self.bearer(self.ana1))
        self.assertEqual(got, self.ids(self.e_all, self.e_co1))

    def test_plain_specialist_gets_only_own_user_events_and_broadcast(self):
        got = self.recent_ids(**self.bearer(self.spec1))
        self.assertEqual(got, self.ids(self.e_all, self.e_spec1))
        self.assertNotIn(self.e_co1.id, got)          # team signal withheld
        self.assertNotIn(self.e_mgr1.id, got)         # a colleague's private event

    def test_other_tenant_manager_never_sees_tenant_one(self):
        got = self.recent_ids(**self.bearer(self.mgr2))
        self.assertEqual(got, self.ids(self.e_all, self.e_co2, self.e_mgr2))
        for leaked in (self.e_co1, self.e_spec1, self.e_mgr1, self.e_admin):
            self.assertNotIn(leaked.id, got)

    def test_admin_session_gets_admin_and_broadcast_not_tenant_private(self):
        got = self.recent_ids(**self.admin_auth())
        self.assertEqual(got, self.ids(self.e_admin, self.e_all))

    def test_static_admin_token_from_loopback_is_admin(self):
        got = self.recent_ids(HTTP_AUTHORIZATION=f'Bearer {STATIC_ADMIN}')
        self.assertEqual(got, self.ids(self.e_admin, self.e_all))

    def test_admin_events_never_reach_a_portal_user_via_cursor_either(self):
        for u in (self.mgr1, self.spec1, self.mgr2):
            got = self.recent_ids(f'?after={self.sentinel.id}', **self.bearer(u))
            self.assertNotIn(self.e_admin.id, got, u.username)

    def test_cookie_session_is_scoped_like_bearer(self):
        self.client.cookies['kg_portal_token'] = AuthToken.issue(self.spec1).key
        got = self.recent_ids()
        self.assertEqual(got, self.ids(self.e_all, self.e_spec1))

    def test_company_event_without_company_id_reaches_no_tenant(self):
        orphan = events.emit('activity', {'k': 'orphan'}, audience='company')
        for u in (self.mgr1, self.mgr2):
            self.assertNotIn(orphan.id, self.recent_ids(**self.bearer(u)))
        self.assertNotIn(orphan.id, self.recent_ids(**self.admin_auth()))

    def test_wire_shape_does_not_leak_audience_or_tenant_ids(self):
        r = self.recent(**self.bearer(self.mgr1))
        for ev in r.json()['events']:
            self.assertEqual(set(ev), {'id', 'type', 'ts', 'payload'})
        co1 = next(e for e in r.json()['events'] if e['id'] == self.e_co1.id)
        self.assertEqual(co1['type'], 'activity')
        self.assertEqual(co1['payload'], {'k': 'co1'})


class RecentAuthTests(_World):

    def test_anonymous_is_401(self):
        r = self.recent()
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {'error': 'unauthorized'})

    def test_garbage_bearer_is_401(self):
        self.assertEqual(self.recent(HTTP_AUTHORIZATION='Bearer not-a-token').status_code, 401)

    def test_wrong_static_admin_token_is_401(self):
        r = self.recent(HTTP_AUTHORIZATION=f'Bearer {STATIC_ADMIN}x')
        self.assertEqual(r.status_code, 401)

    def test_empty_configured_admin_token_does_not_match_empty_presented(self):
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': ''}):
            r = self.recent(HTTP_X_ADMIN_TOKEN='')
        self.assertEqual(r.status_code, 401)

    def test_inactive_admin_session_is_401(self):
        PlatformAdmin.objects.filter(pk=self.admin.pk).update(active=False)
        self.assertEqual(self.recent(**self.admin_auth()).status_code, 401)

    def test_locked_or_inactive_portal_user_is_401(self):
        auth = self.bearer(self.mgr1)
        PortalUser.objects.filter(pk=self.mgr1.pk).update(locked=True)
        self.assertEqual(self.recent(**auth).status_code, 401)
        PortalUser.objects.filter(pk=self.mgr1.pk).update(locked=False, active=False)
        self.assertEqual(self.recent(**auth).status_code, 401)

    def test_user_of_deactivated_company_is_401(self):
        auth = self.bearer(self.mgr1)
        Company.objects.filter(pk=self.co1.pk).update(active=False)
        self.assertEqual(self.recent(**auth).status_code, 401)

    def test_portal_token_is_not_an_admin_token(self):
        # A portal session presented on the admin header path stays a portal
        # viewer: admin-only events must not appear.
        key = AuthToken.issue(self.mgr1).key
        got = self.recent_ids(HTTP_X_ADMIN_TOKEN=key, HTTP_AUTHORIZATION=f'Bearer {key}')
        self.assertNotIn(self.e_admin.id, got)

    def test_sentinel_user_event_without_user_reaches_nobody(self):
        for auth in (self.bearer(self.mgr1), self.bearer(self.spec1), self.admin_auth()):
            self.assertNotIn(self.sentinel.id, self.recent_ids(**auth))

    def test_static_admin_token_relayed_from_internet_is_refused(self):
        # Regression (fixed in this change): events._resolve_viewer (events.py:121-124) accepts the static KG_ADMIN_TOKEN from any client; require_admin_token (admin_auth.py:65-67) only honours it from loopback without proxy headers.
        r = self.recent(HTTP_AUTHORIZATION=f'Bearer {STATIC_ADMIN}',
                        REMOTE_ADDR='203.0.113.9', HTTP_X_FORWARDED_FOR='203.0.113.9')
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# after / limit parsing, ordering, cursor
# ---------------------------------------------------------------------------
class RecentParamsTests(_World):

    def test_default_is_oldest_first_and_cursor_is_latest_id(self):
        r = self.recent(**self.admin_auth())
        got = [e['id'] for e in r.json()['events']]
        self.assertEqual(got, sorted(got))
        self.assertEqual(r.json()['cursor'], Event.objects.order_by('-id').first().id)

    def test_limit_without_after_returns_newest_n_in_ascending_order(self):
        extra = [events.emit('x.tick', {'n': i}) for i in range(5)]
        got = self.recent_ids('?limit=2', **self.admin_auth())
        self.assertEqual(got, self.ids(extra[3], extra[4]))

    def test_after_returns_strictly_newer_scoped_rows_ascending(self):
        got = self.recent_ids(f'?after={self.e_co1.id}', **self.bearer(self.mgr1))
        self.assertEqual(got, self.ids(self.e_mgr1))         # e_co1 itself excluded
        newer = events.emit_company('activity', self.co1.id, {'k': 'n'})
        got = self.recent_ids(f'?after={self.e_mgr1.id}', **self.bearer(self.mgr1))
        self.assertEqual(got, [newer.id])

    def test_after_with_limit_returns_the_oldest_n_past_the_cursor(self):
        extra = [events.emit('x.tick', {'n': i}) for i in range(4)]
        got = self.recent_ids(f'?after={self.e_all.id}&limit=2', **self.admin_auth())
        self.assertEqual(got, self.ids(extra[0], extra[1]))

    def test_after_at_or_past_latest_is_empty(self):
        latest = Event.objects.order_by('-id').first().id
        self.assertEqual(self.recent_ids(f'?after={latest}', **self.admin_auth()), [])
        self.assertEqual(self.recent_ids(f'?after={latest + 1000}', **self.admin_auth()), [])

    def test_limit_boundaries_are_clamped(self):
        for i in range(3):
            events.emit('x.tick', {'n': i})
        self.assertEqual(len(self.recent_ids('?limit=0', **self.admin_auth())), 1)
        self.assertEqual(len(self.recent_ids('?limit=-7', **self.admin_auth())), 1)
        self.assertEqual(len(self.recent_ids('?limit=1', **self.admin_auth())), 1)

    def test_limit_upper_cap_is_500_and_default_is_100(self):
        Event.objects.bulk_create([Event(type='x.bulk', audience='admin') for _ in range(520)])
        self.assertEqual(len(self.recent_ids('?limit=100000', **self.admin_auth())), 500)
        self.assertEqual(len(self.recent_ids('?limit=500', **self.admin_auth())), 500)
        self.assertEqual(len(self.recent_ids('?limit=501', **self.admin_auth())), 500)
        self.assertEqual(len(self.recent_ids('', **self.admin_auth())), 100)

    def test_junk_after_and_limit_fall_back_instead_of_500(self):
        baseline = self.recent_ids(**self.bearer(self.mgr1))
        for q in ('?after=abc', '?after=1.5', '?after=', '?after=-3', '?after=%20',
                  '?limit=abc', '?limit=2.5', '?limit=', '?after=x&limit=y',
                  '?after[]=1', '?limit=1e3'):
            r = self.recent(q, **self.bearer(self.mgr1))
            self.assertEqual(r.status_code, 200, q)
            self.assertEqual([e['id'] for e in r.json()['events']], baseline, q)

    def test_after_beyond_sqlite_integer_range_does_not_500(self):
        r = self.recent('?after=' + '9' * 30, **self.admin_auth())
        self.assertNotEqual(r.status_code, 500)

    def test_limit_beyond_integer_range_is_capped(self):
        r = self.recent('?limit=' + '9' * 30, **self.admin_auth())
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# emit(): best-effort + retention
# ---------------------------------------------------------------------------
class EmitAndRetentionTests(TestCase):

    def test_emit_defaults_to_admin_audience_and_empty_payload(self):
        ev = events.emit('x.type')
        ev.refresh_from_db()
        self.assertEqual((ev.audience, ev.payload, ev.company_id, ev.user_id),
                         ('admin', {}, None, None))

    def test_emit_failure_returns_none_and_does_not_raise(self):
        with mock.patch.object(events, '_emit_count', 0):
            n = Event.objects.count()
            # The savepoint stands in for the autocommit a request runs under
            # (TestCase wraps every test in one transaction).
            with transaction.atomic():
                self.assertIsNone(events.emit('x.bad', {'o': object()}))   # not JSON-serialisable
            self.assertEqual(Event.objects.count(), n)
            self.assertEqual(events._emit_count, 0)    # a failed emit never counts toward trim

    def test_trim_keeps_only_newest_max_events(self):
        with mock.patch.object(events, '_MAX_EVENTS', 3), \
                mock.patch.object(events, '_TRIM_EVERY', 1), \
                mock.patch.object(events, '_emit_count', 0):
            evs = [events.emit('x.t', {'i': i}) for i in range(6)]
        self.assertEqual(list(Event.objects.order_by('id').values_list('id', flat=True)),
                         [e.id for e in evs[-3:]])

    def test_trim_is_a_noop_at_exactly_the_cap(self):
        with mock.patch.object(events, '_MAX_EVENTS', 3), \
                mock.patch.object(events, '_TRIM_EVERY', 1), \
                mock.patch.object(events, '_emit_count', 0):
            evs = [events.emit('x.t') for _ in range(3)]
        self.assertEqual(Event.objects.count(), 3)
        self.assertTrue(Event.objects.filter(id=evs[0].id).exists())

    def test_trim_is_amortised_to_every_nth_emit(self):
        with mock.patch.object(events, '_MAX_EVENTS', 2), \
                mock.patch.object(events, '_TRIM_EVERY', 3), \
                mock.patch.object(events, '_emit_count', 0):
            events.emit('x.t'); events.emit('x.t')
            self.assertEqual(Event.objects.count(), 2)
            events.emit('x.t')                       # 3rd emit -> trim to 2
            self.assertEqual(Event.objects.count(), 2)
            events.emit('x.t')                       # 4th -> no trim yet
            self.assertEqual(Event.objects.count(), 3)

    def test_trim_failure_is_swallowed(self):
        with mock.patch.object(events.Event.objects, 'order_by', side_effect=RuntimeError('db')):
            events._trim()                           # must not raise


# ---------------------------------------------------------------------------
# Change detector (admin-only signal)
# ---------------------------------------------------------------------------
def _snap(vehicles=1, catalog=0, rag=0, diag=0, embed=0, graph=0, job=None):
    """Shape of snapshot_pending(); the real one stats the warehouse on disk
    and reads the pipeline worker, which is outside this unit."""
    return {'pending': {'vehicles_on_disk': vehicles, 'pages_to_embed': embed,
                        'graph_pending': graph, 'has_work': bool(catalog or rag or diag),
                        'counts': {'catalog': catalog, 'rag_ingest': rag, 'diag': diag}},
            'active_job': job}


class DetectAndEmitTypingTests(TestCase):

    def setUp(self):
        # No baseline from any other source (migrations / earlier ticks).
        SystemState.objects.filter(key='pending_fingerprint').delete()

    def run_with(self, snap):
        with mock.patch.object(events, 'snapshot_pending', return_value=snap):
            return events.detect_and_emit()

    def test_first_run_only_establishes_baseline(self):
        # Regression (fixed in this change): SystemState.get (models.py:859) returns {} instead of None when the key is missing, so detect_and_emit's baseline branch (events.py:326-328) is dead and the first tick after a fresh DB emits a spurious 'data.detected' with changed_from={}.
        self.assertIsNone(self.run_with(_snap(vehicles=1)))
        self.assertFalse(Event.objects.exists())

    def test_new_vehicle_is_data_detected_with_previous_picture(self):
        self.run_with(_snap(vehicles=1))
        self.assertEqual(self.run_with(_snap(vehicles=2, catalog=1)), 'data.detected')
        ev = Event.objects.order_by('-id').first()
        self.assertEqual((ev.type, ev.audience), ('data.detected', 'admin'))
        self.assertEqual(ev.payload['changed_from']['vehicles'], 1)
        self.assertEqual(ev.payload['pending']['counts']['catalog'], 1)

    def test_unchanged_picture_is_quiet(self):
        self.run_with(_snap(vehicles=3, rag=1))
        n = Event.objects.count()
        self.assertIsNone(self.run_with(_snap(vehicles=3, rag=1)))
        self.assertEqual(Event.objects.count(), n)

    def test_shrinking_backlog_is_processing_pending(self):
        self.run_with(_snap(catalog=3, rag=2))
        self.assertEqual(self.run_with(_snap(catalog=1, rag=2)), 'processing.pending')

    def test_job_status_change_alone_emits(self):
        self.run_with(_snap(job={'id': 7, 'status': 'running'}))
        self.assertEqual(self.run_with(_snap(job={'id': 7, 'status': 'done'})),
                         'processing.pending')

    def test_snapshot_failure_emits_nothing(self):
        with mock.patch.object(events, 'snapshot_pending', side_effect=OSError('disk')):
            self.assertIsNone(events.detect_and_emit())
        self.assertFalse(Event.objects.exists())

    def test_detector_event_is_admin_only(self):
        co = Company.objects.create(name='QA-Ev-Det')
        mgr = _user(co, 'qa_ev_det_mgr', manager=True)
        self.run_with(_snap(vehicles=1))
        self.run_with(_snap(vehicles=5))
        self.assertEqual(events.events_since(0, is_admin=False, company_id=co.id,
                                             user_id=mgr.id, can_see_company=True), [])
        admin_rows = events.events_since(0, is_admin=True)
        self.assertGreaterEqual(len(admin_rows), 1)
        self.assertEqual({e.audience for e in Event.objects.all()}, {'admin'})


# ---------------------------------------------------------------------------
# /api/events/stream/ — auth, headers, scoped frames (no real waiting)
# ---------------------------------------------------------------------------
class _FakeClock:
    def __init__(self, *ticks):
        self._ticks = list(ticks)
        self.sleeps = 0

    def monotonic(self):
        return self._ticks.pop(0)

    def sleep(self, _s):
        self.sleeps += 1


class StreamTests(_World):

    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()
        conn = mock.patch.object(events, 'connection')   # don't close the test DB conn
        conn.start()
        self.addCleanup(conn.stop)

    def open(self, auth=None, query='', clock=None, **headers):
        req = self.rf.get('/api/events/stream/' + query, **(auth or {}), **headers)
        clock = clock or _FakeClock(0, 0, 10 ** 6)
        p = mock.patch.object(events, 'time', types.SimpleNamespace(
            monotonic=clock.monotonic, sleep=clock.sleep))
        p.start()
        self.addCleanup(p.stop)
        return events.stream_view(req)

    @staticmethod
    def frames(resp):
        body = ''.join(c.decode() if isinstance(c, bytes) else c
                       for c in resp.streaming_content)
        return [f for f in body.split('\n\n') if f]

    @staticmethod
    def data_ids(frames):
        out = []
        for f in frames:
            lines = dict(l.split(': ', 1) for l in f.split('\n') if ': ' in l)
            if 'id' in lines:
                out.append(int(lines['id']))
        return out

    def test_anonymous_is_refused_without_streaming(self):
        resp = self.open()
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(getattr(resp, 'streaming', False))
        self.assertEqual(json.loads(resp.content), {'error': 'unauthorized'})

    def test_garbage_token_is_refused(self):
        resp = self.open({'HTTP_AUTHORIZATION': 'Bearer nope'})
        self.assertEqual(resp.status_code, 401)

    def test_headers_disable_buffering_and_caching(self):
        resp = self.open(self.bearer(self.spec1))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.streaming)
        self.assertTrue(resp['Content-Type'].startswith('text/event-stream'))
        self.assertEqual(resp['Cache-Control'], 'no-cache, no-transform')
        self.assertEqual(resp['X-Accel-Buffering'], 'no')

    def test_fresh_subscriber_starts_at_live_edge_and_gets_no_history(self):
        latest = Event.objects.order_by('-id').first().id
        fr = self.frames(self.open(self.bearer(self.mgr1)))
        self.assertEqual(fr[0], ': connected\nretry: 3000')
        self.assertEqual(fr[1], 'event: ready\ndata: ' + json.dumps({'cursor': latest}))
        self.assertEqual(self.data_ids(fr), [])
        self.assertEqual(fr[-1], 'event: reconnect\ndata: {}')

    def test_resume_delivers_only_scoped_events_past_cursor(self):
        fr = self.frames(self.open(self.bearer(self.mgr1), f'?after={self.e_all.id}'))
        self.assertEqual(self.data_ids(fr), self.ids(self.e_co1, self.e_mgr1))

    def test_specialist_stream_excludes_company_and_colleague_events(self):
        fr = self.frames(self.open(self.bearer(self.spec1), f'?after={self.sentinel.id}'))
        self.assertEqual(self.data_ids(fr), self.ids(self.e_all, self.e_spec1))

    def test_other_tenant_stream_is_isolated(self):
        fr = self.frames(self.open(self.bearer(self.mgr2), f'?after={self.sentinel.id}'))
        self.assertEqual(self.data_ids(fr), self.ids(self.e_all, self.e_co2, self.e_mgr2))

    def test_admin_stream_frame_format(self):
        fr = self.frames(self.open(self.admin_auth(), f'?after={self.sentinel.id}'))
        self.assertEqual(self.data_ids(fr), self.ids(self.e_admin, self.e_all))
        frame = next(f for f in fr if f.startswith(f'id: {self.e_admin.id}\n'))
        lines = frame.split('\n')
        self.assertEqual(lines[1], 'event: data.detected')
        self.assertEqual(json.loads(lines[2][len('data: '):])['payload'], {'k': 'admin'})

    def test_last_event_id_header_wins_over_query(self):
        resp = self.open(self.admin_auth(), '?after=1',
                         HTTP_LAST_EVENT_ID=str(self.e_admin.id))
        fr = self.frames(resp)
        self.assertIn(json.dumps({'cursor': self.e_admin.id}), fr[1])
        self.assertEqual(self.data_ids(fr), [self.e_all.id])

    def test_junk_or_negative_resume_ids_start_at_live_edge(self):
        latest = Event.objects.order_by('-id').first().id
        for kw in ({'HTTP_LAST_EVENT_ID': 'abc'}, {'HTTP_LAST_EVENT_ID': '-5'},
                   {'query': '?after=zzz'}):
            q = kw.pop('query', '')
            fr = self.frames(self.open(self.admin_auth(), q, **kw))
            self.assertIn(json.dumps({'cursor': latest}), fr[1], kw or q)
            self.assertEqual(self.data_ids(fr), [])

    def test_heartbeat_when_idle(self):
        # start=0; tick 1 at t=20 (idle >= 15s -> ping); tick 2 past lifetime.
        clock = _FakeClock(0, 20, 10 ** 6)
        fr = self.frames(self.open(self.admin_auth(), clock=clock))
        self.assertIn(': ping', fr)
        self.assertEqual(clock.sleeps, 1)

    def test_no_heartbeat_before_interval(self):
        clock = _FakeClock(0, 5, 10 ** 6)
        fr = self.frames(self.open(self.admin_auth(), clock=clock))
        self.assertNotIn(': ping', fr)

    def test_new_event_after_connect_is_pushed_on_next_tick(self):
        clock = _FakeClock(0, 0, 0, 10 ** 6)
        resp = self.open(self.bearer(self.mgr1), clock=clock)
        it = iter(resp.streaming_content)
        next(it); next(it)                          # connected + ready
        # The cursor was fixed at connect time; these land after it and must
        # be picked up by the next tail tick (only the in-scope one).
        mine = events.emit_company('activity', self.co1.id, {'k': 'live'})
        other = events.emit_company('activity', self.co2.id, {'k': 'other'})
        rest = [c.decode() if isinstance(c, bytes) else c for c in it]
        joined = ''.join(rest)
        self.assertIn(f'id: {mine.id}\n', joined)
        self.assertNotIn(f'id: {other.id}\n', joined)

    def test_query_failure_inside_loop_is_survived(self):
        with mock.patch.object(events, 'events_since', side_effect=RuntimeError('locked')):
            fr = self.frames(self.open(self.admin_auth(), '?after=1'))
        self.assertEqual(fr[-1], 'event: reconnect\ndata: {}')
        self.assertEqual(self.data_ids(fr), [])
