"""Authorization rules that mutation testing showed were not pinned.

qa/mutation/run.sh on api/access.py (2026-10-29) left these changes alive with
the whole suite green; each test below fails on the corresponding mutant:

* manager_can_target: ``>=`` -> ``>`` on the legacy (seatless) path, i.e. a
  manager could manage a peer of the same rank;
* apply_user_access: ``override_purchase`` defaulting to True, i.e. an admin
  call without an explicit flag would bypass the company's purchase;
* apply_user_access / apply_managed_access: ``continue`` -> ``break``, i.e.
  one unknown, out-of-scope or duplicate entry silently drops every grant
  after it;
* manager_grantable_cars: ``and`` -> ``or``, i.e. a stale non-admin grant for a
  car the company no longer owns becomes delegable, and the manager's own
  narrower layers replace the company's on purchased cars.
"""
from django.test import TestCase

from .access import (
    apply_managed_access, apply_user_access, manager_can_target, manager_grantable_cars,
)
from .models import Car, Company, CompanyCarAccess, PortalUser, UserCarAccess


class World(TestCase):
    def setUp(self):
        self.co = Company.objects.create(name='Rules Co', active=True)
        self.camry = Car.objects.create(brand_name='Toyota', car_name='Camry', year=2024, db_address='a')
        self.supra = Car.objects.create(brand_name='Toyota', car_name='Supra', year=2024, db_address='b')
        self.rav4 = Car.objects.create(brand_name='Toyota', car_name='RAV4', year=2024, db_address='c')
        # The company bought Camry (manual + parts) and Supra (everything). Not RAV4.
        CompanyCarAccess.objects.create(company=self.co, car=self.camry, documents=['manual', 'parts'])
        CompanyCarAccess.objects.create(company=self.co, car=self.supra, documents=[])

    def user(self, name, role='after_sales_specialist', **kw):
        return PortalUser.objects.create(company=self.co, username=name, password_hash='x',
                                         role=role, active=True, **kw)

    def grants(self, user):
        return {g.car_id: (sorted(g.documents), g.admin_granted)
                for g in UserCarAccess.objects.filter(user=user)}


class LegacyRankTests(World):
    """Seatless users (no org-graph seat) fall back to the reports_to chain,
    where a manager must also outrank the target."""

    def test_same_rank_report_cannot_be_managed(self):
        boss = self.user('boss', can_manage_team=True)
        peer = self.user('peer', reports_to=boss)                 # same rank, reports to boss
        self.assertFalse(manager_can_target(boss, peer))

    def test_lower_rank_report_can_be_managed(self):
        boss = self.user('boss', role='after_sales_supervisor', can_manage_team=True)
        report = self.user('report', reports_to=boss)
        self.assertTrue(manager_can_target(boss, report))


class ApplyUserAccessTests(World):
    def test_admin_call_without_explicit_flag_stays_inside_the_purchase(self):
        u = self.user('u')
        apply_user_access(u, [{'car_id': self.rav4.id, 'documents': ['manual']},
                              {'car_id': self.camry.id, 'documents': ['manual', 'full_spec']}],
                          allow_admin_grants=True)
        self.assertEqual(self.grants(u), {self.camry.id: (['manual'], False)})

    def test_admin_flag_grants_beyond_the_purchase_only_for_the_admin(self):
        u = self.user('u')
        acc = [{'car_id': self.rav4.id, 'documents': ['manual', 'bogus'], 'admin_granted': True}]
        apply_user_access(u, acc)                                  # a manager's call
        self.assertEqual(self.grants(u), {})
        apply_user_access(u, acc, allow_admin_grants=True)         # the platform admin
        self.assertEqual(self.grants(u), {self.rav4.id: (['manual'], True)})

    def test_bad_entries_do_not_drop_the_good_ones_after_them(self):
        u = self.user('u')
        apply_user_access(u, [
            {'car_id': 999999, 'documents': ['manual']},           # unknown car
            {'car_id': self.rav4.id, 'documents': ['manual']},     # not purchased
            {'car_id': self.camry.id, 'documents': ['manual']},
            {'car_id': self.camry.id, 'documents': ['parts']},     # duplicate: first one wins
            {'car_id': self.supra.id, 'documents': ['parts']},
        ])
        self.assertEqual(self.grants(u), {self.camry.id: (['manual'], False),
                                          self.supra.id: (['parts'], False)})

    def test_several_admin_grants_in_one_call(self):
        u = self.user('u')
        apply_user_access(u, [{'car_id': self.rav4.id, 'admin_granted': True, 'documents': ['parts']},
                              {'car_id': self.camry.id, 'documents': ['manual']}],
                          allow_admin_grants=True)
        self.assertEqual(self.grants(u), {self.rav4.id: (['parts'], True),
                                          self.camry.id: (['manual'], False)})


