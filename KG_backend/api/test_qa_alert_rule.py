"""Nightly QA results raise alerts like infrastructure does (alert_rules._qa).

qa/nightly.sh writes kgkg_qa_* metrics through the node-exporter textfile
collector; the rule reads them from Prometheus. It must page on a failed
suite or on results that stopped arriving, and stay silent when the nightly
run has never reported (timer not installed yet) or everything passed.
"""
import time
from unittest import mock

from django.test import SimpleTestCase

from api import alert_rules as ar


def prom(suites=None, last_run=None):
    def query(q):
        if q.startswith('kgkg_qa_suite_ok'):
            return [{'metric': {'suite': s}, 'value': [0, str(v)]} for s, v in (suites or {}).items()]
        if q.startswith('kgkg_qa_last_run_timestamp_seconds'):
            return [] if last_run is None else [{'metric': {}, 'value': [0, str(last_run)]}]
        return []
    return query


class QaAlertTests(SimpleTestCase):
    def run_rule(self, **kw):
        with mock.patch.object(ar, '_prom', side_effect=prom(**kw)):
            return ar._qa()

    def test_silent_when_the_nightly_run_never_reported(self):
        self.assertEqual(self.run_rule(), {})

    def test_silent_when_every_suite_passed_recently(self):
        ok = {'stack': 1, 'e2e': 1, 'dast': 1, 'perf': 1}
        self.assertEqual(self.run_rule(suites=ok, last_run=time.time() - 3600), {})

    def test_failed_suite_is_a_warning_naming_the_suite(self):
        out = self.run_rule(suites={'stack': 1, 'e2e': 0, 'dast': 1, 'perf': 0},
                            last_run=time.time() - 3600)
        self.assertEqual(set(out), {'infra:qa:e2e', 'infra:qa:perf'})
        self.assertTrue(all(sev == 'warning' for sev, _msg, _d in out.values()))

    def test_results_that_stopped_arriving_are_flagged(self):
        out = self.run_rule(suites={'e2e': 1}, last_run=time.time() - 40 * 3600)
        self.assertIn('infra:qa:stale', out)
        self.assertEqual(out['infra:qa:stale'][2]['age_h'], 40)

    def test_rule_is_part_of_the_sweep_and_owned(self):
        self.assertTrue(any(k.startswith(p) for p in ar.OWNED_PREFIXES for k in ('infra:qa:e2e',)))
        with mock.patch.object(ar, '_qa', return_value={'infra:qa:e2e': ('warning', 'x', {})}) as qa, \
             mock.patch.object(ar, '_infra', return_value={}), \
             mock.patch.object(ar, '_login_bruteforce', return_value={}), \
             mock.patch.object(ar, '_admin_logins', return_value={}), \
             mock.patch.object(ar, '_sms_failures', return_value={}), \
             mock.patch.object(ar, '_ai_health', return_value={}):
            self.assertIn('infra:qa:e2e', ar.evaluate())
        qa.assert_called_once()
