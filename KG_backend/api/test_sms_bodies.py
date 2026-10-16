"""Every SMS template must be link-free: the operator rejects bodies with links."""
import re

from django.test import SimpleTestCase

from api import notify, portal

LINK = re.compile(r"https?://|www\.|\b[\w-]+\.(com|ir|net|org)\b", re.I)


class SmsBodiesTests(SimpleTestCase):
    def test_welcome_templates_have_no_links(self):
        for body in (portal._WELCOME_SMS, notify._WELCOME_TEXT):
            self.assertIsNone(LINK.search(body.format(u="u", p="p", username="u", password="p")), body)

    def test_provisioning_sends_one_link_free_body(self):
        sent = []
        orig = portal._post_sms
        portal._post_sms = lambda phone, body: (sent.append(body), (True, 1))[1]
        try:
            self.assertTrue(portal._notify_provisioned("09120000000", "ali", "pw"))
        finally:
            portal._post_sms = orig
        self.assertEqual(len(sent), 1)
        self.assertIn("ali", sent[0])
        self.assertIsNone(LINK.search(sent[0]))
