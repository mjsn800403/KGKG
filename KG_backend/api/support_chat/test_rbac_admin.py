"""``support_roles grant|revoke``: rules, guards, audit and dry-run default.

The role table (migration B) does not exist yet, so the logic runs against a store
interface; these tests use an in-memory fake. The real table-backed store is a thin
adapter and is exercised once the migration exists.
"""
import io
import os
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from api.models import AuditLog, PlatformAdmin

from . import rbac, rbac_admin


class FakeStore:
    def __init__(self, available=True):
        self.table = {}                  # admin id -> set(role)
        self.ok = available
        self.granted_by = []

    def available(self):
        return self.ok

    def roles(self, admin):
        return set(self.table.get(admin.id, ()))

    def add(self, admin, role, granted_by):
        have = self.table.setdefault(admin.id, set())
        if role in have:
            return False
        have.add(role)
        self.granted_by.append(granted_by)
        return True

    def remove(self, admin, role):
        have = self.table.get(admin.id, set())
        if role not in have:
            return False
        have.discard(role)
        return True

    def owner_ids(self):
        return {i for i, roles in self.table.items() if rbac.SUPPORT_OWNER in roles}


class Base(TestCase):
    def setUp(self):
        self.store = FakeStore()
        e = mock.patch.dict(os.environ, {'KG_SUPPORT_OWNERS': '', 'KG_SUPPORT_RBAC': 'off'})
        e.start()
        self.addCleanup(e.stop)
        self.ann = PlatformAdmin.objects.create(username='ann', password_hash='x', active=True)
        self.bob = PlatformAdmin.objects.create(username='bob', password_hash='x', active=True)
        self.gone = PlatformAdmin.objects.create(username='gone', password_hash='x', active=False)

    def audits(self):
        return list(AuditLog.objects.filter(action__in=('support_chat.role_granted',
                                                        'support_chat.role_revoked')).order_by('id'))


class GrantTests(Base):
    def test_dry_run_is_the_default_and_changes_nothing(self):
        r = rbac_admin.grant(self.store, 'bob', 'support_agent', apply=False)
        self.assertEqual((r.ok, r.changed, r.code), (True, False, 'would_grant'))
        self.assertEqual(self.store.table, {})
        self.assertEqual(self.audits(), [])

    def test_apply_grants_and_audits_ids_only(self):
        r = rbac_admin.grant(self.store, 'BOB', 'sales_agent', apply=True)     # case-insensitive username
        self.assertEqual((r.ok, r.changed, r.code), (True, True, 'granted'))
        self.assertEqual(self.store.table, {self.bob.id: {'sales_agent'}})
        (row,) = self.audits()
        self.assertEqual((row.action, row.target_id, row.detail), ('support_chat.role_granted',
                                                                    str(self.bob.id), {'role': 'sales_agent'}))
        self.assertNotIn('bob', f'{row.detail} {row.actor_label}'.replace('support_roles command', ''))

    def test_granting_twice_is_a_no_op_with_no_second_audit_row(self):
        rbac_admin.grant(self.store, 'bob', 'support_agent', apply=True)
        r = rbac_admin.grant(self.store, 'bob', 'support_agent', apply=True)
        self.assertEqual((r.ok, r.changed, r.code), (True, False, 'already_held'))
        self.assertEqual(len(self.audits()), 1)

    def test_validation_rejects_bad_input_without_touching_anything(self):
        cases = (('bob', 'superuser', 'unknown_role'), ('bob', '', 'unknown_role'),
                 ('nobody', 'support_agent', 'unknown_admin'), ('gone', 'support_agent', 'inactive_admin'))
        for username, role, code in cases:
            r = rbac_admin.grant(self.store, username, role, apply=True)
            self.assertEqual((r.ok, r.code), (False, code), (username, role))
        self.assertEqual(self.store.table, {})
        self.assertEqual(self.audits(), [])

    def test_refuses_cleanly_when_the_role_table_does_not_exist(self):
        r = rbac_admin.grant(FakeStore(available=False), 'bob', 'support_agent', apply=True)
        self.assertEqual((r.ok, r.code), (False, 'table_missing'))
        self.assertIn('migration B', r.message)
        self.assertEqual(self.audits(), [])

    def test_the_granter_is_recorded_as_the_operator_not_a_person(self):
        rbac_admin.grant(self.store, 'bob', 'support_lead', apply=True)
        self.assertEqual(self.store.granted_by, [None])

    def test_a_granted_role_is_what_the_authorisation_layer_then_sees(self):
        """End to end with the real rbac module: grant, then enforce reads it back."""
        with mock.patch.object(rbac, '_table_roles', side_effect=lambda a: self.store.roles(a)), \
                mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': 'enforce'}):
            self.assertFalse(rbac.strict_allows(self.bob, rbac.REPLY))
            rbac_admin.grant(self.store, 'bob', 'support_agent', apply=True)
            self.assertTrue(rbac.strict_allows(self.bob, rbac.REPLY))
            rbac_admin.revoke(self.store, 'bob', 'support_agent', apply=True)
            self.assertFalse(rbac.strict_allows(self.bob, rbac.REPLY))


