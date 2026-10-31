"""QA audit: authorization & entitlement rules (api/access.py, api/portal_auth.py,
api/quota.py).

Each test pins one business rule: who may manage whom (role ladder / org graph),
which subscription layers a seat effectively holds (purchase vs platform-admin
grants), AI-assistant eligibility, the manager/analytics gates, account
lock/expiry/inactivity, cross-company isolation, and the AI question allowance
with its exact boundaries. Nothing under test is mocked; the only patch used
simulates a concurrent request racing the quota check.
"""
import json
import unittest
from datetime import timedelta
from unittest import mock

from django.http import JsonResponse
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from . import access
from . import orggraph as og
from . import quota
from .access import (
    AI_REQUIRED_PACKAGE, ROLE_LEVEL, VALID_PACKAGES, apply_managed_access,
    apply_user_access, company_role_options, default_capabilities_for_role,
    effective_documents, enforce_org_consistency, ensure_company_role,
    find_valid_supervisor, legacy_role_for_rank, manageable_user_ids,
    manager_can_target, manager_grantable_cars, normalize_role, parse_seat_plan,
    role_can_manage, role_label, seed_company_roles, subtree_user_ids,
    user_ai_eligible, user_can_open_car, user_car_documents, user_package_set,
)
from .models import (
    ActivityLog, AuthToken, Car, Company, CompanyCarAccess, CompanyRequest,
    CompanyRole, NodePermission, OrgGraph, OrgNode, PortalUser, UserCarAccess,
)
from .portal_auth import (
    require_analytics, require_manager, user_can_view_company_stream,
)

ALL = set(VALID_PACKAGES)


def mkcar(i, db=''):
    return Car.objects.create(brand_name='QB', car_name=f'QC{i}', year=2000 + i,
                              db_address=db)


def mkcompany(name, **kw):
    kw.setdefault('active', True)
    return Company.objects.create(name=name, **kw)


def mkuser(company, username, role='after_sales_specialist', **kw):
    kw.setdefault('active', True)
    return PortalUser.objects.create(company=company, username=username, role=role,
                                     password_hash='x', **kw)


def bearer(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(user).key}'}


def fresh(u):
    """Re-fetch so reverse one-to-one (``seat``) caches are not stale."""
    return PortalUser.objects.get(pk=u.pk)


# ---------------------------------------------------------------------------
# Role ladder
# ---------------------------------------------------------------------------

class RoleHierarchyTests(TestCase):
    def test_role_levels_are_strict_top_down(self):
        order = ['after_sales_manager', 'after_sales_head',
                 'after_sales_supervisor', 'after_sales_specialist']
        self.assertEqual([ROLE_LEVEL[r] for r in order], [1, 2, 3, 4])

    def test_higher_role_manages_every_lower_role_and_never_upward(self):
        roles = sorted(ROLE_LEVEL, key=ROLE_LEVEL.get)
        for i, actor in enumerate(roles):
            for j, target in enumerate(roles):
                self.assertEqual(role_can_manage(actor, target), i < j,
                                 f'{actor} -> {target}')

    def test_equal_roles_cannot_manage_each_other(self):
        for r in ROLE_LEVEL:
            self.assertFalse(role_can_manage(r, r))

    def test_legacy_roles_are_treated_as_specialist(self):
        self.assertEqual(normalize_role('technical_expert'), 'after_sales_specialist')
        self.assertEqual(normalize_role('technical_staff'), 'after_sales_specialist')
        self.assertTrue(role_can_manage('after_sales_supervisor', 'technical_expert'))
        self.assertFalse(role_can_manage('technical_staff', 'after_sales_specialist'))
        self.assertEqual(normalize_role('after_sales_head'), 'after_sales_head')

    def test_unknown_role_has_no_authority(self):
        # An unrecognised (custom) role ranks below the whole ladder: it can
        # manage nobody, while any built-in role outranks it.
        for r in ROLE_LEVEL:
            self.assertFalse(role_can_manage('janitor', r))
            self.assertTrue(role_can_manage(r, 'janitor'))
        self.assertFalse(role_can_manage('janitor', 'janitor'))

    def test_legacy_role_for_rank_boundaries(self):
        self.assertEqual(legacy_role_for_rank(0), 'after_sales_manager')
        self.assertEqual(legacy_role_for_rank(1), 'after_sales_manager')
        self.assertEqual(legacy_role_for_rank(2), 'after_sales_head')
        self.assertEqual(legacy_role_for_rank(3), 'after_sales_supervisor')
        self.assertEqual(legacy_role_for_rank(4), 'after_sales_specialist')
        self.assertEqual(legacy_role_for_rank(99), 'after_sales_specialist')

    def test_default_capabilities_seeded_from_role(self):
        mgr = default_capabilities_for_role('after_sales_manager')
        head = default_capabilities_for_role('after_sales_head')
        sup = default_capabilities_for_role('after_sales_supervisor')
        spec = default_capabilities_for_role('after_sales_specialist')
        custom = default_capabilities_for_role('custom-role')
        self.assertEqual((mgr['can_manage_team'], mgr['can_view_analytics']), (True, True))
        self.assertEqual((head['can_manage_team'], head['can_view_analytics']), (True, True))
        self.assertEqual((sup['can_manage_team'], sup['can_view_analytics']), (False, True))
        self.assertEqual((spec['can_manage_team'], spec['can_view_analytics']), (False, False))
        self.assertEqual((custom['can_manage_team'], custom['can_view_analytics']), (False, False))
        for caps in (mgr, head, sup, spec, custom):
            self.assertTrue(caps['ai_assistant_enabled'])

    def test_role_label_substitutes_custom_department(self):
        self.assertEqual(role_label('after_sales_manager'), 'مدیر خدمات پس از فروش')
        self.assertEqual(role_label('after_sales_manager', 'خدمات پس از فروش'),
                         'مدیر خدمات پس از فروش')
        self.assertEqual(role_label('after_sales_head', 'فنی'), 'رئیس فنی')
        # legacy id resolves through the map; unknown ids pass through verbatim
        self.assertEqual(role_label('technical_expert'), 'کارشناس خدمات پس از فروش')
        self.assertEqual(role_label('Night Shift Lead'), 'Night Shift Lead')

    def test_display_role_label_uses_company_department(self):
        c = mkcompany('QA-dept', department_label='تعمیرات')
        u = mkuser(c, 'qa-dept-u', role='after_sales_supervisor')
        self.assertEqual(access.display_role_label(u), 'سرپرست تعمیرات')
        self.assertEqual(access.display_role_label(u, ''), 'سرپرست خدمات پس از فروش')
        self.assertEqual(access.user_rank(u), 3)
        self.assertEqual(access.user_manage_scope(u), 'subtree')


