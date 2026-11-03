"""Support-chat tables: visitor threads, their messages, ratings, staff presence."""
from django.db import IntegrityError, transaction
from django.test import TestCase

from api.models import Company, CompanyRequest, PlatformAdmin

from .models import SupportMessage, SupportPresence, SupportRating, SupportThread


def _thread(**kw):
    kw.setdefault('token_hash', 'h' * 64)
    return SupportThread.objects.create(**kw)


class SupportModelTests(TestCase):
    def test_thread_defaults(self):
        t = _thread()
        self.assertEqual((t.intent, t.status, t.priority), ('other', 'open', 'normal'))
        self.assertEqual((t.reopen_count, t.staff_seen_at, t.closed_at), (0, None, None))
        self.assertIsNotNone(t.last_activity_at)
        self.assertEqual(len(str(t.id)), 36)
        self.assertIsNone(t.promoted_request)

    def test_token_hash_is_unique(self):
        _thread(token_hash='a' * 64)
        with self.assertRaises(IntegrityError), transaction.atomic():
            _thread(token_hash='a' * 64)

    def test_client_id_unique_per_thread_but_blank_repeats_allowed(self):
        t, other = _thread(token_hash='1' * 64), _thread(token_hash='2' * 64)
        SupportMessage.objects.create(thread=t, author_kind='visitor', body='a', client_id='c1')
        SupportMessage.objects.create(thread=other, author_kind='visitor', body='a', client_id='c1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupportMessage.objects.create(thread=t, author_kind='visitor', body='b', client_id='c1')
        SupportMessage.objects.create(thread=t, author_kind='admin', body='x')
        SupportMessage.objects.create(thread=t, author_kind='admin', body='y')
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
        p = SupportPresence.objects.create(admin=a)
        self.assertEqual(p.manual_status, 'offline')
        self.assertIsNone(p.last_heartbeat_at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupportPresence.objects.create(admin=a)

    def test_one_rating_per_closure_but_history_across_closures(self):
        t = _thread()
        SupportRating.objects.create(thread=t, score=2, closure=0)
        SupportRating.objects.create(thread=t, score=5, closure=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupportRating.objects.create(thread=t, score=3, closure=1)
        self.assertEqual(t.ratings.count(), 2)

    def test_ratings_go_with_their_thread(self):
        t = _thread()
        SupportRating.objects.create(thread=t, score=4)
        t.delete()
        self.assertEqual(SupportRating.objects.count(), 0)
