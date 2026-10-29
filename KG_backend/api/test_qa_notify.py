"""QA audit: SMS notifications (api/notify.py).

Focus is the login-device check (``check_login_device``) that runs inside every
successful portal login: the rotating ``kg_dev`` cookie, the new-device SMS,
copied-cookie (clone) detection, the ``notify_new_device`` opt-out, and the
rule that a notification problem can never break a login. The manual-update
fan-out and the welcome SMS are covered for their opt-out / dedupe / scoping
rules.

Only the SMS provider boundary (``portal._post_sms``) is faked; every SMS the
code would send is captured so the real body is asserted.
"""
import hashlib
import json
import os
import re
from datetime import timedelta
from unittest import mock

from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from api import notify, portal, ratelimit
from api.models import (
    AuthToken, Car, Company, CompanyCarAccess, KnownDevice, NotificationLog, OtpChallenge,
    PortalUser, RetiredDevice, UserCarAccess,
)

LINK = re.compile(r"https?://|www\.|\b[\w-]+\.(com|ir|net|org)\b", re.I)
PASSWORD = 'qa-notify-pass-123'


def _sha(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class _SmsCapture(TestCase):
    sms_result = (True, '1234567890')

    def setUp(self):
        self.sms = []

        def fake(phone, text):
            self.sms.append((phone, text))
            if isinstance(self.sms_result, BaseException):
                raise self.sms_result
            return self.sms_result

        p = mock.patch.object(portal, '_post_sms', side_effect=fake)
        p.start()
        self.addCleanup(p.stop)
        self.rf = RequestFactory()
        self.company = Company.objects.create(name='QA-Notify-Co')

    def user(self, username, phone='09121112233', **kw):
        u = PortalUser(company=self.company, username=username, phone=phone,
                       role='after_sales_specialist', **kw)
        u.set_password(PASSWORD)
        u.save()
        return u

    def login(self, user, cookie=None, ua='QA-Browser/1.0', keep_token_id=None):
        req = self.rf.get('/', HTTP_USER_AGENT=ua)
        if cookie is not None:
            req.COOKIES[notify.DEVICE_COOKIE] = cookie
        resp = notify.check_login_device(user, req, HttpResponse(), keep_token_id=keep_token_id)
        c = resp.cookies.get(notify.DEVICE_COOKIE)
        return resp, (c.value if c is not None else None)

    def kinds(self, user):
        return list(NotificationLog.objects.filter(user=user).order_by('id')
                    .values_list('kind', 'sent'))


# ---------------------------------------------------------------------------
# Device cookie lifecycle
# ---------------------------------------------------------------------------
class DeviceCookieTests(_SmsCapture):

    def test_first_ever_login_registers_device_without_sms(self):
        u = self.user('qa_n_first')
        resp, dev = self.login(u)
        self.assertEqual(self.sms, [])
        self.assertRegex(dev, r'^[0-9a-f]{32}$')
        kd = KnownDevice.objects.get(user=u)
        self.assertEqual(kd.device_hash, _sha(dev))           # stored hashed, never raw
        self.assertFalse(KnownDevice.objects.filter(device_hash=dev).exists())
        self.assertEqual(kd.user_agent, 'QA-Browser/1.0')
        self.assertEqual(self.kinds(u), [])

    def test_cookie_attributes_are_hardened(self):
        resp, _ = self.login(self.user('qa_n_attr'))
        c = resp.cookies[notify.DEVICE_COOKIE]
        self.assertTrue(c['httponly'])
        self.assertTrue(c['secure'])
        self.assertEqual(c['samesite'], 'Lax')
        self.assertEqual(c['path'], '/')
        self.assertEqual(int(c['max-age']), 2 * 365 * 86400)

    def test_known_device_rotates_silently(self):
        u = self.user('qa_n_rot')
        _, d1 = self.login(u)
        _, d2 = self.login(u, cookie=d1, ua='QA-Browser/2.0')
        self.assertNotEqual(d1, d2)
        self.assertEqual(self.sms, [])
        kd = KnownDevice.objects.get(user=u)                  # same row, rotated
        self.assertEqual(kd.device_hash, _sha(d2))
        self.assertEqual(kd.user_agent, 'QA-Browser/2.0')
        self.assertTrue(RetiredDevice.objects.filter(user=u, device_hash=_sha(d1)).exists())

    def test_rotation_chain_over_many_logins_never_alerts(self):
        u = self.user('qa_n_chain')
        _, d = self.login(u)
        seen = {d}
        for _ in range(4):
            _, d = self.login(u, cookie=d)
            self.assertNotIn(d, seen)
            seen.add(d)
        self.assertEqual(self.sms, [])
        self.assertEqual(KnownDevice.objects.filter(user=u).count(), 1)
        self.assertEqual(RetiredDevice.objects.filter(user=u).count(), 4)

    def test_long_user_agent_is_truncated_to_300(self):
        u = self.user('qa_n_ua')
        self.login(u, ua='A' * 1000)
        self.assertEqual(len(KnownDevice.objects.get(user=u).user_agent), 300)

    def test_request_none_still_sets_cookie(self):
        u = self.user('qa_n_noreq')
        resp = notify.check_login_device(u, None, HttpResponse())
        self.assertIn(notify.DEVICE_COOKIE, resp.cookies)
        self.assertEqual(KnownDevice.objects.get(user=u).user_agent, '')


# ---------------------------------------------------------------------------
# New-device SMS
# ---------------------------------------------------------------------------
class NewDeviceSmsTests(_SmsCapture):

    def test_second_device_triggers_one_link_free_sms_to_owner(self):
        u = self.user('qa_n_new', phone=' 09125550001 ')
        self.login(u)                                          # device A
        resp, _ = self.login(u, cookie=None)                   # device B (no cookie)
        self.assertEqual(len(self.sms), 1)
        phone, body = self.sms[0]
        self.assertEqual(phone, '09125550001')                 # stripped
        self.assertIn('qa_n_new', body)
        self.assertIn('دستگاه جدید', body)
        self.assertTrue(body.rstrip().endswith('لغو11'))      # operator opt-out footer
        self.assertIsNone(LINK.search(body))
        self.assertRegex(body, r'\d{4}/\d{2}/\d{2} \d{2}:\d{2}')   # Jalali timestamp
        self.assertEqual(self.kinds(u), [('new_device', True)])
        self.assertEqual(KnownDevice.objects.filter(user=u).count(), 2)

    def test_unknown_or_blank_cookie_counts_as_new_device(self):
        u = self.user('qa_n_unknown')
        self.login(u)
        self.login(u, cookie='deadbeef' * 4)                   # never issued
        self.login(u, cookie='   ')                            # blank after strip
        self.assertEqual([k for k, _ in self.kinds(u)], ['new_device', 'new_device'])

    def test_opt_out_suppresses_new_device_sms_but_still_tracks_device(self):
        u = self.user('qa_n_optout', notify_new_device=False)
        self.login(u)
        _, dev = self.login(u)
        self.assertEqual(self.sms, [])
        self.assertEqual(self.kinds(u), [])
        self.assertTrue(KnownDevice.objects.filter(user=u, device_hash=_sha(dev)).exists())

    def test_no_phone_means_no_sms(self):
        u = self.user('qa_n_nophone', phone='   ')
        self.login(u)
        self.login(u)
        self.assertEqual(self.sms, [])
        self.assertEqual(self.kinds(u), [])

    def test_another_users_device_cookie_is_new_for_me_and_silent_for_them(self):
        a = self.user('qa_n_owner_a', phone='09120000001')
        b = self.user('qa_n_owner_b', phone='09120000002')
        _, dev_a = self.login(a)
        self.login(b)                                          # b's first device
        self.login(b, cookie=dev_a)                            # b presents a's cookie
        self.assertEqual([p for p, _ in self.sms], ['09120000002'])
        self.assertEqual(self.kinds(a), [])
        # a's device is untouched: still current, not retired, a's next login is silent
        self.assertTrue(KnownDevice.objects.filter(user=a, device_hash=_sha(dev_a)).exists())
        self.assertFalse(RetiredDevice.objects.filter(device_hash=_sha(dev_a)).exists())
        self.login(a, cookie=dev_a)
        self.assertEqual(len(self.sms), 1)

    def test_provider_rejection_is_logged_as_unsent_and_login_proceeds(self):
        self.sms_result = (False, '11')
        u = self.user('qa_n_reject')
        self.login(u)
        resp, dev = self.login(u)
        self.assertIsNotNone(dev)
        self.assertEqual(self.kinds(u), [('new_device', False)])

    def test_provider_crash_does_not_break_login(self):
        self.sms_result = ConnectionError('gateway down')
        u = self.user('qa_n_crash')
        self.login(u)
        resp, dev = self.login(u)
        self.assertEqual(resp.status_code, 200)
        self.assertRegex(dev, r'^[0-9a-f]{32}$')
        self.assertEqual(self.kinds(u), [('new_device', False)])

    def test_unexpected_internal_error_returns_response_unchanged(self):
        ghost = PortalUser(company=self.company, username='qa_n_unsaved', phone='0912')
        resp = notify.check_login_device(ghost, self.rf.get('/'), HttpResponse('ok'))
        self.assertEqual(resp.content, b'ok')
        self.assertNotIn(notify.DEVICE_COOKIE, resp.cookies)
        self.assertEqual(self.sms, [])


# ---------------------------------------------------------------------------
# Copied-cookie (clone) detection
# ---------------------------------------------------------------------------
class CloneDetectionTests(_SmsCapture):

    def _rotated_pair(self, u):
        _, old = self.login(u)
        _, new = self.login(u, cookie=old)
        return old, new

    def test_retired_cookie_revokes_other_sessions_and_alerts(self):
        u = self.user('qa_n_clone', notify_new_device=False)   # security SMS ignores opt-out
        old, _ = self._rotated_pair(u)
        t_other = AuthToken.issue(u)
        t_keep = AuthToken.issue(u)
        self.login(u, cookie=old, keep_token_id=t_keep.pk)
        self.assertFalse(AuthToken.objects.filter(pk=t_other.pk).exists())
        self.assertTrue(AuthToken.objects.filter(pk=t_keep.pk).exists())
        self.assertEqual(self.kinds(u), [('device_clone', True)])
        body = self.sms[-1][1]
        self.assertIn('qa_n_clone', body)
        self.assertIn('هشدار امنیتی', body)
        self.assertIsNone(LINK.search(body))
        self.assertTrue(body.rstrip().endswith('لغو11'))
        log = NotificationLog.objects.get(user=u, kind='device_clone')
        self.assertEqual(log.key, _sha(old)[:16])

    def test_clone_without_keep_token_revokes_all_sessions(self):
        u = self.user('qa_n_clone_all')
        old, _ = self._rotated_pair(u)
        AuthToken.issue(u); AuthToken.issue(u)
        self.login(u, cookie=old)
        self.assertFalse(AuthToken.objects.filter(user=u).exists())

    def test_clone_without_phone_still_revokes_but_sends_nothing(self):
        u = self.user('qa_n_clone_nophone', phone='')
        old, _ = self._rotated_pair(u)
        AuthToken.issue(u)
        self.login(u, cookie=old)
        self.assertFalse(AuthToken.objects.filter(user=u).exists())
        self.assertEqual(self.sms, [])

    def test_clone_detection_is_per_user(self):
        a = self.user('qa_n_ca', phone='09120000011')
        b = self.user('qa_n_cb', phone='09120000012')
        old_a, _ = self._rotated_pair(a)
        tok_a = AuthToken.issue(a)
        self.login(b)
        self.login(b, cookie=old_a)                            # a's retired id, at b
        self.assertTrue(AuthToken.objects.filter(pk=tok_a.pk).exists())
        self.assertEqual(self.kinds(a), [])
        self.assertEqual(self.kinds(b), [('new_device', True)])

    def test_current_cookie_used_by_copier_first_is_not_flagged(self):
        # By design the chain cannot tell who rotates first: the holder of the
        # current id rotates silently, and the other party then holds a retired id.
        u = self.user('qa_n_race')
        _, cur = self.login(u)
        self.login(u, cookie=cur)                              # copier rotates first
        self.assertEqual(self.sms, [])
        self.login(u, cookie=cur)                              # owner comes back
        self.assertEqual(self.kinds(u), [('device_clone', True)])


# ---------------------------------------------------------------------------
# Wired into the real login (OTP flow)
# ---------------------------------------------------------------------------
class LoginFlowIntegrationTests(_SmsCapture):

    def setUp(self):
        super().setUp()
        ratelimit._HITS.clear()
        for p in (mock.patch.object(portal, '_verify_turnstile', return_value=True),
                  mock.patch.dict(os.environ, {'KG_RL_DISABLE': '1'})):
            p.start()
            self.addCleanup(p.stop)
        self.u = self.user('qa_n_flow', phone='09127778899')

    def _login(self, client):
        # Back-date earlier challenges so the per-account resend interval
        # (a separate, separately-tested control) does not block this login.
        OtpChallenge.objects.filter(user=self.u).update(
            last_sent_at=timezone.now() - timedelta(hours=1))
        r = client.post('/api/auth/login/', json.dumps(
            {'username': 'qa_n_flow', 'password': PASSWORD, 'turnstile_token': 't'}),
            content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        sess = r.json()['otp_session']
        code = re.search(r'(\d{6})', [t for _, t in self.sms if 'کد ورود' in t][-1]).group(1)
        r = client.post('/api/auth/verify-otp/', json.dumps({'otp_session': sess, 'code': code}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        return r

    def device_sms(self):
        return [t for _, t in self.sms if 'دستگاه جدید' in t]

    def test_login_sets_device_cookie_and_second_browser_alerts(self):
        browser1 = Client()
        r = self._login(browser1)
        first = r.cookies[notify.DEVICE_COOKIE].value
        self.assertEqual(self.device_sms(), [])                # very first device
        r = self._login(browser1)                              # same browser again
        self.assertNotEqual(r.cookies[notify.DEVICE_COOKIE].value, first)
        self.assertEqual(self.device_sms(), [])
        self._login(Client())                                  # a different browser
        self.assertEqual(len(self.device_sms()), 1)

    def test_sms_gateway_failure_does_not_block_session(self):
        self._login(Client())
        orig = portal._post_sms.side_effect

        def flaky(phone, text):                                # OTP ok, alert crashes
            if 'دستگاه جدید' in text:
                raise TimeoutError('gateway')
            return orig(phone, text)

        portal._post_sms.side_effect = flaky
        r = self._login(Client())
        self.assertIn('token', r.json())
        self.assertIsNotNone(AuthToken.resolve(r.json()['token']))
        self.assertEqual(NotificationLog.objects.get(user=self.u, kind='new_device').sent, False)


# ---------------------------------------------------------------------------
# Manual-update fan-out + welcome SMS
# ---------------------------------------------------------------------------
class ManualUpdateTests(_SmsCapture):

    def setUp(self):
        super().setUp()
        self.car = Car.objects.create(brand_name='Toyota', car_name='  Camry QA  ', year=2023,
                                      db_address='x')
        CompanyCarAccess.objects.create(company=self.company, car=self.car, documents=[])

    def grant(self, u, car=None):
        UserCarAccess.objects.create(user=u, car=car or self.car, documents=[])
        return u

    def test_sends_once_per_user_per_car_per_day(self):
        u = self.grant(self.user('qa_m_a'))
        self.assertEqual(notify.notify_manual_update(self.car), 1)
        self.assertEqual(notify.notify_manual_update(self.car), 0)
        self.assertEqual(len(self.sms), 1)
        body = self.sms[0][1]
        self.assertIn('Camry QA', body)
        self.assertNotIn('  Camry', body)
        self.assertIsNone(LINK.search(body))
        log = NotificationLog.objects.get(user=u)
        self.assertEqual((log.kind, log.key), ('manual_update', f'car:{self.car.id}'))
        NotificationLog.objects.filter(pk=log.pk).update(
            created_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(notify.notify_manual_update(self.car), 1)

    def test_only_opted_in_active_reachable_users_with_access(self):
        ok = self.grant(self.user('qa_m_ok', phone='09120000100'))
        self.grant(self.user('qa_m_opt', phone='09120000101', notify_manual_update=False))
        self.grant(self.user('qa_m_nophone', phone=''))
        self.grant(self.user('qa_m_locked', phone='09120000103', locked=True))
        self.grant(self.user('qa_m_inactive', phone='09120000104', active=False))
        self.user('qa_m_nogrant', phone='09120000105')
        self.assertEqual(notify.notify_manual_update(self.car), 1)
        self.assertEqual([p for p, _ in self.sms], ['09120000100'])
        self.assertTrue(NotificationLog.objects.filter(user=ok).exists())

    def test_company_losing_the_car_stops_notifications(self):
        self.grant(self.user('qa_m_revoked'))
        CompanyCarAccess.objects.filter(company=self.company, car=self.car).delete()
        self.assertEqual(notify.notify_manual_update(self.car), 0)
        self.assertEqual(self.sms, [])

    def test_other_tenant_users_not_notified(self):
        other = Company.objects.create(name='QA-Notify-Other')
        u = PortalUser(company=other, username='qa_m_other', phone='09120000200',
                       role='after_sales_specialist')
        u.set_password('x'); u.save()
        # a stray per-user row without the other company's purchase
        UserCarAccess.objects.create(user=u, car=self.car, documents=[])
        self.assertEqual(notify.notify_manual_update(self.car), 0)

    def test_inactive_company_not_notified(self):
        self.grant(self.user('qa_m_coinactive'))
        Company.objects.filter(pk=self.company.pk).update(active=False)
        self.assertEqual(notify.notify_manual_update(self.car), 0)

    def test_failed_send_is_not_counted_and_retried_next_run(self):
        self.sms_result = (False, '11')
        self.grant(self.user('qa_m_fail'))
        self.assertEqual(notify.notify_manual_update(self.car), 0)
        self.assertEqual(NotificationLog.objects.get().sent, False)


class WelcomeSmsTests(_SmsCapture):

    def test_welcome_carries_credentials_but_never_logs_password(self):
        u = self.user('qa_w_user', phone=' 09121230000 ')
        self.assertTrue(notify.send_welcome_credentials(u, 'S3cret-pw'))
        phone, body = self.sms[0]
        self.assertEqual(phone, '09121230000')
        self.assertIn('qa_w_user', body)
        self.assertIn('S3cret-pw', body)
        log = NotificationLog.objects.get(user=u)
        self.assertEqual((log.kind, log.key, log.sent), ('welcome', '', True))
        self.assertNotIn('S3cret-pw', json.dumps(list(
            NotificationLog.objects.values_list('key', flat=True))))

    def test_no_phone_sends_nothing(self):
        u = self.user('qa_w_nophone', phone='')
        self.assertFalse(notify.send_welcome_credentials(u, 'pw'))
        self.assertEqual(self.sms, [])
        self.assertFalse(NotificationLog.objects.exists())

    def test_gateway_rejection_returns_false_and_logs_unsent(self):
        self.sms_result = (False, '11')
        u = self.user('qa_w_reject')
        self.assertFalse(notify.send_welcome_credentials(u, 'pw'))
        self.assertFalse(NotificationLog.objects.get(user=u).sent)

    def test_gateway_crash_returns_false(self):
        self.sms_result = OSError('down')
        u = self.user('qa_w_crash')
        self.assertFalse(notify.send_welcome_credentials(u, 'pw'))
        self.assertFalse(NotificationLog.objects.get(user=u).sent)
