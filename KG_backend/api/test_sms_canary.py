"""SMS paging canary (#24): a weekly test message whose delivery receipt is
read back, so a provider that silently drops pages is noticed."""
import datetime
import os
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from . import alert_rules
from .models import SystemState

# 07:00 UTC is 10:30 in Tehran (inside the window); 20:00 UTC is 23:30 (outside).
IN_WINDOW = datetime.datetime(2026, 11, 4, 7, 0, tzinfo=datetime.timezone.utc)
OUT_OF_WINDOW = datetime.datetime(2026, 11, 4, 20, 0, tzinfo=datetime.timezone.utc)


class CanaryTests(TestCase):
    def setUp(self):
        for p in (mock.patch('api.monitoring.TESTING', False),
                  mock.patch.dict(os.environ, {'KG_ALERT_PHONES': '09120000001,09120000002'})):
            p.start()
            self.addCleanup(p.stop)
        self.sms = mock.patch('api.portal._post_sms', return_value=(True, '123456789')).start()
        self.addCleanup(mock.patch.stopall)
        self.dlv = mock.patch.object(alert_rules, '_sms_delivery', return_value='0').start()

    def run_at(self, when):
        with mock.patch.object(timezone, 'now', return_value=when):
            return alert_rules._sms_canary()

    def state(self):
        return SystemState.get('sms_canary', {})

    def test_sends_once_in_the_daytime_window_to_every_number(self):
        self.assertEqual(self.run_at(OUT_OF_WINDOW), {})
        self.sms.assert_not_called()
        self.assertEqual(self.run_at(IN_WINDOW), {})
        self.assertEqual(self.sms.call_count, 2)
        self.assertIn('لغو11', self.sms.call_args[0][1])
        self.assertEqual(self.state()['status'], 'pending')
        self.run_at(IN_WINDOW + datetime.timedelta(minutes=5))
        self.assertEqual(self.sms.call_count, 2)            # not again while pending

    def test_a_delivered_receipt_resolves_it(self):
        self.run_at(IN_WINDOW)
        self.dlv.return_value = '1'
        self.assertEqual(self.run_at(IN_WINDOW + datetime.timedelta(minutes=10)), {})
        self.assertEqual(self.state()['status'], 'delivered')

    def test_no_receipt_within_the_wait_opens_the_alert(self):
        self.run_at(IN_WINDOW)
        self.assertEqual(self.run_at(IN_WINDOW + datetime.timedelta(minutes=30)), {})
        out = self.run_at(IN_WINDOW + datetime.timedelta(hours=3))
        self.assertEqual(out['infra:sms_canary'][0], 'critical')

    def test_final_failure_codes_alert_without_waiting(self):
        self.run_at(IN_WINDOW)
        self.dlv.return_value = '2'
        self.assertIn('infra:sms_canary', self.run_at(IN_WINDOW + datetime.timedelta(minutes=10)))

    def test_a_refused_send_alerts_at_once(self):
        self.sms.return_value = (False, '11')
        self.assertIn('infra:sms_canary', self.run_at(IN_WINDOW))
        self.assertEqual(self.state()['status'], 'failed')

    def test_the_alert_stays_open_until_a_later_canary_is_delivered(self):
        self.sms.return_value = (False, '2')
        self.run_at(IN_WINDOW)
        self.sms.return_value = (True, '987654321')
        week = IN_WINDOW + datetime.timedelta(days=7)
        self.assertIn('infra:sms_canary', self.run_at(week))   # new one pending, old one failed
        self.dlv.return_value = '1'
        self.assertEqual(self.run_at(week + datetime.timedelta(minutes=10)), {})

    def test_next_canary_after_the_cadence(self):
        self.run_at(IN_WINDOW)
        self.dlv.return_value = '1'
        self.run_at(IN_WINDOW + datetime.timedelta(minutes=10))
        self.run_at(IN_WINDOW + datetime.timedelta(days=6))
        self.assertEqual(self.sms.call_count, 2)
        self.run_at(IN_WINDOW + datetime.timedelta(days=7))
        self.assertEqual(self.sms.call_count, 4)

    def test_off_switch_no_numbers_and_test_runs(self):
        with mock.patch.object(alert_rules, 'CANARY_DAYS', 0):
            self.assertEqual(self.run_at(IN_WINDOW), {})
        with mock.patch.dict(os.environ, {'KG_ALERT_PHONES': ''}):
            self.assertEqual(self.run_at(IN_WINDOW), {})
        with mock.patch('api.monitoring.TESTING', True):
            self.assertEqual(self.run_at(IN_WINDOW), {})
        self.sms.assert_not_called()
