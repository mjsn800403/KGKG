"""Service-desk tests: the capabilities the 2026-10-30 evaluation found missing
from the request/ticket channel (api/requests_api.py, api/sla.py, api/feedback.py).

Covered here, each the fix for a named root cause in
audit-evidence/16-improvement-programme/ROOT_CAUSE_ANALYSIS.md §Finding 4:

  * the channel is open to every seat, not only managers (the reason feedback
    arrived by telephone), with the commercial kinds still manager-only;
  * a real conversation thread, with admin-only internal notes;
  * an assignee that is a foreign key, not a free-text string;
  * SLA response/resolution clocks with a stated policy and a breach state;
  * reopen, so a problem's true resolution time is knowable;
  * CSAT after closure;
  * a `source` field, so the shift away from the telephone is measurable;
  * a general feedback channel that is not a support request;
  * support metrics computed from all of the above.

Real HTTP stack, real models, nothing mocked.

Run:  python manage.py test api.test_helpdesk
"""
import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from . import events as events_mod
from . import sla
from .models import (AdminAuthToken, AuthToken, Company, CompanyRequest, Event,
                     Feedback, PlatformAdmin, PortalUser, TicketMessage)

URL = '/api/company/requests/'
ADMIN_URL = '/api/admin/company-requests/'
METRICS_URL = '/api/admin/support/metrics/'
FEEDBACK_URL = '/api/feedback/submit/'
ADMIN_FEEDBACK_URL = '/api/admin/feedback/'


def _bearer(key):
    return {'HTTP_AUTHORIZATION': f'Bearer {key}'}


