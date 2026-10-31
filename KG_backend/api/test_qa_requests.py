"""QA integration tests for company requests (api/requests_api.py).

Manager side (portal token + team-manager capability) and admin side (platform
admin session). Focus: tenant isolation (no cross-company read / cancel —
IDOR), input validation and payload sanitising, status lifecycle, and the
real-time Event rows each transition must emit. Real HTTP stack, real models,
nothing mocked.

Run:  python manage.py test api.test_qa_requests
"""
import json

from django.test import Client, TestCase

from .models import (AdminAuthToken, AuthToken, Car, Company, CompanyRequest,
                     Event, PlatformAdmin, PortalUser)

URL = '/api/company/requests/'
ADMIN_URL = '/api/admin/company-requests/'


def _bearer(key):
    return {'HTTP_AUTHORIZATION': f'Bearer {key}'}


class CompanyRequestsBase(TestCase):
    def setUp(self):
        self.c = Client()
        self.co_a = Company.objects.create(name='QA Req A')
        self.co_b = Company.objects.create(name='QA Req B')
        self.mgr_a = PortalUser.objects.create(company=self.co_a, username='qa_mgr_a',
                                               role='after_sales_manager',
                                               can_manage_team=True, display_name='Mgr A')
        self.mgr_a2 = PortalUser.objects.create(company=self.co_a, username='qa_mgr_a2',
                                                role='after_sales_manager',
                                                can_manage_team=True)
        self.mgr_b = PortalUser.objects.create(company=self.co_b, username='qa_mgr_b',
                                               role='after_sales_manager',
                                               can_manage_team=True)
        self.spec_a = PortalUser.objects.create(company=self.co_a, username='qa_spec_a',
                                                role='after_sales_specialist')
        self.car1 = Car.objects.create(brand_name='Toyota', car_name='Hilux', year=2020,
                                       db_address='x.db')
        self.car2 = Car.objects.create(brand_name='Toyota', car_name='Corolla', year=2022,
                                       db_address='y.db')
        self.h_a = _bearer(AuthToken.issue(self.mgr_a).key)
        self.h_a2 = _bearer(AuthToken.issue(self.mgr_a2).key)
        self.h_b = _bearer(AuthToken.issue(self.mgr_b).key)
        self.h_spec = _bearer(AuthToken.issue(self.spec_a).key)

    def post(self, url, body, hdr):
        return self.c.post(url, json.dumps(body), content_type='application/json', **hdr)

    def create(self, hdr=None, **body):
        body.setdefault('subject', 'Need access')
        r = self.post(URL, body, hdr or self.h_a)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['request']


