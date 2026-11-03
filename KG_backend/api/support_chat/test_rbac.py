"""RBAC core: the permission matrix, the off/audit/enforce modes and query scope.

The expectation table below is written out by hand and is deliberately NOT built
from ``rbac.MATRIX``: a test that reads the matrix it is testing proves nothing.
Role rows come from the (not yet existing) role table, so tests inject them
through ``rbac._table_roles``.
"""
import os
from unittest import mock

from django.test import TestCase

from api.models import AuditLog, PlatformAdmin

from . import rbac
from .models import SupportThread

P = rbac  # permission constants live on rbac and are re-exported by permissions

# (own thread, someone else's thread, unassigned thread), all in the role's intent scope.
T, F = True, False
EXPECT = {
    'support_agent': {
        P.READ: (T, F, T), P.REPLY: (T, F, T), P.TAKE: (T, F, T), P.ASSIGN: (F, F, F),
        P.PRIORITY: (T, F, F), P.INTENT: (T, F, F), P.CLOSE: (T, F, F), P.REOPEN: (T, F, F),
        P.SPAM: (F, F, F), P.REVEAL_CONTACT: (T, F, F), P.EXCLUDE: (F, F, F),
    },
    'support_lead': {
        P.READ: (T, T, T), P.REPLY: (T, T, T), P.TAKE: (T, T, T), P.ASSIGN: (T, T, T),
        P.PRIORITY: (T, T, T), P.INTENT: (T, T, T), P.CLOSE: (T, T, T), P.REOPEN: (T, T, T),
        P.SPAM: (T, T, T), P.REVEAL_CONTACT: (T, T, T), P.EXCLUDE: (T, T, T),
    },
    'support_auditor': {
        P.READ: (T, T, T), P.REPLY: (F, F, F), P.TAKE: (F, F, F), P.ASSIGN: (F, F, F),
        P.PRIORITY: (F, F, F), P.INTENT: (F, F, F), P.CLOSE: (F, F, F), P.REOPEN: (F, F, F),
        P.SPAM: (F, F, F), P.REVEAL_CONTACT: (F, F, F), P.EXCLUDE: (F, F, F),
    },
    'support_owner': {
        P.READ: (T, T, T), P.REPLY: (T, T, T), P.TAKE: (T, T, T), P.ASSIGN: (T, T, T),
        P.PRIORITY: (T, T, T), P.INTENT: (T, T, T), P.CLOSE: (T, T, T), P.REOPEN: (T, T, T),
        P.SPAM: (T, T, T), P.REVEAL_CONTACT: (T, T, T), P.EXCLUDE: (T, T, T),
    },
}
EXPECT['sales_agent'] = EXPECT['support_agent']          # same shape, different intents
# Permissions that are not about one thread: does the role hold it at all?
NON_THREAD = {
    'support_agent': {P.METRICS: F, P.NOTIFY_HEALTH: F, P.AVAILABILITY: T, P.ROLES: F},
    'sales_agent': {P.METRICS: F, P.NOTIFY_HEALTH: F, P.AVAILABILITY: T, P.ROLES: F},
    'support_lead': {P.METRICS: T, P.NOTIFY_HEALTH: T, P.AVAILABILITY: T, P.ROLES: F},
    'support_auditor': {P.METRICS: T, P.NOTIFY_HEALTH: T, P.AVAILABILITY: F, P.ROLES: F},
    'support_owner': {P.METRICS: T, P.NOTIFY_HEALTH: T, P.AVAILABILITY: T, P.ROLES: T},
}
IN_SCOPE = {'support_agent': 'technical', 'sales_agent': 'sales', 'support_lead': 'technical',
            'support_auditor': 'sales', 'support_owner': 'demo'}
OUT_OF_SCOPE = {'support_agent': 'sales', 'sales_agent': 'technical'}