class DeskBase(TestCase):
    def setUp(self):
        self.c = Client()
        self.co_a = Company.objects.create(name='Desk A')
        self.co_b = Company.objects.create(name='Desk B')
        self.mgr = PortalUser.objects.create(company=self.co_a, username='desk_mgr',
                                             role='after_sales_manager',
                                             can_manage_team=True, display_name='Mgr')
        self.spec = PortalUser.objects.create(company=self.co_a, username='desk_spec',
                                              role='after_sales_specialist',
                                              display_name='Spec')
        self.spec2 = PortalUser.objects.create(company=self.co_a, username='desk_spec2',
                                               role='after_sales_specialist')
        self.other = PortalUser.objects.create(company=self.co_b, username='desk_other',
                                               role='after_sales_specialist')
        self.admin = PlatformAdmin.objects.create(username='desk_admin',
                                                  password_hash='x', active=True)
        self.admin2 = PlatformAdmin.objects.create(username='desk_admin2',
                                                   password_hash='x', active=True)
        self.h_mgr = _bearer(AuthToken.issue(self.mgr).key)
        self.h_spec = _bearer(AuthToken.issue(self.spec).key)
        self.h_spec2 = _bearer(AuthToken.issue(self.spec2).key)
        self.h_other = _bearer(AuthToken.issue(self.other).key)
        self.h_admin = _bearer(AdminAuthToken.issue(self.admin).key)
        self.h_admin2 = _bearer(AdminAuthToken.issue(self.admin2).key)

    def post(self, url, body, hdr):
        return self.c.post(url, json.dumps(body), content_type='application/json', **hdr)

    def create(self, hdr=None, **body):
        body.setdefault('subject', 'The brake chapter will not open')
        body.setdefault('kind', 'support')
        r = self.post(URL, body, hdr or self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['request']


# ---------------------------------------------------------------------------
# A. The channel itself — root cause of "feedback arrives by telephone"
# ---------------------------------------------------------------------------

class ChannelAccessTests(DeskBase):
    def test_a_specialist_can_open_a_support_ticket(self):
        """The whole finding: before this change require_manager made every
        non-manager seat a 403, leaving the telephone as the only channel."""
        r = self.post(URL, {'kind': 'support', 'subject': 'No brake chapter'}, self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        req = CompanyRequest.objects.get(id=r.json()['request']['id'])
        self.assertEqual(req.created_by_id, self.spec.id)
        self.assertEqual(req.company_id, self.co_a.id)

    def test_a_specialist_may_not_open_a_commercial_request(self):
        for kind in ('seats', 'vehicle_access', 'ai_assistant', 'documents'):
            r = self.post(URL, {'kind': kind, 'subject': 'x'}, self.h_spec)
            self.assertEqual(r.status_code, 403, f'{kind}: {r.content}')
        self.assertFalse(CompanyRequest.objects.exists())

    def test_a_manager_may_open_every_kind(self):
        for kind in ('seats', 'vehicle_access', 'ai_assistant', 'documents',
                     'support', 'other'):
            r = self.post(URL, {'kind': kind, 'subject': 'x'}, self.h_mgr)
            self.assertEqual(r.status_code, 200, f'{kind}: {r.content}')

    def test_signed_out_is_still_401(self):
        self.assertEqual(self.c.get(URL).status_code, 401)
        self.assertEqual(self.c.post(URL, '{}', content_type='application/json').status_code, 401)

    def test_a_specialist_sees_only_their_own_tickets(self):
        mine = self.create(hdr=self.h_spec, subject='Mine')
        self.create(hdr=self.h_spec2, subject='Colleague')
        self.create(hdr=self.h_mgr, subject='Manager')
        got = self.c.get(URL, **self.h_spec).json()['requests']
        self.assertEqual([x['id'] for x in got], [mine['id']])

    def test_a_manager_sees_every_ticket_in_the_company(self):
        a = self.create(hdr=self.h_spec, subject='Mine')
        b = self.create(hdr=self.h_mgr, subject='Manager')
        got = self.c.get(URL, **self.h_mgr).json()['requests']
        self.assertEqual(sorted(x['id'] for x in got), sorted([a['id'], b['id']]))

    def test_a_specialist_cannot_read_a_colleagues_ticket(self):
        theirs = self.create(hdr=self.h_spec2)
        self.assertEqual(self.c.get(f"{URL}{theirs['id']}/", **self.h_spec).status_code, 404)

    def test_another_company_cannot_read_the_ticket(self):
        mine = self.create(hdr=self.h_spec)
        self.assertEqual(self.c.get(f"{URL}{mine['id']}/", **self.h_other).status_code, 404)


# ---------------------------------------------------------------------------
# B. The conversation thread
# ---------------------------------------------------------------------------

class ThreadTests(DeskBase):
    def test_creation_seeds_the_opening_message_from_the_body(self):
        req = self.create(body='It returns an empty page.')
        msgs = TicketMessage.objects.filter(request_id=req['id'])
        self.assertEqual(msgs.count(), 1)
        m = msgs.first()
        self.assertEqual(m.body, 'It returns an empty page.')
        self.assertEqual(m.author_user_id, self.spec.id)
        self.assertFalse(m.internal)

    def test_creation_without_a_body_seeds_no_message(self):
        req = self.create(body='')
        self.assertEqual(TicketMessage.objects.filter(request_id=req['id']).count(), 0)

    def test_the_customer_can_reply_and_the_thread_is_returned(self):
        req = self.create(body='first')
        r = self.post(f"{URL}{req['id']}/", {'message': 'and another thing'}, self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        thread = r.json()['request']['messages']
        self.assertEqual([m['body'] for m in thread], ['first', 'and another thing'])
        self.assertEqual(thread[-1]['author']['kind'], 'user')

    def test_an_empty_message_is_rejected(self):
        req = self.create()
        r = self.post(f"{URL}{req['id']}/", {'message': '   '}, self.h_spec)
        self.assertEqual(r.status_code, 400)

    def test_an_admin_public_reply_reaches_the_customer(self):
        req = self.create()
        r = self.post(f"{ADMIN_URL}{req['id']}/", {'message': 'Fixed in 1.0.1'}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        seen = self.c.get(f"{URL}{req['id']}/", **self.h_spec).json()['request']['messages']
        self.assertEqual([m['body'] for m in seen], ['Fixed in 1.0.1'])
        self.assertEqual(seen[0]['author'], {'kind': 'admin', 'name': 'desk_admin'})

    def test_an_internal_note_is_never_shown_to_the_customer(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/",
                  {'message': 'customer is on an old build', 'internal': True}, self.h_admin)
        customer = self.c.get(f"{URL}{req['id']}/", **self.h_spec).json()['request']
        self.assertEqual(customer['messages'], [])
        admin = self.c.get(f"{ADMIN_URL}{req['id']}/", **self.h_admin).json()['request']
        self.assertEqual([m['internal'] for m in admin['messages']], [True])

    def test_a_customer_message_on_a_closed_ticket_reopens_it(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'status': 'completed'}, self.h_admin)
        r = self.post(f"{URL}{req['id']}/", {'message': 'still broken'}, self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        row = CompanyRequest.objects.get(id=req['id'])
        self.assertEqual(row.status, 'pending')
        self.assertEqual(row.reopen_count, 1)
        self.assertIsNone(row.resolved_at)
        self.assertTrue(Event.objects.filter(type='request.reopened').exists())

    def test_a_message_from_another_company_is_a_404_and_writes_nothing(self):
        req = self.create(body='opening')
        r = self.post(f"{URL}{req['id']}/", {'message': 'hello'}, self.h_other)
        self.assertEqual(r.status_code, 404)
        # only the opening message the filer wrote
        self.assertEqual(TicketMessage.objects.filter(request_id=req['id']).count(), 1)


# ---------------------------------------------------------------------------
# C. SLA policy and clocks
# ---------------------------------------------------------------------------

class SlaPolicyTests(TestCase):
    def test_every_priority_has_a_policy(self):
        for p, _ in CompanyRequest.PRIORITY_CHOICES:
            self.assertIn(p, sla.POLICY)
            resp, res = sla.POLICY[p]
            self.assertLess(resp, res, f'{p}: response target must be tighter than resolution')

    def test_due_dates_are_the_policy_added_to_the_clock_start(self):
        start = timezone.now()
        resp, res = sla.due_dates('high', start)
        self.assertEqual(resp - start, sla.POLICY['high'][0])
        self.assertEqual(res - start, sla.POLICY['high'][1])

    def test_an_unknown_priority_falls_back_to_normal(self):
        start = timezone.now()
        self.assertEqual(sla.due_dates('nonsense', start), sla.due_dates('normal', start))

    def test_response_state_is_pending_met_or_breached(self):
        now = timezone.now()
        due = now - timedelta(hours=1)
        self.assertEqual(sla.state(due, None, now), 'breached')
        self.assertEqual(sla.state(due, due - timedelta(minutes=1), now), 'met')
        self.assertEqual(sla.state(due, due + timedelta(minutes=1), now), 'breached')
        self.assertEqual(sla.state(now + timedelta(hours=1), None, now), 'pending')

    def test_no_due_date_has_no_state(self):
        self.assertIsNone(sla.state(None, None, timezone.now()))


class SlaOnTicketTests(DeskBase):
    def test_creation_stamps_both_due_dates_from_the_policy(self):
        req = self.create(priority='high')
        row = CompanyRequest.objects.get(id=req['id'])
        resp, res = sla.due_dates('high', row.created_at)
        self.assertEqual(row.sla_response_due_at, resp)
        self.assertEqual(row.sla_resolve_due_at, res)
        self.assertEqual(req['sla']['response_state'], 'pending')

    def test_the_first_public_admin_reply_stamps_first_response_once(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'message': 'looking'}, self.h_admin)
        first = CompanyRequest.objects.get(id=req['id']).first_response_at
        self.assertIsNotNone(first)
        self.post(f"{ADMIN_URL}{req['id']}/", {'message': 'still looking'}, self.h_admin)
        self.assertEqual(CompanyRequest.objects.get(id=req['id']).first_response_at, first)

    def test_a_public_admin_note_also_counts_as_a_first_response(self):
        """The admin_note field is the platform's REPLY — the customer reads it
        on their own ticket. An agent who answers by filling it in has
        responded, so the clock must stop, exactly as it does for a message.
        Before this, a ticket answered that way stayed unmeasured and drifted
        into a false SLA breach."""
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/",
                  {'status': 'in_progress', 'admin_note': 'در حال بررسی'}, self.h_admin)
        self.assertIsNotNone(CompanyRequest.objects.get(id=req['id']).first_response_at)

    def test_an_emptied_admin_note_is_not_a_first_response(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'admin_note': '   '}, self.h_admin)
        self.assertIsNone(CompanyRequest.objects.get(id=req['id']).first_response_at)

    def test_a_status_change_alone_is_not_a_first_response(self):
        """Moving a ticket to 'in progress' tells the customer nothing they can
        read; it is not an answer."""
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'status': 'in_progress'}, self.h_admin)
        self.assertIsNone(CompanyRequest.objects.get(id=req['id']).first_response_at)

    def test_an_admin_note_does_not_overwrite_an_earlier_first_response(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'message': 'سلام'}, self.h_admin)
        first = CompanyRequest.objects.get(id=req['id']).first_response_at
        self.post(f"{ADMIN_URL}{req['id']}/", {'admin_note': 'توضیح'}, self.h_admin)
        self.assertEqual(CompanyRequest.objects.get(id=req['id']).first_response_at, first)

    def test_an_internal_note_is_not_a_first_response(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'message': 'hm', 'internal': True}, self.h_admin)
        self.assertIsNone(CompanyRequest.objects.get(id=req['id']).first_response_at)

    def test_an_unanswered_ticket_past_its_due_date_reads_as_breached(self):
        req = self.create()
        CompanyRequest.objects.filter(id=req['id']).update(
            sla_response_due_at=timezone.now() - timedelta(minutes=5))
        got = self.c.get(f"{URL}{req['id']}/", **self.h_spec).json()['request']
        self.assertEqual(got['sla']['response_state'], 'breached')

    def test_a_ticket_resolved_before_its_due_date_reads_as_met(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'status': 'completed'}, self.h_admin)
        got = self.c.get(f"{URL}{req['id']}/", **self.h_spec).json()['request']
        self.assertEqual(got['sla']['resolve_state'], 'met')

    def test_reopening_restarts_the_resolution_clock(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'status': 'completed'}, self.h_admin)
        before = CompanyRequest.objects.get(id=req['id']).sla_resolve_due_at
        self.post(f"{URL}{req['id']}/", {'message': 'no'}, self.h_spec)
        after = CompanyRequest.objects.get(id=req['id']).sla_resolve_due_at
        self.assertGreater(after, before)


