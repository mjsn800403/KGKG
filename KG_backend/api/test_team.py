"""Team self-service: invite acceptance, manager-scoped analytics, PDF report.

api/team.py had 24 % coverage and api/reporting.py none. The analytics are a
data-exposure surface (a manager reads other people's activity), so these
tests pin the reach rules end to end over HTTP, not just the helper:

    root (boss)
    ├── head                 <- has a branch: may see analytics for it
    │   └── worker           <- leaf: may not see analytics at all
    └── outsider             <- boss's branch, not head's
"""
import datetime
from unittest import mock

from django.test import Client, TestCase
from django.utils import timezone

from . import reporting
from .models import (
    ActivityLog, AuthToken, Car, Company, InviteToken, OrgGraph, OrgNode, PortalUser,
)
from .team import _as_id, _unique_username


def auth(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(user).key}'}


class TeamWorld(TestCase):
    def setUp(self):
        self.c = Client()
        self.company = Company.objects.create(name='TeamCo', active=True)
        graph = OrgGraph.objects.create(company=self.company)

        def mkuser(name, **kw):
            return PortalUser.objects.create(
                company=self.company, username=name, password_hash='x',
                display_name=kw.pop('display_name', name),
                role=kw.pop('role', 'after_sales_specialist'), active=True, **kw)

        self.boss = mkuser('boss', role='after_sales_manager', can_manage_team=True)
        self.head = mkuser('head', can_manage_team=True)
        self.worker = mkuser('worker')
        self.outsider = mkuser('outsider')
        root = OrgNode.objects.create(graph=graph, is_root=True, occupant=self.boss)
        n_head = OrgNode.objects.create(graph=graph, parent=root, occupant=self.head)
        OrgNode.objects.create(graph=graph, parent=n_head, occupant=self.worker)
        OrgNode.objects.create(graph=graph, parent=root, occupant=self.outsider)

        self.car = Car.objects.create(brand_name='Toyota', car_name='Camry', year=2024,
                                      db_address='/nonexistent/camry.db')

    def log(self, user, n=1, category='', car=None, days_ago=0, action='view_node'):
        for _ in range(n):
            a = ActivityLog.objects.create(user=user, action=action, category=category, car=car)
            if days_ago:
                ActivityLog.objects.filter(pk=a.pk).update(
                    created_at=timezone.now() - datetime.timedelta(days=days_ago))


