"""Portal views that had no test (#22, step 3): the caller's own preferences,
the activity signal, the per-company role picker and its safe removal, and the
admin activity / analytics reports.

Each view is pinned on what it refuses (anonymous, wrong method, bad input) as
well as what it stores, since these are the paths a client can reach.
"""
import json
import os
from unittest import mock

from django.test import Client, TestCase

from .models import ActivityLog, AuthToken, Car, Company, CompanyRole, PortalUser

TOKEN = 'portal-views-test-token'


class Base(TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': TOKEN})
        env.start()
        self.addCleanup(env.stop)
        emit = mock.patch('api.events.emit')
        emit.start()
        self.addCleanup(emit.stop)
        self.c = Client()
        self.admin = {'HTTP_AUTHORIZATION': f'Bearer {TOKEN}'}
        self.co = Company.objects.create(name='Co', active=True)
        self.user = PortalUser.objects.create(company=self.co, username='u1', password_hash='x',
                                              phone='', role='technician')
        self.auth = {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(self.user).key}'}

    def post(self, url, body, **h):
        return self.c.post(url, json.dumps(body), content_type='application/json', **h)


class MePrefsTests(Base):
    URL = '/api/auth/me/prefs/'

    def test_refuses_anonymous_and_get(self):
        self.assertEqual(self.post(self.URL, {}).status_code, 401)
        self.assertEqual(self.c.get(self.URL, **self.auth).status_code, 405)

    def test_browse_mode_is_validated_and_stored(self):
        self.assertEqual(self.post(self.URL, {'browse_mode': 'fancy'}, **self.auth).status_code, 400)
        r = self.post(self.URL, {'browse_mode': 'classic'}, **self.auth)
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.browse_mode, 'classic')

    def test_two_step_login_needs_a_phone(self):
        self.assertEqual(self.post(self.URL, {'otp_enabled': True}, **self.auth).status_code, 400)
        self.user.phone = '09120000000'
        self.user.save(update_fields=['phone'])
        self.assertEqual(self.post(self.URL, {'otp_enabled': True}, **self.auth).status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.otp_enabled)
        self.post(self.URL, {'otp_enabled': False}, **self.auth)
        self.user.refresh_from_db()
        self.assertFalse(self.user.otp_enabled)

    def test_notification_switches(self):
        self.post(self.URL, {'notify_manual_update': False, 'notify_new_device': True}, **self.auth)
        self.user.refresh_from_db()
        self.assertFalse(self.user.notify_manual_update)
        self.assertTrue(self.user.notify_new_device)