class ManagerRequestTests(CompanyRequestsBase):
    # -- auth -------------------------------------------------------------
    def test_signed_out_is_401_everywhere(self):
        r = CompanyRequest.objects.create(company=self.co_a, subject='x')
        self.assertEqual(self.c.get(URL).status_code, 401)
        self.assertEqual(self.c.post(URL, '{}', content_type='application/json').status_code, 401)
        self.assertEqual(self.c.get(f'{URL}{r.id}/').status_code, 401)

    def test_non_manager_may_use_the_support_channel_but_not_commercial_kinds(self):
        """Changed 2026-10-30. This test used to assert 403 for every request a
        non-manager made. That blanket gate was the root cause of the
        "customer feedback is collected by telephone" finding: a specialist
        with a problem could not file anything. A support ticket is now theirs
        to open; the commercial kinds stay a manager's decision. The
        per-kind rules are covered in api/test_helpdesk.py."""
        self.assertEqual(self.c.get(URL, **self.h_spec).status_code, 200)
        self.assertEqual(self.post(URL, {'subject': 'x', 'kind': 'support'},
                                   self.h_spec).status_code, 200)
        self.assertEqual(self.post(URL, {'subject': 'x', 'kind': 'seats'},
                                   self.h_spec).status_code, 403)

    def test_wrong_method_is_405(self):
        self.assertEqual(self.c.put(URL, '{}', content_type='application/json',
                                    **self.h_a).status_code, 405)

    # -- create -----------------------------------------------------------
    def test_create_stamps_company_and_creator_from_token_not_body(self):
        req = self.create(subject='  Grant Hilux  ', body='please', kind='support',
                          company_id=self.co_b.id, created_by=self.mgr_b.id)
        row = CompanyRequest.objects.get(id=req['id'])
        self.assertEqual(row.company_id, self.co_a.id)
        self.assertEqual(row.created_by_id, self.mgr_a.id)
        self.assertEqual(req['subject'], 'Grant Hilux')
        self.assertEqual(req['status'], 'pending')
        self.assertTrue(req['is_open'])
        self.assertEqual(req['created_by'], {'id': self.mgr_a.id, 'name': 'Mgr A'})
        self.assertNotIn('company', req)

    def test_create_emits_company_and_admin_events(self):
        req = self.create()
        evs = Event.objects.filter(type='request.created')
        self.assertEqual({e.audience for e in evs}, {'company', 'admin'})
        comp = evs.get(audience='company')
        self.assertEqual(comp.company_id, self.co_a.id)
        self.assertEqual(comp.payload['request']['id'], req['id'])

    def test_create_validation(self):
        self.assertEqual(self.post(URL, {'subject': 'x', 'kind': 'hack'}, self.h_a).status_code, 400)
        for subj in ('', '   ', None):
            with self.subTest(subject=subj):
                self.assertEqual(self.post(URL, {'subject': subj}, self.h_a).status_code, 400)
        self.assertEqual(self.c.post(URL, 'not json', content_type='application/json',
                                     **self.h_a).status_code, 400)
        self.assertFalse(CompanyRequest.objects.exists())

    def test_create_defaults_and_truncation(self):
        req = self.create(subject='S' * 500, body='B' * 9000, priority='urgent!!')
        self.assertEqual(req['kind'], 'support')
        self.assertEqual(len(req['subject']), 200)
        self.assertEqual(len(req['body']), 4000)
        self.assertEqual(req['priority'], 'normal')
        req = self.create(priority='high')
        self.assertEqual(req['priority'], 'high')

    def test_vehicle_access_payload_is_sanitised(self):
        req = self.create(kind='vehicle_access', payload={
            'car_ids': [self.car1.id, 999999, str(self.car2.id), None, self.car2.id],
            'documents': ['manual', 5, 'parts'] + ['x'] * 20,
            'evil': '<script>'})
        self.assertEqual(sorted(req['payload']['car_ids']), sorted([self.car1.id, self.car2.id]))
        self.assertEqual(len(req['payload']['documents']), 10)
        self.assertNotIn(5, req['payload']['documents'])
        self.assertNotIn('evil', req['payload'])
        self.assertEqual([c['name'] for c in req['cars']], ['Corolla 2022', 'Hilux 2020'])

    def test_vehicle_access_with_only_unknown_cars_drops_car_ids(self):
        req = self.create(kind='vehicle_access', payload={'car_ids': [987654]})
        self.assertEqual(req['payload'], {})
        self.assertEqual(req['cars'], [])

    def test_seats_payload_is_clamped(self):
        for raw, expected in ((5, {'seats': 5}), (0, {'seats': 1}), (-9, {'seats': 1}),
                              (10 ** 9, {'seats': 10000}), ('12', {'seats': 12}),
                              ('lots', {}), (None, {})):
            with self.subTest(seats=raw):
                req = self.create(kind='seats', payload={'seats': raw})
                self.assertEqual(req['payload'], expected)

    def test_non_dict_payload_and_unrelated_kinds_store_nothing(self):
        self.assertEqual(self.create(kind='vehicle_access', payload=[1, 2])['payload'], {})
        self.assertEqual(self.create(kind='support', payload={'seats': 5})['payload'], {})

    # -- list -------------------------------------------------------------
    def test_list_is_scoped_to_own_company(self):
        mine = self.create(subject='A1')
        self.create(subject='A2', hdr=self.h_a2)
        theirs = self.create(subject='B1', hdr=self.h_b)
        body = self.c.get(URL, **self.h_a).json()
        ids = {r['id'] for r in body['requests']}
        self.assertIn(mine['id'], ids)
        self.assertNotIn(theirs['id'], ids)
        self.assertEqual(len(ids), 2)                      # both A managers' requests
        self.assertEqual(body['meta']['open_count'], 2)
        self.assertEqual(len(body['meta']['kinds']), len(CompanyRequest.KIND_CHOICES))
        body_b = self.c.get(URL, **self.h_b).json()
        self.assertEqual([r['subject'] for r in body_b['requests']], ['B1'])

    def test_list_status_filter_and_invalid_filter_ignored(self):
        a = self.create(subject='open')
        b = self.create(subject='done')
        CompanyRequest.objects.filter(id=b['id']).update(status='completed')
        got = self.c.get(URL, {'status': 'completed'}, **self.h_a).json()['requests']
        self.assertEqual([r['id'] for r in got], [b['id']])
        got = self.c.get(URL, {'status': "pending' OR 1=1"}, **self.h_a).json()
        self.assertEqual({r['id'] for r in got['requests']}, {a['id'], b['id']})
        self.assertEqual(got['meta']['open_count'], 1)

    # -- detail / cancel (IDOR) -------------------------------------------
    def test_other_company_cannot_read_request(self):
        req = self.create(subject='secret plan')
        r = self.c.get(f'{URL}{req["id"]}/', **self.h_b)
        self.assertEqual(r.status_code, 404)
        self.assertNotIn('secret plan', r.content.decode())

    def test_other_company_cannot_cancel_request(self):
        req = self.create()
        r = self.post(f'{URL}{req["id"]}/', {'cancel': True}, self.h_b)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(CompanyRequest.objects.get(id=req['id']).status, 'pending')

    def test_unknown_id_is_404(self):
        self.assertEqual(self.c.get(f'{URL}999999/', **self.h_a).status_code, 404)

    def test_detail_includes_company(self):
        req = self.create()
        body = self.c.get(f'{URL}{req["id"]}/', **self.h_a).json()['request']
        self.assertEqual(body['company'], {'id': self.co_a.id, 'name': 'QA Req A'})

    def test_cancel_lifecycle(self):
        req = self.create()
        url = f'{URL}{req["id"]}/'
        r = self.post(url, {'cancel': True}, self.h_a2)          # same company, other manager
        self.assertEqual(r.status_code, 200)
        out = r.json()['request']
        self.assertEqual(out['status'], 'rejected')
        self.assertFalse(out['is_open'])
        self.assertIsNotNone(out['resolved_at'])
        self.assertIn('لغو', out['admin_note'])
        ev = Event.objects.get(type='request.updated', audience='company')
        self.assertEqual(ev.payload['prev_status'], 'pending')
        # closed requests cannot be cancelled again
        self.assertEqual(self.post(url, {'cancel': True}, self.h_a).status_code, 400)
        # any other POST verb is rejected
        self.assertEqual(self.post(url, {'reopen': True}, self.h_a).status_code, 400)

    def test_cancel_appends_to_existing_admin_note(self):
        req = self.create()
        CompanyRequest.objects.filter(id=req['id']).update(status='in_progress',
                                                           admin_note='working on it')
        out = self.post(f'{URL}{req["id"]}/', {'cancel': True}, self.h_a).json()['request']
        self.assertTrue(out['admin_note'].startswith('working on it\n'))


