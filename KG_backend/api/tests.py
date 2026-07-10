import json

from django.test import TestCase, Client, override_settings

from .models import (
    ActivityLog, AuthToken, Car, Company, CompanyCarAccess, InviteToken,
    PortalUser, PurchaseRequest,
)
from .access import (
    manager_can_target, parse_seat_plan, resolve_category, subtree_user_ids,
    user_ai_eligible,
)


SAMPLE_SEAT_PLAN = [
    {'role': 'after_sales_manager', 'department': 'گارانتی', 'count': 1, 'note': 'دسترسی کامل'},
    {'role': 'after_sales_specialist', 'department': 'خدمات پس از فروش', 'count': 2, 'note': 'راهنما و قطعات'},
]


@override_settings(DEBUG=True)
class PortalAdminFlowTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.car1 = Car.objects.create(brand_name='Toyota', car_name='bZ4X', year=2023, db_address='x')
        self.car2 = Car.objects.create(brand_name='Lexus', car_name='NX 350h', year=2022, db_address='y')
        self.admin_token = self._admin_login()

    def _post(self, url, payload, **kw):
        return self.c.post(url, json.dumps(payload), content_type='application/json', **kw)

    def _admin_login(self):
        r = self._post('/api/admin/login/', {'username': 'admin', 'password': 'admin'})
        self.assertEqual(r.status_code, 200)
        return r.json()['token']

    def _admin_headers(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.admin_token}'}

    def test_admin_login_default_credentials(self):
        r = self._post('/api/admin/login/', {'username': 'admin', 'password': 'admin'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['token'])

    def test_admin_requires_auth_in_debug(self):
        r = self.c.get('/api/admin/overview/')
        self.assertEqual(r.status_code, 401)

    def test_parse_seat_plan_validates(self):
        rows, total = parse_seat_plan(SAMPLE_SEAT_PLAN)
        self.assertEqual(total, 3)
        self.assertEqual(len(rows), 2)
        bad, err = parse_seat_plan([])
        self.assertIsNone(bad)
        self.assertIn('حداقل', err)

    def test_purchase_request_requires_seat_plan(self):
        base = dict(brand='Toyota', model='bZ4X', year='2023', documents=['manual'],
                    company='گستر', landline='021', mobile='0912', reg_no='1',
                    employees_count=100, seats_count=5)
        r = self._post('/api/purchase-request/', base, REMOTE_ADDR='10.0.0.1')
        self.assertEqual(r.status_code, 400)

        r = self._post('/api/purchase-request/', {
            **base,
            'seat_plan': SAMPLE_SEAT_PLAN,
            'seats_count': 3,
            'wants_demo': True,
            'wants_ai_assistant': True,
        }, REMOTE_ADDR='10.0.0.2')
        self.assertEqual(r.status_code, 200)
        pr = PurchaseRequest.objects.get()
        self.assertEqual(pr.employees_count, 100)
        self.assertEqual(pr.seats_count, 3)
        self.assertEqual(len(pr.seat_plan), 2)
        self.assertTrue(pr.wants_demo)
        self.assertEqual(pr.status, 'new')

    def test_admin_full_flow(self):
        pr = PurchaseRequest.objects.create(
            brand='Toyota', model='bZ4X', year='2023', documents=['manual'],
            company='گستر', landline='021', mobile='0912', reg_no='1',
            employees_count=10, seats_count=3,
            seat_plan=SAMPLE_SEAT_PLAN,
        )
        r = self._post(f'/api/admin/requests/{pr.id}/status/', {'status': 'approved'}, **self._admin_headers())
        self.assertEqual(r.status_code, 200)

        r = self._post('/api/admin/companies/', {
            'name': 'گستر', 'seats_count': 2, 'ai_assistant_enabled': True,
            'department_label': 'فنی و مهندسی',
        }, **self._admin_headers())
        self.assertEqual(r.status_code, 200)
        cid = r.json()['company']['id']
        r = self._post(f'/api/admin/companies/{cid}/access/',
                       {'accesses': [{'car_id': self.car1.id, 'documents': ['manual']}]},
                       **self._admin_headers())
        self.assertEqual(r.status_code, 200)

        r = self._post('/api/admin/users/', {'company_id': cid, 'username': 'gostar_te_01',
                                             'role': 'after_sales_specialist',
                                             'ai_assistant_enabled': True},
                       **self._admin_headers())
        self.assertEqual(r.status_code, 200)
        uid = r.json()['user']['id']
        password = r.json()['password']

        r = self._post(f'/api/admin/users/{uid}/access/', {'accesses': [
            {'car_id': self.car1.id, 'documents': ['manual', 'parts']},
            {'car_id': self.car2.id, 'documents': ['manual'], 'admin_granted': True},
        ], 'override_purchase': True}, **self._admin_headers())
        accesses = r.json()['user']['accesses']
        self.assertEqual(len(accesses), 2)
        u = PortalUser.objects.get(id=uid)
        self.assertTrue(user_ai_eligible(u))

        r = self._post('/api/auth/login/', {'username': 'gostar_te_01', 'password': password})
        self.assertEqual(r.status_code, 200)
        token = r.json()['token']

        r = self._post(f'/api/admin/users/{uid}/', {'locked': True}, **self._admin_headers())
        self.assertEqual(r.status_code, 200)
        r = self.c.get('/api/auth/me/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(r.status_code, 401)

    def test_ai_requires_manual_package(self):
        company = Company.objects.create(name='Y', ai_assistant_enabled=True)
        CompanyCarAccess.objects.create(company=company, car=self.car1, documents=['parts'])
        u = PortalUser(company=company, username='u2', role='after_sales_specialist',
                        ai_assistant_enabled=True)
        u.set_password('p')
        u.save()
        self._post(f'/api/admin/users/{u.id}/access/',
                   {'accesses': [{'car_id': self.car1.id, 'documents': ['parts']}]},
                   **self._admin_headers())
        u.refresh_from_db()
        self.assertFalse(user_ai_eligible(u))

    def test_company_access_prunes_user_grants(self):
        company = Company.objects.create(name='X')
        CompanyCarAccess.objects.create(company=company, car=self.car1, documents=[])
        u = PortalUser(company=company, username='u1', role='after_sales_specialist')
        u.set_password('p')
        u.save()
        self._post(f'/api/admin/users/{u.id}/access/',
                   {'accesses': [{'car_id': self.car1.id, 'documents': []}]},
                   **self._admin_headers())
        self.assertEqual(u.car_accesses.count(), 1)
        self._post(f'/api/admin/companies/{company.id}/access/',
                   {'accesses': [{'car_id': self.car2.id, 'documents': []}]},
                   **self._admin_headers())
        self.assertEqual(u.car_accesses.count(), 0)

    def test_admin_requests_include_seat_plan(self):
        PurchaseRequest.objects.create(
            brand='Toyota', model='bZ4X', year='2023', documents=['manual'],
            company='گستر', landline='021', mobile='0912', reg_no='1',
            employees_count=10, seats_count=3, seat_plan=SAMPLE_SEAT_PLAN,
        )
        r = self.c.get('/api/admin/requests/', **self._admin_headers())
        self.assertEqual(r.status_code, 200)
        item = r.json()['items'][0]
        self.assertEqual(len(item['seat_plan']), 2)


class TeamManagementTests(TestCase):
    """Company-manager self-service: invites, scoping, RBAC, analytics."""

    def setUp(self):
        self.c = Client()
        self.car1 = Car.objects.create(brand_name='Toyota', car_name='bZ4X', year=2023, db_address='x')
        self.car2 = Car.objects.create(brand_name='Lexus', car_name='NX', year=2022, db_address='y')
        # Company A: purchased car1 with [manual, parts]; has a manager.
        self.company = Company.objects.create(name='Alpha', ai_assistant_enabled=True)
        CompanyCarAccess.objects.create(company=self.company, car=self.car1, documents=['manual', 'parts'])
        self.manager = self._mk_user(self.company, 'alpha_mgr', 'after_sales_manager',
                                     email='mgr@alpha.test', can_manage_team=True,
                                     can_view_analytics=True, password='managerpass')
        # Issue the manager's session token directly (avoids tripping the login
        # rate-limiter across the many tests in this class).
        self.mtok = AuthToken.issue(self.manager).key
        # Company B: separate manager + employee (isolation target).
        self.other = Company.objects.create(name='Beta')
        self.other_mgr = self._mk_user(self.other, 'beta_mgr', 'after_sales_manager',
                                       can_manage_team=True, password='betapass')
        self.other_emp = self._mk_user(self.other, 'beta_emp', 'after_sales_specialist',
                                       reports_to=self.other_mgr, password='e')

    # -- helpers ------------------------------------------------------------
    def _mk_user(self, company, username, role, password='p', **kw):
        u = PortalUser(company=company, username=username, role=role, **kw)
        u.set_password(password)
        u.save()
        return u

    def _post(self, url, payload, token=None):
        kw = {}
        if token:
            kw['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        return self.c.post(url, json.dumps(payload), content_type='application/json', **kw)

    def _get(self, url, token=None):
        kw = {}
        if token:
            kw['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        return self.c.get(url, **kw)

    def _login(self, username, password):
        r = self._post('/api/auth/login/', {'username': username, 'password': password})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['token']

    # -- tests --------------------------------------------------------------
    def test_login_by_email(self):
        r = self._post('/api/auth/login/', {'username': 'mgr@alpha.test', 'password': 'managerpass'})
        self.assertEqual(r.status_code, 200)

    def test_manager_creates_employee_and_invite_flow(self):
        r = self._post('/api/team/members/', {
            'display_name': 'کارمند یک', 'email': 'emp1@alpha.test',
            'role': 'after_sales_specialist',
        }, token=self.mtok)
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertTrue(data['invite_url'])
        self.assertFalse(data['emailed'])  # no SMTP in tests
        uid = data['user']['id']
        u = PortalUser.objects.get(id=uid)
        self.assertEqual(u.invite_status, 'invited')
        self.assertFalse(u.password_set)
        self.assertEqual(u.reports_to_id, self.manager.id)

        # Cannot log in before accepting.
        r = self._post('/api/auth/login/', {'username': 'emp1@alpha.test', 'password': 'whatever'})
        self.assertEqual(r.status_code, 401)

        # Accept the invite -> sets password, activates, auto-logs-in.
        token = data['invite_url'].rsplit('/', 1)[1]
        r = self._get(f'/api/invite/{token}/')
        self.assertEqual(r.status_code, 200)
        r = self._post(f'/api/invite/{token}/', {'password': 'newpass123'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['token'])
        u.refresh_from_db()
        self.assertTrue(u.password_set)
        self.assertEqual(u.invite_status, 'active')

        # Token is single-use.
        r = self._post(f'/api/invite/{token}/', {'password': 'again123'})
        self.assertEqual(r.status_code, 400)

        # Now normal login works.
        r = self._post('/api/auth/login/', {'username': 'emp1@alpha.test', 'password': 'newpass123'})
        self.assertEqual(r.status_code, 200)

    def test_manager_cannot_escalate_role(self):
        # Manager (level 1) creating another manager (level 1) is rejected.
        r = self._post('/api/team/members/', {
            'display_name': 'x', 'email': 'x@alpha.test', 'role': 'after_sales_manager',
        }, token=self.mtok)
        self.assertEqual(r.status_code, 403)

    def test_manager_scoped_to_own_company(self):
        # Manager A cannot touch company B's employee.
        r = self._post(f'/api/team/members/{self.other_emp.id}/',
                       {'display_name': 'hax'}, token=self.mtok)
        self.assertEqual(r.status_code, 403)
        # Nor appears in A's member list.
        r = self._get('/api/team/members/', token=self.mtok)
        ids = [m['id'] for m in r.json()['members']]
        self.assertNotIn(self.other_emp.id, ids)

    def test_manager_access_clamped_to_company_scope(self):
        r = self._post('/api/team/members/', {
            'display_name': 'ک', 'email': 'emp2@alpha.test', 'role': 'after_sales_specialist',
            'accesses': [
                {'car_id': self.car1.id, 'documents': ['manual', 'parts', 'standard_time']},
                {'car_id': self.car2.id, 'documents': ['manual'], 'admin_granted': True},
            ],
        }, token=self.mtok)
        self.assertEqual(r.status_code, 200, r.content)
        u = PortalUser.objects.get(id=r.json()['user']['id'])
        grants = {a.car_id: set(a.documents) for a in u.car_accesses.all()}
        # car2 is outside the company's purchase -> dropped even with admin_granted.
        self.assertNotIn(self.car2.id, grants)
        # car1 clamped: standard_time (not purchased) removed.
        self.assertEqual(grants[self.car1.id], {'manual', 'parts'})

    def test_requires_manager_capability(self):
        emp_tok = AuthToken.issue(self.other_emp).key  # a plain specialist
        r = self._get('/api/team/members/', token=emp_tok)
        self.assertEqual(r.status_code, 403)

    # -- manager delegates cars they can access (company + admin-granted) ----
    def test_meta_and_grant_include_manager_admin_cars(self):
        from .models import UserCarAccess
        # car2 is NOT in the company's purchase, but the admin granted it to the
        # manager directly -> the manager may now delegate it.
        UserCarAccess.objects.create(user=self.manager, car=self.car2,
                                     documents=['manual'], admin_granted=True)
        meta = self._get('/api/team/members/', token=self.mtok).json()['meta']
        car_ids = {c['id'] for c in meta['cars']}
        self.assertIn(self.car1.id, car_ids)   # company-purchased
        self.assertIn(self.car2.id, car_ids)   # admin-granted to the manager
        # Create an employee and grant the admin-granted car2.
        r = self._post('/api/team/members/', {
            'display_name': 'د', 'email': 'emp3@alpha.test', 'role': 'after_sales_specialist',
            'accesses': [{'car_id': self.car2.id, 'documents': ['manual']}],
        }, token=self.mtok)
        self.assertEqual(r.status_code, 200, r.content)
        u = PortalUser.objects.get(id=r.json()['user']['id'])
        a = u.car_accesses.get(car=self.car2)
        # Delivered as an admin grant (outside company scope) so it isn't pruned.
        self.assertTrue(a.admin_granted)
        self.assertEqual(set(a.documents), {'manual'})

    # -- create an employee with username+password, no email ----------------
    def test_create_with_generated_credentials_no_email(self):
        r = self._post('/api/team/members/', {
            'display_name': 'بدون ایمیل', 'role': 'after_sales_specialist',
            'provision': 'credentials',
        }, token=self.mtok)
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        creds = data['credentials']
        self.assertTrue(creds['username'] and len(creds['password']) >= 8)
        u = PortalUser.objects.get(id=data['user']['id'])
        self.assertTrue(u.password_set and u.active)
        self.assertEqual(u.invite_status, 'active')
        # The employee can log in immediately with the generated credentials.
        r = self._post('/api/auth/login/',
                       {'username': creds['username'], 'password': creds['password']})
        self.assertEqual(r.status_code, 200, r.content)

    def test_create_with_manager_password(self):
        r = self._post('/api/team/members/', {
            'display_name': 'با رمز دستی', 'username': 'ali_manual', 'password': 'secret12',
            'role': 'after_sales_specialist', 'provision': 'credentials',
        }, token=self.mtok)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['credentials']['username'], 'ali_manual')
        r = self._post('/api/auth/login/', {'username': 'ali_manual', 'password': 'secret12'})
        self.assertEqual(r.status_code, 200, r.content)

    def test_invite_mode_still_requires_email(self):
        r = self._post('/api/team/members/', {
            'display_name': 'x', 'role': 'after_sales_specialist', 'provision': 'invite',
        }, token=self.mtok)
        self.assertEqual(r.status_code, 400)

    def test_manager_can_target_helper(self):
        emp = self._mk_user(self.company, 'a_emp', 'after_sales_specialist',
                            reports_to=self.manager)
        self.assertTrue(manager_can_target(self.manager, emp))
        self.assertFalse(manager_can_target(self.manager, self.other_emp))
        self.assertIn(emp.id, subtree_user_ids(self.manager))

    def test_team_analytics_scoped(self):
        emp = self._mk_user(self.company, 'a_emp2', 'after_sales_specialist',
                            reports_to=self.manager)
        ActivityLog.objects.create(user=emp, action='view_node', category='engine', car=self.car1)
        ActivityLog.objects.create(user=emp, action='assist', category='electrical')
        ActivityLog.objects.create(user=self.other_emp, action='view_node', category='engine')
        r = self._get('/api/team/analytics/', token=self.mtok)
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        # Only company A's events (2), not company B's.
        self.assertEqual(data['total_events'], 2)
        cats = {c['id']: c['count'] for c in data['categories']}
        self.assertEqual(cats.get('engine'), 1)
        self.assertEqual(cats.get('electrical'), 1)

    def test_resolve_category(self):
        self.assertEqual(resolve_category(['Repair and Diagnosis', 'Engine Mechanical', 'X']), 'engine')
        self.assertEqual(resolve_category(['Repair and Diagnosis', 'Electrical']), 'electrical')
        self.assertEqual(resolve_category('Body & Frame/Doors'), 'body')
        self.assertEqual(resolve_category([]), '')


class ContentAccessGateTests(TestCase):
    """The vehicle-manual endpoints are paid content: they now require a logged-in
    portal user who has the specific car granted (per-car authorization). The
    brand/year catalog listings stay public for the sales page."""

    def setUp(self):
        from .models import UserCarAccess
        self.c = Client()
        # car1 is owned by the company AND granted to the user; car2 is neither.
        self.car1 = Car.objects.create(brand_name='Toyota', car_name='bZ4X', year=2023, db_address='x')
        self.car2 = Car.objects.create(brand_name='Lexus', car_name='NX', year=2022, db_address='y')
        self.company = Company.objects.create(name='Alpha', ai_assistant_enabled=True)
        CompanyCarAccess.objects.create(company=self.company, car=self.car1, documents=['manual'])
        self.user = PortalUser(company=self.company, username='seat1', role='after_sales_specialist')
        self.user.set_password('p')
        self.user.save()
        UserCarAccess.objects.create(user=self.user, car=self.car1, documents=['manual'])
        self.tok = AuthToken.issue(self.user).key

    def _get(self, url, token=None, cookie=None):
        kw = {}
        if token:
            kw['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        if cookie:
            kw['HTTP_COOKIE'] = f'kg_portal_token={cookie}'
        return self.c.get(url, **kw)

    # -- car content (car_view Case 3) --------------------------------------
    def test_content_anonymous_401(self):
        self.assertEqual(self._get('/Toyota/2023/bZ4X/').status_code, 401)

    def test_content_forbidden_without_grant(self):
        # Logged in, but no grant to car2 -> 403 (not their subscription).
        self.assertEqual(self._get('/Lexus/2022/NX/', token=self.tok).status_code, 403)

    def test_content_allowed_with_grant_passes_gate(self):
        # Granted car: passes auth+access; the test car has no real db file, so
        # it stops at 404 (readiness) — the point is it is NOT 401/403.
        r = self._get('/Toyota/2023/bZ4X/', token=self.tok)
        self.assertNotIn(r.status_code, (401, 403))

    def test_content_cookie_auth_works(self):
        # SSR carries the token as a cookie, not a header.
        r = self._get('/Toyota/2023/bZ4X/', cookie=self.tok)
        self.assertNotIn(r.status_code, (401, 403))

    def test_catalog_listings_stay_public(self):
        # Brand/year catalog (sales page) is still reachable anonymously.
        self.assertEqual(self._get('/Toyota/').status_code, 200)
        self.assertEqual(self._get('/Toyota/2023/').status_code, 200)

    def test_catalog_never_leaks_db_address(self):
        Car.objects.create(brand_name='Toyota', car_name='Ready', year=2024, db_address='x')
        # Even when a row is returned, db_address must not appear.
        body = self._get('/Toyota/').content.decode()
        self.assertNotIn('db_address', body)

    # -- assist / search gates (run before any RAG work) --------------------
    def test_assist_anonymous_401(self):
        r = self.c.post('/api/assist/', json.dumps({'query': 'x', 'car': 'bZ4X'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 401)

    def test_assist_forbidden_without_grant(self):
        r = self.c.post('/api/assist/', json.dumps({'query': 'x', 'car': 'NX'}),
                        content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {self.tok}')
        self.assertEqual(r.status_code, 403)

    def test_search_anonymous_401(self):
        self.assertEqual(self._get('/api/search/?q=oil&car=bZ4X').status_code, 401)
