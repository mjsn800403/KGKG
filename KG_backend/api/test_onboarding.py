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
    def test_a_seat_with_no_grants_is_offered_nothing(self):
        """Changed by the 2026-10-30 review (finding 3): `ask_support` used to
        be entitled unconditionally, so a freshly invited seat with no vehicles
        saw a strip whose only suggestion was "file a support ticket". Their
        screen already tells them to contact their administrator."""
        self.assertEqual(self.ids(self.bare), [])

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
        self.assertIs(self.done(self.seat, 'invite_colleague'), True,
                      'the company already has another seat')
        # read_team_report follows the org-graph gate, not this flag — see
        # test_the_team_report_item_follows_the_gate_that_actually_serves_it.
        self.assertIsNone(self.done(self.seat, 'read_team_report'))


class ReviewFixTests(OnboardingBase):
    """Findings from the 2026-10-30 whole-branch review. Each test fails on the
    code as first written."""

    def test_an_item_is_never_offered_against_an_action_nothing_writes(self):
        """FINDING 1 (critical). `invite_colleague` completed on an ActivityLog
        action `team_add`, which NOTHING in the product writes. Most actions
        are sent by the frontend to POST /api/activity/ (see logActivity); the
        backend writes a few directly. `team_add` appears only as a KEY in two
        Persian label maps — a display string for an action nobody logs.

        The item could never tick: a manager who had invited their whole team
        was told to invite someone on every page load, and the metric reported
        a permanent 0 % to management. Every completion signal must be an
        action some code path actually produces, or be derived from state.
        """
        import os
        import re
        from . import onboarding
        roots = [os.path.join(os.getcwd(), 'api'),
                 os.path.abspath(os.path.join(os.getcwd(), '..', 'kg_frontend', 'src'))]
        written = set()
        for root in roots:
            for dirpath, _dirs, files in os.walk(root):
                if 'node_modules' in dirpath or '__pycache__' in dirpath:
                    continue
                for name in files:
                    if not name.endswith(('.py', '.js', '.jsx', '.ts', '.tsx')):
                        continue
                    if name.startswith('test') or 'onboarding' in name:
                        continue        # a reader is not a writer
                    try:
                        src = open(os.path.join(dirpath, name), encoding='utf-8').read()
                    except OSError:
                        continue
                    # A quoted literal is a value being sent or stored. An
                    # object KEY (`team_add: 'label'`) is not, which is exactly
                    # how the defect hid.
                    written |= set(re.findall(r"""['"]([a-z_]{3,30})['"]""", src))
        for action in onboarding.ACTIONS_USED:
            self.assertIn(action, written,
                          f"onboarding completes on ActivityLog action "
                          f"'{action}', which no code path writes")

    def test_a_manager_who_already_has_a_team_has_discovered_inviting(self):
        """FINDING 1, the half that must stay true for existing customers. A
        manager whose company already has colleagues plainly knows the feature
        exists; the item is about discovery, so it is satisfied by the state
        rather than by an action nobody logged at the time."""
        alone = Company.objects.create(name='Onb Solo')
        boss = PortalUser.objects.create(company=alone, username='onb_boss',
                                         role='after_sales_manager',
                                         can_manage_team=True)
        UserCarAccess.objects.create(user=boss, car=self.car, documents=[],
                                     admin_granted=True)
        self.assertIs(self.done(boss, 'invite_colleague'), False)
        PortalUser.objects.create(company=alone, username='onb_colleague',
                                  role='after_sales_specialist')
        self.assertIs(self.done(boss, 'invite_colleague'), True)

    def test_the_team_report_item_follows_the_gate_that_actually_serves_it(self):
        """FINDING 2 (critical). The item was offered on `can_manage_team`, but
        /api/team/analytics/ is gated by orggraph.user_can_view_team — an
        org-graph position test. A manager at a leaf node was handed the item
        and got a 403 for following it: precisely the "manufactures support
        tickets" harm the module exists to avoid."""
        from . import orggraph
        self.seat.can_manage_team = True
        self.seat.save(update_fields=['can_manage_team'])
        self.assertFalse(orggraph.user_can_view_team(self.seat))
        self.assertIsNone(self.done(self.seat, 'read_team_report'),
                          'offered an item whose page would refuse them')

    def test_a_seat_with_nothing_assigned_is_offered_nothing(self):
        """FINDING 3. `ask_support` was entitled unconditionally, so a freshly
        invited seat with no vehicles saw a strip whose only suggestion was
        "file a support ticket" — the product's first instruction to a new
        user. It also made the frontend's own "empty payload" test pin a state
        the server could not produce."""
        self.assertEqual(self.ids(self.bare), [])

    def test_vehicle_scoped_items_do_not_link_to_the_page_they_appear_on(self):
        """FINDING 6. Search, parts and the CSV exports all live under a
        vehicle. They were given href='/browse' — the page the strip itself is
        rendered on — so three of eight pointers pointed at themselves."""
        from . import onboarding
        for item in onboarding.ITEMS:
            if item.id in ('use_search', 'open_parts', 'export_times'):
                self.assertIsNone(item.href,
                                  f'{item.id} must not pretend to be a link')


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

    def test_seats_that_have_never_signed_in_are_not_counted_as_failures(self):
        """FINDING 5. `active=True` includes invited seats that have never set a
        password and cannot sign in. Counting them as discovery failures is the
        same error the module docstring rejects for unentitled seats."""
        invited = PortalUser.objects.create(company=self.co, username='onb_invited',
                                            role='after_sales_specialist')
        invited.password_set = False
        invited.save(update_fields=['password_set'])
        UserCarAccess.objects.create(user=invited, car=self.car, documents=[],
                                     admin_granted=True)
        counts = onboarding.discovery_counts(onboarding.measurable_seats())
        self.assertNotIn(invited.id,
                         [u.id for u in onboarding.measurable_seats()],
                         'a seat that cannot sign in cannot discover anything')
        self.assertEqual(counts['read_manual']['entitled'], 1)

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
        """Re-fetch the seat each time: Django caches related managers on the
        instance, so measuring twice on one object compares a warm call with a
        cold one and reports a difference that has nothing to do with the
        activity volume under test."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        fresh = PortalUser.objects.get(id=user.id)
        with CaptureQueriesContext(connection) as ctx:
            onboarding.progress_for(fresh)
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
        self.assertEqual(d['items'], [])
        self.assertEqual((d['done'], d['total'], d['dismissed']), (0, 0, False))

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