class ActivityTests(Base):
    URL = '/api/activity/'

    def test_refuses_get_and_anonymous(self):
        self.assertEqual(self.c.get(self.URL, **self.auth).status_code, 405)
        self.assertEqual(self.post(self.URL, {'action': 'view'}).status_code, 401)

    def test_assistant_quota_action_cannot_be_forged(self):
        self.assertEqual(self.post(self.URL, {'action': 'ask_assistant'}, **self.auth).status_code, 400)
        self.assertFalse(ActivityLog.objects.exists())

    def test_logs_with_car_by_id_and_drops_an_unknown_category(self):
        car = Car.objects.create(brand_name='Toyota', car_name='Corolla', year=2025)
        r = self.post(self.URL, {'action': 'view', 'detail': 'd' * 500, 'category': 'nonsense',
                                 'car_id': car.id, 'node_title': 'Brakes'}, **self.auth)
        self.assertEqual(r.status_code, 200)
        log = ActivityLog.objects.get()
        self.assertEqual((log.car_id, log.category, log.node_title, len(log.detail)),
                         (car.id, '', 'Brakes', 400))

    def test_resolves_the_car_from_brand_model_and_year(self):
        Car.objects.create(brand_name='Toyota', car_name='Corolla', year=2024)
        want = Car.objects.create(brand_name='Toyota', car_name='Corolla', year=2025)
        self.post(self.URL, {'action': 'view', 'brand': 'toyota', 'model': 'COROLLA', 'year': '2025'},
                  **self.auth)
        self.assertEqual(ActivityLog.objects.get().car_id, want.id)

    def test_a_bad_year_is_ignored_not_an_error(self):
        Car.objects.create(brand_name='Toyota', car_name='Corolla', year=2025)
        r = self.post(self.URL, {'action': 'view', 'brand': 'Toyota', 'model': 'Corolla', 'year': 'x'},
                      **self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(ActivityLog.objects.get().car_id)

    def test_no_action_stores_nothing(self):
        self.assertEqual(self.post(self.URL, {'detail': 'x'}, **self.auth).status_code, 200)
        self.assertFalse(ActivityLog.objects.exists())


class CompanyRoleTests(Base):
    def url(self, cid=None, delete=False):
        return f'/api/admin/companies/{cid or self.co.id}/roles/' + ('delete/' if delete else '')

    def test_needs_the_admin_token_and_a_real_company(self):
        self.assertEqual(self.c.get(self.url()).status_code, 401)
        self.assertEqual(self.c.get(self.url(cid=999999), **self.admin).status_code, 404)
        self.assertEqual(self.post(self.url(cid=999999, delete=True), {'value': 'x'}, **self.admin).status_code, 404)

    def test_list_add_and_duplicate(self):
        roles = self.c.get(self.url(), **self.admin).json()['roles']
        self.assertTrue(roles)
        self.assertEqual(self.post(self.url(), {'value': '  '}, **self.admin).status_code, 400)
        r = self.post(self.url(), {'value': 'Night shift'}, **self.admin)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(CompanyRole.objects.filter(company=self.co, value='Night shift').exists())
        self.assertEqual(self.post(self.url(), {'value': 'Night shift'}, **self.admin).status_code, 409)

    def test_delete_an_unused_role_is_immediate(self):
        self.post(self.url(), {'value': 'Spare'}, **self.admin)
        self.assertEqual(self.c.get(self.url(delete=True), **self.admin).status_code, 405)
        self.assertEqual(self.post(self.url(delete=True), {}, **self.admin).status_code, 400)
        r = self.post(self.url(delete=True), {'value': 'Spare'}, **self.admin).json()
        self.assertEqual((r['ok'], r['reassigned']), (True, 0))
        self.assertFalse(CompanyRole.objects.filter(company=self.co, value='Spare').exists())

    def test_a_held_role_is_not_removed_without_a_replacement(self):
        self.post(self.url(), {'value': 'Lead'}, **self.admin)
        self.user.role = 'Lead'
        self.user.save(update_fields=['role'])
        r = self.post(self.url(delete=True), {'value': 'Lead'}, **self.admin).json()
        self.assertTrue(r['requires_reassign'])
        self.assertEqual([a['username'] for a in r['affected']], ['u1'])
        self.assertTrue(CompanyRole.objects.filter(company=self.co, value='Lead').exists())
        same = self.post(self.url(delete=True), {'value': 'Lead', 'reassign_to': 'Lead'}, **self.admin)
        self.assertEqual(same.status_code, 400)

        r = self.post(self.url(delete=True), {'value': 'Lead', 'reassign_to': 'Senior'}, **self.admin).json()
        self.assertEqual(r['reassigned'], 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, 'Senior')
        self.assertFalse(CompanyRole.objects.filter(company=self.co, value='Lead').exists())


class AdminReportTests(Base):
    def setUp(self):
        super().setUp()
        other = Company.objects.create(name='Other', active=True)
        self.other_user = PortalUser.objects.create(company=other, username='u2', password_hash='x')
        ActivityLog.objects.create(user=self.user, action='view', category='')
        ActivityLog.objects.create(user=self.user, action='search', category='')
        ActivityLog.objects.create(user=self.other_user, action='view', category='')

    def test_both_reports_need_the_admin_token(self):
        for url in ('/api/admin/activity/', '/api/admin/analytics/'):
            self.assertEqual(self.c.get(url).status_code, 401, url)

    def test_activity_filters_and_limit(self):
        get = lambda **q: self.c.get('/api/admin/activity/', q, **self.admin).json()['items']
        self.assertEqual(len(get()), 3)
        self.assertEqual(len(get(limit='1')), 1)
        self.assertEqual(len(get(limit='abc')), 3)
        self.assertEqual({i['user'] for i in get(user_id=self.user.id)}, {'u1'})
        self.assertEqual({i['company'] for i in get(company_id=self.co.id)}, {'Co'})
        self.assertEqual(get(category='nope'), [])

    def test_analytics_totals_and_breakdowns(self):
        d = self.c.get('/api/admin/analytics/', {'range': 'x'}, **self.admin).json()
        self.assertEqual(d['range_days'], 30)
        self.assertEqual(d['totals']['events'], 3)
        self.assertEqual(d['totals']['active_users'], 2)
        self.assertEqual(d['action_breakdown'], {'view': 2, 'search': 1})
        self.assertEqual(d['companies_usage'][0], {'company_id': self.co.id, 'company': 'Co', 'events': 2})
        self.assertEqual(sum(s['count'] for s in d['series']), 3)
        self.assertTrue(d['categories'])

    def test_analytics_by_company_and_range_clamp(self):
        d = self.c.get('/api/admin/analytics/', {'company_id': self.other_user.company_id, 'range': '9999'},
                       **self.admin).json()
        self.assertEqual(d['range_days'], 365)
        self.assertEqual(d['totals']['events'], 1)
        self.assertEqual([u['user'] for u in d['top_users']], ['u2'])


class AdminUsersTests(Base):
    URL = '/api/admin/users/'

    def give_root(self):
        from .models import OrgGraph, OrgNode
        root = PortalUser.objects.create(company=self.co, username='root', password_hash='x',
                                         phone='09120000001')
        graph = OrgGraph.objects.create(company=self.co)
        OrgNode.objects.create(graph=graph, is_root=True, occupant=root)
        return root

    def create(self, **kw):
        body = {'company_id': self.co.id, 'username': 'new1', 'role': 'technician',
                'phone': '09351234567', **kw}
        return self.post(self.URL, body, **self.admin)

    def test_needs_the_admin_token(self):
        self.assertEqual(self.c.get(self.URL).status_code, 401)

    def test_create_is_refused_without_a_company_or_its_root_seat(self):
        self.assertEqual(self.create(company_id=999999).status_code, 400)
        self.assertEqual(self.create().status_code, 400)
        self.assertFalse(PortalUser.objects.filter(username='new1').exists())

    def test_create_validates_role_username_and_phone(self):
        self.give_root()
        self.assertEqual(self.create(role='').status_code, 400)
        self.assertEqual(self.create(username='  ').status_code, 400)
        self.assertEqual(self.create(phone='').status_code, 400)
        self.assertEqual(self.create(phone='09120000001').status_code, 400)   # the root's number
        self.assertFalse(PortalUser.objects.filter(username='new1').exists())

    def test_create_respects_the_seat_cap(self):
        self.give_root()
        self.co.seats_count = PortalUser.objects.filter(company=self.co, active=True).count()
        self.co.save(update_fields=['seats_count'])
        self.assertEqual(self.create().status_code, 400)

    def test_create_returns_a_one_time_password_and_stores_only_its_hash(self):
        self.give_root()
        r = self.create(display_name='New One', reports_to_id=self.user.id)
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        u = PortalUser.objects.get(username='new1')
        self.assertNotEqual(u.password_hash, d['password'])
        self.assertTrue(u.check_password(d['password']))
        self.assertTrue(CompanyRole.objects.filter(company=self.co, value='technician').exists())
        self.assertEqual(self.create(phone='09351234568').status_code, 400)   # username taken

    def test_list_filters_by_company(self):
        other = Company.objects.create(name='Other', active=True)
        PortalUser.objects.create(company=other, username='o1', password_hash='x')
        d = self.c.get(self.URL, {'company_id': self.co.id}, **self.admin).json()
        self.assertEqual({i['username'] for i in d['items']}, {'u1'})
        self.assertIn('all_docs', d)
        self.assertEqual(len(self.c.get(self.URL, **self.admin).json()['items']), 2)


class AdminUserDetailTests(Base):
    def url(self, uid=None):
        return f'/api/admin/users/{uid or self.user.id}/'

    def test_unknown_user_is_404_and_get_returns_the_user(self):
        self.assertEqual(self.c.get(self.url(999999), **self.admin).status_code, 404)
        self.assertEqual(self.c.get(self.url(), **self.admin).json()['user']['username'], 'u1')

    def test_deactivating_or_locking_ends_the_sessions(self):
        self.post(self.url(), {'active': False}, **self.admin)
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())
        AuthToken.issue(self.user)
        self.post(self.url(), {'active': True, 'locked': True}, **self.admin)
        self.user.refresh_from_db()
        self.assertTrue(self.user.active and self.user.locked)
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())

    def test_profile_fields_and_switches(self):
        r = self.post(self.url(), {'display_name': ' Ali ', 'email': '', 'personnel_code': 'P1',
                                   'otp_enabled': True, 'can_manage_team': True,
                                   'can_view_analytics': True, 'ai_assistant_enabled': False},
                      **self.admin)
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual((self.user.display_name, self.user.email, self.user.personnel_code),
                         ('Ali', None, 'P1'))
        self.assertTrue(self.user.otp_enabled and self.user.can_manage_team and self.user.can_view_analytics)
        self.assertFalse(self.user.ai_assistant_enabled)

    def test_a_phone_already_in_use_is_refused(self):
        PortalUser.objects.create(company=self.co, username='u9', password_hash='x', phone='09127777777')
        self.assertEqual(self.post(self.url(), {'phone': '09127777777'}, **self.admin).status_code, 400)

    def test_reports_to_never_crosses_companies(self):
        # (Within a company the org-consistency pass owns the final line, so
        # only the cross-company refusal is pinned here.)
        outsider = PortalUser.objects.create(company=Company.objects.create(name='X', active=True),
                                             username='out', password_hash='x')
        self.assertEqual(self.post(self.url(), {'reports_to_id': outsider.id}, **self.admin).status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.reports_to_id)
        self.assertEqual(self.post(self.url(), {'reports_to_id': None}, **self.admin).status_code, 200)

    def test_password_set_and_reset_end_the_sessions(self):
        d = self.post(self.url(), {'password': 'chosen-pw'}, **self.admin).json()
        self.assertEqual(d['password'], 'chosen-pw')
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())
        AuthToken.issue(self.user)
        d = self.post(self.url(), {'reset_password': True}, **self.admin).json()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(d['password']))
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())

    def test_a_typed_role_joins_the_company_picker(self):
        self.post(self.url(), {'role': 'Diagnostician'}, **self.admin)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, 'Diagnostician')
        self.assertTrue(CompanyRole.objects.filter(company=self.co, value='Diagnostician').exists())

    def test_expiry_is_only_writable_on_the_root_seat(self):
        self.post(self.url(), {'access_expires_at': '2030-01-01'}, **self.admin)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.access_expires_at)

    def test_delete(self):
        self.assertTrue(self.post(self.url(), {'delete': True}, **self.admin).json()['deleted'])
        self.assertFalse(PortalUser.objects.filter(id=self.user.id).exists())