class AdminRequestTests(CompanyRequestsBase):
    def setUp(self):
        super().setUp()
        admin = PlatformAdmin.objects.create(username='qa_req_admin')
        admin.set_password('pw')
        admin.save()
        self.h_admin = _bearer(AdminAuthToken.issue(admin).key)
        self.ra = CompanyRequest.objects.create(company=self.co_a, created_by=self.mgr_a,
                                                subject='A ask')
        self.rb = CompanyRequest.objects.create(company=self.co_b, created_by=self.mgr_b,
                                                subject='B ask', status='completed')

    def test_admin_endpoints_reject_portal_managers(self):
        self.assertEqual(self.c.get(ADMIN_URL).status_code, 401)
        self.assertEqual(self.c.get(ADMIN_URL, **self.h_a).status_code, 401)
        r = self.post(f'{ADMIN_URL}{self.ra.id}/', {'status': 'completed'}, self.h_a)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(CompanyRequest.objects.get(id=self.ra.id).status, 'pending')

    def test_inbox_lists_all_companies_with_counts(self):
        body = self.c.get(ADMIN_URL, **self.h_admin).json()
        self.assertEqual({r['id'] for r in body['requests']}, {self.ra.id, self.rb.id})
        self.assertEqual(body['counts']['pending'], 1)
        self.assertEqual(body['counts']['completed'], 1)
        self.assertEqual(body['open_count'], 1)
        self.assertEqual({r['company']['name'] for r in body['requests']},
                         {'QA Req A', 'QA Req B'})

    def test_inbox_filters(self):
        got = self.c.get(ADMIN_URL, {'company_id': self.co_b.id}, **self.h_admin).json()
        self.assertEqual([r['id'] for r in got['requests']], [self.rb.id])
        got = self.c.get(ADMIN_URL, {'status': 'pending'}, **self.h_admin).json()
        self.assertEqual([r['id'] for r in got['requests']], [self.ra.id])

    def test_inbox_non_numeric_company_filter_is_not_a_500(self):
        # Regression (fixed in this change): requests_api.py:184-186 passes ?company_id= straight into
        # .filter(company_id=...); a non-numeric value raises ValueError -> 500.
        c = Client(raise_request_exception=False)
        r = c.get(ADMIN_URL, {'company_id': 'abc'}, **self.h_admin)
        self.assertLess(r.status_code, 500)

    def test_detail_serves_get_and_404s_an_unknown_id(self):
        # Changed 2026-10-30: the admin detail route now answers GET with the
        # full ticket including internal notes (it used to be POST-only).
        self.assertEqual(self.c.get(f'{ADMIN_URL}{self.ra.id}/', **self.h_admin).status_code, 200)
        self.assertEqual(self.c.put(f'{ADMIN_URL}{self.ra.id}/', '{}',
                                    content_type='application/json',
                                    **self.h_admin).status_code, 405)
        self.assertEqual(self.post(f'{ADMIN_URL}999999/', {}, self.h_admin).status_code, 404)

    def test_invalid_status_rejected_without_change(self):
        r = self.post(f'{ADMIN_URL}{self.ra.id}/', {'status': 'approved'}, self.h_admin)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(CompanyRequest.objects.get(id=self.ra.id).status, 'pending')

    def test_status_transitions_stamp_and_clear_resolution(self):
        url = f'{ADMIN_URL}{self.ra.id}/'
        out = self.post(url, {'status': 'completed', 'admin_note': '  done  '},
                        self.h_admin).json()['request']
        self.assertEqual(out['status'], 'completed')
        self.assertIsNotNone(out['resolved_at'])
        self.assertEqual(out['admin_note'], 'done')
        # Changed 2026-10-30: the acting admin is recorded, not the literal
        # string 'admin' — ownership has to be a fact for workload and
        # escalation to mean anything (see api/test_helpdesk.py AssignmentTests).
        self.assertEqual(out['handled_by'], 'qa_req_admin')
        ev = Event.objects.filter(type='request.updated', audience='company').latest('id')
        self.assertEqual(ev.company_id, self.co_a.id)            # pushed to the owner only
        self.assertEqual(ev.payload['prev_status'], 'pending')
        out = self.post(url, {'status': 'in_progress', 'handled_by': 'ops-' + 'x' * 300},
                        self.h_admin).json()['request']
        self.assertIsNone(out['resolved_at'])
        self.assertEqual(len(out['handled_by']), 100)
        # the manager now sees the admin's update on their own detail view
        mine = self.c.get(f'{URL}{self.ra.id}/', **self.h_a).json()['request']
        self.assertEqual(mine['status'], 'in_progress')

    def test_noop_post_emits_nothing(self):
        before = Event.objects.count()
        r = self.post(f'{ADMIN_URL}{self.ra.id}/', {'status': 'pending'}, self.h_admin)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Event.objects.count(), before)

    def test_admin_note_truncated(self):
        out = self.post(f'{ADMIN_URL}{self.ra.id}/', {'admin_note': 'n' * 5000},
                        self.h_admin).json()['request']
        self.assertEqual(len(out['admin_note']), 4000)
