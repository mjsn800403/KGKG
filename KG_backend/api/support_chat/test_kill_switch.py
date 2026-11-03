"""Server-side kill switch: the public chat is dark unless a person turns it on."""
import os
from unittest import mock

from django.test import Client, SimpleTestCase

from . import config
from .helpers import CREATE, SupportCase
from .models import SupportThread


class EnabledFlagTests(SimpleTestCase):
    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('KG_SUPPORT_CHAT_ENABLED', None)
            self.assertFalse(config.enabled())

    def test_only_the_literal_one_enables(self):
        for value, expected in (('1', True), (' 1 ', True), ('0', False), ('', False),
                                ('true', False), ('yes', False), ('on', False)):
            with mock.patch.dict(os.environ, {'KG_SUPPORT_CHAT_ENABLED': value}):
                self.assertIs(config.enabled(), expected, value)


class KillSwitchTests(SupportCase):
    def off(self):
        p = mock.patch.dict(os.environ, {'KG_SUPPORT_CHAT_ENABLED': '0'})
        p.start()
        self.addCleanup(p.stop)

    def test_status_reports_enabled(self):
        self.assertTrue(self.c.get('/api/support-chat/status/').json()['enabled'])
        self.off()
        r = self.c.get('/api/support-chat/status/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['enabled'])

    def test_thread_creation_is_refused_while_off_and_stores_nothing(self):
        tid, tok, _ = self.create()
        self.off()
        before = SupportThread.objects.count()
        r = self.send(CREATE, {'message': 'hello', 'client_id': 'c-x'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(SupportThread.objects.count(), before)

    def test_refused_before_turnstile_is_consulted(self):
        self.off()
        self.turnstile.reset_mock()
        self.send(CREATE, {'message': 'hello', 'client_id': 'c-x'})
        self.turnstile.assert_not_called()

    def test_idempotent_create_with_known_token_is_also_refused(self):
        tid, tok, _ = self.create()
        self.off()
        r = self.send(CREATE, {'message': 'again', 'client_id': 'c-first', 'token': tok})
        self.assertEqual(r.status_code, 404)

    def test_existing_threads_stay_usable_by_their_owners(self):
        tid, tok, _ = self.create(message='before the switch was turned off')
        self.off()
        got = self.poll(tid, tok)
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()['messages'][0]['body'], 'before the switch was turned off')
        sent = self.send(f'/api/support-chat/threads/{tid}/messages/',
                         {'message': 'still here', 'client_id': 'c-2'}, token=tok)
        self.assertEqual(sent.status_code, 201)

    def test_staff_can_still_reply_while_off(self):
        tid, _, _ = self.create()
        self.off()
        self.assertEqual(self.staff(tid, 'reply', {'message': 'we are here'}).status_code, 201)

    def test_default_environment_is_off(self):
        """Without the test helper's opt-in the public create endpoint is dark."""
        env = {k: v for k, v in os.environ.items() if k != 'KG_SUPPORT_CHAT_ENABLED'}
        with mock.patch.dict(os.environ, env, clear=True):
            r = Client().post(CREATE, '{"message":"hi"}', content_type='application/json')
        self.assertEqual(r.status_code, 404)
