"""The pipeline disk guard must clear its own alert when the disk recovers.

Why this file exists: a `pipeline_disk_low` alert raised on 2026-07-19 was
still open and critical on 2026-10-27, with 75 GB free. The guard raises the
alert when the pipeline is about to run and finds too little space, and
evaluate_alerts deliberately does not own that key — so once raised, nothing
ever cleared it. A permanently-open critical makes "open critical alerts"
useless as a signal, which is worse than not having the alert at all.

The fix resolves it only by re-checking the real condition, never merely
because a sweep did not raise it. These tests pin that distinction down.
"""

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from . import ingest
from .models import SystemAlert


FLOOR = ingest.DISK_MIN_FREE_GB


def _open_alert(age_days=0):
    alert = SystemAlert.objects.create(
        key='pipeline_disk_low', severity='critical',
        message='پردازش بسته‌ها متوقف شد', context={'free_gb': 8.5, 'min_gb': FLOOR},
    )
    if age_days:
        old = timezone.now() - timedelta(days=age_days)
        SystemAlert.objects.filter(pk=alert.pk).update(first_seen=old, last_seen=old)
    return alert


def _is_open():
    return SystemAlert.objects.filter(key='pipeline_disk_low', is_open=True).exists()


class DiskGuardRaiseTests(TestCase):
    def test_guard_raises_and_alerts_below_the_floor(self):
        with mock.patch.object(ingest, 'disk_free_gb', return_value=FLOOR - 10):
            with self.assertRaises(RuntimeError):
                ingest.check_disk_guard()
        self.assertTrue(_is_open())

    def test_guard_passes_above_the_floor(self):
        with mock.patch.object(ingest, 'disk_free_gb', return_value=FLOOR + 50):
            self.assertEqual(ingest.check_disk_guard(), FLOOR + 50)
        self.assertFalse(_is_open())


class DiskGuardResolveTests(TestCase):
    def test_guard_clears_its_own_alert_once_space_is_back(self):
        _open_alert()
        with mock.patch.object(ingest, 'disk_free_gb', return_value=FLOOR + 50):
            ingest.check_disk_guard()
        self.assertFalse(_is_open())
        row = SystemAlert.objects.get(key='pipeline_disk_low')
        self.assertIsNotNone(row.resolved_at)

    def test_resolution_requires_margin_above_the_floor(self):
        """Resolving the instant the disk crosses the floor would flap the
        alert on and off around the boundary."""
        _open_alert()
        with mock.patch.object(ingest, 'disk_free_gb', return_value=FLOOR + 0.5):
            self.assertIsNone(ingest.resolve_disk_guard_if_recovered())
        self.assertTrue(_is_open())

    def test_resolution_reports_the_free_space_it_saw(self):
        _open_alert()
        with mock.patch.object(ingest, 'disk_free_gb', return_value=FLOOR * 2):
            self.assertEqual(ingest.resolve_disk_guard_if_recovered(), FLOOR * 2)

    def test_nothing_to_do_when_no_alert_is_open(self):
        with mock.patch.object(ingest, 'disk_free_gb', return_value=FLOOR * 2):
            self.assertIsNone(ingest.resolve_disk_guard_if_recovered())

    def test_a_resolved_alert_is_not_resolved_twice(self):
        alert = _open_alert()
        alert.is_open = False
        alert.resolved_at = timezone.now()
        alert.save()
        with mock.patch.object(ingest, 'disk_free_gb', return_value=FLOOR * 2):
            self.assertIsNone(ingest.resolve_disk_guard_if_recovered())

    def test_still_low_leaves_the_alert_open(self):
        _open_alert()
        with mock.patch.object(ingest, 'disk_free_gb', return_value=FLOOR - 1):
            self.assertIsNone(ingest.resolve_disk_guard_if_recovered())
        self.assertTrue(_is_open())


class SweepResolvesStaleAlertTests(TestCase):
    """The regression that started this: the pipeline may not run for months,
    so the five-minute sweep has to be able to clear it too."""

    def test_sweep_clears_a_three_month_old_alert_when_disk_is_healthy(self):
        _open_alert(age_days=100)
        from . import monitoring
        with mock.patch.object(ingest, 'disk_free_gb', return_value=FLOOR * 3):
            result = monitoring.evaluate_alerts()
        self.assertFalse(_is_open())
        self.assertIn('pipeline_disk_low', result['resolved'])

    def test_sweep_leaves_it_open_while_the_disk_is_still_low(self):
        _open_alert(age_days=100)
        from . import monitoring
        with mock.patch.object(ingest, 'disk_free_gb', return_value=FLOOR - 5):
            result = monitoring.evaluate_alerts()
        self.assertTrue(_is_open())
        self.assertNotIn('pipeline_disk_low', result['resolved'])

    def test_sweep_does_not_resolve_it_merely_because_it_did_not_raise_it(self):
        """The ownership rule still holds: the sweep clears this key only by
        re-checking the condition, which is why the disk read is mocked low
        here and the alert survives."""
        _open_alert()
        from . import monitoring
        with mock.patch.object(ingest, 'disk_free_gb', return_value=0.1):
            monitoring.evaluate_alerts()
        self.assertTrue(_is_open())
