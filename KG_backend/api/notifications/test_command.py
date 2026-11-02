"""process_outbox command and the opportunistic kick."""
import io
import os
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from . import kick


class CommandTests(TestCase):
    def test_command_prints_counts_and_exits_zero(self):
        out = io.StringIO()
        call_command('process_outbox', stdout=out)
        text = out.getvalue()
        for key in ('sent', 'retried', 'dead', 'deferred', 'skipped'):
            self.assertIn(f'{key}=0', text)

    def test_limit_option_is_passed_through(self):
        with mock.patch('api.notifications.worker.process_due',
                        return_value=dict(sent=0, retried=0, dead=0, deferred=0, skipped=0)) as m:
            call_command('process_outbox', '--limit', '7', stdout=io.StringIO())
        m.assert_called_once_with(limit=7)


class KickTests(SimpleTestCase):
    def test_kick_is_noop_in_off_mode(self):
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch('api.notifications.kick._spawn') as spawn:
            os.environ.pop('KG_NOTIFY_SMS', None)
            os.environ.pop('KG_NOTIFY_EMAIL', None)
            self.assertFalse(kick.kick(_testing=False))
        spawn.assert_not_called()

    def test_kick_is_noop_under_tests(self):
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'live'}), \
                mock.patch('api.notifications.kick._spawn') as spawn:
            self.assertFalse(kick.kick())
        spawn.assert_not_called()

    def test_kick_does_not_start_second_thread_while_one_runs(self):
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'live'}), \
                mock.patch('api.notifications.kick._spawn') as spawn:
            self.assertTrue(kick.kick(_testing=False))
            self.assertFalse(kick.kick(_testing=False))
            self.assertEqual(spawn.call_count, 1)
            kick._release()
            self.assertTrue(kick.kick(_testing=False))
            kick._release()
