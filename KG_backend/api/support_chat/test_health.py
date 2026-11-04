"""Unanswered-conversation health: counts, wait time, internal notes, thresholds, exit codes."""
import io
import json
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import health
from .helpers import SupportCase
from .models import SupportMessage, SupportThread


class HealthTests(SupportCase):
    def age(self, tid, seconds):
        """Make every message of a thread `seconds` old (created_at is auto_now_add)."""
        when = timezone.now() - timedelta(seconds=seconds)
        SupportMessage.objects.filter(thread_id=tid).update(created_at=when)

    def test_empty_queue_is_ok(self):
        r = health.report()
        self.assertEqual((r['level'], r['waiting'], r['oldest_wait_s']), ('ok', 0, 0))

    def test_a_fresh_visitor_message_is_waiting_but_ok(self):
        self.create()
        r = health.report()
        self.assertEqual((r['waiting'], r['level']), (1, 'ok'))
        self.assertEqual(r['waiting_by_intent'], {'sales': 1})

    def test_wait_levels_follow_the_thresholds(self):
        tid, _, _ = self.create()
        self.age(tid, 400)
        self.assertEqual(health.report()['level'], 'warn')
        self.age(tid, 1000)
        r = health.report()
        self.assertEqual((r['level'], r['over_crit']), ('crit', 1))

    def test_a_public_staff_reply_clears_the_wait_but_an_internal_note_does_not(self):
        tid, _, _ = self.create()
        self.age(tid, 1000)
        SupportMessage.objects.create(thread_id=tid, author_kind='admin', author_admin=self.admin,
                                      body='note', internal=True)
        self.assertEqual(health.report()['waiting'], 1)
        SupportMessage.objects.create(thread_id=tid, author_kind='admin', author_admin=self.admin,
                                      body='hello', internal=False)
        self.assertEqual(health.report()['waiting'], 0)

    def test_a_new_visitor_message_after_the_reply_restarts_the_wait_from_that_message(self):
        tid, token, _ = self.create()
        self.age(tid, 2000)
        SupportMessage.objects.create(thread_id=tid, author_kind='admin', author_admin=self.admin, body='hi')
        SupportMessage.objects.filter(thread_id=tid, author_kind='admin').update(
            created_at=timezone.now() - timedelta(seconds=1000))
        r = self.send(f'/api/support-chat/threads/{tid}/messages/',
                      {'message': 'again', 'client_id': 'c-2'}, token)
        self.assertEqual(r.status_code, 201, r.content)
        rep = health.report()
        self.assertEqual(rep['waiting'], 1)
        self.assertLess(rep['oldest_wait_s'], 60)          # measured from "again", not from the first message

    def test_closed_and_spam_threads_are_not_counted(self):
        tid, _, _ = self.create()
        for status in ('closed', 'spam'):
            SupportThread.objects.filter(pk=tid).update(status=status)
            self.assertEqual(health.report()['waiting'], 0)

    def test_bad_threshold_settings_fall_back_to_defaults(self):
        with mock.patch.dict('os.environ', {'KG_SUPPORT_WAIT_WARN_S': 'abc', 'KG_SUPPORT_WAIT_CRIT_S': '-5'}):
            self.assertEqual(health.thresholds(), (300, 900))


class CommandTests(SupportCase):
    def run_cmd(self, *args):
        out = io.StringIO()
        try:
            call_command('support_health', *args, stdout=out, stderr=io.StringIO())
            code = 0
        except SystemExit as exc:
            code = exc.code
        return code, out.getvalue()

    def test_reports_json_and_never_changes_anything(self):
        self.create()
        before = SupportMessage.objects.count()
        code, text = self.run_cmd('--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)['waiting'], 1)
        self.assertEqual(SupportMessage.objects.count(), before)

    def test_fail_on_sets_the_exit_code_only_when_the_level_is_reached(self):
        tid, _, _ = self.create()
        self.assertEqual(self.run_cmd('--fail-on', 'warn')[0], 0)
        SupportMessage.objects.filter(thread_id=tid).update(
            created_at=timezone.now() - timedelta(seconds=1000))
        self.assertEqual(self.run_cmd('--fail-on', 'warn')[0], 1)
        self.assertEqual(self.run_cmd('--fail-on', 'crit')[0], 1)
        self.assertEqual(self.run_cmd()[0], 0)

    def test_a_failing_report_exits_2_not_0(self):
        with mock.patch.object(health, 'report', side_effect=RuntimeError('db down')):
            self.assertEqual(self.run_cmd('--fail-on', 'warn')[0], 2)


class ScaleTests(SupportCase):
    def bulk(self, n):
        now = timezone.now()
        threads = SupportThread.objects.bulk_create(
            [SupportThread(token_hash=f'{i:064d}', intent='sales' if i % 2 else 'technical') for i in range(n)])
        SupportMessage.objects.bulk_create(
            [SupportMessage(thread=t, author_kind='visitor', body='x') for t in threads])
        SupportMessage.objects.all().update(created_at=now - timedelta(seconds=1000))
        return threads

    def test_the_report_is_one_query_however_many_visitors_wait(self):
        self.bulk(60)
        with CaptureQueriesContext(connection) as q:
            r = health.report()
        self.assertEqual(len(q), 1)
        self.assertEqual((r['waiting'], r['over_crit'], r['level']), (60, 60, 'crit'))

    def test_more_than_the_old_500_cap_is_counted_exactly(self):
        self.bulk(650)
        r = health.report()
        self.assertEqual((r['waiting'], r['truncated']), (650, False))
        self.assertEqual(sum(r['waiting_by_intent'].values()), 650)

    def test_benchmark_prints_timings_for_the_ci_log(self):
        import time
        self.bulk(2000)
        health.report()
        runs = []
        for _ in range(5):
            t0 = time.perf_counter()
            health.report()
            runs.append((time.perf_counter() - t0) * 1000)
        print(f'BENCH support_health vendor={connection.vendor} waiting=2000 queries=1 '
              f'median_ms={sorted(runs)[2]:.0f} max_ms={max(runs):.0f}', flush=True)
        self.assertLess(sorted(runs)[2], 2000)
