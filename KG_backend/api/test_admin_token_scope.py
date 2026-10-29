from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings

from api.admin_auth import require_admin_token


@require_admin_token
def _view(request):
    return JsonResponse({'ok': True})


@override_settings(DEBUG=False)
class StaticAdminTokenScopeTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def _call(self, **meta):
        import os
        os.environ['KG_ADMIN_TOKEN'] = 'scope-test-token'
        req = self.rf.get('/api/admin/x/', HTTP_AUTHORIZATION='Bearer scope-test-token', **meta)
        return _view(req).status_code

    def test_loopback_direct_call_is_allowed(self):
        self.assertEqual(self._call(REMOTE_ADDR='127.0.0.1'), 200)

    def test_via_cloudflare_is_rejected(self):
        self.assertEqual(self._call(REMOTE_ADDR='127.0.0.1', HTTP_CF_CONNECTING_IP='1.2.3.4'), 401)

    def test_via_forwarding_proxy_is_rejected(self):
        self.assertEqual(self._call(REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='1.2.3.4'), 401)

    def test_remote_address_is_rejected(self):
        self.assertEqual(self._call(REMOTE_ADDR='5.6.7.8'), 401)

    def test_via_nginx_real_ip_header_is_rejected(self):
        # nginx sets X-Real-IP on every proxied request; without this check the
        # static token would work from the internet through the reverse proxy.
        # (Found by mutation testing: dropping the header from _PROXY_HEADERS
        # survived the whole suite.)
        self.assertEqual(self._call(REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP='1.2.3.4'), 401)

    def test_ipv6_loopback_is_allowed(self):
        self.assertEqual(self._call(REMOTE_ADDR='::1'), 200)


@override_settings(DEBUG=False)
class AdminGateResponseTests(TestCase):
    """The frontend reads these bodies; pin them."""

    def setUp(self):
        self.rf = RequestFactory()

    def test_refusal_body(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'scope-test-token'}):
            r = _view(self.rf.get('/api/admin/x/', REMOTE_ADDR='5.6.7.8'))
        self.assertEqual((r.status_code, r.content), (401, b'{"error": "unauthorized"}'))

    def test_unconfigured_token_fails_closed_with_503(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': ''}):
            r = _view(self.rf.get('/api/admin/x/', REMOTE_ADDR='127.0.0.1'))
        self.assertEqual(r.status_code, 503)
        import json
        self.assertEqual(json.loads(r.content)['error'], 'admin_disabled')

    def test_wrapped_view_keeps_its_identity(self):
        self.assertEqual(_view.__name__, '_view')
