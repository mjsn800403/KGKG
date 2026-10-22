"""Content guard: page/media buckets, warn alert, block with 429; one session per account."""
from unittest import mock

from django.test import RequestFactory, TestCase

from api import contentguard as cg
from api.models import AuthToken, Company, PortalUser, SystemAlert


class BucketTests(TestCase):
    def test_paths(self):
        self.assertEqual(cg.bucket('/Toyota/2025/Corolla/'), 'page')
        self.assertEqual(cg.bucket('/api/parts/Toyota/2025/Corolla/'), 'page')
        self.assertEqual(cg.bucket('/api/frm/corolla-cross/'), 'page')
        self.assertEqual(cg.bucket('/api/media-auth/'), 'media')
        for p in ('/', '/Toyota/', '/Toyota/2025/', '/api/auth/me/', '/api/admin/overview/', '/api/health/'):
            self.assertIsNone(cg.bucket(p), p)


class GuardTests(TestCase):
    def setUp(self):
        cg._LOCAL.clear()
        co = Company.objects.create(name='cg-co')
        self.user = PortalUser.objects.create(username='cg_user', company=co)
        self.rf = RequestFactory()

    def _hit(self):
        req = self.rf.get('/Toyota/2025/Corolla/')
        with mock.patch('api.portal.portal_user', return_value=self.user):
            return cg.check(req)

    def test_warn_then_block(self):
        with mock.patch.dict(cg._LIMITS, {'page': (3, 5)}), mock.patch.object(cg.ratelimit, '_STORE', None):
            results = [self._hit() for _ in range(6)]
        self.assertTrue(all(r is None for r in results[:5]))
        self.assertEqual(results[5].status_code, 429)
        alert = SystemAlert.objects.get(key=f'sec:scrape:{self.user.id}')
        self.assertEqual(alert.severity, 'critical')
        self.assertTrue(alert.context['blocked'])

    def test_anonymous_is_not_counted(self):
        with mock.patch('api.portal.portal_user', return_value=None):
            self.assertIsNone(cg.check(self.rf.get('/Toyota/2025/Corolla/')))
        self.assertFalse(cg._LOCAL)


class SingleSessionTests(TestCase):
    def test_new_login_ends_other_sessions(self):
        from api.portal import _issue_session
        co = Company.objects.create(name='ss-co')
        u = PortalUser.objects.create(username='ss_user', company=co)
        _issue_session(u)
        _issue_session(u)
        self.assertEqual(AuthToken.objects.filter(user=u).count(), 1)