class RbacBase(TestCase):
    def setUp(self):
        self.table = {}
        p = mock.patch.object(rbac, '_table_roles',
                              side_effect=lambda a: set(self.table.get(a.username, ())))
        p.start()
        self.addCleanup(p.stop)
        self.me = PlatformAdmin.objects.create(username='me', password_hash='x', active=True)
        self.other = PlatformAdmin.objects.create(username='other', password_hash='x', active=True)

    def env(self, **kw):
        p = mock.patch.dict(os.environ, kw)
        p.start()
        self.addCleanup(p.stop)

    def thread(self, intent, assignee=None):
        return SupportThread.objects.create(token_hash=os.urandom(16).hex() * 2, intent=intent,
                                            assignee=assignee)


class MatrixTests(RbacBase):
    def test_every_role_permission_and_ownership_combination(self):
        self.env(KG_SUPPORT_RBAC='enforce')
        for role, perms in EXPECT.items():
            self.table = {'me': [role]}
            intent = IN_SCOPE[role]
            own, theirs, free = (self.thread(intent, self.me), self.thread(intent, self.other),
                                 self.thread(intent))
            for perm, (e_own, e_other, e_free) in perms.items():
                got = (rbac.can(self.me, perm, own), rbac.can(self.me, perm, theirs),
                       rbac.can(self.me, perm, free))
                self.assertEqual(got, (e_own, e_other, e_free), f'{role} {perm}')

    def test_agents_are_confined_to_their_intents(self):
        self.env(KG_SUPPORT_RBAC='enforce')
        for role, outside in OUT_OF_SCOPE.items():
            self.table = {'me': [role]}
            for perm in (P.READ, P.REPLY, P.TAKE, P.PRIORITY, P.CLOSE, P.REVEAL_CONTACT):
                self.assertFalse(rbac.can(self.me, perm, self.thread(outside, self.me)),
                                 f'{role} {perm} out of scope (own)')
                self.assertFalse(rbac.can(self.me, perm, self.thread(outside)),
                                 f'{role} {perm} out of scope (unassigned)')

    def test_non_thread_permissions_per_role(self):
        self.env(KG_SUPPORT_RBAC='enforce')
        for role, perms in NON_THREAD.items():
            self.table = {'me': [role]}
            for perm, expected in perms.items():
                self.assertEqual(rbac.can(self.me, perm), expected, f'{role} {perm}')

    def test_roles_union_and_unknown_role_names_are_ignored(self):
        self.env(KG_SUPPORT_RBAC='enforce')
        self.table = {'me': ['support_agent', 'sales_agent']}
        self.assertTrue(rbac.can(self.me, P.READ, self.thread('sales')))
        self.assertTrue(rbac.can(self.me, P.READ, self.thread('technical')))
        self.table = {'me': ['superuser', 'root', '']}
        self.assertFalse(rbac.can(self.me, P.READ, self.thread('technical')))

    def test_unknown_permission_names_are_a_programming_error(self):
        with self.assertRaises(ValueError):
            rbac.can(self.me, 'support.nonsense')


