"""QA audit: org-graph API authorization (api/orggraph_api.py).

Pins: only the root seat may mutate; scoped read-only views for non-root
seats (subtree + father, never siblings or the full roster); leaf/seatless
denial; strict cross-company isolation (IDOR) on every node endpoint; seat and
user caps at their exact boundary; permission clamping to the purchase; the
platform-admin break-glass root reassignment.
"""
import json
import unittest
from unittest import mock

from django.test import Client, TestCase

from . import orggraph as og
from .access import VALID_PACKAGES, user_car_documents
from .models import (
    AuthToken, Car, Company, CompanyCarAccess, NodePermission, OrgGraph, OrgNode,
    PortalUser, UserCarAccess,
)


def mkcar(i):
    return Car.objects.create(brand_name='QG', car_name=f'G{i}', year=2010 + i, db_address='')


def mkuser(company, username, **kw):
    kw.setdefault('role', 'after_sales_specialist')
    kw.setdefault('active', True)
    return PortalUser.objects.create(company=company, username=username,
                                     password_hash='x', **kw)


def fresh(u):
    return PortalUser.objects.get(pk=u.pk)


def seat(graph, parent, occupant=None, label=''):
    n = OrgNode.objects.create(graph=graph, parent=parent, occupant=occupant, label=label)
    NodePermission.objects.create(node=n)
    return n


def build_company(name, prefix, seats_count=None):
    c = Company.objects.create(name=name, active=True, seats_count=seats_count,
                               ai_assistant_enabled=True, plan='annual')
    root = mkuser(c, f'{prefix}-root', role='after_sales_manager', can_manage_team=True)
    og.seed_graph_for_company(c)
    og.reassign_root(c, root)
    g = OrgGraph.objects.get(company=c)
    OrgNode.objects.filter(graph=g, is_root=False).delete()
    return c, root, g


class _Base(TestCase):
    def setUp(self):
        self.car = mkcar(1)
        self.car_b = mkcar(2)         # bought by company B only
        self.a, self.root, self.g = build_company('QA-OG-A', 'qa-oga')
        CompanyCarAccess.objects.create(company=self.a, car=self.car, documents=['manual', 'parts'])
        rn = self.g.root_node
        # root -> mid -> leaf ; root -> sibling
        self.mid = mkuser(self.a, 'qa-oga-mid', can_manage_team=True)
        self.leaf = mkuser(self.a, 'qa-oga-leaf')
        self.sib = mkuser(self.a, 'qa-oga-sib')
        self.unseated = mkuser(self.a, 'qa-oga-free')
        self.n_mid = seat(self.g, rn, self.mid, 'mid')
        self.n_leaf = seat(self.g, self.n_mid, self.leaf, 'leaf')
        self.n_sib = seat(self.g, rn, self.sib, 'sib')
        # company B
        self.b, self.root_b, self.g_b = build_company('QA-OG-B', 'qa-ogb')
        CompanyCarAccess.objects.create(company=self.b, car=self.car_b, documents=[])
        self.emp_b = mkuser(self.b, 'qa-ogb-emp', phone='09120000101')
        self.n_b = seat(self.g_b, self.g_b.root_node, self.emp_b, 'b-seat')

    def h(self, user):
        return {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(user).key}'}

    def req(self, method, url, user, body=None):
        c = Client()
        fn = getattr(c, method)
        kw = self.h(user) if user else {}
        if body is not None:
            return fn(url, data=json.dumps(body), content_type='application/json', **kw)
        return fn(url, **kw)


