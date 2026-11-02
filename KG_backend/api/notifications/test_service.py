"""enqueue(): the only way request code asks for a notification."""
import os
from datetime import datetime, timezone as dt_tz
from unittest import mock

from django.test import TestCase

from . import service
from .models import NotificationOutbox


def _enqueue(**kw):
    base = dict(event_type='chat.new', channel='sms', recipient_kind='staff',
                recipient_ref='09120000000', subject='', body='x')
    base.update(kw)
    return service.enqueue(**base)


class EnqueueTests(TestCase):
    def test_enqueue_off_mode_creates_suppressed_row(self):
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'off'}):
            r = _enqueue()
        self.assertEqual(r.status, 'suppressed')

    def test_unset_mode_also_suppresses(self):
        os.environ.pop('KG_NOTIFY_SMS', None)
        self.assertEqual(_enqueue().status, 'suppressed')

    def test_enqueue_dry_run_and_live_create_queued_rows(self):
        for m in ('dry_run', 'live'):
            with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': m}):
                self.assertEqual(_enqueue().status, 'queued', m)

    def test_duplicate_dedupe_key_returns_none_and_creates_no_second_row(self):
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'live'}):
            self.assertIsNotNone(_enqueue(dedupe_key='k1'))
            self.assertIsNone(_enqueue(dedupe_key='k1'))
        self.assertEqual(NotificationOutbox.objects.filter(dedupe_key='k1').count(), 1)

    def test_persian_digit_phone_is_normalised(self):
        r = _enqueue(recipient_ref='۰۹۱۲-۰۰۰ ۰۰۰۰')
        self.assertEqual(r.recipient_ref, '09120000000')

    def test_email_recipient_is_left_alone(self):
        r = _enqueue(channel='email', recipient_ref='Staff@Example.com', subject='s')
        self.assertEqual(r.recipient_ref, 'Staff@Example.com')

    def test_body_and_subject_are_stored_in_payload(self):
        r = _enqueue(subject='subj', body='hello')
        self.assertEqual(r.payload, {'subject': 'subj', 'body': 'hello'})

    def test_unknown_channel_is_rejected(self):
        with self.assertRaises(ValueError):
            _enqueue(channel='pigeon')


class WindowKeyTests(TestCase):
    def test_window_key_same_inside_window_differs_across_windows(self):
        t = lambda m, s=0: datetime(2026, 11, 2, 10, m, s, tzinfo=dt_tz.utc)
        a = service.window_key('thread:7:new', 10, now=t(1))
        self.assertEqual(a, service.window_key('thread:7:new', 10, now=t(9, 59)))
        self.assertNotEqual(a, service.window_key('thread:7:new', 10, now=t(10)))
        self.assertTrue(a.startswith('thread:7:new:'))