# ---------------------------------------------------------------------------
# D. Ownership and escalation
# ---------------------------------------------------------------------------

class AssignmentTests(DeskBase):
    def test_an_admin_can_assign_a_ticket_to_a_named_admin(self):
        req = self.create()
        r = self.post(f"{ADMIN_URL}{req['id']}/", {'assignee_id': self.admin2.id}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['request']['assignee'],
                         {'id': self.admin2.id, 'name': 'desk_admin2'})
        self.assertEqual(CompanyRequest.objects.get(id=req['id']).assignee_id, self.admin2.id)

    def test_assigning_to_an_unknown_admin_is_a_400(self):
        req = self.create()
        r = self.post(f"{ADMIN_URL}{req['id']}/", {'assignee_id': 9999}, self.h_admin)
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(CompanyRequest.objects.get(id=req['id']).assignee_id)

    def test_assignee_id_null_unassigns(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'assignee_id': self.admin2.id}, self.h_admin)
        r = self.post(f"{ADMIN_URL}{req['id']}/", {'assignee_id': None}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNone(CompanyRequest.objects.get(id=req['id']).assignee_id)

    def test_handled_by_records_the_acting_admin_not_the_literal_admin(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'status': 'in_progress'}, self.h_admin2)
        self.assertEqual(CompanyRequest.objects.get(id=req['id']).handled_by, 'desk_admin2')

    def test_escalation_stamps_the_time_raises_priority_and_emits(self):
        req = self.create(priority='low')
        r = self.post(f"{ADMIN_URL}{req['id']}/", {'escalate': True}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        row = CompanyRequest.objects.get(id=req['id'])
        self.assertIsNotNone(row.escalated_at)
        self.assertEqual(row.priority, 'high')
        self.assertTrue(Event.objects.filter(type='request.escalated').exists())

    def test_escalation_is_idempotent(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'escalate': True}, self.h_admin)
        first = CompanyRequest.objects.get(id=req['id']).escalated_at
        self.post(f"{ADMIN_URL}{req['id']}/", {'escalate': True}, self.h_admin)
        self.assertEqual(CompanyRequest.objects.get(id=req['id']).escalated_at, first)


