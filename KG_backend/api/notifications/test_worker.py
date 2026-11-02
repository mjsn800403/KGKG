"""The outbox worker: claim, send, retry, give up visibly, never double-send."""
import os
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from api.models import SystemAlert

from . import providers, worker
from .models import NotificationOutbox

SMS_OK = 'خدمات گستر\nپاسخ پشتیبانی آماده است.\nلغو11'


def _row(**kw):
    base = dict(event_type='chat.new', channel='sms', recipient_kind='staff',
                recipient_ref='09120000000', status='queued',
                next_attempt_at=timezone.now() - timedelta(hours=1),
                payload={'subject': '', 'body': SMS_OK})
    base.update(kw)
    return NotificationOutbox.objects.create(**base)


class WorkerBase(TestCase):
    def setUp(self):
        self.fake = providers.FakeProvider()
        self.env = mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'live', 'KG_NOTIFY_EMAIL': 'live'})
        self.env.start()
        self.addCleanup(self.env.stop)
        p = mock.patch('api.notifications.worker.providers.get_provider', return_value=self.fake)
        p.start()
        self.addCleanup(p.stop)
        self.now = timezone.now()

    def run_worker(self, now=None, **kw):
        return worker.process_due(now=now or self.now, **kw)


class SendTests(WorkerBase):
    def test_success_marks_sent_with_provider_ref(self):
        r = _row()
        counts = self.run_worker()
        r.refresh_from_db()
        self.assertEqual(r.status, 'sent')
        self.assertEqual(r.provider_ref, 'fake-1')
        self.assertEqual(r.attempts, 1)
        self.assertEqual(r.sent_at, self.now)
        self.assertEqual(counts['sent'], 1)

    def test_future_rows_are_not_due(self):
        _row(next_attempt_at=self.now + timedelta(minutes=5))
        self.run_worker()
        self.assertEqual(self.fake.sent, [])

    def test_sms_body_the_operator_would_refuse_is_dead_without_sending(self):
        r = _row(payload={'subject': '', 'body': 'سلام https://x.ir'})
        self.run_worker()
        r.refresh_from_db()
        self.assertEqual(r.status, 'dead')
        self.assertEqual(self.fake.sent, [])
        self.assertIn('link', r.last_error)


class RetryTests(WorkerBase):
    def test_failure_schedules_backoff_1_then_5_minutes(self):
        r = _row()
        self.fake.fail_with = 'down'
        self.run_worker()
        r.refresh_from_db()
        self.assertEqual((r.status, r.attempts), ('failed', 1))
        self.assertEqual(r.next_attempt_at, self.now + timedelta(minutes=1))
        later = self.now + timedelta(minutes=1)
        self.run_worker(now=later)
        r.refresh_from_db()
        self.assertEqual(r.attempts, 2)
        self.assertEqual(r.next_attempt_at, later + timedelta(minutes=5))
        self.assertEqual(r.last_error, 'down')

    def test_fifth_failure_marks_dead_and_opens_systemalert(self):
        r = _row()
        self.fake.fail_with = 'down'
        t = self.now
        for step in (0, 1, 5, 15, 60):
            t += timedelta(minutes=step)
            self.run_worker(now=t)
        r.refresh_from_db()
        self.assertEqual((r.status, r.attempts), ('dead', 5))
        alert = SystemAlert.objects.get(key='notify:dead', is_open=True)
        self.assertEqual(alert.severity, 'warning')

    def test_dead_alert_resolves_once_nothing_recent_is_dead(self):
        _row(status='dead', attempts=5)
        self.run_worker()
        self.assertTrue(SystemAlert.objects.filter(key='notify:dead', is_open=True).exists())
        NotificationOutbox.objects.update(created_at=self.now - timedelta(days=2))
        self.run_worker()
        self.assertFalse(SystemAlert.objects.filter(key='notify:dead', is_open=True).exists())

    def test_provider_exception_is_a_failure_not_a_crash(self):
        r = _row()
        with mock.patch.object(self.fake, 'send', side_effect=RuntimeError('kaboom')):
            self.run_worker()
        r.refresh_from_db()
        self.assertEqual(r.status, 'failed')
        self.assertIn('kaboom', r.last_error)


class ClaimTests(WorkerBase):
    def test_stuck_sending_row_is_reclaimed_after_10_minutes(self):
        r = _row(status='sending', claimed_at=self.now - timedelta(minutes=11))
        self.run_worker()
        r.refresh_from_db()
        self.assertEqual(r.status, 'sent')

    def test_fresh_sending_row_is_left_to_its_owner(self):
        _row(status='sending', claimed_at=self.now - timedelta(minutes=2))
        self.run_worker()
        self.assertEqual(self.fake.sent, [])

    def test_second_claim_on_same_row_does_not_send_twice(self):
        r = _row()
        self.assertTrue(worker._claim(r.pk, self.now))
        self.assertFalse(worker._claim(r.pk, self.now))


class ModeTests(WorkerBase):
    def test_off_mode_leaves_queued_rows_untouched(self):
        r = _row()
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'off'}):
            counts = self.run_worker()
        r.refresh_from_db()
        self.assertEqual((r.status, r.attempts), ('queued', 0))
        self.assertEqual(self.fake.sent, [])
        self.assertEqual(counts['skipped'], 1)

    def test_dry_run_never_calls_real_provider_and_ends_dry_run(self):
        r = _row()
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'dry_run'}):
            self.run_worker()
        r.refresh_from_db()
        self.assertEqual(r.status, 'dry_run')
        self.assertEqual(self.fake.sent, [])

    def test_mode_switched_live_to_off_midway_keeps_remaining_rows_queued(self):
        first, second = _row(), _row()

        def send_then_switch_off(to, subject, body):
            os.environ['KG_NOTIFY_SMS'] = 'off'
            return providers.SendResult(True, provider_ref='x')
        with mock.patch.object(self.fake, 'send', side_effect=send_then_switch_off):
            self.run_worker()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, 'sent')
        self.assertEqual(second.status, 'queued')


class CapTests(WorkerBase):
    def test_sms_hourly_cap_defers_without_dropping(self):
        for _ in range(3):
            _row()
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS_MAX_PER_HOUR': '2'}):
            counts = self.run_worker()
        self.assertEqual(counts['sent'], 2)
        self.assertEqual(counts['deferred'], 1)
        left = NotificationOutbox.objects.get(status='queued')
        self.assertEqual(left.next_attempt_at, self.now + timedelta(minutes=10))
        self.assertEqual(left.attempts, 0)

    def test_cap_counts_messages_already_sent_this_hour(self):
        _row(status='sent', sent_at=self.now - timedelta(minutes=30))
        _row()
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS_MAX_PER_HOUR': '1'}):
            counts = self.run_worker()
        self.assertEqual((counts['sent'], counts['deferred']), (0, 1))

    def test_email_does_not_consume_the_sms_cap(self):
        _row(channel='email', recipient_ref='a@example.com',
             payload={'subject': 's', 'body': 'b'})
        _row()
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS_MAX_PER_HOUR': '1'}):
            counts = self.run_worker()
        self.assertEqual(counts['sent'], 2)
