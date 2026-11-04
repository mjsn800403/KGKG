"""Unanswered-visitor alerts on the existing alert engine (api/alert_rules.py).

Nothing here can send anything: ``deliver`` is replaced by a counter in every test that
runs a sweep, and test runs never SMS anyway (``monitoring.TESTING``). The rule is off
unless KG_SUPPORT_ALERTS is set, and these tests prove the off state first.
"""
import json
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from api import alert_rules, monitoring
from api.models import SystemAlert

from .helpers import SupportCase
from .models import SupportMessage

OTHER_RULES = ('_login_bruteforce', '_admin_logins', '_sms_failures', '_ai_health', '_infra', '_qa')


def quiet_snapshot(real=monitoring.system_snapshot):
    """The real host snapshot with disk and memory forced healthy, so only the support rule can fire."""
    snap = dict(real())
    snap['disk'] = {**snap.get('disk', {}), 'used_pct': 1}
    snap['memory'] = {**snap.get('memory', {}), 'used_pct': 1}
    snap['db_ok'] = True
    snap['rag_index'] = {**snap.get('rag_index', {}), 'present': True}
    return snap


class AlertCase(SupportCase):
    def setUp(self):
        super().setUp()
        self.deliver = mock.patch.object(alert_rules, 'deliver')
        self.sent = self.deliver.start()
        self.addCleanup(self.deliver.stop)

    def mode(self, value):
        p = mock.patch.dict('os.environ', {'KG_SUPPORT_ALERTS': value})
        p.start()
        self.addCleanup(p.stop)

    def wait(self, seconds, **create):
        tid, _, _ = self.create(client_id=f'c-{seconds}-{SupportMessage.objects.count()}', **create)
        SupportMessage.objects.filter(thread_id=tid).update(
            created_at=timezone.now() - timedelta(seconds=seconds))
        return tid

    def sweep(self):
        """The real evaluate_alerts, with the unrelated rules and the host snapshot silenced."""
        patches = [mock.patch.object(alert_rules, n, return_value={}) for n in OTHER_RULES]
        patches.append(mock.patch.object(monitoring, 'system_snapshot', side_effect=quiet_snapshot))
        for p in patches:
            p.start()
        try:
            return monitoring.evaluate_alerts()
        finally:
            for p in reversed(patches):
                p.stop()


class OffByDefault(AlertCase):
    def test_nothing_fires_when_the_flag_is_unset_even_with_a_long_wait(self):
        self.wait(5000)
        self.assertEqual(alert_rules._support_chat(), {})
        self.assertEqual(self.sweep()['open'], [])
        self.assertFalse(SystemAlert.objects.exists())

    def test_unrecognised_and_zero_values_are_off(self):
        self.wait(5000)
        for value in ('0', 'off', 'yes', 'true', 'PAGEX', ''):
            self.mode(value)
            self.assertEqual(alert_rules._support_chat(), {}, value)


class Rule(AlertCase):
    def test_a_fresh_queue_is_silent(self):
        self.mode('1')
        self.wait(10)
        self.assertEqual(alert_rules._support_chat(), {})

    def test_mode_1_warns_but_never_goes_critical(self):
        self.mode('1')
        self.wait(5000)
        out = alert_rules._support_chat()
        self.assertEqual(set(out), {'support:unanswered'})
        severity, message, ctx = out['support:unanswered']
        self.assertEqual(severity, 'warning')
        self.assertIn('گفتگوی پشتیبانی', message)

    def test_mode_page_adds_a_critical_alert_only_past_the_critical_wait(self):
        self.mode('page')
        tid = self.wait(400)                                   # past warn (300 s), before crit (900 s)
        self.assertEqual(set(alert_rules._support_chat()), {'support:unanswered'})
        SupportMessage.objects.filter(thread_id=tid).update(
            created_at=timezone.now() - timedelta(seconds=1000))
        out = alert_rules._support_chat()
        self.assertEqual(set(out), {'support:unanswered', 'support:unanswered:critical'})
        self.assertEqual(out['support:unanswered:critical'][0], 'critical')

    def test_the_alert_carries_counts_and_never_customer_data(self):
        self.mode('page')
        self.wait(1000, message='confidential question 5521',
                  contact={'phone': '09125556677', 'email': 'who@example.com'})
        out = alert_rules._support_chat()
        dump = json.dumps(out, ensure_ascii=False, default=str)
        for secret in ('confidential question 5521', '09125556677', 'who@example.com'):
            self.assertNotIn(secret, dump)
        self.assertEqual(set(out['support:unanswered'][2]), {'waiting', 'oldest_wait_s', 'by_intent'})

    def test_a_failing_health_report_cannot_break_the_other_rules(self):
        self.mode('1')
        with mock.patch('api.support_chat.health.report', side_effect=RuntimeError('db')):
            with mock.patch.object(alert_rules, '_login_bruteforce',
                                   return_value={'sec:x': ('warning', 'm', {})}):
                for n in OTHER_RULES[1:]:
                    p = mock.patch.object(alert_rules, n, return_value={})
                    p.start()
                    self.addCleanup(p.stop)
                self.assertIn('sec:x', alert_rules.evaluate())


class Lifecycle(AlertCase):
    """Through the real sweep: open once, no repeat delivery, escalate once, resolve by itself."""

    def test_dedup_escalation_and_auto_resolve(self):
        self.mode('page')
        tid = self.wait(400)
        first = self.sweep()
        self.assertEqual(first['open'], ['support:unanswered'])
        self.assertEqual(self.sent.call_count, 1)                       # opened and handed to delivery once

        again = self.sweep()                                            # same state: updated, not re-delivered
        self.assertEqual(again['open'], ['support:unanswered'])
        self.assertEqual(SystemAlert.objects.filter(is_open=True).count(), 1)
        self.assertEqual(self.sent.call_count, 1)

        SupportMessage.objects.filter(thread_id=tid).update(
            created_at=timezone.now() - timedelta(seconds=1000))
        esc = self.sweep()                                              # now critical: ONE new alert, delivered once
        self.assertIn('support:unanswered:critical', esc['open'])
        self.assertEqual(self.sent.call_count, 2)
        self.assertEqual(self.sweep()['open'].count('support:unanswered:critical'), 1)
        self.assertEqual(self.sent.call_count, 2)                       # no page on every sweep

        SupportMessage.objects.create(thread_id=tid, author_kind='admin', author_admin=self.admin, body='hi')
        done = self.sweep()                                             # answered: both close themselves
        self.assertEqual(done['open'], [])
        self.assertEqual(sorted(done['resolved']), ['support:unanswered', 'support:unanswered:critical'])
        self.assertFalse(SystemAlert.objects.filter(is_open=True).exists())
        self.assertEqual(self.sent.call_count, 2)

    def test_the_real_delivery_path_sends_nothing_under_test(self):
        self.deliver.stop()                                             # use the real deliver
        self.addCleanup(self.deliver.start)
        self.mode('page')
        self.wait(1000)
        with mock.patch('api.portal._post_sms') as sms:
            self.sweep()
        sms.assert_not_called()