class CompanyRoleCatalogTests(TestCase):
    def setUp(self):
        self.c = mkcompany('QA-roles')

    def test_seed_is_idempotent_and_builtin(self):
        seed_company_roles(self.c)
        seed_company_roles(self.c)
        rows = CompanyRole.objects.filter(company=self.c)
        self.assertEqual(rows.count(), 4)
        self.assertTrue(all(r.is_builtin for r in rows))

    def test_ensure_company_role_blank_is_noop_and_custom_is_not_builtin(self):
        ensure_company_role(self.c, '   ')
        ensure_company_role(self.c, None)
        self.assertEqual(CompanyRole.objects.filter(company=self.c).count(), 0)
        ensure_company_role(self.c, '  Paint Shop  ')
        ensure_company_role(self.c, 'after_sales_head')
        ensure_company_role(self.c, 'Paint Shop')  # idempotent
        self.assertFalse(CompanyRole.objects.get(company=self.c, value='Paint Shop').is_builtin)
        self.assertTrue(CompanyRole.objects.get(company=self.c, value='after_sales_head').is_builtin)
        self.assertEqual(CompanyRole.objects.filter(company=self.c).count(), 2)

    def test_options_seed_and_surface_roles_in_use(self):
        mkuser(self.c, 'qa-r1', role='after_sales_head')
        mkuser(self.c, 'qa-r2', role='Legacy Lead')     # held but not in the table
        other = mkcompany('QA-roles-other')
        mkuser(other, 'qa-r3', role='Foreign Role')     # must never leak across
        opts = {o['value']: o for o in company_role_options(self.c)}
        self.assertEqual(set(opts), set(ROLE_LEVEL) | {'Legacy Lead'})
        self.assertTrue(opts['after_sales_head']['in_use'])
        self.assertTrue(opts['after_sales_head']['builtin'])
        self.assertFalse(opts['after_sales_manager']['in_use'])
        self.assertEqual(opts['Legacy Lead'], {'value': 'Legacy Lead', 'label': 'Legacy Lead',
                                               'builtin': False, 'in_use': True})
        self.assertNotIn('Foreign Role', opts)
        self.assertEqual(CompanyRole.objects.filter(company=self.c).count(), 4)


# ---------------------------------------------------------------------------
# Packages / document grants
# ---------------------------------------------------------------------------

class EffectiveDocumentsTests(TestCase):
    def test_explicit_documents_drop_unknown_layers(self):
        row = UserCarAccess(documents=['manual', 'bogus', 'parts'])
        self.assertEqual(effective_documents(row), ['manual', 'parts'])
        # With a company scope an explicit list is clamped to it (never widened).
        self.assertEqual(effective_documents(row, ['special_tools']), [])
        self.assertEqual(effective_documents(row, ['parts', 'special_tools']), ['parts'])

    def test_empty_documents_inherit_company_scope_else_everything(self):
        row = UserCarAccess(documents=[])
        self.assertEqual(effective_documents(row, ['parts', 'nope']), ['parts'])
        self.assertEqual(set(effective_documents(row)), ALL)
        self.assertEqual(effective_documents(row, []), [])


