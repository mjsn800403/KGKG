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


class RequestBodyHardeningTests(TestCase):
    """Every JSON endpoint must tolerate a body that is valid JSON but NOT an
    object (a bare string / list / number) — it must never 500. Regression for
    the AttributeError-on-.get() crash."""

    def setUp(self):
        self.c = Client()

    def _raw(self, url, raw, **kw):
        return self.c.post(url, raw, content_type='application/json', **kw)

    def test_login_non_object_body_not_500(self):
        for raw in ('"a string"', '[1,2,3]', '42', 'null'):
            r = self._raw('/api/auth/login/', raw, REMOTE_ADDR='10.0.0.9')
            self.assertNotEqual(r.status_code, 500, raw)
            self.assertEqual(r.status_code, 401, raw)

    def test_admin_login_non_object_body_not_500(self):
        for raw in ('"x"', '[]', '3.14'):
            r = self._raw('/api/admin/login/', raw, REMOTE_ADDR='10.0.0.9')
            self.assertNotEqual(r.status_code, 500, raw)

    def test_purchase_non_object_body_400(self):
        r = self._raw('/api/purchase-request/', '[1,2,3]', REMOTE_ADDR='10.0.0.9')
        self.assertEqual(r.status_code, 400)

    def test_assist_non_object_body_not_500(self):
        # A non-object body collapses to {} -> empty query -> 400 (query required),
        # or 401 at the auth gate. Either is fine; the point is it must never 500.
        r = self._raw('/api/assist/', '"hi"', REMOTE_ADDR='10.0.0.9')
        self.assertIn(r.status_code, (400, 401))
        self.assertNotEqual(r.status_code, 500)


@override_settings(DEBUG=True)
class AdminCompanyUpdateClampTests(TestCase):
    """The company PATCH-via-POST path must clamp field lengths like create does
    (SQLite ignores VARCHAR limits, so an unclamped update could store a blob)."""

    def setUp(self):
        self.c = Client()
        self.company = Company.objects.create(name='ClampCo')

    def _post(self, url, payload, **kw):
        return self.c.post(url, json.dumps(payload), content_type='application/json', **kw)

    def _tok(self):
        r = self._post('/api/admin/login/', {'username': 'admin', 'password': 'admin'})
        return r.json()['token']

    def test_company_name_is_clamped_on_update(self):
        tok = self._tok()
        huge = 'x' * 5000
        r = self._post(f'/api/admin/companies/{self.company.id}/', {'name': huge},
                       HTTP_AUTHORIZATION=f'Bearer {tok}')
        self.assertEqual(r.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(len(self.company.name), 200)


class ManagedAccessDocClampTests(TestCase):
    """apply_managed_access: an explicit doc list naming ONLY layers the manager
    lacks must skip the car, not silently upgrade the employee to every layer."""

    def setUp(self):
        self.car = Car.objects.create(brand_name='Toyota', car_name='bZ4X', year=2023, db_address='x')
        self.company = Company.objects.create(name='DocClampCo')
        # Company/manager hold only 'manual' for the car.
        CompanyCarAccess.objects.create(company=self.company, car=self.car, documents=['manual'])
        self.manager = PortalUser(company=self.company, username='dc_mgr',
                                  role='after_sales_manager', can_manage_team=True)
        self.manager.set_password('p'); self.manager.save()
        self.emp = PortalUser(company=self.company, username='dc_emp',
                              role='after_sales_specialist', reports_to=self.manager)
        self.emp.set_password('p'); self.emp.save()

    def test_disallowed_only_docs_skip_the_car(self):
        from .access import apply_managed_access
        # Manager tries to grant ONLY 'parts' (which they don't hold) -> car skipped.
        apply_managed_access(self.manager, self.emp, [{'car_id': self.car.id, 'documents': ['parts']}])
        self.assertFalse(self.emp.car_accesses.filter(car=self.car).exists())

    def test_omitted_docs_grants_full_ceiling(self):
        from .access import apply_managed_access
        # No documents key -> "grant the whole car" -> manager's ceiling ('manual').
        apply_managed_access(self.manager, self.emp, [{'car_id': self.car.id}])
        row = self.emp.car_accesses.get(car=self.car)
        self.assertEqual(set(row.documents), {'manual'})

    def test_mixed_docs_clamp_to_held_layers(self):
        from .access import apply_managed_access
        apply_managed_access(self.manager, self.emp,
                             [{'car_id': self.car.id, 'documents': ['manual', 'parts']}])
        row = self.emp.car_accesses.get(car=self.car)
        self.assertEqual(set(row.documents), {'manual'})   # 'parts' clamped away