class ModeTests(RbacBase):
    def test_mode_parsing_and_unknown_values_never_mean_enforce(self):
        for raw, want in (('', 'off'), ('off', 'off'), ('audit', 'audit'), ('enforce', 'enforce'),
                          (' ENFORCE ', 'enforce'), ('Audit', 'audit'), ('on', 'off'),
                          ('true', 'off'), ('1', 'off'), ('enforced', 'off')):
            self.env(KG_SUPPORT_RBAC=raw)
            self.assertEqual(rbac.mode(), want, raw)

    def test_off_keeps_todays_flat_model_for_every_active_person(self):
        self.env(KG_SUPPORT_RBAC='off')
        t = self.thread('technical')
        for perm in rbac.ALL:
            self.assertTrue(rbac.can(self.me, perm, t), perm)         # no role at all
        self.assertFalse(rbac.can(None, P.READ))                      # loopback is never a person
        self.me.active = False
        self.assertFalse(rbac.can(self.me, P.READ))

    def test_default_when_unset_is_off(self):
        os.environ.pop('KG_SUPPORT_RBAC', None)
        self.assertEqual(rbac.mode(), 'off')
        self.assertTrue(rbac.can(self.me, P.REPLY, self.thread('sales')))

    def test_audit_allows_but_records_each_would_be_denial_with_ids_only(self):
        self.env(KG_SUPPORT_RBAC='audit')
        t = self.thread('technical')
        self.assertTrue(rbac.can(self.me, P.SPAM, t))                 # no role: would be denied
        row = AuditLog.objects.get(action='support_chat.rbac_would_deny')
        self.assertEqual((row.actor_id, row.target_id), (self.me.id, str(t.pk)))
        self.assertEqual(row.detail, {'permission': 'support.spam', 'intent': 'technical'})
        self.table = {'me': ['support_owner']}
        before = AuditLog.objects.count()
        self.assertTrue(rbac.can(self.me, P.SPAM, t))                 # allowed: nothing recorded
        self.assertEqual(AuditLog.objects.count(), before)

    def test_enforce_denies_without_a_role_and_never_falls_back(self):
        self.env(KG_SUPPORT_RBAC='enforce')
        t = self.thread('technical')
        for perm in rbac.ALL:
            self.assertFalse(rbac.can(self.me, perm, t), perm)
        self.assertFalse(AuditLog.objects.filter(action='support_chat.rbac_would_deny').exists())

    def test_enforce_with_no_owner_stays_closed_and_says_why(self):
        self.env(KG_SUPPORT_RBAC='enforce', KG_SUPPORT_OWNERS='')
        self.assertFalse(rbac.active_owner_exists())
        self.assertFalse(rbac.can(self.me, P.READ, self.thread('sales')))
        self.assertEqual(rbac.denial_code(), 'rbac_no_owner')
        self.table = {'me': ['support_owner']}
        self.assertTrue(rbac.active_owner_exists())
        self.assertEqual(rbac.denial_code(), 'forbidden')

    def test_audit_and_off_never_report_no_owner(self):
        for m in ('off', 'audit'):
            self.env(KG_SUPPORT_RBAC=m, KG_SUPPORT_OWNERS='')
            self.assertEqual(rbac.denial_code(), 'forbidden')


class BootstrapOwnerTests(RbacBase):
    def test_env_owners_hold_owner_without_any_table_row(self):
        self.env(KG_SUPPORT_RBAC='enforce', KG_SUPPORT_OWNERS='me')
        self.assertEqual(rbac.roles_for(self.me), {'support_owner'})
        self.assertTrue(rbac.can(self.me, P.ROLES))
        self.assertFalse(rbac.can(self.other, P.READ, self.thread('sales')))

    def test_owner_names_are_case_insensitive_trimmed_and_split_on_commas_or_spaces(self):
        self.env(KG_SUPPORT_OWNERS=' ME ,  Other ;x')
        self.assertEqual(rbac.bootstrap_owner_names(), {'me', 'other', 'x'})

    def test_an_inactive_owner_does_not_count_and_has_no_access(self):
        self.env(KG_SUPPORT_RBAC='enforce', KG_SUPPORT_OWNERS='me')
        self.me.active = False
        self.me.save()
        self.assertFalse(rbac.active_owner_exists())
        self.assertFalse(rbac.can(self.me, P.READ, self.thread('sales')))

    def test_a_misspelt_owner_name_grants_nothing_to_anyone(self):
        self.env(KG_SUPPORT_RBAC='enforce', KG_SUPPORT_OWNERS='mee')
        self.assertFalse(rbac.active_owner_exists())
        self.assertFalse(rbac.can(self.me, P.READ, self.thread('sales')))

    def test_owner_status_comes_from_the_table_too(self):
        self.env(KG_SUPPORT_RBAC='enforce', KG_SUPPORT_OWNERS='')
        self.table = {'other': ['support_owner']}
        self.assertTrue(rbac.active_owner_exists())


