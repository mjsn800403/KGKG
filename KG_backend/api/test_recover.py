"""Forgotten-password recovery by SMS code (portal.recover_*)."""
import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from api import portal, ratelimit
from api.models import AuthToken, Company, OtpChallenge, PortalUser


class RecoverTest(TestCase):
    def setUp(self):
        cache.clear()
        ratelimit._HITS.clear()
        self.co = Company.objects.create(name='RecCo')
        self.user = PortalUser(company=self.co, username='rec_user', email='rec@x.ir',
                               phone='09121234567', role='after_sales_specialist')
        self.user.set_password('old-password')
        self.user.save()
        self.sent = []
        p1 = mock.patch.object(portal, '_verify_turnstile', return_value=True)
        p2 = mock.patch.object(portal, '_send_sms_otp',
                               side_effect=lambda ph, code: self.sent.append((ph, code)) or True)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def post(self, path, **body):
        r = self.client.post(f'/api/auth/{path}/', json.dumps(body),
                             content_type='application/json')
        return r.status_code, r.json()

    def start(self, identifier):
        return self.post('recover/start', identifier=identifier, turnstile_token='t')

    def test_phone_lookup_reset_logs_in_and_revokes_sessions(self):
        AuthToken.issue(self.user)
        st, data = self.start('+98 ۹۱۲ 123 4567')
        self.assertEqual(st, 200)
        self.assertEqual(self.sent[0][0], '09121234567')
        st, data = self.post('recover/reset', otp_session=data['otp_session'],
                             code=str(self.sent[0][1]), new_password='new-password-1')
        self.assertEqual(st, 200)
        self.assertIn('token', data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('new-password-1'))
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 1)

    def test_unknown_account_looks_the_same_and_sends_nothing(self):
        st, data = self.start('nobody')
        self.assertEqual(st, 200)
        self.assertIn('otp_session', data)
        self.assertEqual(self.sent, [])
        st, _ = self.post('recover/reset', otp_session=data['otp_session'],
                          code='123456', new_password='whatever-123')
        self.assertEqual(st, 401)

    def test_wrong_code_and_short_password_keep_old_password(self):
        _, data = self.start('rec@x.ir')
        st, _ = self.post('recover/reset', otp_session=data['otp_session'],
                          code=str(self.sent[0][1]), new_password='short')
        self.assertEqual(st, 400)
        st, _ = self.post('recover/reset', otp_session=data['otp_session'],
                          code='000000' if self.sent[0][1] != 0 else '111111',
                          new_password='new-password-1')
        self.assertEqual(st, 401)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-password'))

    def test_recovery_code_cannot_be_used_as_login_second_factor(self):
        _, data = self.start('rec_user')
        st, _ = self.post('verify-otp', otp_session=data['otp_session'],
                          code=str(self.sent[0][1]))
        self.assertEqual(st, 401)
        self.assertEqual(OtpChallenge.objects.get(user=self.user).purpose, 'recover')

    def test_locked_account_gets_no_code(self):
        self.user.locked = True
        self.user.save()
        st, _ = self.start('rec_user')
        self.assertEqual((st, self.sent), (200, []))


class PhoneUniqueTest(TestCase):
    def test_same_number_in_any_format_is_taken(self):
        co = Company.objects.create(name="PhCo")
        u = PortalUser(company=co, username="ph1", phone="09121234567")
        u.set_password("x" * 8)
        u.save()
        self.assertTrue(PortalUser.phone_taken("+98 ۹۱۲ 123 4567"))
        self.assertFalse(PortalUser.phone_taken("09121234567", exclude_id=u.id))
        self.assertFalse(PortalUser.phone_taken("09121234568"))