class ManagerDelegationTests(World):
    def setUp(self):
        super().setUp()
        self.mgr = self.user('mgr', can_manage_team=True)
        self.emp = self.user('emp')

    def test_grantable_is_the_company_purchase_not_the_managers_own_narrower_layers(self):
        UserCarAccess.objects.create(user=self.mgr, car=self.camry, documents=['manual'])
        self.assertEqual(manager_grantable_cars(self.mgr)[self.camry.id], {'manual', 'parts'})

    def test_stale_non_admin_grant_outside_the_purchase_is_not_delegable(self):
        UserCarAccess.objects.create(user=self.mgr, car=self.rav4, documents=['manual'])
        self.assertNotIn(self.rav4.id, manager_grantable_cars(self.mgr))

    def test_admin_granted_car_beyond_the_purchase_is_delegable_as_admin_grant(self):
        UserCarAccess.objects.create(user=self.mgr, car=self.rav4, documents=['parts'], admin_granted=True)
        self.assertEqual(manager_grantable_cars(self.mgr)[self.rav4.id], {'parts'})
        apply_managed_access(self.mgr, self.emp, [{'car_id': self.rav4.id}])
        self.assertEqual(self.grants(self.emp), {self.rav4.id: (['parts'], True)})

    def test_bad_entries_do_not_drop_the_good_ones_after_them(self):
        apply_managed_access(self.mgr, self.emp, [
            {'car_id': self.rav4.id},                              # not grantable
            {'car_id': self.camry.id, 'documents': ['full_spec']}, # only layers the manager lacks
            {'car_id': self.supra.id, 'documents': ['parts']},
            {'car_id': self.supra.id, 'documents': ['manual']},    # duplicate
            {'car_id': self.camry.id},                             # whole car -> company ceiling
        ])
        self.assertEqual(self.grants(self.emp), {self.supra.id: (['parts'], False),
                                                 self.camry.id: (['manual', 'parts'], False)})

    def test_grants_outside_the_managers_purview_are_left_alone(self):
        UserCarAccess.objects.create(user=self.emp, car=self.rav4, documents=['manual'], admin_granted=True)
        apply_managed_access(self.mgr, self.emp, [{'car_id': self.camry.id, 'documents': ['parts']}])
        self.assertEqual(self.grants(self.emp), {self.rav4.id: (['manual'], True),
                                                 self.camry.id: (['parts'], False)})

    def test_non_list_payload_is_refused(self):
        for bad in ({'car_id': 1}, 'x', None):
            with self.assertRaises(ValueError):
                apply_managed_access(self.mgr, self.emp, bad)
            with self.assertRaises(ValueError):
                apply_user_access(self.emp, bad)


class OrgConsistencyTests(World):
    def test_every_broken_edge_is_repaired_even_after_valid_ones(self):
        from .access import enforce_org_consistency
        boss = self.user('boss', role='after_sales_manager')
        head = self.user('head', role='after_sales_head', reports_to=boss)       # valid edge
        self.user('free', role='after_sales_specialist')                         # no supervisor
        spec = self.user('spec', role='after_sales_specialist', reports_to=head) # valid edge
        sup = self.user('sup', role='after_sales_supervisor', reports_to=spec)   # points down: broken
        peer = self.user('peer', role='after_sales_head', reports_to=head)       # same rank: broken
        self.assertEqual(enforce_org_consistency(self.co.id), 2)
        for u in (sup, peer):
            u.refresh_from_db()
        self.assertEqual(sup.reports_to_id, head.id)      # nearest valid ancestor up the old chain
        self.assertEqual(peer.reports_to_id, boss.id)
        self.assertEqual(enforce_org_consistency(self.co.id), 0)