class FilerEventTests(DeskBase):
    """A ticket's events have to reach the person who filed it.

    Opening the channel to every seat created a hole nobody would have seen
    from the API tests: `events._scoped_qs` gives a plain user only their OWN
    'user' events plus broadcasts, while the desk emitted 'company' events,
    which only managers and analytics viewers receive. A specialist therefore
    filed a ticket and then watched a dashboard that never moved.
    """

    def _delivered(self, user, after=0):
        from .portal_auth import user_can_view_company_stream
        return [e.type for e in events_mod.events_since(
            after, is_admin=False, company_id=user.company_id, user_id=user.id,
            can_see_company=user_can_view_company_stream(user))]

    def test_a_specialists_own_ticket_events_reach_them(self):
        req = self.create(hdr=self.h_spec)
        after = Event.objects.latest('id').id
        self.post(f"{ADMIN_URL}{req['id']}/", {'message': 'در حال بررسی'}, self.h_admin)
        self.assertIn('request.updated', self._delivered(self.spec, after))

    def test_a_status_change_reaches_the_specialist_who_filed_it(self):
        req = self.create(hdr=self.h_spec)
        after = Event.objects.latest('id').id
        self.post(f"{ADMIN_URL}{req['id']}/", {'status': 'completed'}, self.h_admin)
        self.assertIn('request.updated', self._delivered(self.spec, after))

    def test_a_colleagues_ticket_events_do_not_reach_another_specialist(self):
        req = self.create(hdr=self.h_spec2)
        after = Event.objects.latest('id').id
        self.post(f"{ADMIN_URL}{req['id']}/", {'message': 'x'}, self.h_admin)
        self.assertEqual(self._delivered(self.spec, after), [])

    def test_a_manager_filer_is_not_told_twice(self):
        """A manager already receives the company event; a user copy would
        double every toast on their dashboard."""
        req = self.create(hdr=self.h_mgr)
        after = Event.objects.latest('id').id
        self.post(f"{ADMIN_URL}{req['id']}/", {'message': 'x'}, self.h_admin)
        self.assertEqual(
            Event.objects.filter(id__gt=after, audience='user',
                                 user_id=self.mgr.id).count(), 0)
        self.assertIn('request.updated', self._delivered(self.mgr, after))

    def test_a_ticket_logged_by_the_platform_side_emits_no_user_event(self):
        """A telephone call has no filer, so there is nobody to address."""
        before = Event.objects.count()
        self.post(ADMIN_URL, {'company_id': self.co_a.id, 'subject': 'call',
                              'source': 'phone'}, self.h_admin)
        self.assertEqual(Event.objects.filter(id__gt=before, audience='user').count(), 0)

    def test_the_user_copy_carries_the_same_payload_as_the_company_one(self):
        req = self.create(hdr=self.h_spec)
        after = Event.objects.latest('id').id
        self.post(f"{ADMIN_URL}{req['id']}/", {'status': 'completed'}, self.h_admin)
        user_ev = Event.objects.filter(id__gt=after, audience='user',
                                       user_id=self.spec.id).latest('id')
        company_ev = Event.objects.filter(id__gt=after, audience='company').latest('id')
        self.assertEqual(user_ev.payload, company_ev.payload)
        self.assertEqual(user_ev.company_id, self.co_a.id)


