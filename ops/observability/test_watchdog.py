"""Tests for the alerting watchdog (ops/observability/watchdog.py).

Run by CI and by ops/deploy/gate.sh. Standard library only, like the module
itself — it has to be runnable on a host where the application's virtualenv is
the thing that is broken.

    python3 -m unittest discover -s ops -p 'test_*.py'
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import watchdog  # noqa: E402


SHOW_OK = (
    'NRestarts=0\n'
    'ExecMainExitTimestampMonotonic=1000000000\n'   # 1000s since boot
    'ExecMainStatus=0\n'
)


class SweepFreshnessTests(unittest.TestCase):
    """systemd, not the application's tables, is the source of truth here: if
    the sweep cannot reach the database, its own tables are the wrong place to
    ask whether it ran."""

    def test_recent_successful_run_is_fresh(self):
        ok, detail = watchdog.check_alert_sweep_fresh(now=1100.0, show_output=SHOW_OK)
        self.assertTrue(ok)
        self.assertIn('exit 0', detail)

    def test_old_run_is_stale(self):
        ok, detail = watchdog.check_alert_sweep_fresh(
            now=1000.0 + watchdog.ALERTS_STALE_S + 60, show_output=SHOW_OK)
        self.assertFalse(ok)
        self.assertIn('limit', detail)

    def test_nonzero_exit_fails_even_when_recent(self):
        ok, detail = watchdog.check_alert_sweep_fresh(
            now=1100.0, show_output=SHOW_OK.replace('ExecMainStatus=0', 'ExecMainStatus=1'))
        self.assertFalse(ok)
        self.assertIn('exited 1', detail)

    def test_never_run_fails(self):
        ok, detail = watchdog.check_alert_sweep_fresh(
            now=1100.0,
            show_output=SHOW_OK.replace('ExecMainExitTimestampMonotonic=1000000000',
                                        'ExecMainExitTimestampMonotonic=0'))
        self.assertFalse(ok)
        self.assertIn('no recorded successful run', detail)

    def test_systemd_silence_fails_closed(self):
        ok, _ = watchdog.check_alert_sweep_fresh(now=1100.0, show_output='')
        self.assertFalse(ok)


class FailedUnitTests(unittest.TestCase):
    """A unit can fail silently for a long time: logrotate failed for 14 hours
    on 2026-10-27 and nothing said so."""

    def test_no_failed_units(self):
        ok, detail = watchdog.check_failed_units(show_output='')
        self.assertTrue(ok)
        self.assertEqual(detail, 'no failed units')

    def test_failed_units_named(self):
        ok, detail = watchdog.check_failed_units(
            show_output='logrotate.service loaded failed failed Rotate log files\n')
        self.assertFalse(ok)
        self.assertIn('logrotate.service', detail)

    def test_many_failures_are_truncated(self):
        out = ''.join(f'u{i}.service loaded failed failed x\n' for i in range(9))
        ok, detail = watchdog.check_failed_units(show_output=out)
        self.assertFalse(ok)
        self.assertEqual(detail.count(','), 4)      # five names at most

    def test_failed_units_do_not_page(self):
        """The alert engine owns paging; this check is for visibility."""
        self.assertNotIn('systemd_units', watchdog.PAGING_PATH)


class BackupSnapshotTests(unittest.TestCase):
    """An hourly job that quietly stopped looks exactly like one that is fine."""

    def _stamp(self, tmp, age_h):
        p = Path(tmp) / 'SNAPSHOT_AT'
        p.write_text('2026-10-27 15:00:12 UTC\n')
        import os
        when = watchdog.time.time() - age_h * 3600
        os.utime(p, (when, when))
        return p

    def test_recent_snapshot_is_fine(self):
        with tempfile.TemporaryDirectory() as d:
            ok, detail = watchdog.check_backup_snapshot(stamp=self._stamp(d, 1))
        self.assertTrue(ok)
        self.assertIn('1.0h old', detail)

    def test_stale_snapshot_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            ok, detail = watchdog.check_backup_snapshot(stamp=self._stamp(d, 48))
        self.assertFalse(ok)
        self.assertIn('limit', detail)

    def test_missing_stamp_fails_closed(self):
        ok, detail = watchdog.check_backup_snapshot(
            stamp=Path('/nonexistent/SNAPSHOT_AT'))
        self.assertFalse(ok)
        self.assertIn('no off-host snapshot', detail)

    def test_backup_does_not_page(self):
        """A late backup wants looking at, not waking someone for."""
        self.assertNotIn('backup_snapshot', watchdog.PAGING_PATH)


class CooldownTests(unittest.TestCase):
    def test_first_page_is_due(self):
        self.assertTrue(watchdog.due({}, 'k', 1000.0))

    def test_repeat_inside_cooldown_is_suppressed(self):
        state = {}
        watchdog.mark_sent(state, 'k', 1000.0)
        self.assertFalse(watchdog.due(state, 'k', 1000.0 + 300))

    def test_cooldown_expires(self):
        state = {}
        watchdog.mark_sent(state, 'k', 1000.0)
        self.assertTrue(watchdog.due(state, 'k', 1000.0 + watchdog.COOLDOWN_H * 3600 + 1))

    def test_corrupt_state_does_not_suppress(self):
        """A damaged state file must fail towards paging, not towards silence."""
        self.assertTrue(watchdog.due({'sent': {'k': 'not-a-number'}}, 'k', 1000.0))

    def test_state_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'state.json'
            watchdog.save_state({'sent': {'k': 1.5}}, p)
            self.assertEqual(watchdog.load_state(p), {'sent': {'k': 1.5}})

    def test_missing_state_file_reads_as_empty(self):
        self.assertEqual(watchdog.load_state(Path('/nonexistent/state.json')), {})


class EnvParsingTests(unittest.TestCase):
    def test_parses_quotes_exports_and_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / '.env'
            p.write_text(
                '# a comment\n'
                '\n'
                'SMS_USERNAME=user\n'
                'export SMS_API_KEY="se=cret"\n'
                "SMS_FROM='5000'\n"
                'KG_ALERT_PHONES=0912,0913\n'
                'MALFORMED\n'
            )
            env = watchdog.read_env(p)
        self.assertEqual(env['SMS_USERNAME'], 'user')
        self.assertEqual(env['SMS_API_KEY'], 'se=cret')   # value keeps its '='
        self.assertEqual(env['SMS_FROM'], '5000')
        self.assertNotIn('MALFORMED', env)
        self.assertEqual(watchdog.phones(env), ['0912', '0913'])

    def test_missing_file_is_not_fatal(self):
        self.assertEqual(watchdog.read_env(Path('/nonexistent/.env.prod')), {})


class MessageTests(unittest.TestCase):
    def test_scrub_removes_links_and_hostnames(self):
        self.assertEqual(watchdog.scrub('health http://127.0.0.1:8000/x -> 502'),
                         'health -> 502')
        self.assertEqual(watchdog.scrub('probe kgtechvault.com failed'), 'probe failed')

    def test_message_names_the_broken_paging_path(self):
        msg = watchdog.compose_message([
            ('alerts_timer_active', False, 'kgkg-alerts.timer is failed'),
            ('alert_sweep_fresh', True, 'fine'),
            ('prometheus', True, 'fine'),
        ])
        self.assertIn('kgkg-alerts.timer is failed', msg)
        self.assertIn('سایر بررسی‌ها سالم است', msg)

    def test_message_carries_service_state_when_engine_is_down(self):
        msg = watchdog.compose_message([
            ('alerts_timer_active', False, 'kgkg-alerts.timer is inactive'),
            ('alert_sweep_fresh', False, 'last alert sweep exited 1 (90s ago)'),
            ('prometheus', True, 'fine'),
            ('backend_health', False, 'health http://127.0.0.1:8000/api/health/ -> 502'),
            ('containers', True, '2 production container(s) healthy'),
        ])
        self.assertIn('۵۰۲', msg)                 # digits localised
        self.assertNotIn('://', msg)              # provider rejects links
        self.assertNotIn('.com', msg)

    def test_digits_are_localised(self):
        self.assertEqual(watchdog.fa('2026'), '۲۰۲۶')


class TextfileTests(unittest.TestCase):
    def test_exposition_is_written_and_parsable(self):
        checks = [('alerts_timer_active', True, 'ok'), ('disk', False, 'disk 97.0% used')]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'kgkg_watchdog.prom'
            watchdog.write_textfile(checks, watched=False, path=p)
            body = p.read_text()
        self.assertIn('kgkg_watchdog_check{check="alerts_timer_active"} 1', body)
        self.assertIn('kgkg_watchdog_check{check="disk"} 0', body)
        self.assertIn('kgkg_watchdog_alerting_healthy 0', body)
        for name in ('kgkg_watchdog_check', 'kgkg_watchdog_alerting_healthy',
                     'kgkg_watchdog_last_run_timestamp_seconds'):
            self.assertIn(f'# HELP {name} ', body)
            self.assertIn(f'# TYPE {name} gauge', body)

    def test_unwritable_directory_is_survivable(self):
        """Losing the metric must not stop the page."""
        watchdog.write_textfile([], watched=True, path=Path('/proc/nope/x.prom'))


class PagingTests(unittest.TestCase):
    def test_unconfigured_sms_is_reported_not_raised(self):
        ok, info = watchdog.send_sms({}, '0912', 'text')
        self.assertFalse(ok)
        self.assertEqual(info, 'sms_not_configured')

    def test_provider_failure_code_is_surfaced(self):
        env = {'SMS_USERNAME': 'u', 'SMS_API_KEY': 'k', 'SMS_FROM': '5000'}

        class _Resp:
            status = 200

            def read(self):
                return json.dumps({'RetStatus': 1, 'Value': '14'}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch('urllib.request.urlopen', return_value=_Resp()):
            ok, info = watchdog.send_sms(env, '0912', 'text')
        self.assertFalse(ok)
        self.assertEqual(info, 'provider_code:14')

    def test_success_returns_record_id(self):
        env = {'SMS_USERNAME': 'u', 'SMS_API_KEY': 'k', 'SMS_FROM': '5000'}

        class _Resp:
            status = 200

            def read(self):
                return json.dumps({'Value': '123456789'}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch('urllib.request.urlopen', return_value=_Resp()):
            ok, info = watchdog.send_sms(env, '0912', 'text')
        self.assertTrue(ok)
        self.assertEqual(info, '123456789')

    def test_transport_error_is_reported(self):
        env = {'SMS_USERNAME': 'u', 'SMS_API_KEY': 'k', 'SMS_FROM': '5000'}
        with mock.patch('urllib.request.urlopen', side_effect=OSError('boom')):
            ok, info = watchdog.send_sms(env, '0912', 'text')
        self.assertFalse(ok)
        self.assertIn('transport_error', info)


class SelftestTests(unittest.TestCase):
    def test_builtin_selftest_passes(self):
        self.assertEqual(watchdog.selftest(), 0)


if __name__ == '__main__':
    unittest.main()
