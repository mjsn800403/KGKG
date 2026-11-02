"""Minimal staff reply path (the full inbox is Phase 5)."""
import json
import uuid
from unittest import mock

from django.test import Client, TestCase

from api import ratelimit
from api.models import AdminAuthToken, PlatformAdmin

from .models import ChatMessage, ChatThread


def _bearer(key):
    return {'HTTP_AUTHORIZATION': f'Bearer {key}'}


class ReplyTests(TestCase):
    def setUp(self):
        ratelimit._HITS.clear()
        self.c = Client()
        p = mock.patch('api.chat.views_public._verify_turnstile', return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.admin = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True)
        self.h = _bearer(AdminAuthToken.issue(self.admin).key)
        r = self.c.post('/api/chat/threads/', json.dumps({'message': 'hello', 'client_id': 'c1'}),
                        content_type='application/json')
        d = r.json()
        self.tid, self.token = d['thread_id'], d['token']

    def reply(self, body, hdr=None, tid=None):
        return self.c.post(f'/api/admin/chat/threads/{tid or self.tid}/reply/',
                           json.dumps(body), content_type='application/json',
                           **(self.h if hdr is None else hdr))

    def poll(self):
        return self.c.get(f'/api/chat/threads/{self.tid}/messages/',
                          HTTP_X_CHAT_TOKEN=self.token).json()

    def test_public_reply_appears_in_visitor_poll_and_sets_waiting_customer(self):
        r = self.reply({'message': 'Our plans start at ...'})
        self.assertEqual(r.status_code, 201)
        got = self.poll()
        self.assertEqual([(m['author_kind'], m['body']) for m in got['messages']],
                         [('visitor', 'hello'), ('admin', 'Our plans start at ...')])
        self.assertEqual(got['status'], 'waiting_customer')
        self.assertEqual(ChatMessage.objects.get(author_kind='admin').author_admin, self.admin)

    def test_internal_note_never_appears_in_visitor_poll_and_keeps_status(self):
        self.reply({'message': 'looks like a duplicate lead', 'internal': True})
        got = self.poll()
        self.assertEqual([m['body'] for m in got['messages']], ['hello'])
        self.assertEqual(got['status'], 'waiting_staff')
        self.assertTrue(ChatMessage.objects.get(internal=True).internal)

    def test_reply_requires_admin_token(self):
        self.assertEqual(self.reply({'message': 'x'}, hdr={}).status_code, 401)
        self.assertEqual(ChatMessage.objects.filter(author_kind='admin').count(), 0)

    def test_visitor_token_is_not_an_admin_credential(self):
        self.assertEqual(self.reply({'message': 'x'}, hdr=_bearer(self.token)).status_code, 401)

    def test_reply_to_unknown_thread_404(self):
        self.assertEqual(self.reply({'message': 'x'}, tid=str(uuid.uuid4())).status_code, 404)
        self.assertEqual(self.reply({'message': 'x'}, tid='junk').status_code, 404)

    def test_empty_reply_rejected(self):
        self.assertEqual(self.reply({'message': ' ​ '}).status_code, 400)

    def test_public_reply_reopens_a_closed_thread(self):
        ChatThread.objects.filter(pk=self.tid).update(status='closed')
        self.assertEqual(self.reply({'message': 'one more thing'}).status_code, 201)
        self.assertEqual(ChatThread.objects.get(pk=self.tid).status, 'waiting_customer')
