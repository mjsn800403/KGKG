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

    def test_malformed_signature_headers_are_refused(self):
        req = self._req()
        req.META['HTTP_X_KG_E'] = 'soon'
        self.assertEqual(self.mw(req).status_code, 403)
        req = self._req(nonce='short')                       # nonce under 16 chars
        self.assertEqual(self.mw(req).status_code, 403)
        req = self._req()
        req.META['HTTP_X_KG_N'] = 'x' * 20 + '/../'          # outside the nonce alphabet
        self.assertEqual(self.mw(req).status_code, 403)

    def test_only_successful_json_answers_are_sealed(self):
        from django.http import HttpResponse
        for resp in (HttpResponse('<p>torque</p>', content_type='text/html'),
                     JsonResponse({'error': 'nope', 'torque': 1}, status=404)):
            mw = shield.ShieldMiddleware(lambda r, resp=resp: resp)
            self.assertIn(b'torque', mw(self._req()).content)

    def test_repeated_bad_requests_raise_one_alert(self):
        user = mock.Mock(id=7, username='scraper')
        with mock.patch('api.portal.portal_user', return_value=user), \
             mock.patch('api.monitoring._raise_alert') as alert:
            for _ in range(shield._BAD_WARN + 5):
                self.assertEqual(self.mw(self._req(sign=False)).status_code, 403)
        alert.assert_called_once()
        self.assertEqual(alert.call_args.args[0], 'sec:shield:7')


class ShieldKeyViewTests(TestCase):
    """GET /api/shield/key/: the per-session keys the browser signs and unseals with."""

    def setUp(self):
        from .models import AuthToken, Company, PortalUser
        p = mock.patch.dict('os.environ', ENV)
        p.start()
        self.addCleanup(p.stop)
        co = Company.objects.create(name='S', active=True)
        u = PortalUser.objects.create(company=co, username='s', password_hash='x',
                                      role='after_sales_specialist', active=True)
        self.raw = AuthToken.issue(u).key
        self.h = {'HTTP_AUTHORIZATION': f'Bearer {self.raw}'}

    def get(self, **params):
        from django.test import Client
        return Client().get('/api/shield/key/', params, **self.h)

    def test_switched_off_says_so_and_hands_out_nothing(self):
        with mock.patch.dict('os.environ', {'KG_SHIELD': '0'}):
            self.assertEqual(self.get().json(), {'on': False})

    def test_anonymous_is_401(self):
        from django.test import Client
        self.assertEqual(Client().get('/api/shield/key/').status_code, 401)

    def test_current_epoch_keys_match_the_server_side_keys(self):
        r = self.get()
        d = r.json()
        self.assertEqual(r['Cache-Control'], 'no-store')
        enc, sig = shield.keys(self.raw, d['e'])
        self.assertEqual((d['enc'], d['sig']), (shield._b64(enc), shield._b64(sig)))
        self.assertTrue(0 < d['ttl'] <= shield.EPOCH)

    def test_ttl_is_never_zero_anywhere_in_the_epoch(self):
        """The deploy gate caught this at 04:40 on 2026-10-30, on a commit whose
        CI had passed: `int(EPOCH - now % EPOCH)` truncated a float, so in the
        final second of every epoch the endpoint answered `ttl: 0` and told the
        client its freshly minted key had already expired. One call in 600.

        The old form fails this test at every offset below; the loop is the
        point, since a single mocked instant is what let the bug live.
        """
        base = shield.epoch() * shield.EPOCH
        for frac in (0.0, 0.5, 1.0, 299.5, 598.0, 599.0, 599.5, 599.9, 599.999, 599.9999):
            with mock.patch.object(shield.time, 'time', return_value=base + frac):
                d = self.get().json()
            self.assertGreaterEqual(d['ttl'], 1, f'ttl fell to {d["ttl"]} at +{frac}s')
            self.assertLessEqual(d['ttl'], shield.EPOCH, f'ttl exceeded EPOCH at +{frac}s')

    def test_ttl_counts_down_in_whole_seconds(self):
        base = shield.epoch() * shield.EPOCH
        with mock.patch.object(shield.time, 'time', return_value=base + 0.0):
            self.assertEqual(self.get().json()['ttl'], shield.EPOCH)
        with mock.patch.object(shield.time, 'time', return_value=base + 1.0):
            self.assertEqual(self.get().json()['ttl'], shield.EPOCH - 1)
        # Sub-second progress must not change the answer: a client polling
        # twice in the same second should not see the deadline move.
        with mock.patch.object(shield.time, 'time', return_value=base + 1.4):
            self.assertEqual(self.get().json()['ttl'], shield.EPOCH - 1)

    def test_only_the_last_two_epochs_and_never_the_future(self):
        cur = shield.epoch()
        self.assertEqual(self.get(e=cur - 2).json()['e'], cur - 2)
        self.assertEqual(self.get(e=cur - 3).status_code, 400)
        self.assertEqual(self.get(e=cur + 1).status_code, 400)
        self.assertEqual(self.get(e='abc').json()['e'], cur)      # unparsable -> current
