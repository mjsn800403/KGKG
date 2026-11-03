"""Outbox: customer-facing rows do not keep their text after delivery, and the
queue stays correct when workers and producers race."""
import os
import threading
from datetime import timedelta
from unittest import mock

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from . import providers, service, worker
from .models import NotificationOutbox

SMS = 'خدمات گستر\nپاسخ پشتیبانی آماده است.\nلغو11'


def _row(**kw):
    base = dict(event_type='support_chat.reply', channel='sms', recipient_kind='visitor',
                recipient_ref='09120000000', status='queued',
                next_attempt_at=timezone.now() - timedelta(hours=1),
                payload={'subject': 'subject text', 'body': SMS})
    base.update(kw)
    return NotificationOutbox.objects.create(**base)


class ScrubTests(TestCase):
    def setUp(self):
        self.fake = providers.FakeProvider()
        env = mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'live', 'KG_NOTIFY_EMAIL': 'live'})
        env.start()
        self.addCleanup(env.stop)
        p = mock.patch('api.notifications.worker.providers.get_provider', return_value=self.fake)
        p.start()
        self.addCleanup(p.stop)

    def test_a_visitor_message_body_is_removed_once_sent(self):
        r = _row()
        worker.process_due()
        r.refresh_from_db()
        self.assertEqual(r.status, 'sent')
        self.assertEqual(self.fake.sent[0][2], SMS)                  # it WAS sent in full
        self.assertNotIn('پشتیبانی', str(r.payload))
        self.assertEqual(r.payload.get('scrubbed'), True)

    def test_customer_rows_are_scrubbed_too_and_staff_rows_are_not(self):
        cust, staff = _row(recipient_kind='customer'), _row(recipient_kind='staff')
        worker.process_due()
        cust.refresh_from_db()
        staff.refresh_from_db()
        self.assertTrue(cust.payload.get('scrubbed'))
        self.assertEqual(staff.payload['body'], SMS)

    def test_a_dead_visitor_row_is_scrubbed_but_a_retrying_one_keeps_its_text(self):
        self.fake.fail_with = 'down'
        r = _row()
        worker.process_due()
        r.refresh_from_db()
        self.assertEqual(r.status, 'failed')
        self.assertEqual(r.payload['body'], SMS)                    # still needed for the retry
        NotificationOutbox.objects.filter(pk=r.pk).update(attempts=4,
                                                          next_attempt_at=timezone.now())
        worker.process_due()
        r.refresh_from_db()
        self.assertEqual(r.status, 'dead')
        self.assertTrue(r.payload.get('scrubbed'))

    def test_a_dry_run_visitor_row_is_scrubbed(self):
        r = _row()
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'dry_run'}):
            worker.process_due()
        r.refresh_from_db()
        self.assertEqual(r.status, 'dry_run')
        self.assertTrue(r.payload.get('scrubbed'))

    def test_scrubbing_keeps_the_audit_facts(self):
        r = _row()
        worker.process_due()
        r.refresh_from_db()
        self.assertEqual((r.event_type, r.channel, r.recipient_kind, r.status),
                         ('support_chat.reply', 'sms', 'visitor', 'sent'))
        self.assertTrue(r.provider_ref)
        self.assertIsNotNone(r.sent_at)


def _parallel(n, fn):
    barrier = threading.Barrier(n)
    results, errors = [None] * n, []

    def work(i):
        try:
            barrier.wait(timeout=15)
            results[i] = fn(i)
        except Exception as exc:
            errors.append(repr(exc))
        finally:
            connections.close_all()
    ts = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    assert not errors, errors
    return results


class OutboxConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor == 'sqlite' and connection.is_in_memory_db():
            self.skipTest('threads need a real database: PostgreSQL, or file-backed SQLite')
        self.fake = providers.FakeProvider()
        env = mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'live'})
        env.start()
        self.addCleanup(env.stop)
        p = mock.patch('api.notifications.worker.providers.get_provider', return_value=self.fake)
        p.start()
        self.addCleanup(p.stop)

    def test_simultaneous_enqueues_with_one_dedupe_key_make_one_row(self):
        results = _parallel(8, lambda i: service.enqueue(
            event_type='support_chat.new', channel='sms', recipient_kind='staff',
            recipient_ref='09120000000', subject='', body=SMS, dedupe_key='thread:1:new:w0'))
        self.assertEqual(sum(1 for r in results if r is not None), 1)
        self.assertEqual(NotificationOutbox.objects.count(), 1)

    def test_simultaneous_workers_send_a_row_once(self):
        _row(recipient_kind='staff')
        _parallel(6, lambda i: worker.process_due())
        self.assertEqual(len(self.fake.sent), 1)
        self.assertEqual(NotificationOutbox.objects.get().status, 'sent')