class PackageEntitlementTests(TestCase):
    def setUp(self):
        self.c = mkcompany('QA-pkg', ai_assistant_enabled=True)
        self.car_bought = mkcar(1)
        self.car_extra = mkcar(2)
        self.car_none = mkcar(3)
        CompanyCarAccess.objects.create(company=self.c, car=self.car_bought,
                                        documents=['parts', 'standard_time'])
        self.u = mkuser(self.c, 'qa-pkg-u', ai_assistant_enabled=True)

    # Regression (fixed in this change): access.py:113 effective_documents returns a purchase row's explicit layers without intersecting the company scope, so a seat keeps layers (e.g. 'manual') the company did not buy
    def test_purchase_grant_is_clamped_to_company_scope(self):
        UserCarAccess.objects.create(user=self.u, car=self.car_bought,
                                     documents=['parts', 'manual'])
        self.assertEqual(user_package_set(self.u), {'parts'})
        self.assertEqual(user_car_documents(self.u, self.car_bought), {'parts'})

    def test_purchase_grant_within_scope_is_honoured(self):
        UserCarAccess.objects.create(user=self.u, car=self.car_bought, documents=['parts'])
        self.assertEqual(user_package_set(self.u), {'parts'})
        self.assertEqual(user_car_documents(self.u, self.car_bought), {'parts'})

    # Regression (fixed in this change): portal.py:1334 company re-scope prunes only removed CARS, not removed layers; with access.py:113 the seat keeps the dropped layer (and AI eligibility)
    def test_admin_layer_rescope_revokes_layer_for_seats(self):
        cca = CompanyCarAccess.objects.get(company=self.c, car=self.car_bought)
        cca.documents = ['manual', 'parts']
        cca.save()
        apply_user_access(self.u, [{'car_id': self.car_bought.id,
                                    'documents': ['manual', 'parts']}])
        self.assertTrue(user_ai_eligible(fresh(self.u)))
        with mock.patch.dict('os.environ', {'KG_ADMIN_TOKEN': 'qa-admin-secret'}):
            r = Client().post(f'/api/admin/companies/{self.c.id}/access/',
                              data=json.dumps({'accesses': [{'car_id': self.car_bought.id,
                                                             'documents': ['parts']}]}),
                              content_type='application/json',
                              HTTP_X_ADMIN_TOKEN='qa-admin-secret')
        self.assertEqual(r.status_code, 200)
        u = fresh(self.u)
        self.assertEqual(user_car_documents(u, self.car_bought), {'parts'})
        self.assertFalse(user_ai_eligible(u))

    def test_empty_purchase_grant_means_whole_company_scope(self):
        UserCarAccess.objects.create(user=self.u, car=self.car_bought, documents=[])
        self.assertEqual(user_package_set(self.u), {'parts', 'standard_time'})

    def test_company_with_unrestricted_purchase_grants_every_layer(self):
        cca = CompanyCarAccess.objects.get(company=self.c, car=self.car_bought)
        cca.documents = []
        cca.save()
        UserCarAccess.objects.create(user=self.u, car=self.car_bought, documents=[])
        self.assertEqual(user_package_set(self.u), ALL)
        self.assertEqual(user_car_documents(self.u, self.car_bought), ALL)

    def test_admin_grant_bypasses_company_scope(self):
        UserCarAccess.objects.create(user=self.u, car=self.car_extra,
                                     documents=['manual'], admin_granted=True)
        self.assertEqual(user_package_set(self.u), {'manual'})
        self.assertEqual(user_car_documents(self.u, self.car_extra), {'manual'})
        self.assertTrue(user_can_open_car(self.u, self.car_extra))

    def test_purchase_grant_revoked_when_company_loses_car(self):
        # Regression: a re-scoped company must revoke the car for every seat
        # even if a stale UserCarAccess row survived.
        UserCarAccess.objects.create(user=self.u, car=self.car_none, documents=['manual'])
        self.assertEqual(user_package_set(self.u), set())
        self.assertIsNone(user_car_documents(self.u, self.car_none))
        self.assertFalse(user_can_open_car(self.u, self.car_none))

    def test_no_grant_no_access(self):
        self.assertIsNone(user_car_documents(self.u, self.car_bought))
        self.assertFalse(user_can_open_car(self.u, self.car_bought))


class AiEligibilityTests(TestCase):
    def setUp(self):
        self.c = mkcompany('QA-ai', ai_assistant_enabled=True)
        self.car = mkcar(10)
        CompanyCarAccess.objects.create(company=self.c, car=self.car,
                                        documents=['manual', 'parts'])
        self.u = mkuser(self.c, 'qa-ai-u', ai_assistant_enabled=True)

    def test_required_package_is_repair_manual(self):
        self.assertEqual(AI_REQUIRED_PACKAGE, 'manual')

    def test_eligible_with_manual(self):
        UserCarAccess.objects.create(user=self.u, car=self.car, documents=['manual'])
        self.assertTrue(user_ai_eligible(self.u))

    def test_not_eligible_without_manual_layer(self):
        UserCarAccess.objects.create(user=self.u, car=self.car, documents=['parts'])
        self.assertFalse(user_ai_eligible(self.u))

    def test_not_eligible_without_any_car(self):
        self.assertFalse(user_ai_eligible(self.u))

    def test_user_toggle_off_blocks_even_with_manual(self):
        UserCarAccess.objects.create(user=self.u, car=self.car, documents=['manual'])
        self.u.ai_assistant_enabled = False
        self.assertFalse(user_ai_eligible(self.u))

    def test_company_toggle_off_blocks_even_with_manual(self):
        UserCarAccess.objects.create(user=self.u, car=self.car, documents=['manual'])
        self.c.ai_assistant_enabled = False
        self.c.save()
        self.assertFalse(user_ai_eligible(fresh(self.u)))

    # Regression (fixed in this change): access.py:113/132 explicit purchase-row layers bypass company scope, so 'manual' not bought by the company still makes the seat AI-eligible
    def test_manual_requested_but_not_purchased_does_not_qualify(self):
        cca = CompanyCarAccess.objects.get(company=self.c, car=self.car)
        cca.documents = ['parts']
        cca.save()
        UserCarAccess.objects.create(user=self.u, car=self.car, documents=['manual'])
        self.assertFalse(user_ai_eligible(self.u))


