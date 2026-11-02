"""Tests for ops/observability/delivery.py — one per metric definition.

    python3 -m unittest discover -s ops/observability -t ops/observability -p 'test_*.py'
"""
import datetime
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import delivery  # noqa: E402

UTC = datetime.timezone.utc

OK = """[07:13:49] 1/5 GATE in /opt/KGKG_release/w-1083e91f0
[07:24:45] 4/5 PROMOTE 0618fa48a -> 1083e91f0
[07:25:22] DEPLOYED 1083e91f0 as deploy-20261102-071348 (previous 0618fa48a)
"""
ROLLED = """[08:34:30] 3/4 PROMOTE aaaaaaaaa -> bbbbbbbbb
[08:37:11] ROLLBACK to aaaaaaaaa (build .next-pre-aaaaaaaaa)
[08:37:12] DEPLOY ABORTED: production smoke failed -> rolled back to aaaaaaaaa
"""
CAUGHT = """[08:30:47] 1/5 GATE in /opt/KGKG_release/w-ccc
[08:33:16] DEPLOY FAILED at line 180: npx next start
"""
STAGED = """[09:00:00] 3/5 STAGING
[09:05:00] STAGING PASSED for 91d72c05f (production untouched)
"""
MANUAL = """[12:00:00] ROLLBACK to 1083e91f0
"""


class ParseLog(unittest.TestCase):
    def test_deployed_takes_the_deployed_line(self):
        r = delivery.parse_log('deploy-20261102-071348.log', OK)
        self.assertEqual((r['outcome'], r['sha']), ('deployed', '1083e91f0'))
        self.assertEqual(r['ts'], datetime.datetime(2026, 11, 2, 7, 25, 22, tzinfo=UTC))

    def test_auto_rollback_is_a_failure_with_restore_time_from_promote(self):
        r = delivery.parse_log('deploy-20261015-083428.log', ROLLED)
        self.assertEqual((r['outcome'], r['sha']), ('failed', 'bbbbbbbbb'))
        self.assertEqual(r['restore_s'], 162)

    def test_failure_before_promote_is_caught_not_failed(self):
        r = delivery.parse_log('deploy-20261015-083047.log', CAUGHT)
        self.assertEqual(r['outcome'], 'caught')

    def test_staging_only_and_unrelated_logs_are_ignored(self):
        self.assertIsNone(delivery.parse_log('deploy-20261020-090000.log', STAGED))
        self.assertIsNone(delivery.parse_log('gate-20261020-090000.log', OK))

    def test_midnight_crossing(self):
        r = delivery.parse_log('deploy-20261020-235900.log',
                               '[23:59:00] 4/5 PROMOTE a -> b\n'
                               '[00:01:00] DEPLOYED bbbbbbb as deploy-x\n')
        self.assertEqual(r['ts'].day, 21)


class Rollups(unittest.TestCase):
    def test_manual_rollback_fails_the_deploy_it_undid(self):
        d = delivery.parse_log('deploy-20261102-071348.log', OK)
        rb = delivery.parse_log('deploy-20261102-120000.log', MANUAL)
        out = delivery.attach_rollbacks([d, rb])
        self.assertEqual(d['outcome'], 'failed')
        self.assertAlmostEqual(d['restore_s'], (rb['ts'] - d['ts']).total_seconds())
        self.assertEqual(out[1]['outcome'], 'rollback')

    def test_summary_definitions(self):
        now = datetime.datetime(2026, 11, 2, tzinfo=UTC)
        t = lambda d: now - datetime.timedelta(days=d)  # noqa: E731
        recs = [
            {'ts': t(1), 'sha': 'a', 'outcome': 'deployed', 'restore_s': None, 'lead_h': 2.0},
            {'ts': t(2), 'sha': 'b', 'outcome': 'deployed', 'restore_s': None, 'lead_h': 6.0},
            {'ts': t(3), 'sha': 'c', 'outcome': 'failed', 'restore_s': 120, 'lead_h': 4.0},
            {'ts': t(4), 'sha': None, 'outcome': 'caught', 'restore_s': None},
            {'ts': t(60), 'sha': 'z', 'outcome': 'deployed', 'restore_s': None, 'lead_h': 99},
        ]
        s = delivery.summary(recs, now, 28)
        self.assertEqual(s['deploys'], 3)
        self.assertEqual(s['deploys_per_week'], 0.75)
        self.assertEqual(s['lead_time_h_median'], 4.0)
        self.assertEqual(s['change_failure_rate'], 0.333)
        self.assertEqual(s['time_to_restore_min_median'], 2.0)
        self.assertEqual(s['caught_before_production'], 1)

    def test_empty_window_is_null_not_zero(self):
        s = delivery.summary([], datetime.datetime(2026, 11, 2, tzinfo=UTC), 30)
        self.assertIsNone(s['change_failure_rate'])
        self.assertIsNone(s['lead_time_h_median'])
        self.assertEqual(s['deploys'], 0)


class EndToEnd(unittest.TestCase):
    def test_collect_and_write(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in (('deploy-20261102-071348.log', OK),
                               ('deploy-20261015-083047.log', CAUGHT),
                               ('deploy-20261020-090000.log', STAGED)):
                with open(os.path.join(d, name), 'w') as fh:
                    fh.write(text)
            recs = delivery.collect(d, d)  # not a git repo: lead time stays empty
            self.assertEqual([r['outcome'] for r in recs], ['caught', 'deployed'])
            db = os.path.join(d, 'biz.sqlite')
            delivery.write(recs, db)
            rows = sqlite3.connect(db).execute(
                'SELECT outcome, sha FROM deploys ORDER BY ts').fetchall()
            self.assertEqual(rows, [('caught', None), ('deployed', '1083e91f0')])


if __name__ == '__main__':
    unittest.main()
