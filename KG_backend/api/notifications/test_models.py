"""Outbox model: the durable record behind every SMS/email the support
system wants to send. Run:  python manage.py test api.notifications"""
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import NotificationOutbox


def _row(**kw):
    base = dict(event_type='chat.new', channel='sms', recipient_kind='staff',
                recipient_ref='09120000000')
    base.update(kw)
    return NotificationOutbox.objects.create(**base)


class OutboxModelTests(TestCase):
    def test_defaults_are_queued_with_zero_attempts(self):
        r = _row()
        self.assertEqual(r.status, 'queued')
        self.assertEqual(r.attempts, 0)
        self.assertIsNone(r.dedupe_key)
        self.assertIsNotNone(r.next_attempt_at)

    def test_dedupe_key_is_unique(self):
        _row(dedupe_key='thread:1:new:w0')
        with self.assertRaises(IntegrityError), transaction.atomic():
            _row(dedupe_key='thread:1:new:w0')

    def test_two_rows_with_null_dedupe_key_allowed(self):
        _row()
        _row()
        self.assertEqual(NotificationOutbox.objects.count(), 2)
