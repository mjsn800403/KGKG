"""Feature-discovery derivation (api/onboarding.py).

Spec: docs/superpowers/specs/2026-10-30-feature-discovery-onboarding-design.md

Completion is EARNED: a seat has discovered a feature when the activity log
already says so. There is no "mark as done", so these tests are about two
properties — that the right activity completes the right item, and that an item
the company has not bought is neither offered to the seat nor counted against
them in the metric.

Run:  python manage.py test api.test_onboarding
"""
from django.test import TestCase

from . import onboarding
from .models import (ActivityLog, Car, Company, CompanyRequest, PortalUser,
                     SearchLog, UserCarAccess)


class OnboardingBase(TestCase):
    def setUp(self):
        self.co = Company.objects.create(name='Onb Co')
        self.car = Car.objects.create(brand_name='Toyota', car_name='Camry', year=2021,
                                      db_address='c.db')
        self.seat = PortalUser.objects.create(company=self.co, username='onb_seat',
                                              role='after_sales_specialist')
        self.bare = PortalUser.objects.create(company=self.co, username='onb_bare',
                                              role='after_sales_specialist')
        # A full grant: empty documents means "every layer the company grants".
        UserCarAccess.objects.create(user=self.seat, car=self.car, documents=[],
                                     admin_granted=True)

    # -- helpers ----------------------------------------------------------
    def ids(self, user):
        return [i['id'] for i in onboarding.progress_for(user)]

    def done(self, user, item_id):
        for i in onboarding.progress_for(user):
            if i['id'] == item_id:
                return i['done']
        return None            # not offered at all


class EntitlementTests(OnboardingBase):
    def test_a_seat_with_no_grants_is_offered_only_what_needs_none(self):
        """A freshly invited seat with nothing assigned. Filing a support
        request needs no entitlement; everything else does."""
        self.assertEqual(self.ids(self.bare), ['ask_support'])

    def test_the_assistant_item_follows_user_ai_eligible_exactly(self):
        from . import access
        self.assertFalse(access.user_ai_eligible(self.seat))
        self.assertIsNone(self.done(self.seat, 'ask_assistant'))

        self.seat.ai_assistant_enabled = True
        self.seat.save(update_fields=['ai_assistant_enabled'])
        self.co.ai_assistant_enabled = True
        self.co.save(update_fields=['ai_assistant_enabled'])
        self.seat.refresh_from_db()
        self.assertEqual(access.user_ai_eligible(self.seat),
                         'ask_assistant' in self.ids(self.seat),
                         'the item must agree with access.user_ai_eligible, not '
                         'with a second definition of eligibility')

    def test_the_parts_item_needs_a_grant_that_includes_parts(self):
        UserCarAccess.objects.filter(user=self.seat).update(documents=['manual'])
        self.assertIsNone(self.done(self.seat, 'open_parts'))
        UserCarAccess.objects.filter(user=self.seat).update(documents=['manual', 'parts'])
        self.assertIs(self.done(self.seat, 'open_parts'), False)

    def test_manager_items_need_can_manage_team(self):
        self.assertIsNone(self.done(self.seat, 'invite_colleague'))
        self.seat.can_manage_team = True
        self.seat.save(update_fields=['can_manage_team'])
        self.assertIs(self.done(self.seat, 'invite_colleague'), False)
        self.assertIs(self.done(self.seat, 'read_team_report'), False)


