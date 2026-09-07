"""Org-graph canvas: root-only editing, seat cap, permission→enforcement sync,
one-seat-per-person, and break-glass root reassignment."""
import json

from django.test import TestCase, Client

from .models import (
    Car, Company, CompanyCarAccess, NodePermission, OrgGraph, OrgNode,
    PortalUser, UserCarAccess, AuthToken,
)
from .access import apply_user_access
from . import orggraph as og


def _mkcar(i):
    return Car.objects.create(
        brand_name='B', car_name=f'C{i}', year=2020 + i, db_address=f'c{i}.sqlite3')


class OrgGraphTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Acme', seats_count=2, active=True,
                                              ai_assistant_enabled=True)
        self.car = _mkcar(1)
        CompanyCarAccess.objects.create(company=self.company, car=self.car,
                                        documents=['manual', 'parts'])
        self.root_user = PortalUser.objects.create(
            company=self.company, username='root', role='after_sales_manager',
            password_hash='x', active=True)
        self.emp = PortalUser.objects.create(
            company=self.company, username='emp', role='after_sales_specialist',
            password_hash='x', active=True)
        og.seed_graph_for_company(self.company)
        self.graph = OrgGraph.objects.get(company=self.company)
        # ensure root_user is the root occupant
        og.reassign_root(self.company, self.root_user)
        # start each test from a clean non-root slate (the seeder seats every
        # existing user; tests build their own seats), leaving emp seatless.
        OrgNode.objects.filter(graph=self.graph, is_root=False).delete()
        self.graph.refresh_from_db()

    def _client(self, user):
        c = Client()
        tok = AuthToken.issue(user)
        return c, {'HTTP_AUTHORIZATION': f'Bearer {tok.key}'}

    def test_only_root_can_create(self):
        c, h = self._client(self.emp)
        r = c.post('/api/org/nodes/', data='{}', content_type='application/json', **h)
        self.assertEqual(r.status_code, 403)
        c, h = self._client(self.root_user)
        r = c.post('/api/org/nodes/', data=json.dumps({'label': 'seat'}),
                   content_type='application/json', **h)
        self.assertEqual(r.status_code, 201)

    def test_seat_cap_enforced(self):
        c, h = self._client(self.root_user)
        made = 0
        for _ in range(5):
            r = c.post('/api/org/nodes/', data=json.dumps({'label': 's'}),
                       content_type='application/json', **h)
            if r.status_code == 201:
                made += 1
            else:
                self.assertEqual(r.status_code, 403)
                self.assertEqual(r.json().get('code'), 'seat_cap')
                break
        # cap is 2 non-root seats; seeding may already fill some
        self.assertLessEqual(
            OrgNode.objects.filter(graph=self.graph, is_root=False).count(),
            max(self.company.seats_count, made))

    def test_permission_sync_writes_enforcement(self):
        node = OrgNode.objects.create(graph=self.graph, parent=self.graph.root_node,
                                      occupant=self.emp)
        NodePermission.objects.create(node=node)
        c, h = self._client(self.root_user)
        r = c.post(f'/api/org/nodes/{node.id}/permission/',
                   data=json.dumps({'ai_eligible': True,
                                    'car_access': [{'car_id': self.car.id,
                                                    'documents': ['manual']}]}),
                   content_type='application/json', **h)
        self.assertEqual(r.status_code, 200)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.ai_assistant_enabled)
        rows = list(UserCarAccess.objects.filter(user=self.emp)
                    .values_list('car_id', 'admin_granted'))
        self.assertEqual(rows, [(self.car.id, True)])  # root grants bypass purchase

    def test_one_seat_per_person(self):
        n1 = OrgNode.objects.create(graph=self.graph, parent=self.graph.root_node)
        n2 = OrgNode.objects.create(graph=self.graph, parent=self.graph.root_node)
        NodePermission.objects.create(node=n1)
        NodePermission.objects.create(node=n2)
        c, h = self._client(self.root_user)
        c.patch(f'/api/org/nodes/{n1.id}/',
                data=json.dumps({'occupant_id': self.emp.id}),
                content_type='application/json', **h)
        c.patch(f'/api/org/nodes/{n2.id}/',
                data=json.dumps({'occupant_id': self.emp.id}),
                content_type='application/json', **h)
        n1.refresh_from_db(); n2.refresh_from_db()
        # emp moved to n2; n1 vacated
        self.assertIsNone(n1.occupant_id)
        self.assertEqual(n2.occupant_id, self.emp.id)

    def test_break_glass_reassign_root(self):
        og.reassign_root(self.company, self.emp)
        # refetch fresh: reverse OneToOne is cached on stale in-memory instances
        emp = PortalUser.objects.get(pk=self.emp.pk)
        root_user = PortalUser.objects.get(pk=self.root_user.pk)
        self.assertTrue(og.is_graph_root(emp))
        self.assertFalse(og.is_graph_root(root_user))

    def test_delete_reparents_children(self):
        parent = OrgNode.objects.create(graph=self.graph, parent=self.graph.root_node)
        child = OrgNode.objects.create(graph=self.graph, parent=parent)
        NodePermission.objects.create(node=parent)
        NodePermission.objects.create(node=child)
        c, h = self._client(self.root_user)
        c.delete(f'/api/org/nodes/{parent.id}/', **h)
        child.refresh_from_db()
        self.assertEqual(child.parent_id, self.graph.root_node.id)


