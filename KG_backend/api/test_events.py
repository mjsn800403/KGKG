"""Event backbone + company-requests lifecycle + scoped delivery."""
import json

from django.test import TestCase, Client, override_settings

from .models import (
    AuthToken, Car, Company, CompanyCarAccess, CompanyRequest, Event, PortalUser,
    SystemState,
)
from . import events


class EventScopingTests(TestCase):
    def setUp(self):
        self.c1 = Company.objects.create(name='EvCo1')
        self.c2 = Company.objects.create(name='EvCo2')
        self.mgr = PortalUser(company=self.c1, username='ev_mgr', role='after_sales_manager',
                              can_manage_team=True, can_view_analytics=True)
        self.mgr.set_password('p'); self.mgr.save()
        self.spec = PortalUser(company=self.c1, username='ev_spec', role='after_sales_specialist',
                               )
        self.spec.set_password('p'); self.spec.save()

    def test_company_event_visible_to_manager_not_other_company(self):
        events.emit_company('activity', self.c1.id, {'x': 1})
        rows = events.events_since(0, is_admin=False, company_id=self.c1.id,
                                   user_id=self.mgr.id, can_see_company=True)
        self.assertEqual(len(rows), 1)
        rows_other = events.events_since(0, is_admin=False, company_id=self.c2.id,
                                         user_id=99, can_see_company=True)
        self.assertEqual(len(rows_other), 0)

    def test_company_event_hidden_from_plain_specialist(self):
        events.emit_company('activity', self.c1.id, {'x': 1})
        rows = events.events_since(0, is_admin=False, company_id=self.c1.id,
                                   user_id=self.spec.id, can_see_company=False)
        self.assertEqual(len(rows), 0)   # no company scope -> not delivered

    def test_user_event_only_to_that_user(self):
        events.emit_user('rec.updated', self.spec.id, {'r': 1}, company_id=self.c1.id)
        mine = events.events_since(0, is_admin=False, company_id=self.c1.id,
                                   user_id=self.spec.id, can_see_company=False)
        self.assertEqual(len(mine), 1)
        others = events.events_since(0, is_admin=False, company_id=self.c1.id,
                                     user_id=self.mgr.id, can_see_company=True)
        self.assertEqual(len(others), 0)

    def test_admin_event_not_visible_to_company(self):
        events.emit('data.detected', {'n': 1}, audience='admin')
        rows = events.events_since(0, is_admin=False, company_id=self.c1.id,
                                   user_id=self.mgr.id, can_see_company=True)
        self.assertEqual(len(rows), 0)
        admin_rows = events.events_since(0, is_admin=True)
        self.assertEqual(len(admin_rows), 1)

    def test_cursor_resume(self):
        e1 = events.emit('data.detected', {}, audience='admin')
        e2 = events.emit('data.detected', {}, audience='admin')
        rows = events.events_since(e1.id, is_admin=True)
        self.assertEqual([r.id for r in rows], [e2.id])


@override_settings(DEBUG=True)
class CompanyRequestLifecycleTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.car = Car.objects.create(brand_name='Toyota', car_name='bZ4X', year=2023, db_address='x')
        self.company = Company.objects.create(name='ReqCo')
        CompanyCarAccess.objects.create(company=self.company, car=self.car, documents=['manual'])
        self.mgr = PortalUser(company=self.company, username='rq_mgr', role='after_sales_manager',
                              can_manage_team=True, can_view_analytics=True)
        self.mgr.set_password('p'); self.mgr.save()
        self.tok = AuthToken.issue(self.mgr).key
        self.admin_tok = self._admin_login()

    def _admin_login(self):
        r = self.c.post('/api/admin/login/', json.dumps({'username': 'admin', 'password': 'admin'}),
                        content_type='application/json')
        return r.json()['token']

    def _post(self, url, payload, tok):
        return self.c.post(url, json.dumps(payload), content_type='application/json',
                           HTTP_AUTHORIZATION=f'Bearer {tok}')

    def test_full_lifecycle_emits_events_both_audiences(self):
        r = self._post('/api/company/requests/',
                       {'kind': 'vehicle_access', 'subject': 'grant access',
                        'payload': {'car_ids': [self.car.id], 'documents': ['manual']}}, self.tok)
        self.assertEqual(r.status_code, 200)
        req_id = r.json()['request']['id']
        # Structured payload was sanitized to valid car ids.
        self.assertEqual(r.json()['request']['payload']['car_ids'], [self.car.id])
        self.assertTrue(Event.objects.filter(type='request.created', audience='company',
                                             company_id=self.company.id).exists())
        self.assertTrue(Event.objects.filter(type='request.created', audience='admin').exists())

        r = self.c.get('/api/admin/company-requests/', HTTP_AUTHORIZATION=f'Bearer {self.admin_tok}')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(x['id'] == req_id for x in r.json()['requests']))
        self.assertEqual(r.json()['open_count'], 1)

        before = Event.objects.filter(type='request.updated').count()
        r = self._post(f'/api/admin/company-requests/{req_id}/',
                       {'status': 'in_progress', 'admin_note': 'reviewing'}, self.admin_tok)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['request']['status'], 'in_progress')
        r = self._post(f'/api/admin/company-requests/{req_id}/', {'status': 'completed'}, self.admin_tok)
        self.assertEqual(r.json()['request']['status'], 'completed')
        self.assertIsNotNone(r.json()['request']['resolved_at'])
        after = Event.objects.filter(type='request.updated').count()
        self.assertGreaterEqual(after - before, 2)
        self.assertTrue(Event.objects.filter(type='request.updated', audience='company',
                                             company_id=self.company.id).exists())

    def test_manager_cannot_see_other_company_requests(self):
        other = Company.objects.create(name='OtherReqCo')
        m2 = PortalUser(company=other, username='rq_mgr2', role='after_sales_manager',
                        can_manage_team=True)
        m2.set_password('p'); m2.save()
        t2 = AuthToken.issue(m2).key
        self._post('/api/company/requests/', {'kind': 'support', 'subject': 'x'}, self.tok)
        r = self.c.get('/api/company/requests/', HTTP_AUTHORIZATION=f'Bearer {t2}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()['requests']), 0)   # isolated per company

    def test_request_requires_subject(self):
        r = self._post('/api/company/requests/', {'kind': 'support'}, self.tok)
        self.assertEqual(r.status_code, 400)

    def test_specialist_cannot_file_request(self):
        spec = PortalUser(company=self.company, username='rq_spec',
                          role='after_sales_specialist', )
        spec.set_password('p'); spec.save()
        st = AuthToken.issue(spec).key
        r = self._post('/api/company/requests/', {'kind': 'support', 'subject': 'x'}, st)
        self.assertEqual(r.status_code, 403)

    def test_manager_can_cancel_own_open_request(self):
        r = self._post('/api/company/requests/', {'kind': 'support', 'subject': 'x'}, self.tok)
        req_id = r.json()['request']['id']
        r = self._post(f'/api/company/requests/{req_id}/', {'cancel': True}, self.tok)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['request']['status'], 'rejected')


class DetectAndEmitTests(TestCase):
    def test_detector_is_quiet_when_nothing_changes(self):
        events.detect_and_emit()          # establishes baseline (no event)
        n0 = Event.objects.count()
        events.detect_and_emit()          # identical state -> no new event
        self.assertEqual(Event.objects.count(), n0)
        self.assertTrue(SystemState.objects.filter(key='pending_fingerprint').exists())
