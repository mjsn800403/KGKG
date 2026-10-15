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
