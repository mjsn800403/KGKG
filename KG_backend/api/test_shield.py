"""Shield: sealed content answers, signed single-use requests, loopback untouched."""
import secrets
from unittest import mock

from django.http import JsonResponse
from django.test import RequestFactory, TestCase

from api import contentguard as cg
from api import shield

ENV = {'KG_SHIELD': '1', 'KG_SHIELD_SECRET': 'test-secret'}
TOKEN = 'tok-123'


def _view(request):
    return JsonResponse([{'title': 'Brake', 'content': '<p>torque 103 N·m</p>'}], safe=False)


class ShieldTests(TestCase):
    def setUp(self):
        cg._LOCAL.clear()
        self.rf = RequestFactory()
        self.mw = shield.ShieldMiddleware(_view)
        p = mock.patch.dict('os.environ', ENV)
        p.start()
        self.addCleanup(p.stop)
        for target in (mock.patch.object(shield, '_token', return_value=TOKEN),
                       mock.patch.object(cg.ratelimit, '_STORE', None)):
            target.start()
            self.addCleanup(target.stop)

    def _req(self, path='/Toyota/2025/Corolla/', query='seg=Brake', sign=True, nonce=None, e=None, external=True):
        e = shield.epoch() if e is None else e
        nonce = nonce or secrets.token_urlsafe(16)
        headers = {}
        if sign:
            headers = {'HTTP_X_KG_E': str(e), 'HTTP_X_KG_N': nonce,
                       'HTTP_X_KG_S': shield.signature(TOKEN, e, 'GET', path, query, nonce)}
        if external:
            headers['HTTP_X_REAL_IP'] = '5.6.7.8'
        return self.rf.get(f'{path}?{query}', **headers)

    def test_signed_request_gets_sealed_answer(self):
        resp = self.mw(self._req())
        self.assertEqual(resp.status_code, 200)
        import json
        blob = json.loads(resp.content)
        self.assertEqual(blob['_kg'], 1)
        self.assertNotIn(b'torque', resp.content)
        self.assertEqual(shield.unseal(blob, TOKEN)[0]['title'], 'Brake')

    def test_unsigned_and_tampered_are_refused(self):
        self.assertEqual(self.mw(self._req(sign=False)).status_code, 403)
        bad = self._req()
        bad.META['QUERY_STRING'] = 'seg=Engine'
        self.assertEqual(self.mw(bad).status_code, 403)

    def test_replay_and_old_epoch_are_refused(self):
        self.assertEqual(self.mw(self._req(nonce='n' * 22)).status_code, 200)
        self.assertEqual(self.mw(self._req(nonce='n' * 22)).status_code, 403)
        self.assertEqual(self.mw(self._req(e=shield.epoch() - 2)).status_code, 403)
        self.assertEqual(self.mw(self._req(e=shield.epoch() - 1)).status_code, 200)

    def test_loopback_callers_are_untouched(self):
        # SSR, the /api/chat route and the RAG retriever reach Django directly.
        resp = self.mw(self._req(sign=False, external=False))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('torque', resp.content.decode())

    def test_unprotected_paths_and_switch_off(self):
        self.assertEqual(self.mw(self._req(path='/Toyota/2025/', sign=False)).status_code, 200)
        self.assertEqual(self.mw(self._req(path='/api/auth/me/', sign=False)).status_code, 200)
        with mock.patch.dict('os.environ', {'KG_SHIELD': '0'}):
            self.assertIn('torque', self.mw(self._req(sign=False)).content.decode())

    def test_keys_rotate_per_epoch_and_session(self):
        e = shield.epoch()
        self.assertNotEqual(shield.keys(TOKEN, e), shield.keys(TOKEN, e + 1))
        self.assertNotEqual(shield.keys(TOKEN, e), shield.keys('other', e))
