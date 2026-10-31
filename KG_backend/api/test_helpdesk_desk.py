"""The conversational desk: categorisation, read state, search and deflection.

A separate file from api/test_helpdesk.py on purpose. Acceptance criterion 30
of the spec is that the 90 tests in that file pass *with no edits* — if making
this feature work required changing one of them, the feature broke behaviour
somebody relies on. Keeping the new tests here makes that diff easy to check:
`git diff --stat origin/work -- api/test_helpdesk.py` must print nothing.

Spec: docs/superpowers/specs/2026-10-31-conversational-helpdesk-design.md
"""
import json

from django.test import TestCase

from django.utils import timezone

from . import reads
from .models import (Car, Company, CompanyRequest, TicketRead, UserCarAccess)
from .requests_api import awaiting_reply
from .test_helpdesk import URL, ADMIN_URL, DeskBase


class TopicFieldTests(TestCase):
    def test_every_topic_choice_has_a_persian_label(self):
        for value, label in CompanyRequest.TOPIC_CHOICES:
            self.assertTrue(value.islower() and value.isascii(), value)
            self.assertNotEqual(value, label)

    def test_the_seven_agreed_topics_exist(self):
        self.assertEqual(
            [v for v, _ in CompanyRequest.TOPIC_CHOICES],
            ['missing_document', 'content_wrong', 'access_problem',
             'assistant_wrong', 'error_or_slow', 'billing', 'other'])

    def test_a_ticket_defaults_to_no_topic_and_no_car(self):
        co = Company.objects.create(name='T')
        r = CompanyRequest.objects.create(company=co, subject='s')
        self.assertEqual(r.topic, '')
        self.assertIsNone(r.car_id)


class DeskCarBase(DeskBase):
    """DeskBase plus two vehicles: one the specialist may open, one they may not.

    The forbidden one is the point — `car` must not become a way to find out
    what exists in the catalogue.
    """
    def setUp(self):
        super().setUp()
        self.car = Car.objects.create(brand_name='Toyota', car_name='Corolla Cross',
                                      year=2024, db_address='cc.sqlite3')
        self.forbidden_car = Car.objects.create(brand_name='Lexus', car_name='LX 600',
                                                year=2025, db_address='lx.sqlite3')
        UserCarAccess.objects.create(user=self.spec, car=self.car,
                                     documents=['manual'], admin_granted=True)