class GraphReadScopeTests(_Base):
    def test_anonymous_rejected(self):
        self.assertEqual(self.req('get', '/api/org/graph/', None).status_code, 401)

    def test_root_sees_whole_graph_and_can_edit(self):
        d = self.req('get', '/api/org/graph/', self.root).json()
        self.assertTrue(d['can_edit'])
        self.assertEqual({n['id'] for n in d['nodes']},
                         {self.g.root_node.id, self.n_mid.id, self.n_leaf.id, self.n_sib.id})
        roster = {e['id'] for e in d['employees']}
        self.assertEqual(roster, {self.root.id, self.mid.id, self.leaf.id, self.sib.id,
                                  self.unseated.id})
        # nothing from company B leaks
        self.assertNotIn(self.emp_b.id, roster)
        self.assertNotIn(self.n_b.id, {n['id'] for n in d['nodes']})
        self.assertEqual(d['seats_used'], 3)
        self.assertEqual({c['car_id'] for c in d['company_cars']}, {self.car.id})
        self.assertEqual({p['id'] for p in d['packages']}, set(VALID_PACKAGES))

    def test_mid_seat_sees_subtree_plus_father_only(self):
        d = self.req('get', '/api/org/graph/', self.mid).json()
        self.assertFalse(d['can_edit'])
        self.assertEqual(d['my_node_id'], self.n_mid.id)
        self.assertEqual({n['id'] for n in d['nodes']},
                         {self.g.root_node.id, self.n_mid.id, self.n_leaf.id})
        # the picker is limited to visible occupants: no sibling, no unseated staff
        self.assertEqual({e['id'] for e in d['employees']},
                         {self.root.id, self.mid.id, self.leaf.id})

    def test_leaf_and_seatless_users_denied(self):
        self.assertEqual(self.req('get', '/api/org/graph/', self.leaf).status_code, 403)
        self.assertEqual(self.req('get', '/api/org/graph/', self.sib).status_code, 403)
        self.assertEqual(self.req('get', '/api/org/graph/', self.unseated).status_code, 403)

    def test_graph_is_seeded_on_first_read(self):
        c = Company.objects.create(name='QA-OG-new', active=True)
        u = mkuser(c, 'qa-ognew', can_manage_team=True)
        self.assertFalse(OrgGraph.objects.filter(company=c).exists())
        r = self.req('get', '/api/org/graph/', u)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['can_edit'])
        self.assertTrue(og.is_graph_root(fresh(u)))


class RootOnlyMutationTests(_Base):
    def test_every_mutator_rejects_non_root(self):
        nid = self.n_leaf.id
        calls = [('post', '/api/org/nodes/', {'label': 'x'}),
                 ('patch', f'/api/org/nodes/{nid}/', {'label': 'hacked'}),
                 ('delete', f'/api/org/nodes/{nid}/', None),
                 ('post', f'/api/org/nodes/{nid}/permission/', {'ai_eligible': True}),
                 ('post', f'/api/org/nodes/{nid}/create-user/', {'display_name': 'x', 'phone': '0912'})]
        for user in (self.mid, self.leaf, self.unseated):
            for method, url, body in calls:
                r = self.req(method, url, user, body)
                self.assertEqual(r.status_code, 403, (user.username, method, url))
        for method, url, body in calls:
            self.assertEqual(self.req(method, url, None, body).status_code, 401)
        self.n_leaf.refresh_from_db()
        self.assertEqual(self.n_leaf.label, 'leaf')
        self.assertEqual(OrgNode.objects.filter(graph=self.g).count(), 4)

    def test_wrong_methods_are_405(self):
        nid = self.n_leaf.id
        self.assertEqual(self.req('get', '/api/org/nodes/', self.root).status_code, 405)
        self.assertEqual(self.req('put', f'/api/org/nodes/{nid}/', self.root, {}).status_code, 405)
        self.assertEqual(self.req('get', f'/api/org/nodes/{nid}/permission/', self.root).status_code, 405)
        self.assertEqual(self.req('get', f'/api/org/nodes/{nid}/create-user/', self.root).status_code, 405)


class CrossCompanyIdorTests(_Base):
    """Root of company A must never touch company B's graph."""

    def test_patch_delete_permission_create_on_foreign_node_are_404(self):
        nb = self.n_b.id
        self.assertEqual(self.req('patch', f'/api/org/nodes/{nb}/', self.root,
                                  {'label': 'pwned', 'occupant_id': None}).status_code, 404)
        self.assertEqual(self.req('delete', f'/api/org/nodes/{nb}/', self.root).status_code, 404)
        self.assertEqual(self.req('post', f'/api/org/nodes/{nb}/permission/', self.root,
                                  {'ai_eligible': True}).status_code, 404)
        self.assertEqual(self.req('post', f'/api/org/nodes/{nb}/create-user/', self.root,
                                  {'display_name': 'x', 'phone': '09129990000'}).status_code, 404)
        n = OrgNode.objects.get(pk=nb)
        self.assertEqual((n.label, n.occupant_id), ('b-seat', self.emp_b.id))
        self.assertEqual(PortalUser.objects.filter(company=self.b).count(), 2)

    def test_cannot_seat_foreign_employee(self):
        r = self.req('patch', f'/api/org/nodes/{self.n_sib.id}/', self.root,
                     {'occupant_id': self.emp_b.id})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(OrgNode.objects.filter(occupant=self.emp_b, graph=self.g).first())
        self.assertEqual(OrgNode.objects.get(pk=self.n_b.id).occupant_id, self.emp_b.id)

    def test_cannot_attach_under_foreign_parent(self):
        r = self.req('post', '/api/org/nodes/', self.root, {'parent_id': self.n_b.id})
        self.assertEqual(r.status_code, 400)
        r = self.req('patch', f'/api/org/nodes/{self.n_sib.id}/', self.root,
                     {'parent_id': self.g_b.root_node.id})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(OrgNode.objects.filter(graph=self.g_b).count(), 2)

    def test_cannot_grant_car_only_other_company_bought(self):
        r = self.req('post', f'/api/org/nodes/{self.n_leaf.id}/permission/', self.root,
                     {'car_access': [{'car_id': self.car_b.id, 'documents': ['manual']},
                                     {'car_id': self.car.id, 'documents': ['manual', 'full_spec']},
                                     {'car_id': 'abc'}, 'junk']})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['permission']['car_access'],
                         [{'car_id': self.car.id, 'documents': ['manual']}])
        leaf = fresh(self.leaf)
        self.assertIsNone(user_car_documents(leaf, self.car_b))
        self.assertEqual(user_car_documents(leaf, self.car), {'manual'})