# ---------------------------------------------------------------------------
# E. Satisfaction
# ---------------------------------------------------------------------------

class CsatTests(DeskBase):
    def _closed(self):
        req = self.create()
        self.post(f"{ADMIN_URL}{req['id']}/", {'status': 'completed'}, self.h_admin)
        return req

    def test_the_requester_can_rate_a_closed_ticket(self):
        req = self._closed()
        r = self.post(f"{URL}{req['id']}/", {'csat': {'score': 5, 'comment': 'quick'}},
                      self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        row = CompanyRequest.objects.get(id=req['id'])
        self.assertEqual(row.csat_score, 5)
        self.assertEqual(row.csat_comment, 'quick')
        self.assertIsNotNone(row.csat_at)
        self.assertEqual(r.json()['request']['csat']['score'], 5)

    def test_an_open_ticket_cannot_be_rated(self):
        req = self.create()
        r = self.post(f"{URL}{req['id']}/", {'csat': {'score': 4}}, self.h_spec)
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(CompanyRequest.objects.get(id=req['id']).csat_score)

    def test_a_score_outside_one_to_five_is_rejected(self):
        req = self._closed()
        for bad in (0, 6, -1, 'five', None):
            r = self.post(f"{URL}{req['id']}/", {'csat': {'score': bad}}, self.h_spec)
            self.assertEqual(r.status_code, 400, f'{bad!r}: {r.content}')

    def test_a_ticket_cannot_be_rated_twice(self):
        req = self._closed()
        self.post(f"{URL}{req['id']}/", {'csat': {'score': 3}}, self.h_spec)
        r = self.post(f"{URL}{req['id']}/", {'csat': {'score': 5}}, self.h_spec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(CompanyRequest.objects.get(id=req['id']).csat_score, 3)

    def test_a_colleague_who_did_not_file_it_cannot_rate_it(self):
        req = self._closed()
        r = self.post(f"{URL}{req['id']}/", {'csat': {'score': 1}}, self.h_mgr)
        self.assertEqual(r.status_code, 403)


# ---------------------------------------------------------------------------
# F. Source — how the telephone-to-digital shift becomes measurable
# ---------------------------------------------------------------------------

class SourceTests(DeskBase):
    def test_a_ticket_filed_in_the_portal_is_sourced_portal(self):
        req = self.create()
        self.assertEqual(req['source'], 'portal')

    def test_the_source_cannot_be_faked_by_the_client(self):
        req = self.create(source='phone')
        self.assertEqual(req['source'], 'portal')

    def test_an_admin_can_log_a_telephone_call_as_a_ticket(self):
        r = self.post(ADMIN_URL, {'company_id': self.co_a.id, 'subject': 'called about brakes',
                                  'body': 'rang at 09:10', 'source': 'phone',
                                  'kind': 'support'}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        row = CompanyRequest.objects.get(id=r.json()['request']['id'])
        self.assertEqual(row.source, 'phone')
        self.assertEqual(row.company_id, self.co_a.id)
        self.assertIsNone(row.created_by_id)
        self.assertEqual(TicketMessage.objects.filter(request=row).count(), 1)

    def test_an_admin_ticket_needs_a_known_company_and_source(self):
        self.assertEqual(self.post(ADMIN_URL, {'company_id': 9999, 'subject': 'x'},
                                   self.h_admin).status_code, 400)
        self.assertEqual(self.post(ADMIN_URL, {'company_id': self.co_a.id, 'subject': ''},
                                   self.h_admin).status_code, 400)
        self.assertEqual(self.post(ADMIN_URL, {'company_id': self.co_a.id, 'subject': 'x',
                                               'source': 'carrier pigeon'},
                                   self.h_admin).status_code, 400)

    def test_a_portal_user_cannot_use_the_admin_create_endpoint(self):
        self.assertEqual(self.post(ADMIN_URL, {'company_id': self.co_a.id, 'subject': 'x'},
                                   self.h_spec).status_code, 401)


# ---------------------------------------------------------------------------
# G. Support metrics
# ---------------------------------------------------------------------------

class SupportMetricsTests(DeskBase):
    def test_the_endpoint_is_admin_only(self):
        self.assertEqual(self.c.get(METRICS_URL).status_code, 401)
        self.assertEqual(self.c.get(METRICS_URL, **self.h_spec).status_code, 401)
        self.assertEqual(self.c.get(METRICS_URL, **self.h_admin).status_code, 200)

    def test_counts_match_the_rows(self):
        a = self.create()
        b = self.create()
        self.post(f"{ADMIN_URL}{b['id']}/", {'status': 'completed'}, self.h_admin)
        m = self.c.get(METRICS_URL, **self.h_admin).json()
        self.assertEqual(m['totals']['created'], 2)
        self.assertEqual(m['totals']['open'], 1)
        self.assertEqual(m['totals']['closed'], 1)
        self.assertEqual(m['by_source'], {'portal': 2})
        self.assertEqual(m['by_kind']['support'], 2)

    def test_first_response_minutes_are_measured_from_the_stamps(self):
        req = self.create()
        now = timezone.now()
        CompanyRequest.objects.filter(id=req['id']).update(
            created_at=now - timedelta(minutes=30), first_response_at=now)
        m = self.c.get(METRICS_URL, **self.h_admin).json()
        self.assertEqual(m['first_response']['measured'], 1)
        self.assertAlmostEqual(m['first_response']['avg_minutes'], 30.0, places=1)

    def test_resolution_hours_are_measured_from_the_stamps(self):
        req = self.create()
        now = timezone.now()
        CompanyRequest.objects.filter(id=req['id']).update(
            created_at=now - timedelta(hours=4), resolved_at=now, status='completed')
        m = self.c.get(METRICS_URL, **self.h_admin).json()
        self.assertEqual(m['resolution']['measured'], 1)
        self.assertAlmostEqual(m['resolution']['avg_hours'], 4.0, places=2)

    def test_sla_compliance_counts_met_against_decided(self):
        met = self.create()
        breached = self.create()
        now = timezone.now()
        CompanyRequest.objects.filter(id=met['id']).update(
            sla_response_due_at=now + timedelta(hours=1), first_response_at=now)
        CompanyRequest.objects.filter(id=breached['id']).update(
            sla_response_due_at=now - timedelta(hours=1))
        m = self.c.get(METRICS_URL, **self.h_admin).json()['sla']['response']
        self.assertEqual((m['met'], m['breached']), (1, 1))
        self.assertAlmostEqual(m['compliance'], 0.5, places=3)

    def test_csat_aggregates_and_response_rate(self):
        a = self.create()
        b = self.create()
        for t in (a, b):
            self.post(f"{ADMIN_URL}{t['id']}/", {'status': 'completed'}, self.h_admin)
        self.post(f"{URL}{a['id']}/", {'csat': {'score': 4}}, self.h_spec)
        m = self.c.get(METRICS_URL, **self.h_admin).json()['csat']
        self.assertEqual(m['responses'], 1)
        self.assertAlmostEqual(m['avg'], 4.0, places=2)
        self.assertEqual(m['distribution']['4'], 1)
        self.assertAlmostEqual(m['response_rate'], 0.5, places=3)

    def test_the_csat_rate_never_exceeds_one_when_a_rated_ticket_is_reopened(self):
        """`rated` and `closed` have to be the same cohort. A ticket rated and
        then reopened keeps its score but is no longer closed, so counting it
        in the numerator alone produced rates above 100 % — and, if every rated
        ticket was reopened, a null rate beside recorded responses."""
        a = self.create()
        b = self.create()
        for t in (a, b):
            self.post(f"{ADMIN_URL}{t['id']}/", {'status': 'completed'}, self.h_admin)
            self.post(f"{URL}{t['id']}/", {'csat': {'score': 5}}, self.h_spec)
        self.post(f"{URL}{a['id']}/", {'message': 'هنوز درست نشده'}, self.h_spec)

        m = self.c.get(METRICS_URL, **self.h_admin).json()['csat']
        self.assertEqual(m['responses'], 2)          # both scores still counted
        self.assertLessEqual(m['response_rate'], 1.0)
        self.assertAlmostEqual(m['response_rate'], 1.0, places=3)   # 1 rated of 1 closed

    def test_the_csat_rate_is_null_when_nothing_closed_in_the_window(self):
        a = self.create()
        self.post(f"{ADMIN_URL}{a['id']}/", {'status': 'completed'}, self.h_admin)
        self.post(f"{URL}{a['id']}/", {'csat': {'score': 4}}, self.h_spec)
        self.post(f"{URL}{a['id']}/", {'message': 'reopen'}, self.h_spec)
        m = self.c.get(METRICS_URL, **self.h_admin).json()['csat']
        self.assertEqual(m['responses'], 1)
        self.assertIsNone(m['response_rate'])

    def test_backlog_reports_age_breaches_and_unassigned(self):
        old = self.create()
        now = timezone.now()
        CompanyRequest.objects.filter(id=old['id']).update(
            created_at=now - timedelta(days=3), sla_resolve_due_at=now - timedelta(hours=2))
        m = self.c.get(METRICS_URL, **self.h_admin).json()['backlog']
        self.assertEqual(m['open'], 1)
        self.assertEqual(m['unassigned'], 1)
        self.assertEqual(m['breaching_now'], 1)
        self.assertAlmostEqual(m['oldest_days'], 3.0, places=1)

    def test_feature_discovery_counts_entitled_and_discovered_seats(self):
        from .models import ActivityLog, Car, UserCarAccess
        car = Car.objects.create(brand_name='T', car_name='C', year=2021, db_address='d.db')
        UserCarAccess.objects.create(user=self.spec, car=car, documents=[],
                                     admin_granted=True)
        ActivityLog.objects.create(user=self.spec, action='view_node')
        fd = self.c.get(METRICS_URL, **self.h_admin).json()['feature_discovery']
        self.assertEqual(fd['read_manual']['entitled'], 1)
        self.assertEqual(fd['read_manual']['discovered'], 1)
        self.assertAlmostEqual(fd['read_manual']['rate'], 1.0)

    def test_feature_discovery_and_the_seat_checklist_agree(self):
        """The property that justifies sharing one function: the number
        management reads is computed from the same question the seat is
        asked."""
        from . import onboarding
        from .models import ActivityLog, Car, UserCarAccess
        car = Car.objects.create(brand_name='T', car_name='C2', year=2021, db_address='e.db')
        UserCarAccess.objects.create(user=self.spec, car=car, documents=[],
                                     admin_granted=True)
        ActivityLog.objects.create(user=self.spec, action='parts_view')
        fd = self.c.get(METRICS_URL, **self.h_admin).json()['feature_discovery']
        for item in onboarding.progress_for(self.spec):
            self.assertEqual(
                item['done'], fd[item['id']]['discovered'] >= 1,
                f"{item['id']}: the checklist and the metric disagree")

    def test_feature_discovery_rate_is_none_when_nobody_is_entitled(self):
        fd = self.c.get(METRICS_URL, **self.h_admin).json()['feature_discovery']
        self.assertEqual(fd['open_parts']['entitled'], 0)
        self.assertIsNone(fd['open_parts']['rate'])

    def test_the_window_excludes_older_rows(self):
        old = self.create()
        CompanyRequest.objects.filter(id=old['id']).update(
            created_at=timezone.now() - timedelta(days=90))
        m = self.c.get(f'{METRICS_URL}?days=30', **self.h_admin).json()
        self.assertEqual(m['totals']['created'], 0)

    def test_an_absurd_window_is_clamped_not_a_500(self):
        for q in ('?days=0', '?days=-5', '?days=99999', '?days=abc'):
            self.assertEqual(self.c.get(METRICS_URL + q, **self.h_admin).status_code, 200, q)


# ---------------------------------------------------------------------------
# H. The general feedback channel (not a support request)
# ---------------------------------------------------------------------------

class FeedbackChannelTests(DeskBase):
    def test_any_seat_can_send_feedback(self):
        r = self.post(FEEDBACK_URL, {'page': '/browse', 'rating': 4,
                                     'comment': 'search is slow'}, self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        f = Feedback.objects.get()
        self.assertEqual((f.user_id, f.company_id, f.rating), (self.spec.id, self.co_a.id, 4))
        self.assertEqual(f.page, '/browse')
        self.assertEqual(f.comment, 'search is slow')

    def test_signed_out_feedback_is_401(self):
        self.assertEqual(self.c.post(FEEDBACK_URL, '{}',
                                     content_type='application/json').status_code, 401)

    def test_a_rating_outside_one_to_five_is_rejected(self):
        for bad in (0, 6, 'x'):
            r = self.post(FEEDBACK_URL, {'rating': bad, 'page': '/x'}, self.h_spec)
            self.assertEqual(r.status_code, 400, f'{bad!r}')
        self.assertFalse(Feedback.objects.exists())

    def test_feedback_with_neither_rating_nor_comment_is_rejected(self):
        r = self.post(FEEDBACK_URL, {'page': '/x'}, self.h_spec)
        self.assertEqual(r.status_code, 400)

    def test_a_comment_alone_is_enough(self):
        r = self.post(FEEDBACK_URL, {'page': '/x', 'comment': 'the RTL wraps wrongly'},
                      self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNone(Feedback.objects.get().rating)

    def test_feedback_submission_is_rate_limited(self):
        """The limiter is per client IP (api/ratelimit.py), in-process. The cap
        is pinned here instead of relying on the default, so the test does not
        depend on how many submissions other tests in this class made."""
        import os
        from unittest import mock
        bodies = {'page': '/x', 'comment': 'again'}
        with mock.patch.dict(os.environ, {'KG_RL_FEEDBACK': '2/60'}):
            codes = [self.post(FEEDBACK_URL, bodies, self.h_spec).status_code
                     for _ in range(4)]
        self.assertIn(429, codes, codes)

    def test_the_admin_feed_lists_and_aggregates(self):
        self.post(FEEDBACK_URL, {'page': '/a', 'rating': 5}, self.h_spec)
        self.post(FEEDBACK_URL, {'page': '/b', 'rating': 3, 'comment': 'meh'}, self.h_mgr)
        self.assertEqual(self.c.get(ADMIN_FEEDBACK_URL, **self.h_spec).status_code, 401)
        got = self.c.get(ADMIN_FEEDBACK_URL, **self.h_admin).json()
        self.assertEqual(got['totals']['submissions'], 2)
        self.assertAlmostEqual(got['totals']['avg_rating'], 4.0, places=2)
        self.assertEqual(len(got['items']), 2)
        self.assertEqual(got['items'][0]['company'], 'Desk A')

    def test_the_metrics_endpoint_reports_the_feedback_channel(self):
        self.post(FEEDBACK_URL, {'page': '/a', 'rating': 5}, self.h_spec)
        m = self.c.get(METRICS_URL, **self.h_admin).json()['feedback']
        self.assertEqual(m['submissions'], 1)
        self.assertAlmostEqual(m['avg_rating'], 5.0, places=2)
