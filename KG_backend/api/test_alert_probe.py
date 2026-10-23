"""Probe alerts: a public-path failure with a healthy loopback backend is not 'backend down'."""
from unittest import mock

from django.test import SimpleTestCase

from api import alert_rules as ar

HEALTH = 'https://kgtechvault.com/kg-api/api/health/'


def fake_prom(down_now, down_long=()):
    def prom(q):
        if 'max_over_time(probe_success' in q:
            ts = down_long if f'[{ar.NETWORK_DOWN_MIN}m]' in q else down_now
            return [{'metric': {'target': t}, 'value': [0, '0']} for t in ts]
        return []
    return prom


class ProbeAlertTests(SimpleTestCase):
    def run_infra(self, prom, local_ok):
        with mock.patch.object(ar, '_prom', side_effect=prom), mock.patch.object(ar, '_local_ok', return_value=local_ok):
            return ar._infra()

    def test_dns_blip_with_healthy_backend_is_silent(self):
        self.assertEqual(self.run_infra(fake_prom([HEALTH]), True), {})

    def test_long_path_failure_is_a_warning_only(self):
        out = self.run_infra(fake_prom([HEALTH], [HEALTH]), True)
        self.assertEqual(list(out), [f'infra:path:{HEALTH}'])
        self.assertEqual(out[f'infra:path:{HEALTH}'][0], 'warning')

    def test_backend_really_down_is_critical(self):
        out = self.run_infra(fake_prom([HEALTH]), False)
        self.assertEqual(out[f'infra:down:{HEALTH}'][0], 'critical')

    def test_third_party_down_still_alerts(self):
        out = self.run_infra(fake_prom(['https://api.metisai.ir/']), True)
        self.assertIn('infra:down:https://api.metisai.ir/', out)


class NoSmsInTestsTests(SimpleTestCase):
    def test_deliver_never_sends_during_tests(self):
        with mock.patch.dict("os.environ", {"KG_ALERT_PHONES": "09000000000"}), \
                mock.patch("api.portal._post_sms") as post:
            ar.deliver("sec:scrape:1", "warning", "test")
        post.assert_not_called()
