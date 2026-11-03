"""The presence heartbeat must never keep an admin session alive.

Background pings every ~20 s would otherwise slide the 12 h idle window forever
(up to the 7 d ceiling): an unattended console would stay signed in. Heartbeats
validate the session read-only; only real actions touch it.
"""
from datetime import timedelta

from django.test import Client
from django.utils import timezone

from api.models import AdminAuthToken

from .helpers import SupportCase, bearer
from .models import SupportPresence

HEARTBEAT = '/api/admin/support-chat/presence/heartbeat/'
PRESENCE = '/api/admin/support-chat/presence/'


class HeartbeatSessionTests(SupportCase):
    def setUp(self):
        super().setUp()
        self.tok = AdminAuthToken.objects.get(admin=self.admin)
        self.stale = timezone.now() - timedelta(hours=2)        # past TOUCH_INTERVAL
        AdminAuthToken.objects.filter(pk=self.tok.pk).update(
            last_used_at=self.stale, expires_at=timezone.now() + timedelta(hours=6))
        self.tok.refresh_from_db()
        self.before = (self.tok.last_used_at, self.tok.expires_at)

    def beat(self, body=None, hdr=None):
        import json
        return self.c.post(HEARTBEAT, json.dumps(body or {}), content_type='application/json',
                           **(self.h if hdr is None else hdr))

    def state(self):
        self.tok.refresh_from_db()
        return (self.tok.last_used_at, self.tok.expires_at)

    def test_repeated_heartbeats_leave_the_session_clock_untouched(self):
        for _ in range(3):
            self.assertEqual(self.beat().status_code, 200)
        self.assertEqual(self.state(), self.before)

    def test_control_other_admin_endpoints_still_slide_the_window(self):
        self.assertEqual(self.c.get(PRESENCE, **self.h).status_code, 200)
        self.assertNotEqual(self.state(), self.before)

    def test_background_marked_calls_do_not_slide_the_window_but_human_calls_do(self):
        bg = dict(self.h, HTTP_X_KG_BACKGROUND='1')
        self.assertEqual(self.c.get('/api/admin/support-chat/threads/', **bg).status_code, 200)
        self.assertEqual(self.state(), self.before)                 # automatic refresh: untouched
        self.assertEqual(self.c.get('/api/admin/support-chat/threads/', **self.h).status_code, 200)
        self.assertNotEqual(self.state(), self.before)              # a person's call: slides

    def test_the_background_header_cannot_be_used_to_gain_access(self):
        self.assertEqual(self.c.get('/api/admin/support-chat/threads/',
                                    HTTP_X_KG_BACKGROUND='1').status_code, 401)
        AdminAuthToken.objects.filter(pk=self.tok.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.c.get('/api/admin/support-chat/threads/',
                                    **dict(self.h, HTTP_X_KG_BACKGROUND='1')).status_code, 401)

    def test_an_idle_session_dies_at_its_expiry_even_with_only_background_traffic(self):
        """12 h idle: automatic traffic never extends it, so it ends on schedule."""
        bg = dict(self.h, HTTP_X_KG_BACKGROUND='1')
        AdminAuthToken.objects.filter(pk=self.tok.pk).update(
            expires_at=timezone.now() + timedelta(seconds=30))
        for _ in range(3):
            self.assertEqual(self.c.get('/api/admin/support-chat/threads/', **bg).status_code, 200)
            self.beat()
        self.tok.refresh_from_db()
        self.assertLess(self.tok.expires_at, timezone.now() + timedelta(seconds=31))
        AdminAuthToken.objects.filter(pk=self.tok.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.c.get('/api/admin/support-chat/threads/', **bg).status_code, 401)
        self.assertEqual(self.beat().status_code, 401)

    def test_heartbeat_records_presence(self):
        self.beat()
        self.assertIsNotNone(SupportPresence.objects.get(admin=self.admin).last_heartbeat_at)

    def test_an_expired_token_is_refused_and_records_nothing(self):
        AdminAuthToken.objects.filter(pk=self.tok.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.beat().status_code, 401)
        self.assertFalse(SupportPresence.objects.filter(admin=self.admin).exists())

    def test_an_inactive_admin_is_refused(self):
        self.admin.active = False
        self.admin.save()
        self.assertEqual(self.beat().status_code, 401)

    def test_no_credentials_is_401_and_the_loopback_token_is_403(self):
        self.assertEqual(self.beat(hdr={}).status_code, 401)
        loop = Client(REMOTE_ADDR='127.0.0.1')
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'loop-secret'}):
            r = loop.post(HEARTBEAT, '{}', content_type='application/json',
                          **bearer('loop-secret'))
        self.assertEqual(r.status_code, 403)

    def test_inactive_beat_keeps_the_console_connected_but_not_counted_as_activity(self):
        """{active:false} says the tab is open but the person is idle: it must not
        refresh availability, so auto-away follows real human activity."""
        self.beat({'active': True})
        first = SupportPresence.objects.get(admin=self.admin).last_heartbeat_at
        r = self.beat({'active': False})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['counted'])
        self.assertEqual(SupportPresence.objects.get(admin=self.admin).last_heartbeat_at, first)

    def test_missing_active_flag_counts_as_active_for_old_clients(self):
        self.assertTrue(self.beat().json()['counted'])

    def test_non_boolean_active_is_rejected(self):
        self.assertEqual(self.beat({'active': 'yes'}).status_code, 400)