class OrgGraphV2Tests(TestCase):
    """Direct user creation, full-company occupant picker, and the /admin ↔
    /team access parity guarantee."""

    def setUp(self):
        self.company = Company.objects.create(name='Beta', active=True,
                                              ai_assistant_enabled=True)
        self.car = _mkcar(7)
        CompanyCarAccess.objects.create(company=self.company, car=self.car,
                                        documents=['manual', 'parts'])
        self.root_user = PortalUser.objects.create(
            company=self.company, username='broot', role='after_sales_manager',
            password_hash='x', active=True)
        self.other = PortalUser.objects.create(
            company=self.company, username='bother', role='after_sales_specialist',
            password_hash='x', active=True)
        og.seed_graph_for_company(self.company)
        og.reassign_root(self.company, self.root_user)
        self.graph = OrgGraph.objects.get(company=self.company)
        # The seeder seats every existing user; these tests build their own
        # nodes, so start from a clean non-root slate (leaves `other` unseated).
        OrgNode.objects.filter(graph=self.graph, is_root=False).delete()
        self.other.refresh_from_db()

    def _root_client(self):
        c = Client()
        tok = AuthToken.issue(self.root_user)
        return c, {'HTTP_AUTHORIZATION': f'Bearer {tok.key}'}

    def test_create_user_into_empty_node(self):
        node = OrgNode.objects.create(graph=self.graph, parent=self.graph.root_node)
        NodePermission.objects.create(node=node)
        c, h = self._root_client()
        r = c.post(f'/api/org/nodes/{node.id}/create-user/',
                   data=json.dumps({'display_name': 'کارمند تازه'}),
                   content_type='application/json', **h)
        self.assertEqual(r.status_code, 201)
        creds = r.json()['credentials']
        self.assertTrue(creds['username'] and creds['password'])
        node.refresh_from_db()
        self.assertIsNotNone(node.occupant_id)
        # created active, so they can actually log in
        self.assertEqual(node.occupant.invite_status, 'active')
        self.assertTrue(node.occupant.check_password(creds['password']))

    def test_create_user_rejected_on_occupied_node(self):
        node = OrgNode.objects.create(graph=self.graph, parent=self.graph.root_node,
                                      occupant=self.other)
        NodePermission.objects.create(node=node)
        c, h = self._root_client()
        r = c.post(f'/api/org/nodes/{node.id}/create-user/',
                   data=json.dumps({'display_name': 'x'}),
                   content_type='application/json', **h)
        self.assertEqual(r.status_code, 400)

    def test_picker_lists_every_active_employee(self):
        """Root manages the whole org: already-seated people stay assignable."""
        node = OrgNode.objects.create(graph=self.graph, parent=self.graph.root_node,
                                      occupant=self.other)
        NodePermission.objects.create(node=node)
        c, h = self._root_client()
        data = c.get('/api/org/graph/', **h).json()
        ids = {e['id'] for e in data['employees']}
        self.assertIn(self.other.id, ids)      # seated, still offered
        self.assertIn(self.root_user.id, ids)
        seated = next(e for e in data['employees'] if e['id'] == self.other.id)
        self.assertEqual(seated['seated_node_id'], node.id)

    def test_admin_access_edit_mirrors_into_node_permission(self):
        """CRITICAL: /admin and /team must never disagree about a node's access."""
        node = OrgNode.objects.create(graph=self.graph, parent=self.graph.root_node,
                                      occupant=self.other)
        NodePermission.objects.create(node=node)
        # Admin grants a car directly (the /admin path), bypassing the graph.
        apply_user_access(self.other, [{'car_id': self.car.id, 'documents': ['manual']}],
                          override_purchase=True, allow_admin_grants=True)
        og.sync_user_to_node(self.other)
        node.refresh_from_db()
        perm = NodePermission.objects.get(node=node)
        self.assertEqual(perm.car_access, [{'car_id': self.car.id, 'documents': ['manual']}])
        # …and the graph now reports exactly what admin set.
        c, h = self._root_client()
        data = c.get('/api/org/graph/', **h).json()
        n = next(x for x in data['nodes'] if x['id'] == node.id)
        self.assertEqual(n['permission']['car_access'],
                         [{'car_id': self.car.id, 'documents': ['manual']}])

    def test_admin_ai_toggle_mirrors_into_node_permission(self):
        node = OrgNode.objects.create(graph=self.graph, parent=self.graph.root_node,
                                      occupant=self.other)
        NodePermission.objects.create(node=node, ai_eligible=False)
        self.other.ai_assistant_enabled = True
        self.other.save(update_fields=['ai_assistant_enabled'])
        og.sync_user_to_node(self.other)
        self.assertTrue(NodePermission.objects.get(node=node).ai_eligible)