class SeatPlanTests(TestCase):
    def test_rejects_non_list_and_empty(self):
        for raw in (None, {}, 'x', [], [1, 'a', None]):
            rows, err = parse_seat_plan(raw)
            self.assertIsNone(rows, raw)
            self.assertIsInstance(err, str)

    def test_rejects_unknown_role(self):
        rows, err = parse_seat_plan([{'role': 'ceo', 'count': 1}])
        self.assertIsNone(rows)
        self.assertIn('نامعتبر', err)

    def test_count_boundaries(self):
        for bad in (0, -1, 1001):
            rows, _ = parse_seat_plan([{'role': 'after_sales_head', 'count': bad}])
            self.assertIsNone(rows, bad)
        for bad in (None, 'abc', ''):
            rows, err = parse_seat_plan([{'role': 'after_sales_head', 'count': bad}])
            self.assertIsNone(rows, bad)
            self.assertIn('الزامی', err)
        rows, total = parse_seat_plan([{'role': 'after_sales_head', 'count': 1},
                                       {'role': 'after_sales_manager', 'count': '1000'}])
        self.assertEqual(total, 1001)
        self.assertEqual([r['count'] for r in rows], [1, 1000])

    def test_normalizes_and_defaults(self):
        rows, total = parse_seat_plan(['junk', {'role': ' technical_expert ', 'count': 3,
                                                'department': 'x' * 200,
                                                'note': 'n' * 900}])
        self.assertEqual(total, 3)
        self.assertEqual(rows[0]['role'], 'after_sales_specialist')
        self.assertEqual(len(rows[0]['department']), 80)
        self.assertEqual(len(rows[0]['note']), 500)
        rows, _ = parse_seat_plan([{'role': 'after_sales_head', 'count': 2}])
        self.assertEqual(rows[0]['department'], 'خدمات پس از فروش')
        self.assertEqual(rows[0]['note'], '')

    def test_only_first_50_rows_are_considered(self):
        raw = [{'role': 'after_sales_specialist', 'count': 1}] * 60
        rows, total = parse_seat_plan(raw)
        self.assertEqual(len(rows), 50)
        self.assertEqual(total, 50)


# ---------------------------------------------------------------------------
# Grant writers: platform admin vs company manager
# ---------------------------------------------------------------------------

class ApplyUserAccessTests(TestCase):
    def setUp(self):
        self.c = mkcompany('QA-apply')
        self.car1 = mkcar(21)
        self.car2 = mkcar(22)
        self.outside = mkcar(23)
        CompanyCarAccess.objects.create(company=self.c, car=self.car1, documents=['manual', 'parts'])
        CompanyCarAccess.objects.create(company=self.c, car=self.car2, documents=[])
        self.u = mkuser(self.c, 'qa-apply-u')

    def rows(self):
        return {a.car_id: (sorted(a.documents), a.admin_granted)
                for a in UserCarAccess.objects.filter(user=self.u)}

    def test_rejects_non_list(self):
        with self.assertRaises(ValueError):
            apply_user_access(self.u, {'car_id': self.car1.id})

    def test_manager_path_clamps_layers_and_drops_unpurchased_cars(self):
        apply_user_access(self.u, [
            {'car_id': self.car1.id, 'documents': ['manual', 'full_spec']},
            {'car_id': self.car2.id, 'documents': ['special_tools', 'nope']},
            {'car_id': self.outside.id, 'documents': ['manual']},
            {'car_id': 999999, 'documents': ['manual']},
        ])
        self.assertEqual(self.rows(), {self.car1.id: (['manual'], False),
                                       self.car2.id: (['special_tools'], False)})

    def test_admin_flag_ignored_without_platform_admin_rights(self):
        # Regression (privilege escalation): a company manager posting
        # admin_granted/override must NOT escape the company's purchase.
        apply_user_access(self.u, [{'car_id': self.outside.id, 'documents': ['manual'],
                                    'admin_granted': True}], override_purchase=True)
        self.assertEqual(self.rows(), {})

    def test_platform_admin_may_grant_beyond_purchase(self):
        apply_user_access(self.u, [{'car_id': self.outside.id, 'documents': ['manual', 'x'],
                                    'admin_granted': True}], allow_admin_grants=True)
        self.assertEqual(self.rows(), {self.outside.id: (['manual'], True)})

    def test_replaces_previous_grants_and_dedupes(self):
        UserCarAccess.objects.create(user=self.u, car=self.car2, documents=['parts'])
        apply_user_access(self.u, [{'car_id': self.car1.id, 'documents': ['manual']},
                                   {'car_id': self.car1.id, 'documents': ['parts']}])
        self.assertEqual(self.rows(), {self.car1.id: (['manual'], False)})


