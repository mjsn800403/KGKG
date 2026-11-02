"""Infrastructure rules that exist because their absence was proved, not guessed.

Each class below names the silence it closes:

* a dead exporter takes its own rules down with it, and `<metric> == 0` finds
  nothing to match, so the engine reads a blackbox outage as four healthy
  probes. `up{job="kgkg_app"}` was 0 for roughly 50 minutes in the week to
  2026-10-29 and nothing was sent.
* nothing watched the watchdog, which is the only thing watching this engine.
* kgkg_db_up, kgkg_rag_index_present and the 5xx counter had no rule at all.

The fake below answers by query substring, and returns [] for anything it does
not recognise — which is also the assertion that these rules stay silent when a
query legitimately matches nothing.
"""
from unittest import mock

from django.test import SimpleTestCase

from api import alert_rules as ar


def fake_prom(**answers):
    """Dispatch on query substring; [] for everything else.

    Keys are substrings of the PromQL, with '.' standing in for characters that
    are awkward in a keyword argument: pass them as a dict instead when needed.
    """
    def prom(q):
        for needle, result in answers.items():
            if needle in q:
                return result
        return []
    return prom


def series(value, **labels):
    return [{'metric': labels, 'value': [0, str(value)]}]


def run_infra(prom, local_ok=True):
    with mock.patch.object(ar, '_prom', side_effect=prom), \
            mock.patch.object(ar, '_local_ok', return_value=local_ok):
        return ar._infra()


class EverythingHealthyTests(SimpleTestCase):
    """The regression guard for every rule added here: a query that matches
    nothing must stay silent, or the engine pages continuously."""

    def test_no_alerts_when_every_query_is_empty(self):
        self.assertEqual(run_infra(fake_prom()), {})


class ScrapeTargetTests(SimpleTestCase):
    """Rules are only as alive as the exporter underneath them."""

    def test_a_down_target_is_named_in_persian(self):
        out = run_infra(fake_prom(**{'max_over_time(up[': series(0, job='cadvisor')}))
        self.assertIn('infra:scrape:cadvisor', out)
        severity, message, ctx = out['infra:scrape:cadvisor']
        self.assertEqual(severity, 'warning')
        self.assertIn('cAdvisor', message)
        self.assertEqual(ctx, {'job': 'cadvisor'})

    def test_the_app_exporter_is_covered_too(self):
        """The 50 minutes on 2026-10-29 that nobody heard about."""
        out = run_infra(fake_prom(**{'max_over_time(up[': series(0, job='kgkg_app')}))
        self.assertIn('infra:scrape:kgkg_app', out)

    def test_an_unknown_job_still_alerts_under_its_own_name(self):
        out = run_infra(fake_prom(**{'max_over_time(up[': series(0, job='something_new')}))
        self.assertIn('infra:scrape:something_new', out)
        self.assertIn('something_new', out['infra:scrape:something_new'][1])

    def test_a_single_missed_scrape_does_not_page(self):
        """max_over_time over the window is what gives this its `for:`. The
        rule asks Prometheus for sustained failure, so a promote swapping
        containers cannot page on one gap."""
        self.assertIn(f'max_over_time(up[{ar.SCRAPE_DOWN_MIN}m]) == 0',
                      _queries_made(fake_prom()))


class StarvationTests(SimpleTestCase):
    """absent() is the whole point: it turns a missing metric into a fact."""

    def test_a_dead_blackbox_is_critical_not_silent(self):
        out = run_infra(fake_prom(**{'absent(probe_success)': series(1)}))
        self.assertIn('infra:nodata:probe_success', out)
        severity, message, ctx = out['infra:nodata:probe_success']
        self.assertEqual(severity, 'critical')
        self.assertEqual(ctx, {'metric': 'probe_success'})
        self.assertIn('دسترس‌پذیری', message)

    def test_a_dead_cadvisor_is_a_warning(self):
        out = run_infra(fake_prom(**{'absent(container_start_time_seconds)': series(1)}))
        self.assertEqual(out['infra:nodata:container_start_time_seconds'][0], 'warning')

    def test_probe_starvation_fires_while_the_probe_rules_see_nothing(self):
        """The exact shape of the bug: probe_success is gone, so
        max_over_time(probe_success) == 0 matches nothing and the probe rules
        are silent. The guard must speak instead of nobody speaking."""
        out = run_infra(fake_prom(**{'absent(probe_success)': series(1)}))
        self.assertEqual([k for k in out if k.startswith('infra:down:')], [])
        self.assertIn('infra:nodata:probe_success', out)


