import json

from django.test import TestCase, Client, override_settings

from .models import Car, Company, CompanyCarAccess, PortalUser, PurchaseRequest
from .access import parse_seat_plan, user_ai_eligible


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