class RevokeTests(Base):
    def setUp(self):
        super().setUp()
        self.store.table = {self.ann.id: {'support_owner'}, self.bob.id: {'support_agent', 'support_owner'}}

    def test_dry_run_default_and_apply(self):
        r = rbac_admin.revoke(self.store, 'bob', 'support_agent', apply=False)
        self.assertEqual((r.ok, r.changed, r.code), (True, False, 'would_revoke'))
        self.assertIn('support_agent', self.store.table[self.bob.id])
        r = rbac_admin.revoke(self.store, 'bob', 'support_agent', apply=True)
        self.assertEqual((r.ok, r.changed, r.code), (True, True, 'revoked'))
        self.assertNotIn('support_agent', self.store.table[self.bob.id])
        (row,) = self.audits()
        self.assertEqual((row.action, row.detail), ('support_chat.role_revoked', {'role': 'support_agent'}))

    def test_revoking_a_role_not_held_is_a_no_op(self):
        r = rbac_admin.revoke(self.store, 'ann', 'sales_agent', apply=True)
        self.assertEqual((r.ok, r.changed, r.code), (True, False, 'not_held'))
        self.assertEqual(self.audits(), [])

    def test_the_last_owner_cannot_be_revoked(self):
        rbac_admin.revoke(self.store, 'bob', 'support_owner', apply=True)         # ann remains: fine
        r = rbac_admin.revoke(self.store, 'ann', 'support_owner', apply=True)
        self.assertEqual((r.ok, r.changed, r.code), (False, False, 'last_owner'))
        self.assertIn('support_owner', self.store.table[self.ann.id])
        self.assertEqual(len(self.audits()), 1)                                   # only the first revoke

    def test_an_inactive_owner_does_not_count_so_revoking_the_only_active_one_is_refused(self):
        self.store.table[self.gone.id] = {'support_owner'}
        rbac_admin.revoke(self.store, 'bob', 'support_owner', apply=True)
        r = rbac_admin.revoke(self.store, 'ann', 'support_owner', apply=True)
        self.assertEqual(r.code, 'last_owner')

    def test_an_active_bootstrap_owner_from_the_environment_lets_the_last_table_owner_go(self):
        with mock.patch.dict(os.environ, {'KG_SUPPORT_OWNERS': 'bob'}):
            rbac_admin.revoke(self.store, 'ann', 'support_owner', apply=True)
            r = rbac_admin.revoke(self.store, 'bob', 'support_owner', apply=True)  # bob is still an env owner
        self.assertEqual((r.ok, r.code), (True, 'revoked'))

    def test_a_misspelt_environment_owner_does_not_count_as_a_safety_net(self):
        with mock.patch.dict(os.environ, {'KG_SUPPORT_OWNERS': 'bobb'}):
            rbac_admin.revoke(self.store, 'bob', 'support_owner', apply=True)
            r = rbac_admin.revoke(self.store, 'ann', 'support_owner', apply=True)
        self.assertEqual(r.code, 'last_owner')

    def test_dry_run_also_reports_the_last_owner_refusal(self):
        rbac_admin.revoke(self.store, 'bob', 'support_owner', apply=True)
        r = rbac_admin.revoke(self.store, 'ann', 'support_owner', apply=False)
        self.assertEqual((r.ok, r.code), (False, 'last_owner'))

    def test_revoking_from_a_deactivated_admin_is_allowed(self):
        self.store.table[self.gone.id] = {'support_agent'}
        r = rbac_admin.revoke(self.store, 'gone', 'support_agent', apply=True)
        self.assertEqual((r.ok, r.code), (True, 'revoked'))

    def test_validation_and_missing_table(self):
        self.assertEqual(rbac_admin.revoke(self.store, 'bob', 'boss', apply=True).code, 'unknown_role')
        self.assertEqual(rbac_admin.revoke(self.store, 'zed', 'support_agent', apply=True).code, 'unknown_admin')
        self.assertEqual(rbac_admin.revoke(FakeStore(False), 'bob', 'support_agent', apply=True).code, 'table_missing')


class CommandTests(Base):
    def run_cmd(self, *args, store=None):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.object(rbac_admin, 'get_store', return_value=store or self.store):
            try:
                call_command('support_roles', *args, stdout=out, stderr=err)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_grant_without_apply_is_a_dry_run_that_says_so(self):
        code, out, _ = self.run_cmd('grant', '--admin', 'bob', '--role', 'support_agent')
        self.assertEqual(code, 0)
        self.assertIn('would grant', out.lower())
        self.assertIn('--apply', out)
        self.assertEqual(self.store.table, {})

    def test_grant_and_revoke_with_apply(self):
        self.assertEqual(self.run_cmd('grant', '--admin', 'bob', '--role', 'sales_agent', '--apply')[0], 0)
        self.assertEqual(self.store.table, {self.bob.id: {'sales_agent'}})
        self.assertEqual(self.run_cmd('revoke', '--admin', 'bob', '--role', 'sales_agent', '--apply')[0], 0)
        self.assertEqual(self.store.table[self.bob.id], set())

    def test_failures_exit_1_with_a_reason(self):
        for args, needle in ((('grant', '--admin', 'zed', '--role', 'support_agent', '--apply'), 'matches no administrator'),
                             (('grant', '--admin', 'bob', '--role', 'boss', '--apply'), 'unknown role'),
                             (('revoke', '--admin', 'ann', '--role', 'support_owner', '--apply'), 'not held')):
            code, out, err = self.run_cmd(*args)
            self.assertIn(needle, (out + err).lower(), args)
        self.store.table = {self.ann.id: {'support_owner'}}
        code, out, err = self.run_cmd('revoke', '--admin', 'ann', '--role', 'support_owner', '--apply')
        self.assertEqual(code, 1)
        self.assertIn('last', (out + err).lower())

    def test_without_the_table_the_real_store_refuses_and_exits_1(self):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        try:
            call_command('support_roles', 'grant', '--admin', 'bob', '--role', 'support_agent', '--apply',
                         stdout=out, stderr=err)
        except SystemExit as exc:
            code = exc.code
        self.assertEqual(code, 1)
        self.assertIn('migration B', out.getvalue() + err.getvalue())

    def test_the_command_never_changes_the_mode_or_environment(self):
        self.run_cmd('grant', '--admin', 'bob', '--role', 'support_agent', '--apply')
        self.assertEqual(rbac.mode(), 'off')
