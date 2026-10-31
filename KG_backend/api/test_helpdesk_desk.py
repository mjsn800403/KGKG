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

from .models import Car, Company, CompanyRequest, UserCarAccess
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