class ManagedAccessTests(TestCase):
    """'Give only what you have': manager delegation."""

    def setUp(self):
        self.c = mkcompany('QA-managed')
        self.bought = mkcar(31)
        self.extra = mkcar(32)      # admin-granted to the manager only
        self.foreign = mkcar(33)    # neither
        self.adminonly = mkcar(34)  # platform admin granted directly to employee
        CompanyCarAccess.objects.create(company=self.c, car=self.bought, documents=['manual', 'parts'])
        self.mgr = mkuser(self.c, 'qa-mg', role='after_sales_manager', can_manage_team=True)
        self.emp = mkuser(self.c, 'qa-me')
        UserCarAccess.objects.create(user=self.mgr, car=self.extra, documents=['parts'],
                                     admin_granted=True)
        UserCarAccess.objects.create(user=self.emp, car=self.adminonly, documents=['manual'],
                                     admin_granted=True)

    def emp_rows(self):
        return {a.car_id: (sorted(a.documents), a.admin_granted)
                for a in UserCarAccess.objects.filter(user=self.emp)}

    def test_grantable_cars_are_purchase_plus_manager_admin_grants(self):
        self.assertEqual(manager_grantable_cars(self.mgr),
                         {self.bought.id: {'manual', 'parts'}, self.extra.id: {'parts'}})

    def test_rejects_non_list(self):
        with self.assertRaises(ValueError):
            apply_managed_access(self.mgr, self.emp, 'all')

    def test_delegation_is_clamped_and_preserves_out_of_purview_grants(self):
        apply_managed_access(self.mgr, self.emp, [
            {'car_id': self.bought.id, 'documents': ['manual', 'full_spec']},
            {'car_id': self.extra.id},                       # whole car -> manager ceiling
            {'car_id': self.foreign.id, 'documents': ['manual']},
            {'car_id': self.bought.id, 'documents': ['parts']},   # duplicate ignored
        ])
        self.assertEqual(self.emp_rows(), {
            self.bought.id: (['manual'], False),
            self.extra.id: (['parts'], True),      # delivered as admin grant
            self.adminonly.id: (['manual'], True),  # untouched: not manager's purview
        })

    def test_requesting_only_layers_manager_lacks_grants_nothing(self):
        # Regression: an empty intersection must not silently upgrade to "all".
        apply_managed_access(self.mgr, self.emp,
                             [{'car_id': self.extra.id, 'documents': ['manual']}])
        self.assertNotIn(self.extra.id, self.emp_rows())

    def test_redelegation_removes_previous_manager_grants(self):
        apply_managed_access(self.mgr, self.emp, [{'car_id': self.bought.id}])
        self.assertEqual(self.emp_rows()[self.bought.id], (['manual', 'parts'], False))
        apply_managed_access(self.mgr, self.emp, [])
        self.assertEqual(set(self.emp_rows()), {self.adminonly.id})


# ---------------------------------------------------------------------------
# Who may manage whom: legacy reports_to chain and the org graph
# ---------------------------------------------------------------------------

class LegacyChainTests(TestCase):
    """Users without an org-graph seat fall back to the reports_to chain."""

    def setUp(self):
        self.c = mkcompany('QA-chain')
        self.m = mkuser(self.c, 'qa-m', role='after_sales_manager', can_manage_team=True)
        self.h = mkuser(self.c, 'qa-h', role='after_sales_head', can_manage_team=True,
                        reports_to=self.m)
        self.s = mkuser(self.c, 'qa-s', role='after_sales_specialist', reports_to=self.h)
        self.loose = mkuser(self.c, 'qa-loose', role='after_sales_specialist')
        self.other_c = mkcompany('QA-chain-B')
        self.foreign = mkuser(self.other_c, 'qa-foreign', role='after_sales_specialist')

    def test_subtree_is_transitive_and_company_scoped(self):
        self.assertEqual(subtree_user_ids(self.m), {self.h.id, self.s.id})
        self.assertEqual(subtree_user_ids(self.m, include_self=True),
                         {self.m.id, self.h.id, self.s.id})
        self.assertEqual(subtree_user_ids(self.s), set())

    def test_subtree_terminates_on_cycle(self):
        PortalUser.objects.filter(pk=self.m.pk).update(reports_to=self.s)
        ids = subtree_user_ids(self.h)
        self.assertIn(self.s.id, ids)
        self.assertIn(self.m.id, ids)

    def test_manageable_ids_fall_back_to_chain_without_seat(self):
        self.assertEqual(manageable_user_ids(self.h), {self.s.id})
        self.assertEqual(manageable_user_ids(self.h, include_self=True), {self.s.id, self.h.id})
        self.assertNotIn(self.loose.id, manageable_user_ids(self.m))

    def test_manager_can_target_rules(self):
        self.assertTrue(manager_can_target(self.m, self.s))
        self.assertTrue(manager_can_target(self.h, self.s))
        self.assertFalse(manager_can_target(self.h, self.m))           # upward
        self.assertFalse(manager_can_target(self.m, self.m))           # self
        self.assertFalse(manager_can_target(self.m, self.loose))       # not in subtree
        self.assertFalse(manager_can_target(self.m, self.foreign))     # other company
        self.assertFalse(manager_can_target(self.s, self.loose))       # no capability
        self.assertFalse(manager_can_target(None, self.s))
        self.assertFalse(manager_can_target(self.m, None))

    def test_rank_still_vetoes_on_legacy_path(self):
        # A specialist granted can_manage_team can't manage a manager even if
        # the manager reports to them on a corrupted chain.
        self.s.can_manage_team = True
        self.s.save()
        PortalUser.objects.filter(pk=self.m.pk).update(reports_to=self.s)
        self.assertFalse(manager_can_target(self.s, fresh(self.m)))

    def test_find_valid_supervisor_skips_inactive_excluded_and_foreign(self):
        self.h.active = False
        self.h.save()
        s = fresh(self.s)
        self.assertEqual(find_valid_supervisor(s.reports_to, 4, self.c.id), self.m)
        self.assertIsNone(find_valid_supervisor(self.m, 1, self.c.id))  # nobody outranks rank 1
        self.assertIsNone(find_valid_supervisor(self.m, 4, self.c.id, exclude_ids={self.m.id}))
        self.assertIsNone(find_valid_supervisor(self.foreign, 4, self.c.id))
        self.assertIsNone(find_valid_supervisor(None, 4, self.c.id))

    def test_enforce_org_consistency_repairs_upward_edges(self):
        # head now "reports to" a specialist: invariant broken.
        PortalUser.objects.filter(pk=self.h.pk).update(reports_to=self.s)
        self.assertEqual(enforce_org_consistency(self.c.id), 1)
        self.assertEqual(fresh(self.h).reports_to_id, self.m.id)
        self.assertEqual(fresh(self.s).reports_to_id, self.h.id)
        self.assertEqual(enforce_org_consistency(self.c.id), 0)  # idempotent

    def test_enforce_org_consistency_clears_edge_when_no_valid_supervisor(self):
        # the manager reports to a specialist; nobody outranks a manager.
        PortalUser.objects.filter(pk=self.m.pk).update(reports_to=self.s)
        self.assertEqual(enforce_org_consistency(self.c.id), 1)
        self.assertIsNone(fresh(self.m).reports_to_id)


