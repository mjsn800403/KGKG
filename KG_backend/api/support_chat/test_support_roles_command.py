"""``manage.py support_roles``: exit codes, each check, and that it never writes."""
import io
import json
import os
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from api.models import AdminAuthToken, AuditLog, PlatformAdmin

from . import rbac


class CommandCase(TestCase):
    def setUp(self):
        self.table = {}
        self.table_exists = True
        for attribute, effect in (('_table_roles', lambda a: set(self.table.get(a.username, ()))),
                                  ('table_available', lambda: self.table_exists)):
            p = mock.patch.object(rbac, attribute, side_effect=effect)
            p.start()
            self.addCleanup(p.stop)
        e = mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': 'off', 'KG_SUPPORT_OWNERS': ''})
        e.start()
        self.addCleanup(e.stop)
        self.ann = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True, phone='09121112222')
        self.bob = PlatformAdmin.objects.create(username='bob', password_hash='x', active=True)

    def env(self, **kw):
        p = mock.patch.dict(os.environ, kw)
        p.start()
        self.addCleanup(p.stop)

    def run_cmd(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        try:
            call_command('support_roles', *args, stdout=out, stderr=err)
        except SystemExit as exc:
            code = exc.code
        return code, out.getvalue(), err.getvalue()

    def codes(self, *args):
        code, out, _ = self.run_cmd('check', '--json', *args)
        return code, {f['code'] for f in json.loads(out)['findings']}, json.loads(out)


class ExitCodeTests(CommandCase):
    def test_plain_check_never_fails_even_when_not_ready(self):
        code, out, _ = self.run_cmd('check')
        self.assertEqual(code, 0)
        self.assertIn('NOT READY', out)
        self.assertIn('Nothing was changed', out)

    def test_for_enforce_exits_1_when_blocked_and_0_when_ready(self):
        self.assertEqual(self.run_cmd('check', '--for-enforce')[0], 1)
        self.env(KG_SUPPORT_OWNERS='ann')
        self.table = {'bob': ['sales_agent', 'support_agent']}
        code, out, _ = self.run_cmd('check', '--for-enforce')
        self.assertEqual(code, 0, out)
        self.assertIn('READY', out)

    def test_an_unexpected_error_exits_2_never_a_pass(self):
        with mock.patch('api.support_chat.rbac_check.run', side_effect=RuntimeError('boom')):
            code, _, err = self.run_cmd('check', '--for-enforce')
        self.assertEqual(code, 2)
        self.assertIn('boom', err)


class CheckTests(CommandCase):
    def test_no_active_owner_blocks(self):
        code, found, _ = self.codes('--for-enforce')
        self.assertIn('no_active_owner', found)
        self.assertEqual(code, 1)

    def test_a_misspelt_owner_name_is_a_distinct_blocking_finding(self):
        self.env(KG_SUPPORT_OWNERS='anne')
        _, found, data = self.codes()
        self.assertIn('owner_name_unknown', found)
        self.assertIn('anne', [f['message'] for f in data['findings'] if f['code'] == 'owner_name_unknown'][0])

    def test_owner_names_are_case_insensitive(self):
        self.env(KG_SUPPORT_OWNERS='ANN')
        _, found, _ = self.codes()
        self.assertIn('owner_present', found)
        self.assertNotIn('owner_name_unknown', found)

    def test_an_inactive_owner_warns_and_does_not_count(self):
        self.ann.active = False
        self.ann.save()
        self.env(KG_SUPPORT_OWNERS='ann')
        _, found, _ = self.codes()
        self.assertIn('owner_inactive', found)
        self.assertIn('no_active_owner', found)

    def test_a_table_owner_is_enough_without_the_environment(self):
        self.table = {'bob': ['support_owner']}
        _, found, _ = self.codes()
        self.assertIn('owner_present', found)
        self.assertNotIn('no_active_owner', found)

    def test_missing_role_table_blocks_for_enforce_until_migration_b(self):
        self.table_exists = False
        self.env(KG_SUPPORT_OWNERS='ann')
        code, found, _ = self.codes('--for-enforce')
        self.assertIn('role_table_missing', found)
        self.assertEqual(code, 1)

    def test_unrecognised_mode_value_blocks_and_says_it_is_enforced_not_ignored(self):
        self.env(KG_SUPPORT_RBAC='enforc', KG_SUPPORT_OWNERS='ann')
        code, found, data = self.codes('--for-enforce')
        self.assertIn('mode_unrecognised', found)
        self.assertEqual(code, 1)
        message = [f['message'] for f in data['findings'] if f['code'] == 'mode_unrecognised'][0]
        self.assertIn('ENFORCED', message)
        self.assertIn('fails closed', message)
        self.assertNotIn('mode', found - {'mode_unrecognised'})   # no cheerful "mode is off" line beside it

    def test_explicit_off_spellings_are_not_flagged(self):
        for raw in ('', 'off', '0', 'false', 'no', 'disabled', 'none'):
            self.env(KG_SUPPORT_RBAC=raw)
            _, found, _ = self.codes()
            self.assertNotIn('mode_unrecognised', found, raw)

    def test_coverage_warnings_do_not_block(self):
        self.env(KG_SUPPORT_OWNERS='ann')
        code, found, data = self.codes('--for-enforce')
        self.assertEqual(code, 0)
        self.assertTrue({'no_sales_agent', 'no_support_agent', 'admins_without_role'} <= found)
        warned = [f for f in data['findings'] if f['code'] == 'admins_without_role'][0]['message']
        self.assertIn('bob', warned)
        self.assertNotIn('ann,', warned)                       # ann is an owner, so has a role

    def test_would_deny_summary_lists_ids_and_permissions_only(self):
        AuditLog.objects.create(action='support_chat.rbac_would_deny', actor_type=AuditLog.ADMIN,
                                actor_id=self.bob.id, detail={'permission': 'support.spam', 'intent': 'sales'})
        AuditLog.objects.create(action='support_chat.rbac_would_deny', actor_type=AuditLog.ADMIN,
                                actor_id=self.bob.id, detail={'permission': 'support.spam', 'intent': 'sales'})
        old = AuditLog.objects.create(action='support_chat.rbac_would_deny', actor_type=AuditLog.ADMIN,
                                      actor_id=self.ann.id, detail={'permission': 'support.read'})
        AuditLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))
        _, out, _ = self.run_cmd('check')
        self.assertIn('2 request(s)', out)
        self.assertIn(f'admin id {self.bob.id}: support.spam x2', out)
        self.assertNotIn('support.read', out)                   # outside the 14-day window


