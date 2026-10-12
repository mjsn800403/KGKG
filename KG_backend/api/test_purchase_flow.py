"""Customer plan request -> super-admin company + accounts -> SMS login (end to end)."""
import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from api import portal, ratelimit
from api.models import Company, PortalUser, PurchaseRequest

PLAN_BRAND = 'همهٔ خودروها'


def plan_payload(code, seats, mobile='09120000001', demo=False):
    plan = [{'role': 'after_sales_manager', 'count': 1}]
    if seats > 1:
        plan.append({'role': 'after_sales_specialist', 'count': seats - 1})
    return {
        'brand': PLAN_BRAND, 'model': f'plan — {seats}', 'year': code,
        'documents': ['manual', 'parts', 'standard_time', 'special_tools', 'full_spec'],
        'company': 'تعمیرگاه نمونه', 'landline': mobile, 'mobile': mobile, 'reg_no': '1234567890',
        'note': 'پلن: test', 'employees_count': seats, 'seats_count': seats,
        'seat_plan': plan, 'wants_demo': demo, 'wants_ai_assistant': True,
    }


@override_settings(DEBUG=True)
class PurchaseToLoginFlowTest(TestCase):
    def setUp(self):
        ratelimit._HITS.clear()
        self.sms = []
        for p in (mock.patch.object(portal, '_verify_turnstile', return_value=True),
                  mock.patch.object(portal, '_send_sms_otp',
                                    side_effect=lambda ph, code: self.sms.append((ph, code)) or True)):
            p.start()
            self.addCleanup(p.stop)
        r = self.post('/api/admin/login/', {'username': 'admin', 'password': 'admin'})
        self.admin = {'HTTP_AUTHORIZATION': f"Bearer {r.json()['token']}"}

    def post(self, url, body, **kw):
        return self.client.post(url, json.dumps(body), content_type='application/json', **kw)

    def login(self, username, password):
        r = self.post('/api/auth/login/', {'username': username, 'password': password,
                                            'turnstile_token': 't'})
        self.assertEqual(r.status_code, 200, r.content)
        r = self.post('/api/auth/verify-otp/', {'otp_session': r.json()['otp_session'],
                                                 'code': str(self.sms[-1][1])})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['token']

    def test_demo_request_to_working_login(self):
        r = self.post('/api/purchase-request/', plan_payload('demo', 1, demo=True))
        self.assertEqual(r.status_code, 200, r.content)
        pr = PurchaseRequest.objects.get(id=r.json()['id'])
        self.assertTrue(pr.wants_demo)
        # Super-admin approves and creates the company with its 0-level account
        # (what the request card's «تعریف شرکت از این درخواست» submits).
        self.assertEqual(self.post(f'/api/admin/requests/{pr.id}/status/',
                                   {'status': 'approved'}, **self.admin).status_code, 200)
        r = self.post('/api/admin/companies/', {
            'name': pr.company, 'mobile': pr.mobile, 'seats_count': 1, 'is_demo': True,
            'ai_assistant_enabled': True, 'admin_username': 'demo_root',
            'admin_display_name': 'رابط', 'admin_phone': pr.mobile,
            'admin_access_expires_at': ''}, **self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        password = r.json()['admin']['password']
        root = PortalUser.objects.get(username='demo_root')
        left = root.access_expires_at - timezone.now()
        self.assertTrue(timedelta(hours=23) < left <= timedelta(days=1))   # demo = 1 day
        token = self.login('demo_root', password)
        self.assertEqual(self.sms[-1][0], pr.mobile)
        me = self.client.get('/api/auth/me/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(me.status_code, 200)
        self.assertTrue(Company.objects.get(name=pr.company).is_demo)

    def test_team_request_extra_seats_need_their_own_phone(self):
        r = self.post('/api/purchase-request/', plan_payload('annual', 3))
        self.assertEqual(r.status_code, 200, r.content)
        r = self.post('/api/admin/companies/', {
            'name': 'تیم', 'seats_count': 3, 'admin_username': 'team_root',
            'admin_phone': '09120000001',
            'admin_access_expires_at': (timezone.now() + timedelta(days=366)).isoformat()},
            **self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        cid = r.json()['company']['id']
        seat = {'company_id': cid, 'username': 'team_spec_1', 'role': 'after_sales_specialist'}
        r = self.post('/api/admin/users/', seat, **self.admin)
        self.assertEqual(r.status_code, 400)                        # no phone
        r = self.post('/api/admin/users/', {**seat, 'phone': '+98 912 000 0001'}, **self.admin)
        self.assertEqual(r.status_code, 400)                        # root's number
        r = self.post('/api/admin/users/', {**seat, 'phone': '09120000002'}, **self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.login('team_spec_1', r.json()['password'])
        self.assertEqual(self.sms[-1][0], '09120000002')

    def test_demo_and_two_day_pass_are_single_user(self):
        for code in ('demo', '2day'):
            r = self.post('/api/purchase-request/', plan_payload(code, 2))
            self.assertEqual(r.status_code, 400, code)
        r = self.post('/api/purchase-request/', plan_payload('2day', 1))
        self.assertEqual(r.status_code, 200)


class AdminApprovalExpiryTest(PurchaseToLoginFlowTest):
    def test_reject_custom_expiry_edit_and_expired_login(self):
        r = self.post('/api/purchase-request/', plan_payload('monthly', 1))
        pid = r.json()['id']
        self.assertEqual(self.post(f'/api/admin/requests/{pid}/status/', {'status': 'rejected'}, **self.admin).status_code, 200)
        self.assertEqual(PurchaseRequest.objects.get(id=pid).status, 'rejected')
        self.assertEqual(self.post(f'/api/admin/requests/{pid}/status/', {'status': 'bogus'}, **self.admin).status_code, 400)
        exp = timezone.now() + timedelta(days=31)
        r = self.post('/api/admin/companies/', {'name': 'M', 'admin_username': 'm_root',
            'admin_phone': '09120000009', 'admin_access_expires_at': exp.isoformat()}, **self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        cid, pw = r.json()['company']['id'], r.json()['admin']['password']
        root = PortalUser.objects.get(username='m_root')
        self.assertLess(abs((root.access_expires_at - exp).total_seconds()), 2)
        self.login('m_root', pw)
        # Admin moves the company window into the past -> login refused.
        past = (timezone.now() - timedelta(minutes=1)).isoformat()
        r = self.post(f'/api/admin/companies/{cid}/', {'access_expires_at': past}, **self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        r = self.post('/api/auth/login/', {'username': 'm_root', 'password': pw, 'turnstile_token': 't'})
        self.assertEqual(r.status_code, 403)
        # Duplicate company name and missing root phone are refused.
        self.assertEqual(self.post('/api/admin/companies/', {'name': 'M'}, **self.admin).status_code, 400)
        self.assertEqual(self.post('/api/admin/companies/', {'name': 'N', 'admin_username': 'n_root'}, **self.admin).status_code, 400)
        self.assertFalse(Company.objects.filter(name='N').exists())


class RootForExistingCompanyTest(PurchaseToLoginFlowTest):
    def test_add_root_later_and_retry_after_failed_create(self):
        r = self.post("/api/admin/companies/", {"name": "Q", "admin_username": "q_root"}, **self.admin)
        self.assertEqual(r.status_code, 400)                       # no phone -> company rolled back
        r = self.post("/api/admin/companies/", {"name": "Q"}, **self.admin)
        self.assertEqual(r.status_code, 200)                       # retry works, no root
        cid = r.json()["company"]["id"]
        self.assertFalse(r.json()["company"]["has_root"])
        r = self.post(f"/api/admin/companies/{cid}/", {"admin_username": "q_root", "admin_phone": "09120000077",
                      "admin_access_expires_at": (timezone.now() + timedelta(days=5)).isoformat()}, **self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["company"]["has_root"])
        self.login("q_root", r.json()["admin"]["password"])
        r = self.post(f"/api/admin/companies/{cid}/", {"admin_username": "q2", "admin_phone": "09120000078"}, **self.admin)
        self.assertEqual(r.status_code, 200); self.assertNotIn("admin", r.json())   # already has a root: no second one


class AutoRootOnSaveTest(PurchaseToLoginFlowTest):
    def test_save_creates_root_from_company_mobile(self):
        r = self.post("/api/admin/companies/", {"name": "R"}, **self.admin)
        cid = r.json()["company"]["id"]
        self.assertFalse(r.json()["company"]["has_root"])
        exp = (timezone.now() + timedelta(days=10)).isoformat()
        r = self.post(f"/api/admin/companies/{cid}/", {"name": "R", "mobile": "09120000055",
                      "admin_username": "r_boss", "access_expires_at": exp}, **self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["admin"]["username"], "r_boss")
        root = PortalUser.objects.get(username="r_boss")
        self.assertEqual((root.phone, root.display_name), ("09120000055", "R"))
        self.assertGreater(root.access_expires_at, timezone.now() + timedelta(days=9))
        self.login("r_boss", r.json()["admin"]["password"])
        # A second save does not create another account.
        r = self.post(f"/api/admin/companies/{cid}/", {"name": "R", "mobile": "09120000055"}, **self.admin)
        self.assertNotIn("admin", r.json())

    def test_new_company_with_mobile_gets_root(self):
        r = self.post("/api/admin/companies/", {"name": "S", "mobile": "09120000066", "is_demo": True, "admin_username": "s_boss"}, **self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["admin"]["username"], "s_boss")
        self.assertEqual(PortalUser.objects.get(username="s_boss").phone, "09120000066")