class GraphReachTests(TestCase):
    """With seats, the org-graph canvas — not the role ladder — is authority."""

    def setUp(self):
        self.c = mkcompany('QA-graph')
        self.root = mkuser(self.c, 'qa-g-root', role='after_sales_manager', can_manage_team=True)
        og.seed_graph_for_company(self.c)
        og.reassign_root(self.c, self.root)
        self.graph = OrgGraph.objects.get(company=self.c)
        rn = self.graph.root_node
        # a "manager"-titled user seated BELOW the root, under an empty seat
        self.below = mkuser(self.c, 'qa-g-below', role='after_sales_manager', can_manage_team=True)
        empty = OrgNode.objects.create(graph=self.graph, parent=rn, label='vacant')
        OrgNode.objects.create(graph=self.graph, parent=empty, occupant=self.below)
        self.side = mkuser(self.c, 'qa-g-side', can_manage_team=True)
        OrgNode.objects.create(graph=self.graph, parent=rn, occupant=self.side)

    def test_reach_passes_through_empty_seats(self):
        root = fresh(self.root)
        self.assertEqual(manageable_user_ids(root), {self.below.id, self.side.id})
        self.assertEqual(manageable_user_ids(root, include_self=True),
                         {self.root.id, self.below.id, self.side.id})

    def test_canvas_position_overrides_role_rank(self):
        root, below, side = fresh(self.root), fresh(self.below), fresh(self.side)
        self.assertTrue(manager_can_target(root, below))
        self.assertFalse(manager_can_target(below, root))
        # siblings never manage each other, whatever their capability flag
        self.assertFalse(manager_can_target(side, below))
        self.assertFalse(manager_can_target(below, side))


# ---------------------------------------------------------------------------
# Misc access helpers
# ---------------------------------------------------------------------------

class CarDbAndCategoryTests(TestCase):
    def test_car_without_db_address_is_not_ready(self):
        car = mkcar(41, db='')
        self.assertFalse(access.car_db_ready(car))

    def test_missing_db_file_is_not_ready(self):
        car = mkcar(42, db='qa_definitely_missing_dir\\nope.sqlite3')
        path = access.car_db_path(car)
        self.assertTrue(str(path).endswith('qa_definitely_missing_dir/nope.sqlite3'))
        self.assertFalse(access.car_db_ready(car))

    def test_resolve_category(self):
        rc = access.resolve_category
        self.assertEqual(rc(''), '')
        self.assertEqual(rc(None), '')
        self.assertEqual(rc('Repair and Diagnosis/Engine Mechanical/Timing'), 'engine')
        self.assertEqual(rc(['Repair and Diagnosis', 'BRAKES ']), 'brakes')
        self.assertEqual(rc(['Repair', 'Wiring Diagrams > Lighting']), 'electrical')
        self.assertEqual(rc(['Unrelated', 'Stuff']), 'other')

    def test_category_label(self):
        self.assertEqual(access.category_label('engine'), 'موتور')
        self.assertEqual(access.category_label('engine', 'en'), 'Engine')
        self.assertEqual(access.category_label('nope'), 'nope')


# ---------------------------------------------------------------------------
# portal_auth gates + account state
# ---------------------------------------------------------------------------

def _ok_view(request):
    who = getattr(request, 'manager', None) or getattr(request, 'viewer', None)
    return JsonResponse({'id': who.id})


class PortalGateTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.c = mkcompany('QA-gate', plan='annual')
        self.root = mkuser(self.c, 'qa-gate-root', role='after_sales_manager',
                           can_manage_team=True)
        og.seed_graph_for_company(self.c)
        og.reassign_root(self.c, self.root)
        g = OrgGraph.objects.get(company=self.c)
        self.mid = mkuser(self.c, 'qa-gate-mid', can_view_analytics=True)
        self.leaf = mkuser(self.c, 'qa-gate-leaf', can_view_analytics=True)
        mid_node = OrgNode.objects.create(graph=g, parent=g.root_node, occupant=self.mid)
        OrgNode.objects.create(graph=g, parent=mid_node, occupant=self.leaf)
        self.seatless = mkuser(self.c, 'qa-gate-none', can_manage_team=True)

    def _call(self, deco, user=None, **extra):
        headers = bearer(user) if user else {}
        headers.update(extra)
        return deco(_ok_view)(self.rf.get('/x', **headers))

    def test_require_manager(self):
        self.assertEqual(self._call(require_manager).status_code, 401)
        self.assertEqual(self._call(require_manager, self.leaf).status_code, 403)
        r = self._call(require_manager, self.root)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(json.loads(r.content)['id'], self.root.id)
        # capability flag, not seat, governs the manager gate
        self.assertEqual(self._call(require_manager, self.seatless).status_code, 200)

    def test_require_manager_rejects_garbage_token(self):
        r = self._call(require_manager, HTTP_AUTHORIZATION='Bearer not-a-real-token')
        self.assertEqual(r.status_code, 401)

    def test_require_analytics_by_graph_position(self):
        self.assertEqual(self._call(require_analytics).status_code, 401)
        self.assertEqual(self._call(require_analytics, self.root).status_code, 200)
        self.assertEqual(self._call(require_analytics, self.mid).status_code, 200)
        # leaf and seatless are denied even with can_view_analytics / can_manage_team
        self.assertEqual(self._call(require_analytics, self.leaf).status_code, 403)
        self.assertEqual(self._call(require_analytics, self.seatless).status_code, 403)

    def test_real_analytics_endpoint_denies_leaf(self):
        self.assertEqual(Client().get('/api/team/analytics/', **bearer(self.leaf)).status_code, 403)
        self.assertEqual(Client().get('/api/team/analytics/').status_code, 401)

    def test_company_stream_visibility(self):
        self.assertTrue(user_can_view_company_stream(self.root))
        self.assertTrue(user_can_view_company_stream(self.leaf))   # analytics flag
        plain = mkuser(self.c, 'qa-gate-plain')
        self.assertFalse(user_can_view_company_stream(plain))
        self.assertFalse(user_can_view_company_stream(None))


