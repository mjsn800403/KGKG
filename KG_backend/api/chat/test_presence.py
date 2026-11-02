"""Agent presence and the public status endpoint. Live is claimed only when a
real agent is available AND recently seen."""
import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from api.models import AdminAuthToken, PlatformAdmin

from . import presence
from .models import AgentPresence

STATUS = '/api/chat/status/'
HEARTBEAT = '/api/admin/chat/presence/heartbeat/'
SET = '/api/admin/chat/presence/'


def _bearer(key):
    return {'HTTP_AUTHORIZATION': f'Bearer {key}'}


class ModeTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.admin = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True)

    def _present(self, status='available', beat_age=10, admin=None):
        return AgentPresence.objects.create(
            admin=admin or self.admin, manual_status=status,
            last_heartbeat_at=self.now - timedelta(seconds=beat_age))

    def test_live_requires_available_and_fresh_heartbeat(self):
        self._present()
        self.assertEqual(presence.current_mode(self.now), 'live')

    def test_no_presence_rows_is_async(self):
        self.assertEqual(presence.current_mode(self.now), 'async')

    def test_heartbeat_older_than_60s_is_async(self):
        self._present(beat_age=61)
        self.assertEqual(presence.current_mode(self.now), 'async')

    def test_away_with_fresh_heartbeat_is_async(self):
        self._present(status='away')
        self.assertEqual(presence.current_mode(self.now), 'async')

    def test_inactive_admin_never_counts(self):
        self.admin.active = False
        self.admin.save()
        self._present()
        self.assertEqual(presence.current_mode(self.now), 'async')

    def test_future_dated_heartbeat_does_not_count_as_live(self):
        self._present(beat_age=-300)
        self.assertEqual(presence.current_mode(self.now), 'async')

    def test_any_one_available_agent_is_enough(self):
        self._present(status='offline')
        other = PlatformAdmin.objects.create(username='bob', password_hash='x', active=True)
        self._present(admin=other)
        self.assertEqual(presence.current_mode(self.now), 'live')

    def test_heartbeat_and_set_status_write_the_row(self):
        presence.set_status(self.admin, 'available')
        presence.heartbeat(self.admin, now=self.now)
        p = AgentPresence.objects.get(admin=self.admin)
        self.assertEqual(p.manual_status, 'available')
        self.assertEqual(p.last_heartbeat_at, self.now)
        with self.assertRaises(ValueError):
            presence.set_status(self.admin, 'busy')


class EndpointTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.admin = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True)
        self.h = _bearer(AdminAuthToken.issue(self.admin).key)

    def _put(self, status):
        return self.c.put(SET, json.dumps({'status': status}),
                          content_type='application/json', **self.h)

    def test_status_endpoint_shape_and_no_names_leaked(self):
        r = self.c.get(STATUS)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {'mode', 'expected_reply_minutes'})
        self.assertEqual(body['mode'], 'async')
        self.assertEqual(body['expected_reply_minutes'], 8 * 60)
        self._put('available')
        self.c.post(HEARTBEAT, '{}', content_type='application/json', **self.h)
        live = self.c.get(STATUS).json()
        self.assertEqual(live['mode'], 'live')
        self.assertNotIn('ann', json.dumps(live))

    def test_status_endpoint_requires_no_auth_and_heartbeat_requires_admin(self):
        self.assertEqual(self.c.get(STATUS).status_code, 200)
        self.assertEqual(self.c.post(HEARTBEAT, '{}', content_type='application/json').status_code, 401)
        self.assertEqual(self.c.put(SET, '{}', content_type='application/json').status_code, 401)

    def test_set_status_rejects_unknown_value(self):
        self.assertEqual(self._put('busy').status_code, 400)
        self.assertEqual(self._put('away').status_code, 200)

    def test_status_endpoint_rejects_post(self):
        self.assertEqual(self.c.post(STATUS, '{}', content_type='application/json').status_code, 405)
