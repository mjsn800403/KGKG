"""/api/eval/report/ is platform-admin only (docs/05, docs/openapi.yaml).

It returns offline evaluation runs, whose rows include logged real user
queries; it was reachable without any credential.
"""
import os
from unittest import mock

from django.test import TestCase


class EvalReportAuthTest(TestCase):
    URL = '/api/eval/report/'

    def test_anonymous_is_refused(self):
        self.assertIn(self.client.get(self.URL).status_code, (401, 403))

    def test_portal_session_is_not_enough(self):
        r = self.client.get(self.URL, HTTP_AUTHORIZATION='Bearer not-an-admin-token')
        self.assertIn(r.status_code, (401, 403))

    def test_admin_token_gets_the_report(self):
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'qa-admin-token-123456'}):
            r = self.client.get(self.URL, HTTP_X_ADMIN_TOKEN='qa-admin-token-123456')
        self.assertEqual(r.status_code, 200)
        self.assertIn('runs', r.json())