class AccountStateTests(TestCase):
    """portal_user() denies locked/inactive/expired accounts on every gate."""
    URL = '/api/auth/ai-usage/'

    def setUp(self):
        self.c = mkcompany('QA-state', plan='annual')
        self.root = mkuser(self.c, 'qa-st-root', role='after_sales_manager',
                           can_manage_team=True)
        og.seed_graph_for_company(self.c)
        og.reassign_root(self.c, self.root)
        self.emp = mkuser(self.c, 'qa-st-emp')

    def status(self, user):
        return Client().get(self.URL, **bearer(user)).status_code

    def test_active_user_passes(self):
        self.assertEqual(self.status(self.emp), 200)

    def test_cookie_session_is_accepted(self):
        c = Client()
        c.cookies['kg_portal_token'] = AuthToken.issue(self.emp).key
        self.assertEqual(c.get(self.URL).status_code, 200)

    def test_locked_user_denied(self):
        h = bearer(self.emp)
        self.emp.locked = True
        self.emp.save()
        self.assertEqual(Client().get(self.URL, **h).status_code, 401)

    def test_inactive_user_denied(self):
        h = bearer(self.emp)
        self.emp.active = False
        self.emp.save()
        self.assertEqual(Client().get(self.URL, **h).status_code, 401)

    def test_inactive_company_denies_everyone(self):
        h1, h2 = bearer(self.emp), bearer(self.root)
        self.c.active = False
        self.c.save()
        self.assertEqual(Client().get(self.URL, **h1).status_code, 401)
        self.assertEqual(Client().get(self.URL, **h2).status_code, 401)

    def test_expired_token_denied(self):
        tok = AuthToken.issue(self.emp)
        AuthToken.objects.filter(pk=tok.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        r = Client().get(self.URL, HTTP_AUTHORIZATION=f'Bearer {tok.key}')
        self.assertEqual(r.status_code, 401)

    def test_root_expiry_governs_whole_company(self):
        # The employee has no own expiry; the root's lapsed window locks all.
        h = bearer(self.emp)
        PortalUser.objects.filter(pk=self.root.pk).update(
            access_expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(Client().get(self.URL, **h).status_code, 401)
        PortalUser.objects.filter(pk=self.root.pk).update(
            access_expires_at=timezone.now() + timedelta(days=1))
        self.assertEqual(Client().get(self.URL, **h).status_code, 200)

    def test_own_expiry_applies_when_company_has_no_root_seat(self):
        c2 = mkcompany('QA-state-nograph', plan='annual')
        u = mkuser(c2, 'qa-st-ng', access_expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.status(u), 401)
        u.access_expires_at = timezone.now() + timedelta(minutes=5)
        u.save()
        self.assertEqual(self.status(u), 200)


class CompanyRequestIsolationTests(TestCase):
    """require_manager endpoints never reach another company's requests (IDOR)."""

    def setUp(self):
        self.a = mkcompany('QA-req-A')
        self.b = mkcompany('QA-req-B')
        self.ma = mkuser(self.a, 'qa-req-ma', role='after_sales_manager', can_manage_team=True)
        self.mb = mkuser(self.b, 'qa-req-mb', role='after_sales_manager', can_manage_team=True)
        self.spec = mkuser(self.a, 'qa-req-spec')
        self.ra = CompanyRequest.objects.create(company=self.a, created_by=self.ma, subject='A1')
        self.rb = CompanyRequest.objects.create(company=self.b, created_by=self.mb, subject='B1')

    def test_list_is_company_scoped(self):
        r = Client().get('/api/company/requests/', **bearer(self.ma))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x['subject'] for x in r.json()['requests']], ['A1'])

    def test_anonymous_rejected_and_a_non_manager_sees_only_their_own(self):
        # Changed 2026-10-30: the support channel is open to every seat, so a
        # specialist gets 200 — but scoped to the tickets they filed, which is
        # none here. Anonymous is still 401.
        r = Client().get('/api/company/requests/', **bearer(self.spec))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['requests'], [])
        self.assertEqual(Client().get('/api/company/requests/').status_code, 401)

    def test_cross_company_detail_and_cancel_are_404(self):
        h = bearer(self.ma)
        self.assertEqual(Client().get(f'/api/company/requests/{self.rb.id}/', **h).status_code, 404)
        r = Client().post(f'/api/company/requests/{self.rb.id}/', data=json.dumps({'cancel': True}),
                          content_type='application/json', **h)
        self.assertEqual(r.status_code, 404)
        self.rb.refresh_from_db()
        self.assertEqual(self.rb.status, 'pending')
        self.assertEqual(Client().get(f'/api/company/requests/{self.ra.id}/', **h).status_code, 200)


