import json

from django.test import TestCase, Client, override_settings

from .models import Car, Company, CompanyCarAccess, PortalUser, PurchaseRequest


@override_settings(DEBUG=True)  # admin gate is open in DEBUG with no token
class PortalAdminFlowTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.car1 = Car.objects.create(brand_name='Toyota', car_name='bZ4X', year=2023, db_address='x')
        self.car2 = Car.objects.create(brand_name='Lexus', car_name='NX 350h', year=2022, db_address='y')

    def _post(self, url, payload, **kw):
        return self.c.post(url, json.dumps(payload), content_type='application/json', **kw)

    def test_purchase_request_requires_sizing(self):
        base = dict(brand='Toyota', model='bZ4X', year='2023', documents=['manual'],
                    company='گستر', landline='021', mobile='0912', reg_no='1')
        r = self._post('/api/purchase-request/', base)
        self.assertEqual(r.status_code, 400)  # missing employees/seats
        r = self._post('/api/purchase-request/', {**base, 'employees_count': 100,
                                                  'seats_count': 5, 'wants_demo': True,
                                                  'wants_ai_assistant': True})
        self.assertEqual(r.status_code, 200)
        pr = PurchaseRequest.objects.get()
        self.assertEqual(pr.employees_count, 100)
        self.assertTrue(pr.wants_demo)
        self.assertEqual(pr.status, 'new')

    def test_admin_full_flow(self):
        # Request status update
        pr = PurchaseRequest.objects.create(
            brand='Toyota', model='bZ4X', year='2023', documents=['manual'],
            company='گستر', landline='021', mobile='0912', reg_no='1',
            employees_count=10, seats_count=2)
        r = self._post(f'/api/admin/requests/{pr.id}/status/', {'status': 'approved'})
        self.assertEqual(r.status_code, 200)
        pr.refresh_from_db()
        self.assertEqual(pr.status, 'approved')
        self.assertTrue(pr.handled)

        # Create company + grant company access to car1 only
        r = self._post('/api/admin/companies/', {'name': 'گستر', 'seats_count': 2,
                                                 'ai_assistant_enabled': True})
        self.assertEqual(r.status_code, 200)
        cid = r.json()['company']['id']
        r = self._post(f'/api/admin/companies/{cid}/access/',
                       {'accesses': [{'car_id': self.car1.id, 'documents': ['manual']}]})
        self.assertEqual(r.status_code, 200)

        # Issue a user; password comes back once
        r = self._post('/api/admin/users/', {'company_id': cid, 'username': 'gostar_te_01',
                                             'role': 'technical_expert'})
        self.assertEqual(r.status_code, 200)
        uid = r.json()['user']['id']
        password = r.json()['password']

        # Per-user grant is clamped to the company scope: car2 must be ignored,
        # and a doc layer the company didn't buy must be stripped.
        r = self._post(f'/api/admin/users/{uid}/access/', {'accesses': [
            {'car_id': self.car1.id, 'documents': ['manual', 'parts']},
            {'car_id': self.car2.id, 'documents': []},
        ]})
        accesses = r.json()['user']['accesses']
        self.assertEqual(len(accesses), 1)
        self.assertEqual(accesses[0]['car']['id'], self.car1.id)
        self.assertEqual(accesses[0]['documents'], ['manual'])

        # Login works and returns granted accesses
        r = self._post('/api/auth/login/', {'username': 'gostar_te_01', 'password': password})
        self.assertEqual(r.status_code, 200)
        token = r.json()['token']
        self.assertEqual(len(r.json()['user']['accesses']), 1)

        # Activity logging + admin report
        r = self._post('/api/activity/', {'action': 'view_car', 'detail': 'bZ4X'},
                       HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(r.status_code, 200)
        r = self.c.get('/api/admin/activity/')
        actions = [i['action'] for i in r.json()['items']]
        self.assertIn('view_car', actions)
        self.assertIn('login', actions)

        # Deactivating the user kills the token
        r = self._post(f'/api/admin/users/{uid}/', {'active': False})
        self.assertEqual(r.status_code, 200)
        r = self.c.get('/api/auth/me/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(r.status_code, 401)

    def test_bad_login(self):
        r = self._post('/api/auth/login/', {'username': 'nobody', 'password': 'x'})
        self.assertEqual(r.status_code, 401)

    def test_company_access_prunes_user_grants(self):
        company = Company.objects.create(name='X')
        CompanyCarAccess.objects.create(company=company, car=self.car1, documents=[])
        u = PortalUser(company=company, username='u1', role='technical_staff')
        u.set_password('p')
        u.save()
        self._post(f'/api/admin/users/{u.id}/access/',
                   {'accesses': [{'car_id': self.car1.id, 'documents': []}]})
        self.assertEqual(u.car_accesses.count(), 1)
        # Company loses car1 -> user grant must be pruned
        self._post(f'/api/admin/companies/{company.id}/access/',
                   {'accesses': [{'car_id': self.car2.id, 'documents': []}]})
        self.assertEqual(u.car_accesses.count(), 0)
