"""Org-chart consistency: the team module as ONE coherent system.

Invariant under test: a reporting edge always points STRICTLY upward in rank
(supervisor.rank < member.rank). Creating, updating, re-ranking and deleting
positions must all keep the hierarchy, user assignments and permissions in
step — no silently inverted edges, no orphaned positions, no stale capability
flags after a position change.

Also regression-covers the workflow bugs reported from the field:
  * form ids arrive as *strings* — every id must be coerced, not rejected;
  * a freshly created position must be immediately assignable (new member OR
    existing member), which previously dead-ended.
"""
import json

from django.test import Client, TestCase

from .access import seed_default_org_roles
from .models import AuthToken, Car, Company, CompanyCarAccess, Event, OrgRole, PortalUser


class OrgConsistencyTests(TestCase):

    def setUp(self):
        self.c = Client()
        self.car1 = Car.objects.create(brand_name='Toyota', car_name='bZ4X',
                                       year=2023, db_address='x')
        self.company = Company.objects.create(name='Delta', ai_assistant_enabled=True)
        CompanyCarAccess.objects.create(company=self.company, car=self.car1,
                                        documents=['manual', 'parts'])
        seed_default_org_roles(self.company)
        roles = {r.rank: r for r in self.company.org_roles.all()}
        self.r_manager, self.r_head = roles[1], roles[2]
        self.r_super, self.r_spec = roles[3], roles[4]

        def mk(username, role, reports_to=None, **kw):
            u = PortalUser(company=self.company, username=username,
                           role={1: 'after_sales_manager', 2: 'after_sales_head',
                                 3: 'after_sales_supervisor'}.get(role.rank, 'after_sales_specialist'),
                           org_role=role, reports_to=reports_to, **kw)
            u.set_password('p')
            u.save()
            return u

        self.manager = mk('d_mgr', self.r_manager, can_manage_team=True, can_view_analytics=True)
        self.head = mk('d_head', self.r_head, reports_to=self.manager,
                       can_manage_team=True, can_view_analytics=True)
        self.sup = mk('d_sup', self.r_super, reports_to=self.head,
                      can_manage_team=True, can_view_analytics=True)
        self.spec = mk('d_spec', self.r_spec, reports_to=self.sup)
        self.t_mgr = AuthToken.issue(self.manager).key

    def _post(self, url, payload, token=None):
        kw = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token else {}
        return self.c.post(url, json.dumps(payload), content_type='application/json', **kw)

    def _get(self, url, token=None):
        kw = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token else {}
        return self.c.get(url, **kw)

    # -- id coercion (the "adding a user doesn't work" field bug) -------------

    def test_create_accepts_string_ids(self):
        r = self._post('/api/team/members/', {
            'display_name': 'عضو جدید', 'provision': 'credentials',
            'org_role_id': str(self.r_spec.id),
            'reports_to_id': str(self.sup.id),
        }, token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        u = PortalUser.objects.get(id=r.json()['user']['id'])
        self.assertEqual(u.org_role_id, self.r_spec.id)
        self.assertEqual(u.reports_to_id, self.sup.id)

    def test_update_accepts_string_supervisor_id(self):
        r = self._post(f'/api/team/members/{self.spec.id}/',
                       {'reports_to_id': str(self.head.id)}, token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        self.spec.refresh_from_db()
        self.assertEqual(self.spec.reports_to_id, self.head.id)

    def test_garbage_supervisor_id_rejected(self):
        r = self._post(f'/api/team/members/{self.spec.id}/',
                       {'reports_to_id': 'abc'}, token=self.t_mgr)
        self.assertEqual(r.status_code, 400)

    # -- org-chart validation on assignment ------------------------------------

    def test_create_rejects_supervisor_not_outranking(self):
        # A specialist cannot supervise another specialist.
        r = self._post('/api/team/members/', {
            'display_name': 'x', 'provision': 'credentials',
            'org_role_id': self.r_spec.id,
            'reports_to_id': self.spec.id,
        }, token=self.t_mgr)
        self.assertEqual(r.status_code, 400, r.content)

    def test_create_rejects_peer_supervisor(self):
        # A supervisor cannot supervise a peer supervisor.
        r = self._post('/api/team/members/', {
            'display_name': 'x', 'provision': 'credentials',
            'org_role_id': self.r_super.id,
            'reports_to_id': self.sup.id,
        }, token=self.t_mgr)
        self.assertEqual(r.status_code, 400, r.content)

    def test_update_rejects_lower_ranked_supervisor(self):
        r = self._post(f'/api/team/members/{self.head.id}/',
                       {'reports_to_id': self.spec.id}, token=self.t_mgr)
        self.assertEqual(r.status_code, 400, r.content)

    # -- permissions follow the hierarchy ---------------------------------------

    def test_quick_role_change_reseeds_capabilities(self):
        # Org-chart quick change sends ONLY the new position; capability flags
        # must follow the new position's defaults (a demoted head must not keep
        # team management).
        r = self._post(f'/api/team/members/{self.head.id}/',
                       {'org_role_id': self.r_spec.id}, token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['adjustments']['caps_reseeded'])
        self.head.refresh_from_db()
        self.assertFalse(self.head.can_manage_team)
        self.assertFalse(self.head.can_view_analytics)

    def test_role_change_keeps_explicit_capabilities(self):
        r = self._post(f'/api/team/members/{self.head.id}/',
                       {'org_role_id': self.r_spec.id, 'can_view_analytics': True},
                       token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()['adjustments']['caps_reseeded'])
        self.head.refresh_from_db()
        self.assertTrue(self.head.can_view_analytics)

    # -- reporting lines self-repair after rank changes -------------------------

    def test_demotion_reparents_orphaned_reports(self):
        # sup (supervising spec) is demoted to specialist: spec may no longer
        # report to a peer — they move up to the nearest valid ancestor (head).
        r = self._post(f'/api/team/members/{self.sup.id}/',
                       {'org_role_id': self.r_spec.id}, token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreaterEqual(r.json()['adjustments']['reparented'], 1)
        self.spec.refresh_from_db()
        self.assertEqual(self.spec.reports_to_id, self.head.id)

    def test_promotion_fixes_own_supervisor(self):
        # spec (reporting to sup, rank 3) promoted to head (rank 2): their old
        # supervisor no longer outranks them -> re-parented to the manager.
        r = self._post(f'/api/team/members/{self.spec.id}/',
                       {'org_role_id': self.r_head.id}, token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        self.spec.refresh_from_db()
        self.assertEqual(self.spec.reports_to_id, self.manager.id)

    def test_reorder_repairs_inverted_edges(self):
        # Push the specialist position ABOVE head/supervisor: existing edges
        # (spec under sup under head) invert and must be repaired upward.
        order = [self.r_spec.id, self.r_super.id, self.r_head.id]
        r = self._post('/api/team/roles/reorder/', {'order': order}, token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreaterEqual(r.json()['reparented'], 1)
        for u in (self.head, self.sup, self.spec):
            u.refresh_from_db()
            if u.reports_to_id:
                parent = PortalUser.objects.select_related('org_role').get(id=u.reports_to_id)
                self.assertLess(parent.org_role.rank, u.org_role.rank,
                                f'{u.username} reports downward/sideways after reorder')

    def test_delete_role_reassign_repairs_edges(self):
        # New position below specialist; a member of it reports to spec's chain.
        r = self._post('/api/team/roles/', {'name': 'کارآموز'}, token=self.t_mgr)
        role_id = r.json()['role']['id']
        r = self._post('/api/team/members/', {
            'display_name': 'کارآموز یک', 'provision': 'credentials',
            'org_role_id': role_id, 'reports_to_id': self.sup.id,
        }, token=self.t_mgr)
        uid = r.json()['user']['id']
        # Delete the new position, reassigning its members to supervisor rank:
        # they may no longer report to a peer supervisor.
        r = self._post(f'/api/team/roles/{role_id}/',
                       {'delete': True, 'reassign_to': self.r_super.id}, token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        u = PortalUser.objects.get(id=uid)
        self.assertEqual(u.org_role_id, self.r_super.id)
        self.assertEqual(u.reports_to_id, self.head.id)

    # -- a new position is immediately usable (field regression) ----------------

    def test_new_position_full_assignment_flow(self):
        # 1. create the position (as the field report: a technical-specialist).
        r = self._post('/api/team/roles/', {'name': 'کارشناس فنی'}, token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        role_id = r.json()['role']['id']
        # 2. hire a NEW member straight into it (string ids, like the form sends).
        r = self._post('/api/team/members/', {
            'display_name': 'فنی جدید', 'provision': 'credentials',
            'org_role_id': str(role_id), 'reports_to_id': str(self.sup.id),
        }, token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        new_id = r.json()['user']['id']
        # 3. move an EXISTING member onto it.
        r = self._post(f'/api/team/members/{self.spec.id}/',
                       {'org_role_id': str(role_id)}, token=self.t_mgr)
        self.assertEqual(r.status_code, 200, r.content)
        # 4. the org endpoint reflects both, and the position's member count.
        r = self._get('/api/team/org/', token=self.t_mgr)
        data = r.json()
        holders = {m['id'] for m in data['members'] if m['role_id'] == role_id}
        self.assertEqual(holders, {new_id, self.spec.id})
        counts = {x['id']: x['members_count'] for x in data['roles']}
        self.assertEqual(counts[role_id], 2)

    # -- the UI never has to say an anonymous "you" -----------------------------

    def test_meta_and_org_identify_the_viewer(self):
        r = self._get('/api/team/members/', token=self.t_mgr)
        me = r.json()['meta']['me']
        self.assertEqual(me['id'], self.manager.id)
        self.assertEqual(me['name'], 'd_mgr')
        self.assertIn('مدیر', me['role_label'])
        r = self._get('/api/team/org/', token=self.t_mgr)
        me = r.json()['me']
        self.assertEqual(me['name'], 'd_mgr')
        self.assertIn('مدیر', me['role_label'])

    # -- live sync events --------------------------------------------------------

    def test_team_changes_emit_company_events(self):
        self._post(f'/api/team/members/{self.spec.id}/',
                   {'display_name': 'اسم نو'}, token=self.t_mgr)
        self._post('/api/team/roles/', {'name': 'نقش نو'}, token=self.t_mgr)
        types = set(Event.objects.filter(company_id=self.company.id)
                    .values_list('type', flat=True))
        self.assertIn('team.member.updated', types)
        self.assertIn('team.role.created', types)