class TopicAndCarApiTests(DeskCarBase):
    def test_a_ticket_round_trips_its_topic(self):
        t = self.create(topic='missing_document')
        self.assertEqual(t['topic'], 'missing_document')
        self.assertTrue(t['topic_label'])

    def test_an_unknown_topic_is_rejected_and_writes_nothing(self):
        r = self.post(URL, {'kind': 'support', 'subject': 's', 'topic': 'nope'}, self.h_spec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(CompanyRequest.objects.count(), 0)

    def test_a_ticket_round_trips_a_car_the_filer_can_open(self):
        t = self.create(car_id=self.car.id)
        self.assertEqual(t['car']['id'], self.car.id)
        self.assertIn('Corolla Cross', t['car']['name'])

    def test_a_car_the_filer_cannot_open_is_rejected_and_writes_nothing(self):
        r = self.post(URL, {'kind': 'support', 'subject': 's',
                            'car_id': self.forbidden_car.id}, self.h_spec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(CompanyRequest.objects.count(), 0)

    def test_an_unknown_car_id_is_rejected(self):
        r = self.post(URL, {'kind': 'support', 'subject': 's', 'car_id': 999999}, self.h_spec)
        self.assertEqual(r.status_code, 400)

    def test_a_ticket_without_either_is_uncategorised(self):
        t = self.create()
        self.assertEqual(t['topic'], '')
        self.assertIsNone(t['car'])

    def test_a_ticket_whose_car_was_deleted_still_serialises(self):
        """Review Focus 1: SET_NULL must leave a readable ticket, not a 500."""
        t = self.create(car_id=self.car.id)
        self.car.delete()
        r = self.c.get(f'{URL}{t["id"]}/', **self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNone(r.json()['request']['car'])

    def test_the_desk_may_log_a_call_about_any_vehicle(self):
        """An admin is not bound by one seat's grants."""
        r = self.post(ADMIN_URL, {'company_id': self.co_a.id, 'subject': 'call',
                                  'car_id': self.forbidden_car.id,
                                  'source': 'phone'}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['request']['car']['id'], self.forbidden_car.id)


class ReadStateTests(DeskCarBase):
    """Acceptance criteria 7-15. The whole point of this model is that every
    unread badge in the product is DERIVED from it: nothing is stored that
    could be left behind, so no badge can go stale."""

    def _unread(self, req, *, user=None, admin=None):
        return reads.unread_count(req, user=user, admin=admin)

    def test_an_unopened_ticket_counts_every_message_the_viewer_did_not_write(self):
        t = self.create(body='opening')                      # authored by spec
        r = CompanyRequest.objects.get(id=t['id'])
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'first'}, self.h_admin)
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'second'}, self.h_admin)
        self.assertEqual(self._unread(r, user=self.spec), 2)

    def test_marking_read_zeroes_the_count(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        reads.mark_read(r, user=self.spec)
        self.assertEqual(self._unread(r, user=self.spec), 0)

    def test_a_message_after_reading_is_unread_again(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        reads.mark_read(r, user=self.spec)
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'later'}, self.h_admin)
        self.assertEqual(self._unread(r, user=self.spec), 1)

    def test_your_own_message_is_never_unread(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        self.assertEqual(self._unread(r, user=self.spec), 0)

    def test_an_internal_note_is_unread_for_an_admin_and_invisible_to_the_customer(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        reads.mark_read(r, user=self.spec)
        self.post(f'{ADMIN_URL}{t["id"]}/',
                  {'message': 'ask licensing', 'internal': True}, self.h_admin)
        self.assertEqual(self._unread(r, user=self.spec), 0)
        self.assertEqual(self._unread(r, admin=self.admin2), 2)

    def test_two_seats_in_one_company_have_independent_read_state(self):
        t = self.create(hdr=self.h_mgr, body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        reads.mark_read(r, user=self.mgr)
        self.assertEqual(self._unread(r, user=self.mgr), 0)
        self.assertEqual(self._unread(r, user=self.spec), 2)

    def test_an_admin_read_mark_does_not_touch_a_seat(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        reads.mark_read(r, admin=self.admin)
        self.assertEqual(self._unread(r, admin=self.admin), 0)
        self.assertEqual(self._unread(r, user=self.spec), 1)

    def test_a_read_ticket_can_still_be_awaiting_our_reply(self):
        """The distinction the old single 'open' signal could not express."""
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        reads.mark_read(r, admin=self.admin)
        self.assertEqual(self._unread(r, admin=self.admin), 0)
        self.assertTrue(awaiting_reply(r))

    def test_a_get_does_not_mark_anything_read(self):
        t = self.create(body='opening')
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        self.c.get(f'{URL}{t["id"]}/', **self.h_spec)
        self.assertEqual(TicketRead.objects.count(), 0)

    def test_the_read_action_marks_it_read_for_the_caller(self):
        t = self.create(body='opening')
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        r = self.post(f'{URL}{t["id"]}/', {'action': 'read'}, self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['request']['unread_count'], 0)

    def test_marking_read_twice_does_not_error_or_duplicate(self):
        """Review Focus 4: two tabs, one ticket, same instant."""
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        for _ in range(2):
            reads.mark_read(r, user=self.spec)
        self.assertEqual(TicketRead.objects.filter(request=r, user=self.spec).count(), 1)

    def test_a_read_mark_belongs_to_exactly_one_viewer(self):
        t = self.create()
        r = CompanyRequest.objects.get(id=t['id'])
        with self.assertRaises(Exception):
            TicketRead.objects.create(request=r, user=self.spec, admin=self.admin,
                                      last_read_at=timezone.now())

    def test_unread_counts_answers_for_a_whole_page_at_once(self):
        a = self.create(body='one')
        b = self.create(body='two')
        for t in (a, b):
            self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        counts = reads.unread_counts([a['id'], b['id']], user=self.spec)
        self.assertEqual(counts, {a['id']: 1, b['id']: 1})

    def test_last_message_names_who_spoke_last(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        self.assertEqual(reads.last_message(r)['by'], 'customer')
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        r.refresh_from_db()
        self.assertEqual(reads.last_message(r)['by'], 'platform')

    def test_a_ticket_with_no_messages_has_no_last_message(self):
        t = self.create()
        r = CompanyRequest.objects.get(id=t['id'])
        self.assertIsNone(reads.last_message(r))

    def test_the_admin_read_action_marks_it_read_for_that_admin(self):
        t = self.create(body='opening')
        r = self.post(f'{ADMIN_URL}{t["id"]}/', {'action': 'read'}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['request']['unread_count'], 0)
        self.assertEqual(reads.unread_count(CompanyRequest.objects.get(id=t['id']),
                                            admin=self.admin2), 1)