class ScopeTests(RbacBase):
    def make_set(self):
        return {
            's_free': self.thread('sales'), 's_mine': self.thread('sales', self.me),
            's_theirs': self.thread('sales', self.other), 't_free': self.thread('technical'),
            't_mine': self.thread('technical', self.me), 't_theirs': self.thread('technical', self.other),
        }

    def visible(self, admin):
        return set(rbac.scoped_threads(admin, SupportThread.objects.all())
                   .values_list('pk', flat=True))

    def ids(self, threads, *names):
        return {threads[n].pk for n in names}

    def test_off_and_audit_do_not_narrow_the_queryset(self):
        threads = self.make_set()
        for m in ('off', 'audit'):
            self.env(KG_SUPPORT_RBAC=m)
            self.assertEqual(self.visible(self.me), {t.pk for t in threads.values()})

    def test_enforce_agent_sees_only_in_scope_own_or_unassigned(self):
        self.env(KG_SUPPORT_RBAC='enforce')
        threads = self.make_set()
        self.table = {'me': ['sales_agent']}
        self.assertEqual(self.visible(self.me), self.ids(threads, 's_free', 's_mine'))
        self.table = {'me': ['support_agent']}
        self.assertEqual(self.visible(self.me), self.ids(threads, 't_free', 't_mine'))
        self.table = {'me': ['support_agent', 'sales_agent']}
        self.assertEqual(self.visible(self.me), self.ids(threads, 's_free', 's_mine', 't_free', 't_mine'))

    def test_enforce_lead_auditor_owner_see_everything_and_no_role_sees_nothing(self):
        self.env(KG_SUPPORT_RBAC='enforce')
        threads = self.make_set()
        everything = {t.pk for t in threads.values()}
        for role in ('support_lead', 'support_auditor', 'support_owner'):
            self.table = {'me': [role]}
            self.assertEqual(self.visible(self.me), everything, role)
        self.table = {}
        self.assertEqual(self.visible(self.me), set())
        self.assertEqual(self.visible(None), set())

    def test_scope_agrees_with_can_for_every_thread(self):
        self.env(KG_SUPPORT_RBAC='enforce')
        threads = self.make_set()
        for roles in (['sales_agent'], ['support_agent'], ['support_lead'], ['support_auditor'], []):
            self.table = {'me': roles}
            seen = self.visible(self.me)
            for t in threads.values():
                self.assertEqual(t.pk in seen, rbac.can(self.me, P.READ, t), f'{roles} {t.intent}')

    def test_event_intents_for_enforce_only(self):
        self.env(KG_SUPPORT_RBAC='off')
        self.assertIsNone(rbac.event_intents(self.me))
        self.env(KG_SUPPORT_RBAC='enforce')
        self.table = {'me': ['sales_agent']}
        self.assertEqual(rbac.event_intents(self.me), frozenset({'sales', 'demo'}))
        self.table = {'me': ['support_lead']}
        self.assertEqual(rbac.event_intents(self.me), frozenset(rbac.ALL_INTENTS))
        self.table = {}
        self.assertEqual(rbac.event_intents(self.me), frozenset())
        self.assertEqual(rbac.event_intents(None), frozenset())        # loopback gets none

    def test_reply_capability_by_intent_for_presence(self):
        self.env(KG_SUPPORT_RBAC='enforce')
        self.table = {'me': ['sales_agent']}
        self.assertTrue(rbac.can_reply_intent(self.me, 'sales'))
        self.assertFalse(rbac.can_reply_intent(self.me, 'technical'))
        self.assertTrue(rbac.can_reply_intent(self.me, None))          # any intent
        self.table = {'me': ['support_auditor']}
        self.assertFalse(rbac.can_reply_intent(self.me, None))
        self.env(KG_SUPPORT_RBAC='off')
        self.table = {}
        self.assertTrue(rbac.can_reply_intent(self.me, 'technical'))   # flat model
