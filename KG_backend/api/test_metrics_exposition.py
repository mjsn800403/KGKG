"""Prometheus exposition endpoint (api/metrics_exposition.py).

The endpoint is the only way infrastructure alerting can see inside the
application, so the tests cover both halves of that: it must refuse anyone
without the token, and the payload must actually parse as Prometheus
exposition with the series the alert rules depend on.
"""

import os
import re
from unittest import mock

from django.test import TestCase, Client
from django.utils import timezone

from .models import SystemAlert, TrafficStat


TOKEN = 'metrics-token-for-tests'


def _series(body):
    """Parse exposition text into {(name, frozenset(labels)): float}."""
    out = {}
    for line in body.splitlines():
        if not line or line.startswith('#'):
            continue
        head, _, value = line.rpartition(' ')
        name, _, labels = head.partition('{')
        pairs = frozenset(
            re.findall(r'(\w+)="([^"]*)"', labels.rstrip('}')) if labels else []
        )
        out[(name, pairs)] = float(value)
    return out


def _names(body):
    return {k[0] for k in _series(body)}


@mock.patch.dict(os.environ, {'KG_METRICS_TOKEN': TOKEN})
class MetricsEndpointTests(TestCase):
    def setUp(self):
        self.c = Client()

    # ---- access control ---------------------------------------------------

    def test_without_token_is_401(self):
        self.assertEqual(self.c.get('/api/metrics/').status_code, 401)

    def test_wrong_token_is_401(self):
        r = self.c.get('/api/metrics/', HTTP_AUTHORIZATION='Bearer nope')
        self.assertEqual(r.status_code, 401)

    def test_admin_token_does_not_open_metrics(self):
        """A separate credential on purpose: the metrics token is handed to
        Prometheus, which must not thereby gain the admin surface."""
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'admin-tok'}):
            r = self.c.get('/api/metrics/', HTTP_AUTHORIZATION='Bearer admin-tok')
        self.assertEqual(r.status_code, 401)

    def test_with_token_is_200_and_prometheus_content_type(self):
        r = self.c.get('/api/metrics/', HTTP_AUTHORIZATION='Bearer ' + TOKEN)
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/plain', r['Content-Type'])
        self.assertIn('version=0.0.4', r['Content-Type'])

    def test_x_metrics_token_header_also_works(self):
        r = self.c.get('/api/metrics/', HTTP_X_METRICS_TOKEN=TOKEN)
        self.assertEqual(r.status_code, 200)

    # ---- payload ----------------------------------------------------------

    def test_core_series_present(self):
        r = self.c.get('/api/metrics/', HTTP_AUTHORIZATION='Bearer ' + TOKEN)
        names = _names(r.content.decode())
        for expected in (
            'kgkg_up',
            'kgkg_build_info',
            'kgkg_db_up',
            'kgkg_disk_used_percent',
            'kgkg_memory_used_percent',
            'kgkg_open_alerts',
            'kgkg_scrape_duration_seconds',
        ):
            self.assertIn(expected, names, f'{expected} missing from exposition')

    def test_every_series_is_help_and_type_annotated(self):
        body = self.c.get(
            '/api/metrics/', HTTP_AUTHORIZATION='Bearer ' + TOKEN
        ).content.decode()
        documented = set(re.findall(r'^# HELP (\w+)', body, re.M))
        typed = set(re.findall(r'^# TYPE (\w+)', body, re.M))
        for name in _names(body):
            self.assertIn(name, documented, f'{name} has no HELP line')
            self.assertIn(name, typed, f'{name} has no TYPE line')

    def test_traffic_rows_become_per_endpoint_series(self):
        bucket = timezone.now().replace(minute=0, second=0, microsecond=0)
        TrafficStat.objects.create(
            bucket=bucket, endpoint='assist', method='POST',
            requests=120, errors_4xx=3, errors_5xx=7,
            total_ms=240_000, max_ms=9000,
        )
        s = _series(self.c.get(
            '/api/metrics/', HTTP_AUTHORIZATION='Bearer ' + TOKEN
        ).content.decode())
        key = frozenset({('endpoint', 'assist'), ('method', 'POST')})
        self.assertEqual(s[('kgkg_http_requests_current_hour', key)], 120)
        self.assertEqual(s[('kgkg_http_errors_5xx_current_hour', key)], 7)
        self.assertEqual(s[('kgkg_http_errors_4xx_current_hour', key)], 3)
        # 240000ms over 120 requests = 2000ms mean.
        self.assertEqual(s[('kgkg_http_latency_mean_ms_current_hour', key)], 2000)
        self.assertEqual(s[('kgkg_http_latency_max_ms_current_hour', key)], 9000)

    def test_previous_hour_rows_are_excluded(self):
        """The window is the current hour only; a stale bucket must not keep
        an alert alive after the condition has gone."""
        old = timezone.now().replace(minute=0, second=0, microsecond=0) \
            - timezone.timedelta(hours=3)
        TrafficStat.objects.create(
            bucket=old, endpoint='assist', method='GET', requests=999, errors_5xx=999,
        )
        s = _series(self.c.get(
            '/api/metrics/', HTTP_AUTHORIZATION='Bearer ' + TOKEN
        ).content.decode())
        key = frozenset({('endpoint', 'assist'), ('method', 'GET')})
        self.assertNotIn(('kgkg_http_requests_current_hour', key), s)

    def test_open_alerts_counted_by_severity(self):
        SystemAlert.objects.create(key='a', severity='critical', message='x')
        SystemAlert.objects.create(key='b', severity='warning', message='y')
        SystemAlert.objects.create(key='c', severity='warning', message='z')
        SystemAlert.objects.create(
            key='d', severity='critical', message='resolved', is_open=False,
        )
        s = _series(self.c.get(
            '/api/metrics/', HTTP_AUTHORIZATION='Bearer ' + TOKEN
        ).content.decode())
        self.assertEqual(s[('kgkg_open_alerts', frozenset({('severity', 'critical')}))], 1)
        self.assertEqual(s[('kgkg_open_alerts', frozenset({('severity', 'warning')}))], 2)
        # Every severity is always present, so a rule never breaks on a
        # missing series when nothing is wrong.
        self.assertEqual(s[('kgkg_open_alerts', frozenset({('severity', 'info')}))], 0)

    def test_label_values_are_escaped(self):
        """A route group is bounded, but the release label comes from the
        environment; an unescaped quote would corrupt the whole payload."""
        with mock.patch.dict(os.environ, {'KG_RELEASE': 'we"ird\\sha'}):
            body = self.c.get(
                '/api/metrics/', HTTP_AUTHORIZATION='Bearer ' + TOKEN
            ).content.decode()
        self.assertIn(r'release="we\"ird\\sha"', body)
        self.assertIn('kgkg_build_info', _names(body))

    def test_endpoint_is_not_counted_in_its_own_traffic_stats(self):
        """Scraping every 30s would otherwise dominate the request counters
        and dilute the error ratio the alert rules read."""
        from . import monitoring
        self.assertEqual(monitoring.endpoint_group('/api/metrics/'), 'metrics')

    def test_db_failure_still_serves_a_payload(self):
        """If the database is down the scrape must still report kgkg_db_up 0
        rather than 500 — a scrape that fails tells Prometheus nothing about
        why."""
        with mock.patch(
            'api.metrics_exposition._traffic_rows', side_effect=RuntimeError('db gone')
        ):
            r = self.c.get('/api/metrics/', HTTP_AUTHORIZATION='Bearer ' + TOKEN)
        self.assertEqual(r.status_code, 200)
        s = _series(r.content.decode())
        self.assertEqual(s[('kgkg_db_up', frozenset())], 0)
        self.assertEqual(s[('kgkg_up', frozenset())], 1)

    def test_disabled_when_no_token_configured(self):
        with mock.patch.dict(os.environ, {'KG_METRICS_TOKEN': ''}):
            r = self.c.get('/api/metrics/', HTTP_AUTHORIZATION='Bearer ' + TOKEN)
        self.assertEqual(r.status_code, 503)