class NodeEditTests(_Base):
    def test_create_seat_and_unknown_parent(self):
        r = self.req('post', '/api/org/nodes/', self.root,
                     {'label': '  New  ', 'parent_id': self.n_mid.id, 'x': 5, 'y': 7})
        self.assertEqual(r.status_code, 201)
        d = r.json()
        self.assertEqual((d['label'], d['parent_id'], d['x'], d['y']), ('New', self.n_mid.id, 5.0, 7.0))
        self.assertTrue(NodePermission.objects.filter(node_id=d['id']).exists())
        self.assertEqual(self.req('post', '/api/org/nodes/', self.root,
                                  {'parent_id': 987654}).status_code, 400)

    def test_patch_unknown_node_404_and_root_undeletable(self):
        self.assertEqual(self.req('patch', '/api/org/nodes/987654/', self.root, {}).status_code, 404)
        r = self.req('delete', f'/api/org/nodes/{self.g.root_node.id}/', self.root)
        self.assertEqual(r.status_code, 400)
        self.assertTrue(OrgNode.objects.filter(pk=self.g.root_node.id).exists())

    def test_patch_geometry_and_label(self):
        r = self.req('patch', f'/api/org/nodes/{self.n_sib.id}/', self.root,
                     {'label': 'x' * 300, 'x': 12.5, 'y': None})
        self.assertEqual(r.status_code, 200)
        n = OrgNode.objects.get(pk=self.n_sib.id)
        self.assertEqual((len(n.label), n.canvas_x, n.canvas_y), (120, 12.5, 0.0))

    def test_reparent_rejects_cycle_and_unknown_parent(self):
        r = self.req('patch', f'/api/org/nodes/{self.n_mid.id}/', self.root,
                     {'parent_id': self.n_leaf.id})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.req('patch', f'/api/org/nodes/{self.n_mid.id}/', self.root,
                                  {'parent_id': 987654}).status_code, 400)
        self.assertEqual(OrgNode.objects.get(pk=self.n_mid.id).parent_id, self.g.root_node.id)

    def test_reparent_moves_reporting_line(self):
        r = self.req('patch', f'/api/org/nodes/{self.n_sib.id}/', self.root,
                     {'parent_id': self.n_mid.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(fresh(self.sib).reports_to_id, self.mid.id)
        self.assertIn(self.sib.id, og.graph_subtree_user_ids(fresh(self.mid)))

    def test_detach_to_no_parent(self):
        r = self.req('patch', f'/api/org/nodes/{self.n_sib.id}/', self.root, {'parent_id': None})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(OrgNode.objects.get(pk=self.n_sib.id).parent_id)

    def test_root_seat_occupant_is_pinned(self):
        root_node = self.g.root_node
        r = self.req('patch', f'/api/org/nodes/{root_node.id}/', self.root,
                     {'occupant_id': self.mid.id})
        self.assertEqual(r.status_code, 400)
        r = self.req('patch', f'/api/org/nodes/{self.n_sib.id}/', self.root,
                     {'occupant_id': self.root.id})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(OrgGraph.objects.get(pk=self.g.pk).root_node.occupant_id, self.root.id)

    def test_seat_inactive_employee_rejected(self):
        self.unseated.active = False
        self.unseated.save()
        r = self.req('patch', f'/api/org/nodes/{self.n_sib.id}/', self.root,
                     {'occupant_id': self.unseated.id})
        self.assertEqual(r.status_code, 400)

    def test_assign_and_vacate_occupant(self):
        r = self.req('patch', f'/api/org/nodes/{self.n_sib.id}/', self.root,
                     {'occupant_id': self.unseated.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['occupant']['id'], self.unseated.id)
        self.assertEqual(fresh(self.unseated).reports_to_id, self.root.id)
        r = self.req('patch', f'/api/org/nodes/{self.n_sib.id}/', self.root, {'occupant_id': None})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(OrgNode.objects.get(pk=self.n_sib.id).occupant_id)

    def test_otp_toggle_requires_phone(self):
        r = self.req('patch', f'/api/org/nodes/{self.n_leaf.id}/', self.root,
                     {'occupant_otp_enabled': True})
        self.assertEqual(r.status_code, 400)
        r = self.req('patch', f'/api/org/nodes/{self.n_leaf.id}/', self.root,
                     {'occupant_otp_enabled': False})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(fresh(self.leaf).otp_enabled)
        PortalUser.objects.filter(pk=self.leaf.pk).update(phone='09120000202')
        r = self.req('patch', f'/api/org/nodes/{self.n_leaf.id}/', self.root,
                     {'occupant_otp_enabled': True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(fresh(self.leaf).otp_enabled)

    def test_delete_reparents_children_to_grandparent_and_frees_occupant(self):
        r = self.req('delete', f'/api/org/nodes/{self.n_mid.id}/', self.root)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(OrgNode.objects.get(pk=self.n_leaf.id).parent_id, self.g.root_node.id)
        self.assertTrue(PortalUser.objects.filter(pk=self.mid.pk, active=True).exists())
        self.assertEqual(fresh(self.leaf).reports_to_id, self.root.id)

    def test_permission_ai_flag_syncs_to_user(self):
        r = self.req('post', f'/api/org/nodes/{self.n_leaf.id}/permission/', self.root,
                     {'ai_eligible': True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(fresh(self.leaf).ai_assistant_enabled)
        self.req('post', f'/api/org/nodes/{self.n_leaf.id}/permission/', self.root,
                 {'ai_eligible': False})
        self.assertFalse(fresh(self.leaf).ai_assistant_enabled)
        self.assertEqual(self.req('post', '/api/org/nodes/987654/permission/', self.root,
                                  {}).status_code, 404)


class AdminExceptionTests(_Base):
    """A platform-admin grant beyond the purchase may be kept by a /team save,
    but never widened."""

    def setUp(self):
        super().setUp()
        self.extra = mkcar(9)
        UserCarAccess.objects.create(user=self.leaf, car=self.extra, documents=['parts'],
                                     admin_granted=True)

    def test_admin_exception_preserved_but_clamped(self):
        r = self.req('post', f'/api/org/nodes/{self.n_leaf.id}/permission/', self.root,
                     {'car_access': [{'car_id': self.extra.id,
                                      'documents': ['parts', 'manual']}]})
        self.assertEqual(r.status_code, 200)
        row = UserCarAccess.objects.get(user=self.leaf, car=self.extra)
        self.assertTrue(row.admin_granted)
        self.assertEqual(user_car_documents(fresh(self.leaf), self.extra), {'parts'})

    # Regression (fixed in this change): orggraph_api.py:426 clamps an admin exception's layers to [] when only non-held layers are posted; orggraph.py:72 stores admin_granted documents=[] which access.effective_documents reads as ALL packages -> root widens a platform-admin exception
    def test_admin_exception_cannot_be_widened_by_posting_unheld_layer(self):
        r = self.req('post', f'/api/org/nodes/{self.n_leaf.id}/permission/', self.root,
                     {'car_access': [{'car_id': self.extra.id, 'documents': ['manual']}]})
        self.assertEqual(r.status_code, 200)
        docs = user_car_documents(fresh(self.leaf), self.extra) or set()
        self.assertTrue(docs <= {'parts'}, docs)


class SeatCapTests(TestCase):
    def setUp(self):
        self.c, self.root, self.g = build_company('QA-OG-cap', 'qa-ogc', seats_count=3)

    def h(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(self.root).key}'}

    def post(self, url, body):
        return Client().post(url, data=json.dumps(body), content_type='application/json',
                             **self.h())

    def test_empty_seat_cap_boundary(self):
        # cap counts the root: cap=3 -> exactly 2 non-root seats
        self.assertEqual(self.post('/api/org/nodes/', {}).status_code, 201)
        self.assertEqual(self.post('/api/org/nodes/', {}).status_code, 201)
        r = self.post('/api/org/nodes/', {})
        self.assertEqual(r.status_code, 403)
        self.assertEqual((r.json()['code'], r.json()['cap'], r.json()['used']), ('seat_cap', 3, 3))
        self.assertEqual(OrgNode.objects.filter(graph=self.g, is_root=False).count(), 2)

    def test_create_user_validation_and_user_cap_boundary(self):
        n1 = seat(self.g, self.g.root_node)
        n2 = seat(self.g, self.g.root_node)
        n3 = seat(self.g, self.g.root_node)
        url = f'/api/org/nodes/{n1.id}/create-user/'
        self.assertEqual(self.post(url, {'phone': '09121110001'}).status_code, 400)  # no name
        self.assertEqual(self.post(url, {'display_name': 'A'}).status_code, 400)     # no phone
        other = Company.objects.create(name='QA-OG-cap-other', active=True)
        mkuser(other, 'qa-ogc-taken', phone='09121110009')
        r = self.post(url, {'display_name': 'A', 'phone': '+989121110009'})  # same number
        self.assertEqual(r.status_code, 400)
        r = self.post(url, {'display_name': 'A', 'phone': '09121110002',
                            'username': 'qa-ogc-taken'})                       # username clash
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(OrgNode.objects.get(pk=n1.id).occupant_id)
        with mock.patch('api.notify.send_welcome_credentials', return_value=False):
            r1 = self.post(url, {'display_name': 'A', 'phone': '09121110003'})
            r2 = self.post(f'/api/org/nodes/{n2.id}/create-user/',
                           {'display_name': 'B', 'phone': '09121110004', 'password': 'Given-pw-1'})
            r3 = self.post(f'/api/org/nodes/{n3.id}/create-user/',
                           {'display_name': 'C', 'phone': '09121110005'})
        self.assertEqual((r1.status_code, r2.status_code), (201, 201))
        self.assertFalse(r1.json()['sms_sent'])
        self.assertEqual(r2.json()['credentials']['password'], 'Given-pw-1')
        # root + 2 created == cap 3: the next one is refused
        self.assertEqual(r3.status_code, 403)
        self.assertEqual(r3.json()['code'], 'seat_cap')
        self.assertEqual(self.c.users.filter(active=True).count(), 3)
        self.assertEqual(self.post(url, {'display_name': 'D', 'phone': '09121110006'}).status_code, 400)
        self.assertEqual(self.post('/api/org/nodes/987654/create-user/',
                                   {'display_name': 'D', 'phone': '09121110007'}).status_code, 404)


class BreakGlassRootTests(_Base):
    URL = '/api/admin/org/reassign-root/'

    def admin(self, body, method='post'):
        with mock.patch.dict('os.environ', {'KG_ADMIN_TOKEN': 'qa-bg-secret'}):
            if method == 'get':
                return Client().get(self.URL, HTTP_X_ADMIN_TOKEN='qa-bg-secret')
            return Client().post(self.URL, data=json.dumps(body), content_type='application/json',
                                 HTTP_X_ADMIN_TOKEN='qa-bg-secret')

    def test_requires_platform_admin(self):
        # a company root's own portal session is not an admin credential
        r = self.req('post', self.URL, self.root, {'company_id': self.a.id,
                                                   'occupant_id': self.mid.id})
        self.assertEqual(r.status_code, 401)
        self.assertTrue(og.is_graph_root(fresh(self.root)))

    def test_validation(self):
        self.assertEqual(self.admin({}, method='get').status_code, 405)
        self.assertEqual(self.admin({'company_id': 987654}).status_code, 404)
        self.assertEqual(self.admin({}).status_code, 404)
        self.assertEqual(self.admin({'company_id': self.a.id}).status_code, 400)
        # a user of ANOTHER company can never become A's root
        self.assertEqual(self.admin({'company_id': self.a.id,
                                     'occupant_id': self.emp_b.id}).status_code, 404)
        self.unseated.active = False
        self.unseated.save()
        self.assertEqual(self.admin({'company_id': self.a.id,
                                     'username': self.unseated.username}).status_code, 404)
        self.assertTrue(og.is_graph_root(fresh(self.root)))

    def test_reassign_by_id_and_username(self):
        r = self.admin({'company_id': self.a.id, 'occupant_id': self.mid.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['occupant']['id'], self.mid.id)
        self.assertTrue(og.is_graph_root(fresh(self.mid)))
        self.assertFalse(og.is_graph_root(fresh(self.root)))
        r = self.admin({'company_id': self.a.id, 'username': self.root.username})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(og.is_graph_root(fresh(self.root)))
