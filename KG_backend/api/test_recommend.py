"""Recommendation engine: continue / focus / popular / explore + manager insights.

The graph-based 'related' section needs the RAG index and is covered by a live
smoke test elsewhere; here we exercise the DB-only paths deterministically."""
from django.test import TestCase, Client, override_settings

from .models import (
    ActivityLog, AuthToken, Car, Company, CompanyCarAccess, PortalUser,
    UserCarAccess,
)
from .access import seed_default_org_roles
from . import recommend


class RecommendUserTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RecCo')
        seed_default_org_roles(self.company)
        roles = {r.rank: r for r in self.company.org_roles.all()}
        self.car1 = Car.objects.create(brand_name='Toyota', car_name='bZ4X', year=2023, db_address='x')
        self.car2 = Car.objects.create(brand_name='Lexus', car_name='NX', year=2022, db_address='y')
        for c in (self.car1, self.car2):
            CompanyCarAccess.objects.create(company=self.company, car=c, documents=['manual'])
        self.user = PortalUser(company=self.company, username='rec_u',
                               role='after_sales_specialist', org_role=roles[4])
        self.user.set_password('p'); self.user.save()
        self.peer = PortalUser(company=self.company, username='rec_peer',
                               role='after_sales_specialist', org_role=roles[4])
        self.peer.set_password('p'); self.peer.save()
        for c in (self.car1, self.car2):
            UserCarAccess.objects.create(user=self.user, car=c, documents=['manual'])
            UserCarAccess.objects.create(user=self.peer, car=c, documents=['manual'])

    def test_continue_returns_recent_distinct_views(self):
        ActivityLog.objects.create(user=self.user, action='view_node', category='brakes',
                                   car=self.car1, node_title='Brake fluid',
                                   app_url='/Toyota/2023/bZ4X/Brakes/Fluid')
        ActivityLog.objects.create(user=self.user, action='view_node', category='engine',
                                   car=self.car1, node_title='Oil change',
                                   app_url='/Toyota/2023/bZ4X/Engine/Oil')
        rec = recommend.recommend_for_user(self.user)
        urls = [x['app_url'] for x in rec['continue']]
        self.assertIn('/Toyota/2023/bZ4X/Engine/Oil', urls)
        self.assertEqual(urls[0], '/Toyota/2023/bZ4X/Engine/Oil')   # newest first

    def test_focus_areas_reflect_engagement(self):
        for _ in range(3):
            ActivityLog.objects.create(user=self.user, action='view_node', category='brakes',
                                       car=self.car1, node_title='B', app_url='/u/b')
        ActivityLog.objects.create(user=self.user, action='view_node', category='engine',
                                   car=self.car1, node_title='E', app_url='/u/e')
        rec = recommend.recommend_for_user(self.user)
        cats = [a['category'] for a in rec['focus_areas']['areas']]
        self.assertEqual(cats[0], 'brakes')     # strongest first

    def test_popular_in_company_from_peers_excludes_self_and_seen(self):
        # Peer views a brake section a lot; user hasn't seen it -> recommended.
        for _ in range(4):
            ActivityLog.objects.create(user=self.peer, action='view_node', category='brakes',
                                       car=self.car1, node_title='Peer fav',
                                       app_url='/Toyota/2023/bZ4X/Brakes/Peer')
        rec = recommend.recommend_for_user(self.user)
        urls = [x['app_url'] for x in rec['popular']]
        self.assertIn('/Toyota/2023/bZ4X/Brakes/Peer', urls)
        # A section the user already saw is not re-recommended as popular.
        ActivityLog.objects.create(user=self.user, action='view_node', category='brakes',
                                   car=self.car1, node_title='Peer fav',
                                   app_url='/Toyota/2023/bZ4X/Brakes/Peer')
        rec2 = recommend.recommend_for_user(self.user)
        self.assertNotIn('/Toyota/2023/bZ4X/Brakes/Peer',
                         [x['app_url'] for x in rec2['popular']])

    def test_explore_lists_unopened_granted_cars(self):
        ActivityLog.objects.create(user=self.user, action='view_node', car=self.car1,
                                   node_title='X', app_url='/u/x')
        rec = recommend.recommend_for_user(self.user)
        explored = [e['car'] for e in rec['explore']]
        self.assertTrue(any('NX' in e for e in explored))     # car2 never opened
        self.assertFalse(any('bZ4X' in e for e in explored))  # car1 opened

    def test_no_grants_no_crash(self):
        u2 = PortalUser(company=self.company, username='rec_empty',
                        role='after_sales_specialist')
        u2.set_password('p'); u2.save()
        rec = recommend.recommend_for_user(u2)      # no grants, no activity
        self.assertEqual(rec['continue'], [])
        self.assertEqual(rec['explore'], [])


@override_settings(DEBUG=True)
class RecommendEndpointTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.company = Company.objects.create(name='RecEpCo')
        seed_default_org_roles(self.company)
        roles = {r.rank: r for r in self.company.org_roles.all()}
        self.mgr = PortalUser(company=self.company, username='rec_mgr',
                              role='after_sales_manager', org_role=roles[1],
                              can_manage_team=True, can_view_analytics=True)
        self.mgr.set_password('p'); self.mgr.save()
        self.spec = PortalUser(company=self.company, username='rec_sp',
                               role='after_sales_specialist', org_role=roles[4],
                               reports_to=self.mgr)
        self.spec.set_password('p'); self.spec.save()

    def test_recommendations_requires_login(self):
        self.assertEqual(self.c.get('/api/recommendations/').status_code, 401)

    def test_recommendations_ok_for_user(self):
        tok = AuthToken.issue(self.spec).key
        r = self.c.get('/api/recommendations/', HTTP_AUTHORIZATION=f'Bearer {tok}')
        self.assertEqual(r.status_code, 200)
        self.assertIn('continue', r.json())

    def test_insights_requires_manager_capability(self):
        tok = AuthToken.issue(self.spec).key   # plain specialist
        r = self.c.get('/api/team/insights/', HTTP_AUTHORIZATION=f'Bearer {tok}')
        self.assertEqual(r.status_code, 403)

    def test_insights_for_manager(self):
        ActivityLog.objects.create(user=self.spec, action='view_node', category='engine')
        tok = AuthToken.issue(self.mgr).key
        r = self.c.get('/api/team/insights/', HTTP_AUTHORIZATION=f'Bearer {tok}')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('seat_utilisation', data)
        self.assertIn('category_gaps', data)
        member_ids = {m['id'] for m in data['members']}
        self.assertIn(self.spec.id, member_ids)