# ---------------------------------------------------------------------------
# AI question allowance
# ---------------------------------------------------------------------------

class CompanyPlanTests(TestCase):
    def plan(self, **kw):
        return quota.company_plan(Company(name='x', **kw))

    def test_explicit_plan_wins(self):
        for p in ('demo', 'pass', 'monthly', 'annual'):
            self.assertEqual(self.plan(plan=f' {p} ', is_demo=(p != 'demo')), p)

    def test_inference_for_legacy_companies(self):
        self.assertEqual(self.plan(plan='bogus', is_demo=True), 'demo')
        self.assertEqual(self.plan(note='اشتراک ۲ روزه'), 'pass')
        self.assertEqual(self.plan(note='2 روزه'), 'pass')
        self.assertEqual(self.plan(note='پلن ماهانه'), 'monthly')
        self.assertEqual(self.plan(note=''), 'annual')

    def test_plan_allowances_match_pricing(self):
        self.assertEqual(quota.PLAN_AI, {'demo': (5, None), 'pass': (20, None),
                                         'monthly': (150, 30), 'annual': (200, 30)})

    def test_exhausted_message_mentions_limit_and_period(self):
        m = quota.exhausted_message({'limit': 150, 'period_days': 30})
        self.assertIn('150', m)
        self.assertIn('۳۰ روز', m)
        m = quota.exhausted_message({'limit': 5, 'period_days': None})
        self.assertIn('در این دوره', m)


class QuotaUsageTests(TestCase):
    URL = '/api/auth/ai-usage/'

    def setUp(self):
        self.c = mkcompany('QA-quota', plan='demo')
        self.u = mkuser(self.c, 'qa-q-u')
        self.peer = mkuser(self.c, 'qa-q-peer')

    def log(self, user=None, n=1, action=quota.ACTION, age_days=0):
        for _ in range(n):
            row = ActivityLog.objects.create(user=user or self.u, action=action)
            if age_days:
                ActivityLog.objects.filter(pk=row.pk).update(
                    created_at=timezone.now() - timedelta(days=age_days))

    def post(self):
        return Client().post(self.URL, data=json.dumps({'detail': 'q'}),
                             content_type='application/json', **bearer(self.u))

    def test_only_own_assistant_questions_count(self):
        self.log(n=2)
        self.log(action='view_car', n=3)
        self.log(user=self.peer, n=4)
        u = quota.usage(self.u)
        self.assertEqual((u['plan'], u['limit'], u['used'], u['remaining'], u['period_days']),
                         ('demo', 5, 2, 3, None))

    def test_demo_window_counts_old_questions(self):
        self.log(n=5, age_days=90)
        self.assertEqual(quota.usage(self.u)['remaining'], 0)

    def test_rolling_30_day_window_for_monthly(self):
        self.c.plan = 'monthly'
        self.c.save()
        self.log(n=3, age_days=31)
        self.log(n=2, age_days=29)
        u = quota.usage(fresh(self.u))
        self.assertEqual((u['limit'], u['used'], u['remaining']), (150, 2, 148))

    def test_admin_reset_restarts_count(self):
        self.log(n=4)
        self.c.quota_reset_at = timezone.now() + timedelta(seconds=1)
        self.c.save()
        self.assertEqual(quota.usage(fresh(self.u))['used'], 0)

    def test_remaining_never_negative(self):
        self.log(n=7)
        self.assertEqual(quota.usage(self.u)['remaining'], 0)

    def test_view_requires_login(self):
        self.assertEqual(Client().get(self.URL).status_code, 401)
        self.assertEqual(Client().post(self.URL).status_code, 401)

    def test_get_reports_usage_and_429_when_exhausted(self):
        self.log(n=4)
        r = Client().get(self.URL, **bearer(self.u))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['remaining'], 1)
        self.assertIn('flags', r.json())
        self.log(n=1)
        r = Client().get(self.URL, **bearer(self.u))
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()['remaining'], 0)
        self.assertIn('error', r.json())

    def test_post_consumes_exactly_up_to_limit(self):
        for i in range(5):
            r = self.post()
            self.assertEqual(r.status_code, 200, i)
            self.assertEqual(r.json()['quota']['used'], i + 1)
        r = self.post()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()['quota']['used'], 5)
        self.assertEqual(ActivityLog.objects.filter(user=self.u, action=quota.ACTION).count(), 5)

    def test_peer_usage_does_not_consume_my_allowance(self):
        self.log(user=self.peer, n=5)
        self.assertEqual(self.post().status_code, 200)

    def test_concurrent_overshoot_is_rolled_back(self):
        """Two workers pass the pre-check with one question left: the loser
        must roll its row back and get 429, never exceed the allowance."""
        self.log(n=4)
        real_create = ActivityLog.objects.create

        def racing_create(**kw):
            real_create(user=self.u, action=quota.ACTION, detail='other worker')
            return real_create(**kw)

        with mock.patch.object(ActivityLog.objects, 'create', side_effect=racing_create):
            r = self.post()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()['quota']['used'], 5)
        self.assertEqual(ActivityLog.objects.filter(user=self.u, action=quota.ACTION).count(), 5)
