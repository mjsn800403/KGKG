import json

from django.test import RequestFactory, SimpleTestCase, override_settings

from api.nulguard import _has_nul

NUL = chr(0)


@override_settings(ALLOWED_HOSTS=['testserver'])
class NulGuardTests(SimpleTestCase):
    """PostgreSQL cannot store U+0000; such input must be a 400, never a 500."""

    def test_nul_in_query_string_is_400(self):
        r = self.client.get('/api/search/', {'q': 'oil' + NUL})
        self.assertEqual(r.status_code, 400)

    def test_nul_in_json_body_is_400(self):
        r = self.client.post('/api/assist/', json.dumps({'query': 'a' + NUL + 'b'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_clean_request_is_not_flagged(self):
        req = RequestFactory().get('/api/search/', {'q': 'oil'})
        self.assertFalse(_has_nul(req))

    def test_binary_upload_is_not_inspected(self):
        req = RequestFactory().post('/api/x/', data=b'PK\x03\x04' + bytes(2),
                                    content_type='application/zip')
        self.assertFalse(_has_nul(req))
