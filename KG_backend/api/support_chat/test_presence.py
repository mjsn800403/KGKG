"""C7: three separate facts about a staff member, and a public status that
claims 'live' only when someone is eligible to answer."""
import json
import os
from datetime import timedelta
from unittest import mock

from django.test import Client, TestCase
from django.utils import timezone

from api import ratelimit
from api.models import AdminAuthToken, PlatformAdmin

from . import presence
from .models import SupportPresence

STATUS = '/api/support-chat/status/'
HEARTBEAT = '/api/admin/support-chat/presence/heartbeat/'
SET = '/api/admin/support-chat/presence/'


def _bearer(key):
    return {'HTTP_AUTHORIZATION': f'Bearer {key}'}


class EligibilityTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.admin = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True)

    def _present(self, status='available', beat_age=10, admin=None):
        return SupportPresence.objects.create(
            admin=admin or self.admin, manual_status=status,
            last_heartbeat_at=None if beat_age is None else self.now - timedelta(seconds=beat_age))

    def test_live_requires_connected_and_declared_available(self):
        self._present()
        self.assertEqual(presence.current_mode(self.now), 'live')

    def test_no_presence_rows_is_async(self):
        self.assertEqual(presence.current_mode(self.now), 'async')

    def test_declared_available_but_not_connected_is_async(self):
        self._present(beat_age=61)
        self.assertEqual(presence.current_mode(self.now), 'async')
        self._present(admin=PlatformAdmin.objects.create(username='b', password_hash='x'),
                      beat_age=None)
        self.assertEqual(presence.current_mode(self.now), 'async')

    def test_connected_but_not_declared_available_is_async(self):
        for status in ('away', 'offline'):
            SupportPresence.objects.all().delete()
            self._present(status=status)
            self.assertEqual(presence.current_mode(self.now), 'async', status)

    def test_inactive_admin_is_never_eligible(self):
        self.admin.active = False
        self.admin.save()
        self._present()
        self.assertEqual(presence.current_mode(self.now), 'async')

    def test_future_dated_heartbeat_is_not_connected(self):
        self._present(beat_age=-300)
        self.assertEqual(presence.current_mode(self.now), 'async')

    def test_any_one_eligible_agent_is_enough(self):
        self._present(status='offline')
        other = PlatformAdmin.objects.create(username='bob', password_hash='x', active=True)
        self._present(admin=other)
        self.assertEqual(presence.current_mode(self.now), 'live')

    def test_window_boundary_and_configuration(self):
        self._present(beat_age=59)
        self.assertEqual(presence.current_mode(self.now), 'live')
        SupportPresence.objects.update(last_heartbeat_at=self.now - timedelta(seconds=61))
        self.assertEqual(presence.current_mode(self.now), 'async')
        with mock.patch.dict(os.environ, {'KG_SUPPORT_PRESENCE_WINDOW_S': '90'}):
            self.assertEqual(presence.current_mode(self.now), 'live')

    def test_snapshot_reports_connected_declared_and_eligible_separately(self):
        self._present(status='away')                                  # connected, not declared
        b = PlatformAdmin.objects.create(username='bob', password_hash='x', active=True)
        self._present(admin=b, beat_age=500)                          # declared, not connected
        c = PlatformAdmin.objects.create(username='cy', password_hash='x', active=True)
        self._present(admin=c, beat_age=5)                            # both
        rows = {r['username']: r for r in presence.snapshot(self.now)}
        self.assertEqual((rows['ann']['connected'], rows['ann']['declared'], rows['ann']['eligible']),
                         (True, False, False))
        self.assertEqual((rows['bob']['connected'], rows['bob']['declared'], rows['bob']['eligible']),
                         (False, True, False))
        self.assertEqual((rows['cy']['connected'], rows['cy']['declared'], rows['cy']['eligible']),
                         (True, True, True))

    def test_heartbeat_and_set_status_write_the_row(self):
        presence.set_status(self.admin, 'available')
        presence.heartbeat(self.admin, now=self.now)
        p = SupportPresence.objects.get(admin=self.admin)
        self.assertEqual(p.manual_status, 'available')
        self.assertEqual(p.last_heartbeat_at, self.now)
        with self.assertRaises(ValueError):
            presence.set_status(self.admin, 'busy')

    def test_going_offline_takes_effect_immediately_despite_a_fresh_heartbeat(self):
        presence.set_status(self.admin, 'available')
        presence.heartbeat(self.admin)
        self.assertEqual(presence.current_mode(), 'live')
        presence.set_status(self.admin, 'offline')
        self.assertEqual(presence.current_mode(), 'async')


class EndpointTests(TestCase):
    def setUp(self):
        ratelimit._HITS.clear()
        self.c = Client()
        self.admin = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True)
        self.h = _bearer(AdminAuthToken.issue(self.admin).key)

    def _put(self, status):
        return self.c.put(SET, json.dumps({'status': status}),
                          content_type='application/json', **self.h)

    def test_status_makes_no_response_time_promise_by_default(self):
        body = self.c.get(STATUS).json()
        self.assertEqual(set(body), {'mode', 'reply_target_minutes'})
        self.assertEqual(body['mode'], 'async')
        self.assertIsNone(body['reply_target_minutes'])

    def test_a_reply_target_appears_only_when_the_owner_configures_one(self):
        with mock.patch.dict(os.environ, {'KG_SUPPORT_REPLY_TARGET_MINUTES': '45'}):
            self.assertEqual(self.c.get(STATUS).json()['reply_target_minutes'], 45)
        for junk in ('', '0', '-5', 'soon'):
            with mock.patch.dict(os.environ, {'KG_SUPPORT_REPLY_TARGET_MINUTES': junk}):
                self.assertIsNone(self.c.get(STATUS).json()['reply_target_minutes'], junk)

    def test_status_never_exposes_the_operational_sla_or_names(self):
        self._put('available')
        self.c.post(HEARTBEAT, '{}', content_type='application/json', **self.h)
        body = self.c.get(STATUS)
        self.assertEqual(body.json()['mode'], 'live')
        self.assertNotIn('480', body.content.decode())
        self.assertNotIn('ann', body.content.decode())

    def test_status_requires_no_auth_and_presence_endpoints_require_admin(self):
        self.assertEqual(self.c.get(STATUS).status_code, 200)
        self.assertEqual(self.c.post(HEARTBEAT, '{}', content_type='application/json').status_code, 401)
        self.assertEqual(self.c.put(SET, '{}', content_type='application/json').status_code, 401)
        self.assertEqual(self.c.get(SET).status_code, 401)

    def test_the_loopback_script_token_has_no_availability_to_report(self):
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'script-token'}):
            hdr = _bearer('script-token')
            self.assertEqual(self.c.post(HEARTBEAT, '{}', content_type='application/json',
                                         **hdr).status_code, 403)
            self.assertEqual(self.c.put(SET, '{"status":"available"}',
                                        content_type='application/json', **hdr).status_code, 403)

    def test_set_status_rejects_unknown_value(self):
        self.assertEqual(self._put('busy').status_code, 400)
        self.assertEqual(self._put('away').status_code, 200)

    def test_admin_snapshot_lists_the_three_facts(self):
        self._put('available')
        self.c.post(HEARTBEAT, '{}', content_type='application/json', **self.h)
        rows = self.c.get(SET, **self.h).json()['agents']
        self.assertEqual([(r['username'], r['connected'], r['declared'], r['eligible'])
                          for r in rows], [('ann', True, True, True)])

    def test_status_endpoint_rejects_post(self):
        self.assertEqual(self.c.post(STATUS, '{}', content_type='application/json').status_code, 405)