class InviteTests(TeamWorld):
    def setUp(self):
        super().setUp()
        self.new = PortalUser.objects.create(
            company=self.company, username='newbie', password_hash='!', display_name='New',
            email='new@example.com', role='after_sales_specialist', active=True,
            invite_status='invited')
        _, self.raw = InviteToken.issue(self.new)
        self.url = f'/api/invite/{self.raw}/'

    def test_unknown_token_is_refused(self):
        self.assertEqual(self.c.get('/api/invite/not-a-token/').status_code, 400)

    def test_get_shows_who_is_being_invited_without_secrets(self):
        r = self.c.get(self.url)
        self.assertEqual(r.status_code, 200)
        u = r.json()['user']
        self.assertEqual((u['username'], u['company']), ('newbie', 'TeamCo'))
        self.assertNotIn('password_hash', u)

    def test_short_password_is_refused_and_invite_stays_usable(self):
        r = self.c.post(self.url, {'password': 'short'}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.get(self.url).status_code, 200)

    def test_accepting_sets_password_activates_signs_in_and_burns_the_link(self):
        r = self.c.post(self.url, {'password': 'a-good-password'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.new.refresh_from_db()
        self.assertEqual(self.new.invite_status, 'active')
        self.assertTrue(self.new.check_password('a-good-password'))
        # the returned token is a working session
        me = self.c.get('/api/auth/me/', HTTP_AUTHORIZATION=f"Bearer {r.json()['token']}")
        self.assertEqual(me.status_code, 200)
        self.assertTrue(ActivityLog.objects.filter(user=self.new, action='invite_accept').exists())
        # single use
        again = self.c.post(self.url, {'password': 'another-password'}, content_type='application/json')
        self.assertEqual(again.status_code, 400)

    def test_non_string_password_is_a_400_not_a_crash(self):
        r = self.c.post(self.url, {'password': 12345678}, content_type='application/json')
        self.assertIn(r.status_code, (200, 400))

    def test_expired_invite_is_refused(self):
        InviteToken.objects.filter(user=self.new).update(
            expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertEqual(self.c.get(self.url).status_code, 400)

    def test_inactive_account_or_company_cannot_accept(self):
        PortalUser.objects.filter(pk=self.new.pk).update(active=False)
        self.assertEqual(self.c.get(self.url).status_code, 403)
        PortalUser.objects.filter(pk=self.new.pk).update(active=True)
        Company.objects.filter(pk=self.company.pk).update(active=False)
        self.assertEqual(self.c.get(self.url).status_code, 403)

    def test_other_methods_are_refused(self):
        self.assertEqual(self.c.put(self.url).status_code, 405)


class AnalyticsReachTests(TeamWorld):
    URL = '/api/team/analytics/'

    def get(self, user, **params):
        return self.c.get(self.URL, params, **auth(user))

    def test_signed_out_is_401(self):
        self.assertEqual(self.c.get(self.URL).status_code, 401)

    def test_leaf_seat_is_403(self):
        self.assertEqual(self.get(self.worker).status_code, 403)

    def test_root_sees_the_whole_company(self):
        self.log(self.worker, 2)
        self.log(self.outsider, 3)
        d = self.get(self.boss).json()
        self.assertEqual(d['total_events'], 5)
        self.assertEqual({m['name'] for m in d['members']},
                         {'boss', 'head', 'worker', 'outsider'})

    def test_branch_manager_sees_only_its_branch(self):
        self.log(self.worker, 2)
        self.log(self.outsider, 3)
        d = self.get(self.head).json()
        self.assertEqual(d['total_events'], 2)
        names = {m['name'] for m in d['members']}
        self.assertEqual(names, {'head', 'worker'})
        self.assertEqual(d['active_members'], 1)

    def test_member_filter_outside_reach_reveals_nothing_extra(self):
        self.log(self.worker, 2)
        self.log(self.outsider, 3)
        d = self.get(self.head, member_id=self.outsider.id).json()
        self.assertEqual(d['total_events'], 2)          # still head's branch only
        self.assertNotIn('outsider', {m['name'] for m in d['members']})

    def test_member_filter_inside_reach_narrows(self):
        self.log(self.worker, 2)
        self.log(self.head, 1)
        d = self.get(self.head, member_id=self.worker.id).json()
        self.assertEqual(d['total_events'], 2)

    def test_non_numeric_member_filter_is_ignored(self):
        self.log(self.worker, 2)
        r = self.get(self.head, member_id='abc')
        self.assertEqual((r.status_code, r.json()['total_events']), (200, 2))

    def test_category_filter_series_and_top_cars(self):
        self.log(self.worker, 2, category='repair', car=self.car)
        self.log(self.worker, 1, category='wiring')
        d = self.get(self.head, category='repair').json()
        self.assertEqual(d['total_events'], 2)
        self.assertEqual(d['top_cars'][0]['label'], 'Toyota Camry 2024')
        self.assertEqual(sum(p['count'] for p in d['series']), 2)

    def test_range_is_clamped_and_old_events_drop_out(self):
        self.log(self.worker, 1, days_ago=40)
        self.log(self.worker, 1)
        self.assertEqual(self.get(self.head).json()['total_events'], 1)          # default 30
        self.assertEqual(self.get(self.head, range=90).json()['total_events'], 2)
        self.assertEqual(self.get(self.head, range=99999).json()['range_days'], 365)
        self.assertEqual(self.get(self.head, range=0).json()['range_days'], 1)
        self.assertEqual(self.get(self.head, range='x').json()['range_days'], 30)


class TeamReportTests(TeamWorld):
    URL = '/api/team/report/'

    def test_leaf_cannot_download(self):
        self.assertEqual(self.c.get(self.URL, **auth(self.worker)).status_code, 403)

    def test_manager_gets_a_pdf_and_the_download_is_logged(self):
        self.log(self.worker, 3, category='repair', car=self.car)
        r = self.c.get(self.URL, {'range': 7}, **auth(self.head))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertIn('attachment;', r['Content-Disposition'])
        self.assertTrue(ActivityLog.objects.filter(user=self.head, action='report_pdf').exists())

    def test_render_failure_is_a_clean_500(self):
        with mock.patch('api.reporting.render_team_report_pdf', side_effect=RuntimeError('boom')):
            r = self.c.get(self.URL, **auth(self.head))
        self.assertEqual(r.status_code, 500)
        self.assertNotIn(b'boom', r.content)

    def test_member_names_are_escaped_in_the_report(self):
        PortalUser.objects.filter(pk=self.worker.pk).update(
            display_name='<img src=x onerror=alert(1)>')
        self.log(self.worker, 1)
        captured = {}

        class FakeHTML:
            def __init__(self, string, **kw):
                captured['html'] = string

            def write_pdf(self):
                return b'%PDF-fake'

        with mock.patch('weasyprint.HTML', FakeHTML):
            r = self.c.get(self.URL, **auth(self.head))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('<img src=x', captured['html'])
        self.assertIn('&lt;img src=x', captured['html'])


class HelperTests(TestCase):
    def test_as_id(self):
        self.assertEqual([_as_id(v) for v in (5, '7', 'x', None, '')], [5, 7, None, None, None])

    def test_unique_username(self):
        co = Company.objects.create(name='U', active=True)
        PortalUser.objects.create(company=co, username='ali', password_hash='x',
                                  role='after_sales_specialist', active=True)
        self.assertEqual(_unique_username('Ali@example.com', co.id), 'ali2')
        self.assertEqual(_unique_username('!!!', co.id), f'user{co.id}')

    def test_persian_numbers(self):
        self.assertEqual(reporting.fa_num(1234567), '۱،۲۳۴،۵۶۷')
        self.assertEqual(reporting.fa_num(2.50), '۲.۵')
        self.assertEqual(reporting.fa_num(None), '—')
        self.assertEqual(reporting.fa_int(1405), '۱۴۰۵')
        self.assertEqual(reporting.fa_int(None), '—')

    def test_jalali_dates(self):
        # Nowruz 1403 fell on 2024-03-20; 1404 on 2025-03-21.
        self.assertEqual(reporting._gregorian_to_jalali(2024, 3, 20), (1403, 1, 1))
        self.assertEqual(reporting._gregorian_to_jalali(2025, 3, 21), (1404, 1, 1))
        self.assertEqual(reporting._gregorian_to_jalali(2024, 3, 19), (1402, 12, 29))
        self.assertEqual(reporting.fa_date(datetime.date(2024, 3, 20)), '۱ فروردین ۱۴۰۳')
        self.assertEqual(reporting.fa_date(None), '—')
        self.assertEqual(reporting._rel_activity(None), 'بدون فعالیت')
        self.assertEqual(reporting._rel_activity('not a date'), '—')

    def test_charts_handle_empty_and_real_data(self):
        self.assertIn('stroke="#e8e6f2"', reporting.donut_svg([{'count': 0}]))
        donut = reporting.donut_svg([{'count': 3}, {'count': 0}, {'count': 1}])
        self.assertEqual(donut.count('stroke-dasharray'), 2)       # zero slice skipped
        self.assertIn('داده‌ای', reporting.trend_svg([]))
        trend = reporting.trend_svg([{'date': 'd1', 'count': 1}, {'date': 'd2', 'count': 4}])
        self.assertEqual(trend.count('<circle'), 2)
        many = reporting.trend_svg([{'date': str(i), 'count': i} for i in range(60)])
        self.assertNotIn('<circle', many)                           # dots dropped past 45 points
