"""Chat tables: anonymous visitor threads, their messages, and agent presence."""
from django.db import IntegrityError, transaction
from django.test import TestCase

from api.models import Company, CompanyRequest, PlatformAdmin

from .models import AgentPresence, ChatMessage, ChatThread


def _thread(**kw):
    kw.setdefault('token_hash', 'h' * 64)
    return ChatThread.objects.create(**kw)


class ChatModelTests(TestCase):
    def test_thread_defaults(self):
        t = _thread()
        self.assertEqual((t.intent, t.status, t.priority), ('other', 'open', 'normal'))
        self.assertIsNotNone(t.last_activity_at)
        self.assertEqual(len(str(t.id)), 36)
        self.assertIsNone(t.promoted_request)

    def test_token_hash_is_unique(self):
        _thread(token_hash='a' * 64)
        with self.assertRaises(IntegrityError), transaction.atomic():
            _thread(token_hash='a' * 64)

    def test_client_id_unique_per_thread_but_blank_repeats_allowed(self):
        t, other = _thread(token_hash='1' * 64), _thread(token_hash='2' * 64)
        ChatMessage.objects.create(thread=t, author_kind='visitor', body='a', client_id='c1')
        ChatMessage.objects.create(thread=other, author_kind='visitor', body='a', client_id='c1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ChatMessage.objects.create(thread=t, author_kind='visitor', body='b', client_id='c1')
        ChatMessage.objects.create(thread=t, author_kind='admin', body='x')
        ChatMessage.objects.create(thread=t, author_kind='admin', body='y')
        self.assertEqual(t.messages.count(), 3)

    def test_deleting_promoted_request_does_not_delete_thread(self):
        co = Company.objects.create(name='Acme')
        req = CompanyRequest.objects.create(company=co, subject='s')
        t = _thread(promoted_request=req)
        req.delete()
        t.refresh_from_db()
        self.assertIsNone(t.promoted_request)

    def test_presence_defaults_offline_and_is_one_per_admin(self):
        a = PlatformAdmin.objects.create(username='ann')
        p = AgentPresence.objects.create(admin=a)
        self.assertEqual(p.manual_status, 'offline')
        self.assertIsNone(p.last_heartbeat_at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AgentPresence.objects.create(admin=a)
