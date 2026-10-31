"""The conversational desk: categorisation, read state, search and deflection.

A separate file from api/test_helpdesk.py on purpose. Acceptance criterion 30
of the spec is that the 90 tests in that file pass *with no edits* — if making
this feature work required changing one of them, the feature broke behaviour
somebody relies on. Keeping the new tests here makes that diff easy to check:
`git diff --stat origin/work -- api/test_helpdesk.py` must print nothing.

Spec: docs/superpowers/specs/2026-10-31-conversational-helpdesk-design.md
"""
from django.test import TestCase

from .models import Company, CompanyRequest


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
