"""Feature-discovery derivation (api/onboarding.py).

Spec: docs/superpowers/specs/2026-10-30-feature-discovery-onboarding-design.md

Completion is EARNED: a seat has discovered a feature when the activity log
already says so. There is no "mark as done", so these tests are about two
properties — that the right activity completes the right item, and that an item
the company has not bought is neither offered to the seat nor counted against
them in the metric.

Run:  python manage.py test api.test_onboarding
"""
import json

from django.test import Client, TestCase

from . import onboarding
from .models import (ActivityLog, AuthToken, Car, Company, CompanyRequest,
                     PortalUser, SearchLog, UserCarAccess)

URL = '/api/auth/onboarding/'


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


# ---------------------------------------------------------------------------
# The seat's own endpoint
# ---------------------------------------------------------------------------

class OnboardingEndpointTests(OnboardingBase):
    def setUp(self):
        super().setUp()
        self.c = Client()
        self.h = {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(self.seat).key}'}

    def post(self, body, hdr=None):
        return self.c.post(URL, json.dumps(body), content_type='application/json',
                           **(hdr or self.h))

    def test_signed_out_is_401(self):
        self.assertEqual(self.c.get(URL).status_code, 401)
        self.assertEqual(self.c.post(URL, '{}', content_type='application/json')
                         .status_code, 401)

    def test_the_payload_counts_done_against_entitled_items_only(self):
        ActivityLog.objects.create(user=self.seat, action='view_node')
        d = self.c.get(URL, **self.h).json()
        self.assertEqual(d['total'], len(d['items']))
        self.assertEqual(d['done'], sum(1 for i in d['items'] if i['done']))
        self.assertEqual(d['done'], 1)
        self.assertNotIn('ask_assistant', [i['id'] for i in d['items']])

    def test_a_seat_with_no_grants_gets_a_payload_it_can_render(self):
        """A freshly invited seat: one item, nothing done, nothing to divide by."""
        h = {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(self.bare).key}'}
        d = self.c.get(URL, **h).json()
        self.assertEqual([i['id'] for i in d['items']], ['ask_support'])
        self.assertEqual((d['done'], d['total'], d['dismissed']), (0, 1, False))

    def test_posting_dismissed_sets_the_timestamp_and_is_idempotent(self):
        self.assertEqual(self.post({'dismissed': True}).status_code, 200)
        self.seat.refresh_from_db()
        first = self.seat.onboarding_dismissed_at
        self.assertIsNotNone(first)
        self.assertEqual(self.post({'dismissed': True}).status_code, 200)
        self.seat.refresh_from_db()
        self.assertEqual(self.seat.onboarding_dismissed_at, first,
                         'a second dismissal must not restart the clock')

    def test_dismissal_survives_a_new_session(self):
        """The whole reason this is a column and not localStorage."""
        self.post({'dismissed': True})
        other_device = {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(self.seat).key}'}
        self.assertTrue(self.c.get(URL, **other_device).json()['dismissed'])

    def test_a_new_entitlement_after_dismissal_does_not_resurrect_the_strip(self):
        self.post({'dismissed': True})
        self.seat.can_manage_team = True
        self.seat.save(update_fields=['can_manage_team'])
        d = self.c.get(URL, **self.h).json()
        self.assertTrue(d['dismissed'])
        self.assertIn('invite_colleague', [i['id'] for i in d['items']],
                      'the items still describe reality; only the strip is hidden')

    def test_an_unknown_body_is_a_400_not_a_silent_success(self):
        self.assertEqual(self.post({'nonsense': True}).status_code, 400)

    def test_wrong_method_is_405(self):
        self.assertEqual(self.c.put(URL, '{}', content_type='application/json',
                                    **self.h).status_code, 405)