class ReportTests(CommandCase):
    def test_report_lists_every_admin_without_secrets(self):
        self.env(KG_SUPPORT_OWNERS='ann')
        self.table = {'bob': ['support_agent']}
        AdminAuthToken.issue(self.bob)
        code, out, _ = self.run_cmd('report')
        self.assertEqual(code, 0)
        for needle in ('ann', 'bob', 'support_agent', f'{PlatformAdmin.objects.count()} administrator(s)'):
            self.assertIn(needle, out)
        self.assertNotIn('password', out.lower())
        self.assertNotIn('09121112222', out)                    # only a yes/no for the phone
        self.assertNotIn('pbkdf2', out)                         # no password hash shape either


class ReadOnlyTests(CommandCase):
    def test_neither_subcommand_writes_anything(self):
        self.env(KG_SUPPORT_OWNERS='ann')
        AuditLog.objects.create(action='support_chat.rbac_would_deny', actor_type=AuditLog.ADMIN,
                                actor_id=self.bob.id, detail={'permission': 'support.spam'})
        before = (AuditLog.objects.count(), PlatformAdmin.objects.count(), AdminAuthToken.objects.count())
        for args in (('report',), ('check',), ('check', '--for-enforce'), ('check', '--json')):
            with CaptureQueriesContext(connection) as ctx:
                self.run_cmd(*args)
            writes = [q['sql'][:60] for q in ctx.captured_queries
                      if q['sql'].lstrip().split(None, 1)[0].upper() in ('INSERT', 'UPDATE', 'DELETE')]
            self.assertEqual(writes, [], args)
        self.assertEqual(before, (AuditLog.objects.count(), PlatformAdmin.objects.count(),
                                  AdminAuthToken.objects.count()))

    def test_the_command_does_not_change_the_environment_or_enable_enforcement(self):
        self.env(KG_SUPPORT_RBAC='off')
        self.run_cmd('check', '--for-enforce')
        self.assertEqual(os.environ['KG_SUPPORT_RBAC'], 'off')
        self.assertEqual(rbac.mode(), 'off')