class WatchdogFreshnessTests(SimpleTestCase):
    """The watchdog watches this engine; this closes the other half."""

    STALE = ar.WATCHDOG_STALE_S + 60

    def test_a_fresh_watchdog_is_silent(self):
        out = run_infra(fake_prom(**{
            'time() - kgkg_watchdog_last_run_timestamp_seconds': series(44)}))
        self.assertNotIn('infra:watchdog', out)

    def test_a_stalled_watchdog_alerts_with_its_age(self):
        out = run_infra(fake_prom(**{
            'time() - kgkg_watchdog_last_run_timestamp_seconds': series(self.STALE)}))
        self.assertIn('infra:watchdog', out)
        self.assertEqual(out['infra:watchdog'][2]['age_s'], int(self.STALE))
        self.assertIn(str(int(self.STALE // 60)), out['infra:watchdog'][1])

    def test_a_watchdog_that_reports_nothing_at_all_alerts(self):
        out = run_infra(fake_prom(**{
            'absent(kgkg_watchdog_last_run_timestamp_seconds)': series(1)}))
        self.assertIn('infra:watchdog', out)

    def test_exactly_at_the_threshold_is_not_stale(self):
        out = run_infra(fake_prom(**{
            'time() - kgkg_watchdog_last_run_timestamp_seconds':
                series(ar.WATCHDOG_STALE_S)}))
        self.assertNotIn('infra:watchdog', out)


class AppSignalTests(SimpleTestCase):
    """Three binary health signals that had no rule in either file."""

    def test_database_unreachable_is_critical(self):
        out = run_infra(fake_prom(**{'min(kgkg_db_up)': series(0)}))
        self.assertEqual(out['infra:app_db'][0], 'critical')

    def test_database_reachable_is_silent(self):
        self.assertNotIn('infra:app_db',
                         run_infra(fake_prom(**{'min(kgkg_db_up)': series(1)})))

    def test_missing_rag_index_is_a_warning(self):
        out = run_infra(fake_prom(**{'min(kgkg_rag_index_present)': series(0)}))
        self.assertEqual(out['infra:rag_index'][0], 'warning')

    def test_5xx_above_the_threshold_is_critical(self):
        out = run_infra(fake_prom(**{
            'sum(kgkg_http_errors_5xx_current_hour)': series(ar.APP_5XX)}))
        self.assertEqual(out['infra:app_5xx'][0], 'critical')
        self.assertEqual(out['infra:app_5xx'][2]['errors_5xx'], int(ar.APP_5XX))

    def test_5xx_below_the_threshold_is_silent(self):
        out = run_infra(fake_prom(**{
            'sum(kgkg_http_errors_5xx_current_hour)': series(ar.APP_5XX - 1)}))
        self.assertNotIn('infra:app_5xx', out)

    def test_the_counter_is_summed_not_read_per_endpoint(self):
        """It carries endpoint and method labels, so an unaggregated read would
        compare one endpoint's count against a whole-service threshold."""
        self.assertIn('sum(kgkg_http_errors_5xx_current_hour)',
                      _queries_made(fake_prom()))


class ResolutionTests(SimpleTestCase):
    """monitoring.evaluate_alerts auto-resolves keys under OWNED_PREFIXES. A
    key outside them would stay open for ever once raised."""

    def test_every_new_key_is_owned(self):
        out = {}
        for answers in ({'max_over_time(up[': series(0, job='node')},
                        {'absent(probe_success)': series(1)},
                        {'absent(container_start_time_seconds)': series(1)},
                        {'absent(kgkg_watchdog_last_run_timestamp_seconds)': series(1)},
                        {'min(kgkg_db_up)': series(0)},
                        {'min(kgkg_rag_index_present)': series(0)},
                        {'sum(kgkg_http_errors_5xx_current_hour)': series(99)}):
            out.update(run_infra(fake_prom(**answers)))
        self.assertTrue(out)
        for key in out:
            self.assertTrue(key.startswith(ar.OWNED_PREFIXES), key)


def _queries_made(prom):
    """Every PromQL string _infra() sends, for asserting on rule shape."""
    seen = []

    def record(q):
        seen.append(q)
        return prom(q)

    with mock.patch.object(ar, '_prom', side_effect=record), \
            mock.patch.object(ar, '_local_ok', return_value=True):
        ar._infra()
    return seen


class RuleShapeTests(SimpleTestCase):
    """A rule shaped `<metric> == 0` with nothing standing behind it starves:
    when the exporter dies the metric vanishes, the expression matches nothing,
    and the engine reads that as healthy. This is the regression guard for the
    whole class of bug, not for one instance of it — a new rule written that
    way fails here instead of failing silently in production.

    A `== 0` comparison is acceptable only if it is evaluated over a window
    (`max_over_time(...[Nm]) == 0`, which still matches while the series is
    merely stale) or if the same sweep separately asks `absent(<metric>)`.
    """

    def test_no_equality_rule_stands_without_a_window_or_an_absent_guard(self):
        queries = _queries_made(fake_prom())
        self.assertTrue(queries, 'the sweep sent no queries at all')
        guarded = {q for q in queries if q.startswith('absent(')}

        for q in queries:
            if '== 0' not in q:
                continue
            if '_over_time(' in q:
                continue
            metric = q.split('==')[0].strip()
            metric = metric.split('{')[0].split('(')[-1].strip()
            self.assertIn(
                f'absent({metric})', guarded,
                f'{q!r} starves when {metric} disappears: evaluate it over a '
                f'window, or ask absent({metric}) in the same sweep',
            )

    def test_the_app_scrape_is_watched_at_all(self):
        # The 50-minute outage that this module exists because of.
        self.assertTrue(
            any('up[' in q for q in _queries_made(fake_prom())),
            'no rule asks about `up`, so a dead exporter pages nobody',
        )