class CompletionTests(OnboardingBase):
    def test_asking_the_assistant_completes_it_but_opening_does_not(self):
        self.seat.ai_assistant_enabled = True
        self.seat.save(update_fields=['ai_assistant_enabled'])
        self.co.ai_assistant_enabled = True
        self.co.save(update_fields=['ai_assistant_enabled'])

        ActivityLog.objects.create(user=self.seat, action='open_assistant')
        self.assertIs(self.done(self.seat, 'ask_assistant'), False,
                      'opening the panel and leaving is not discovery')
        ActivityLog.objects.create(user=self.seat, action='ask_assistant')
        self.assertIs(self.done(self.seat, 'ask_assistant'), True)

    def test_reading_a_manual_completes_read_manual(self):
        self.assertIs(self.done(self.seat, 'read_manual'), False)
        ActivityLog.objects.create(user=self.seat, action='view_section')
        self.assertIs(self.done(self.seat, 'read_manual'), True)

    def test_a_search_completes_use_search(self):
        self.assertIs(self.done(self.seat, 'use_search'), False)
        SearchLog.objects.create(user_id=self.seat.id, query='brake', query_norm='brake')
        self.assertIs(self.done(self.seat, 'use_search'), True)

    def test_a_filed_ticket_completes_ask_support(self):
        self.assertIs(self.done(self.seat, 'ask_support'), False)
        CompanyRequest.objects.create(company=self.co, created_by=self.seat,
                                      subject='help')
        self.assertIs(self.done(self.seat, 'ask_support'), True)

    def test_a_colleagues_activity_does_not_complete_my_item(self):
        ActivityLog.objects.create(user=self.bare, action='view_section')
        CompanyRequest.objects.create(company=self.co, created_by=self.bare, subject='x')
        self.assertIs(self.done(self.seat, 'read_manual'), False)
        self.assertIs(self.done(self.seat, 'ask_support'), False)


class DiscoveryCountsTests(OnboardingBase):
    def test_an_unentitled_seat_is_in_neither_numerator_nor_denominator(self):
        counts = onboarding.discovery_counts([self.bare])
        self.assertEqual(counts['open_parts']['entitled'], 0)
        self.assertEqual(counts['open_parts']['discovered'], 0)
        self.assertIsNone(counts['open_parts']['rate'])

    def test_discovered_never_exceeds_entitled_after_a_grant_is_revoked(self):
        ActivityLog.objects.create(user=self.seat, action='parts_view')
        self.assertEqual(onboarding.discovery_counts([self.seat])['open_parts'],
                         {'entitled': 1, 'discovered': 1, 'rate': 1.0})
        UserCarAccess.objects.filter(user=self.seat).delete()
        after = onboarding.discovery_counts([self.seat])['open_parts']
        self.assertEqual(after['entitled'], 0)
        self.assertLessEqual(after['discovered'], after['entitled'])

    def test_a_rate_with_no_entitled_seats_is_none_not_zero(self):
        self.assertIsNone(onboarding.discovery_counts([])['read_manual']['rate'])

    def test_the_rate_is_discovered_over_entitled(self):
        other = PortalUser.objects.create(company=self.co, username='onb_two',
                                          role='after_sales_specialist')
        UserCarAccess.objects.create(user=other, car=self.car, documents=[],
                                     admin_granted=True)
        ActivityLog.objects.create(user=self.seat, action='view_node')
        counts = onboarding.discovery_counts([self.seat, other])['read_manual']
        self.assertEqual((counts['entitled'], counts['discovered']), (2, 1))
        self.assertAlmostEqual(counts['rate'], 0.5)


class QueryCostTests(OnboardingBase):
    def test_progress_does_not_grow_with_activity_volume(self):
        """The heaviest production seat has ~47,000 activity rows. Derivation
        must ask `exists()` questions, never load them: the cost of the
        checklist cannot scale with how much someone has used the product."""
        ActivityLog.objects.bulk_create(
            [ActivityLog(user=self.seat, action='view_node') for _ in range(10)])
        few = self._count_queries(self.seat)
        ActivityLog.objects.bulk_create(
            [ActivityLog(user=self.seat, action='view_node') for _ in range(500)])
        many = self._count_queries(self.seat)
        self.assertEqual(few, many)

    def _count_queries(self, user):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        with CaptureQueriesContext(connection) as ctx:
            onboarding.progress_for(user)
        return len(ctx)
