"""#62: every @csrf_exempt view is registered and classified, and the Origin
guard refuses cookie-authenticated cross-origin writes."""
import ast
import pathlib

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from api.csrf_registry import EXEMPT
from api.originguard import OriginGuardMiddleware

API = pathlib.Path(__file__).resolve().parent
CLASSES = {'admin-header', 'token-header', 'portal-cookie', 'pre-auth'}


def _exempt_views():
    found = set()
    for f in API.rglob('*.py'):
        if f.name.startswith('test') or 'migrations' in f.parts:
            continue
        src = f.read_text(encoding='utf-8')
        if 'csrf_exempt' not in src:
            continue
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and any(
                    'csrf_exempt' in ast.unparse(d) for d in node.decorator_list):
                found.add(f'api/{f.relative_to(API).as_posix()}:{node.name}')
    return found


class RegistryTests(SimpleTestCase):
    def test_every_exempt_view_is_registered(self):
        missing = _exempt_views() - set(EXEMPT)
        self.assertFalse(missing, f'@csrf_exempt without an entry in api/csrf_registry.py: {sorted(missing)}')

    def test_no_stale_entries(self):
        stale = set(EXEMPT) - _exempt_views()
        self.assertFalse(stale, f'registry entries with no @csrf_exempt view: {sorted(stale)}')

    def test_every_entry_has_a_known_class(self):
        self.assertFalse({k for k, v in EXEMPT.items() if v[0] not in CLASSES})


@override_settings(CSRF_TRUSTED_ORIGINS=['https://kgtechvault.com'],
                   ALLOWED_HOSTS=['kgtechvault.com', 'testserver'])
class OriginGuardTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.mw = OriginGuardMiddleware(lambda r: HttpResponse('ok'))

    def call(self, method='post', cookie=True, **meta):
        req = getattr(self.rf, method)('/api/auth/me/prefs/', **meta)
        if cookie:
            req.COOKIES['kg_portal_token'] = 'x'
        return self.mw(req).status_code

    def test_foreign_origin_with_cookie_is_refused(self):
        self.assertEqual(self.call(HTTP_ORIGIN='https://evil.example'), 403)

    def test_null_origin_is_refused(self):
        self.assertEqual(self.call(HTTP_ORIGIN='null'), 403)

    def test_foreign_referer_without_origin_is_refused(self):
        self.assertEqual(self.call(HTTP_REFERER='https://evil.example/x'), 403)

    def test_our_origin_passes(self):
        self.assertEqual(self.call(HTTP_ORIGIN='https://kgtechvault.com'), 200)

    def test_same_host_origin_passes(self):
        self.assertEqual(self.call(HTTP_ORIGIN='http://testserver'), 200)

    def test_no_origin_or_referer_passes(self):
        """Server-to-server (Next.js forwarding the cookie) sends neither."""
        self.assertEqual(self.call(), 200)

    def test_bearer_header_is_not_checked(self):
        self.assertEqual(self.call(HTTP_ORIGIN='https://evil.example',
                                   HTTP_AUTHORIZATION='Bearer t'), 200)

    def test_without_cookie_is_not_checked(self):
        self.assertEqual(self.call(cookie=False, HTTP_ORIGIN='https://evil.example'), 200)

    def test_safe_methods_are_not_checked(self):
        self.assertEqual(self.call(method='get', HTTP_ORIGIN='https://evil.example'), 200)

    def test_switch_off(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {'KG_ORIGIN_GUARD': '0'}):
            self.assertEqual(self.call(HTTP_ORIGIN='https://evil.example'), 200)
