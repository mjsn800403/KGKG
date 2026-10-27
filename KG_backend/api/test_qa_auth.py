"""QA audit: portal + platform-admin authentication, sessions and abuse controls.

Covers api/portal.py (login_view, verify_otp_view, resend_otp_view, logout_view,
me_view, _issue_session, _otp_required, _verify_turnstile, admin_login_view,
admin_verify_otp_view) and api/admin_auth.py (require_admin_token).

Only the external HTTP boundaries are faked:
  * ``portal._post_sms``  — the Melipayamak SMS provider (every SMS the code
    would send is captured, so tests read the OTP from the real SMS body);
  * ``urllib.request.urlopen`` — Cloudflare Turnstile siteverify;
  * ``portal._verify_turnstile`` in the login-flow classes, the same way the
    existing suites do (Turnstile itself is tested in TurnstileTests).
Time is moved by rewriting DB timestamps; nothing sleeps.
"""
import datetime
import json
import re
from unittest import mock
from urllib.parse import parse_qs

from django.http import JsonResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from api import portal, ratelimit
from api.admin_auth import require_admin_token
from api.models import (
    ActivityLog, AdminAuthToken, AdminOtpChallenge, AuthToken, Company,
    OrgGraph, OrgNode, OtpChallenge, OtpEvent, PlatformAdmin, PortalUser,
)

PASSWORD = 'correct-horse-battery'
GENERIC_401 = 'نام کاربری یا رمز عبور اشتباه است.'


def _company(name=None, **kw):
    return Company.objects.create(name=name or f'QA-Co-{Company.objects.count() + 1}', **kw)


def _user(username, company=None, phone='', password=PASSWORD, **kw):
    u = PortalUser(company=company or _company(), username=username, phone=phone,
                   role='after_sales_specialist', **kw)
    u.set_password(password)
    u.save()
    return u


class _SmsMixin:
    """Capture every SMS instead of calling the provider."""

    sms_ok = True

    def _start_sms_capture(self):
        self.sms = []

        def fake_post(phone, text):
            self.sms.append((phone, text))
            return (True, '9876543210') if self.sms_ok else (False, '11')

        p = mock.patch.object(portal, '_post_sms', side_effect=fake_post)
        p.start()
        self.addCleanup(p.stop)

    def otp_sms(self):
        return [(ph, t) for ph, t in self.sms if 'کد ورود' in t]

    def last_code(self):
        ph, text = self.otp_sms()[-1]
        return re.search(r'(\d{6})', text).group(1)


class _PortalBase(_SmsMixin, TestCase):
    def setUp(self):
        ratelimit._HITS.clear()
        self._start_sms_capture()
        p = mock.patch.object(portal, '_verify_turnstile', return_value=True)
        p.start()
        self.addCleanup(p.stop)
        # Per-IP limiter is exercised in test_qa_ratelimit; here it would only
        # mask the per-account OTP caps under test.
        e = mock.patch.dict('os.environ', {'KG_RL_DISABLE': '1'})
        e.start()
        self.addCleanup(e.stop)
        self.client = Client(raise_request_exception=False)

    def post(self, path, body=None, **extra):
        return self.client.post(path, json.dumps(body if body is not None else {}),
                                content_type='application/json', **extra)

    def login(self, username, password=PASSWORD, **extra):
        return self.post('/api/auth/login/', {'username': username, 'password': password,
                                              'turnstile_token': 't'}, **extra)

    def verify(self, otp_session, code):
        return self.post('/api/auth/verify-otp/', {'otp_session': otp_session, 'code': code})

    def resend(self, otp_session):
        return self.post('/api/auth/resend-otp/', {'otp_session': otp_session})

    def wrong_code(self):
        good = self.last_code()
        return '000000' if good != '000000' else '111111'


# ---------------------------------------------------------------------------
# Password step (accounts without the SMS factor)
# ---------------------------------------------------------------------------
class PasswordLoginTests(_PortalBase):

    def setUp(self):
        super().setUp()
        self.user = _user('qa_tech', email='Tech@Example.ir')

    def test_password_only_login_issues_hardened_session_cookie(self):
        r = self.login('qa_tech')
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertIsNotNone(AuthToken.resolve(data['token']))
        self.assertEqual(data['user']['username'], 'qa_tech')
        c = r.cookies['kg_portal_token']
        self.assertEqual(c.value, data['token'])
        self.assertTrue(c['httponly'])
        self.assertTrue(c['secure'])
        self.assertEqual(c['samesite'], 'Lax')
        # cookie may never outlive the token's idle TTL (14 days)
        self.assertEqual(int(c['max-age']), 14 * 24 * 3600)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login_at)
        self.assertTrue(ActivityLog.objects.filter(user=self.user, action='login').exists())

    def test_login_by_email_is_case_insensitive(self):
        self.assertEqual(self.login('tech@example.IR').status_code, 200)
        self.assertEqual(self.login('QA_TECH').status_code, 200)

    def test_no_otp_sms_for_account_without_phone(self):
        self.login('qa_tech')
        self.assertEqual(self.otp_sms(), [])

    def test_get_is_rejected(self):
        self.assertEqual(self.client.get('/api/auth/login/').status_code, 405)

    def test_failed_turnstile_blocks_before_password_check(self):
        with mock.patch.object(portal, '_verify_turnstile', return_value=False):
            r = self.login('qa_tech')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())

    def test_empty_password_rejected(self):
        self.assertEqual(self.login('qa_tech', password='').status_code, 401)

    def test_non_string_username_is_a_client_error_not_500(self):
        # Regression (fixed in this change): portal.py:556 `(b.get('username') or '').strip()` raises AttributeError
        # for a JSON number/list/object -> HTTP 500 instead of 400/401.
        r = self.post('/api/auth/login/', {'username': 12345, 'password': 'x',
                                           'turnstile_token': 't'})
        self.assertIn(r.status_code, (400, 401))


class UserEnumerationTests(_PortalBase):
    """Unknown user, invited (no password yet) and wrong password must be
    indistinguishable, and the first two must burn a real hash check."""

    def setUp(self):
        super().setUp()
        self.user = _user('known_user')
        self.invited = _user('invited_user')
        self.invited.set_unusable_password()
        self.invited.invite_status = 'invited'
        self.invited.save()

    def _spy(self):
        from django.contrib.auth import hashers
        return mock.patch.object(hashers, 'check_password', wraps=hashers.check_password)

    def test_three_failure_modes_return_identical_responses(self):
        responses = [self.login('no_such_user', 'whatever-pass'),
                     self.login('known_user', 'wrong-password'),
                     self.login('invited_user', 'whatever-pass')]
        self.assertEqual({r.status_code for r in responses}, {401})
        self.assertEqual({r.content for r in responses}, {responses[0].content})
        self.assertEqual(responses[0].json()['error'], GENERIC_401)

    def test_unknown_user_burns_dummy_hash_check(self):
        with self._spy() as spy:
            self.login('no_such_user', 'pw-attempt')
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(spy.call_args[0], ('pw-attempt', portal._DUMMY_PASSWORD_HASH))

    def test_invited_user_burns_dummy_hash_check(self):
        with self._spy() as spy:
            self.login('invited_user', 'pw-attempt')
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(spy.call_args[0][1], portal._DUMMY_PASSWORD_HASH)

    def test_dummy_hash_is_a_real_hash_matching_nothing_useful(self):
        from django.contrib.auth.hashers import check_password, identify_hasher
        identify_hasher(portal._DUMMY_PASSWORD_HASH)   # raises if not a valid hash
        self.assertFalse(check_password('', portal._DUMMY_PASSWORD_HASH))

    def test_invite_not_accepted_rejected_even_with_matching_hash(self):
        # Regression: password_set gates login, not merely the hash.
        self.invited.set_password('known-password')
        self.invited.password_set = False
        self.invited.save()
        r = self.login('invited_user', 'known-password')
        self.assertEqual(r.status_code, 401)
        self.assertFalse(AuthToken.objects.filter(user=self.invited).exists())


class AccountStateTests(_PortalBase):

    def setUp(self):
        super().setUp()
        self.user = _user('state_user')

    def _assert_refused(self, status=403):
        r = self.login('state_user')
        self.assertEqual(r.status_code, status, r.content)
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())
        return r

    def test_inactive_user_refused(self):
        self.user.active = False
        self.user.save()
        self._assert_refused()

    def test_inactive_company_refused(self):
        self.user.company.active = False
        self.user.company.save()
        self._assert_refused()

    def test_locked_user_refused(self):
        self.user.locked = True
        self.user.save()
        self._assert_refused()

    def test_locked_state_not_revealed_without_correct_password(self):
        self.user.locked = True
        self.user.save()
        r = self.login('state_user', 'wrong-password')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()['error'], GENERIC_401)

    def test_expired_user_refused(self):
        self.user.access_expires_at = timezone.now() - datetime.timedelta(minutes=1)
        self.user.save()
        self._assert_refused()

    def test_future_expiry_allows_login(self):
        self.user.access_expires_at = timezone.now() + datetime.timedelta(days=1)
        self.user.save()
        self.assertEqual(self.login('state_user').status_code, 200)

    def test_company_root_expiry_governs_every_seat(self):
        # The user's own expiry is open-ended, but the company's root seat
        # (the 0-level occupant) has lapsed -> the whole company is expired.
        root = _user('root_user', company=self.user.company,
                     access_expires_at=timezone.now() - datetime.timedelta(hours=1))
        graph = OrgGraph.objects.create(company=self.user.company)
        root_node = OrgNode.objects.create(graph=graph, is_root=True, occupant=root)
        OrgNode.objects.create(graph=graph, parent=root_node, occupant=self.user)
        self._assert_refused()

    def test_root_renewal_reopens_seat_despite_stale_own_expiry(self):
        self.user.access_expires_at = timezone.now() - datetime.timedelta(days=3)
        self.user.save()
        root = _user('root_user2', company=self.user.company,
                     access_expires_at=timezone.now() + datetime.timedelta(days=30))
        graph = OrgGraph.objects.create(company=self.user.company)
        OrgNode.objects.create(graph=graph, is_root=True, occupant=root)
        self.assertEqual(self.login('state_user').status_code, 200)


# ---------------------------------------------------------------------------
# Single-session rule
# ---------------------------------------------------------------------------
class SingleSessionTests(_PortalBase):

    def setUp(self):
        super().setUp()
        self.user = _user('shared_acct')
        self.other = _user('bystander')

    def test_new_login_signs_out_previous_browser(self):
        first = self.login('shared_acct').json()['token']
        second = self.login('shared_acct').json()['token']
        self.assertIsNone(AuthToken.resolve(first))
        self.assertIsNotNone(AuthToken.resolve(second))
        self.assertEqual(Client().get('/api/auth/me/', HTTP_AUTHORIZATION=f'Bearer {first}').status_code, 401)
        self.assertEqual(Client().get('/api/auth/me/', HTTP_AUTHORIZATION=f'Bearer {second}').status_code, 200)

    def test_rule_does_not_touch_other_accounts(self):
        theirs = AuthToken.issue(self.other).key
        self.login('shared_acct')
        self.login('shared_acct')
        self.assertIsNotNone(AuthToken.resolve(theirs))

    def test_rule_can_be_switched_off(self):
        with mock.patch.dict('os.environ', {'KG_SINGLE_SESSION': '0'}):
            first = self.login('shared_acct').json()['token']
            second = self.login('shared_acct').json()['token']
        self.assertIsNotNone(AuthToken.resolve(first))
        self.assertIsNotNone(AuthToken.resolve(second))

    def test_logout_revokes_only_presented_session(self):
        with mock.patch.dict('os.environ', {'KG_SINGLE_SESSION': '0'}):
            a = self.login('shared_acct').json()['token']
            b = self.login('shared_acct').json()['token']
        r = self.post('/api/auth/logout/', HTTP_AUTHORIZATION=f'Bearer {a}')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(AuthToken.resolve(a))
        self.assertIsNotNone(AuthToken.resolve(b))


# ---------------------------------------------------------------------------
# SMS second factor
# ---------------------------------------------------------------------------
class OtpLoginTests(_PortalBase):

    def setUp(self):
        super().setUp()
        self.user = _user('otp_user', phone='09121234567')

    def _start(self):
        r = self.login('otp_user')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['otp_session']

    def test_otp_required_only_with_phone_and_flag(self):
        self.assertTrue(portal._otp_required(self.user))
        self.user.otp_enabled = False
        self.assertFalse(portal._otp_required(self.user))
        self.user.otp_enabled = True
        self.user.phone = '   '
        self.assertFalse(portal._otp_required(self.user))

    def test_password_step_sends_code_and_issues_no_session(self):
        r = self.login('otp_user')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertNotIn('token', data)
        self.assertNotIn('kg_portal_token', r.cookies)
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())
        self.assertEqual(data['phone_hint'], '091******67')
        self.assertNotIn('1234', data['phone_hint'])
        self.assertEqual(len(self.otp_sms()), 1)
        self.assertEqual(self.otp_sms()[0][0], '09121234567')
        self.assertEqual(OtpEvent.objects.filter(user=self.user, kind='send').count(), 1)
        # code stored only as a hash
        ch = OtpChallenge.objects.get(user=self.user)
        self.assertNotEqual(ch.code_hash, self.last_code())
        self.assertEqual(ch.code_hash, OtpChallenge._hash(self.last_code()))

    def test_correct_code_issues_session_and_cannot_be_replayed(self):
        sid = self._start()
        code = self.last_code()
        r = self.verify(sid, code)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNotNone(AuthToken.resolve(r.json()['token']))
        self.assertFalse(OtpChallenge.objects.filter(user=self.user).exists())
        self.assertEqual(self.verify(sid, code).status_code, 401)

    def test_otp_disabled_account_logs_in_with_password_only(self):
        self.user.otp_enabled = False
        self.user.save()
        r = self.login('otp_user')
        self.assertEqual(r.status_code, 200)
        self.assertIn('token', r.json())
        self.assertEqual(self.otp_sms(), [])

    def test_wrong_code_counts_a_failure(self):
        sid = self._start()
        r = self.verify(sid, self.wrong_code())
        self.assertEqual(r.status_code, 401)
        self.assertEqual(OtpEvent.objects.filter(user=self.user, kind='fail').count(), 1)
        self.assertEqual(OtpChallenge.objects.get(user=self.user).attempts, 1)

    def test_challenge_dies_after_max_attempts_even_for_correct_code(self):
        sid = self._start()
        good, bad = self.last_code(), self.wrong_code()
        for _ in range(OtpChallenge.MAX_ATTEMPTS):
            self.assertEqual(self.verify(sid, bad).status_code, 401)
        r = self.verify(sid, good)          # 6th attempt
        self.assertEqual(r.status_code, 401)
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())

    def test_fifth_attempt_can_still_succeed(self):
        sid = self._start()
        good, bad = self.last_code(), self.wrong_code()
        for _ in range(OtpChallenge.MAX_ATTEMPTS - 1):
            self.verify(sid, bad)
        self.assertEqual(self.verify(sid, good).status_code, 200)

    def test_expired_challenge_rejected(self):
        sid = self._start()
        OtpChallenge.objects.filter(user=self.user).update(
            expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertEqual(self.verify(sid, self.last_code()).status_code, 401)

    def test_unknown_session_rejected(self):
        self._start()
        self.assertEqual(self.verify('not-a-session', self.last_code()).status_code, 401)

    def test_missing_fields_and_wrong_method(self):
        self.assertEqual(self.post('/api/auth/verify-otp/', {'otp_session': 'x'}).status_code, 400)
        self.assertEqual(self.post('/api/auth/verify-otp/', {'code': '123456'}).status_code, 400)
        self.assertEqual(self.client.get('/api/auth/verify-otp/').status_code, 405)

    def test_account_locked_after_password_step_cannot_finish(self):
        sid = self._start()
        PortalUser.objects.filter(pk=self.user.pk).update(locked=True)
        r = self.verify(sid, self.last_code())
        self.assertEqual(r.status_code, 403)
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())

    def test_account_expired_after_password_step_cannot_finish(self):
        sid = self._start()
        PortalUser.objects.filter(pk=self.user.pk).update(
            access_expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertEqual(self.verify(sid, self.last_code()).status_code, 403)

    def test_relogin_within_resend_interval_is_throttled(self):
        self._start()
        r = self.login('otp_user')
        self.assertEqual(r.status_code, 429)
        wait = int(r['Retry-After'])
        self.assertTrue(1 <= wait <= 120, wait)
        self.assertEqual(len(self.otp_sms()), 1)

    def test_relogin_after_interval_sends_new_code_and_kills_old(self):
        old_sid = self._start()
        old_code = self.last_code()
        past = timezone.now() - OtpChallenge.RESEND_INTERVAL - datetime.timedelta(seconds=1)
        OtpChallenge.objects.filter(user=self.user).update(last_sent_at=past, expires_at=past)
        new_sid = self._start()
        self.assertEqual(len(self.otp_sms()), 2)
        self.assertEqual(self.verify(old_sid, old_code).status_code, 401)
        self.assertEqual(self.verify(new_sid, self.last_code()).status_code, 200)

    def test_daily_send_cap_blocks_at_limit(self):
        for _ in range(10):
            OtpEvent.objects.create(user=self.user, kind=OtpEvent.SEND)
        r = self.login('otp_user')
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.otp_sms(), [])
        self.assertFalse(OtpChallenge.objects.filter(user=self.user).exists())

    def test_daily_send_cap_boundary_one_below_allows(self):
        for _ in range(9):
            OtpEvent.objects.create(user=self.user, kind=OtpEvent.SEND)
        self.assertEqual(self.login('otp_user').status_code, 200)

    def test_send_cap_env_override_and_garbage_fallback(self):
        OtpEvent.objects.create(user=self.user, kind=OtpEvent.SEND)
        OtpEvent.objects.create(user=self.user, kind=OtpEvent.SEND)
        with mock.patch.dict('os.environ', {'KG_OTP_MAX_SENDS_PER_DAY': '2'}):
            self.assertTrue(OtpEvent.sends_exhausted(self.user))
        for bad in ('0', '-5', 'abc'):
            with mock.patch.dict('os.environ', {'KG_OTP_MAX_SENDS_PER_DAY': bad}):
                self.assertFalse(OtpEvent.sends_exhausted(self.user), bad)

    def test_events_older_than_24h_do_not_count(self):
        for _ in range(10):
            OtpEvent.objects.create(user=self.user, kind=OtpEvent.SEND)
        OtpEvent.objects.filter(user=self.user).update(
            at=timezone.now() - datetime.timedelta(hours=25))
        self.assertEqual(self.login('otp_user').status_code, 200)

    def test_daily_fail_cap_blocks_even_correct_code(self):
        sid = self._start()
        for _ in range(15):
            OtpEvent.objects.create(user=self.user, kind=OtpEvent.FAIL)
        r = self.verify(sid, self.last_code())
        self.assertEqual(r.status_code, 429)
        self.assertFalse(OtpChallenge.objects.filter(user=self.user).exists())
        self.assertFalse(AuthToken.objects.filter(user=self.user).exists())

    def test_daily_fail_cap_blocks_new_password_step(self):
        for _ in range(15):
            OtpEvent.objects.create(user=self.user, kind=OtpEvent.FAIL)
        self.assertEqual(self.login('otp_user').status_code, 429)
        self.assertEqual(self.otp_sms(), [])

    def test_fail_cap_cannot_be_dodged_with_fresh_challenges(self):
        # 3 challenges x 5 wrong codes = 15 fails -> daily cap, regardless of
        # per-challenge attempt resets.
        for _ in range(3):
            OtpChallenge.objects.filter(user=self.user).update(
                last_sent_at=timezone.now() - datetime.timedelta(minutes=5),
                expires_at=timezone.now() - datetime.timedelta(minutes=1))
            sid = self._start()
            bad = self.wrong_code()
            for _ in range(5):
                self.verify(sid, bad)
        OtpChallenge.objects.filter(user=self.user).update(
            last_sent_at=timezone.now() - datetime.timedelta(minutes=5),
            expires_at=timezone.now() - datetime.timedelta(minutes=1))
        self.assertEqual(self.login('otp_user').status_code, 429)

    @override_settings(DEBUG=False)
    def test_sms_failure_in_production_returns_503_without_challenge(self):
        self.sms_ok = False
        r = self.login('otp_user')
        self.assertEqual(r.status_code, 503)
        self.assertFalse(OtpChallenge.objects.filter(user=self.user).exists())
        self.assertFalse(OtpEvent.objects.filter(user=self.user).exists())

    @override_settings(DEBUG=True)
    def test_sms_failure_in_debug_still_issues_challenge(self):
        self.sms_ok = False
        r = self.login('otp_user')
        self.assertEqual(r.status_code, 200)
        self.assertIn('otp_session', r.json())

    def test_numeric_code_in_json_is_accepted(self):
        # Regression (fixed in this change): portal.py:620 `(b.get('code') or '').strip()` crashes with
        # AttributeError (HTTP 500) when a client sends the code as a JSON number.
        sid = self._start()
        r = self.verify(sid, int(self.last_code()))
        self.assertEqual(r.status_code, 200)


class ResendOtpTests(_PortalBase):

    def setUp(self):
        super().setUp()
        self.user = _user('resend_user', phone='09351112233')
        r = self.login('resend_user')
        self.sid = r.json()['otp_session']

    def _age_challenge(self):
        past = timezone.now() - OtpChallenge.RESEND_INTERVAL - datetime.timedelta(seconds=1)
        OtpChallenge.objects.filter(user=self.user).update(
            last_sent_at=past, expires_at=timezone.now() + datetime.timedelta(seconds=30))

    def test_unknown_session_400(self):
        self.assertEqual(self.resend('nope').status_code, 400)

    def test_too_soon_is_429_and_sends_nothing(self):
        r = self.resend(self.sid)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(len(self.otp_sms()), 1)

    def test_resend_rotates_code_resets_attempts_and_extends_expiry(self):
        old_code = self.last_code()
        OtpChallenge.objects.filter(user=self.user).update(attempts=3)
        self._age_challenge()
        r = self.resend(self.sid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.otp_sms()), 2)
        ch = OtpChallenge.objects.get(user=self.user)
        self.assertEqual(ch.attempts, 0)
        self.assertGreater(ch.expires_at, timezone.now() + datetime.timedelta(seconds=100))
        new_code = self.last_code()
        if new_code != old_code:
            self.assertEqual(self.verify(self.sid, old_code).status_code, 401)
        self.assertEqual(self.verify(self.sid, new_code).status_code, 200)
        self.assertEqual(OtpEvent.objects.filter(user=self.user, kind='send').count(), 2)

    def test_send_cap_kills_challenge(self):
        for _ in range(10):
            OtpEvent.objects.create(user=self.user, kind=OtpEvent.SEND)
        r = self.resend(self.sid)
        self.assertEqual(r.status_code, 429)
        self.assertFalse(OtpChallenge.objects.filter(user=self.user).exists())

    @override_settings(DEBUG=False)
    def test_provider_failure_in_production_is_503(self):
        self._age_challenge()
        self.sms_ok = False
        self.assertEqual(self.resend(self.sid).status_code, 503)

    def test_get_rejected(self):
        self.assertEqual(self.client.get('/api/auth/resend-otp/').status_code, 405)


# ---------------------------------------------------------------------------
# /me and logout
# ---------------------------------------------------------------------------
class MeAndLogoutTests(_PortalBase):

    def setUp(self):
        super().setUp()
        self.user = _user('me_user')
        self.raw = AuthToken.issue(self.user).key

    def me(self, **extra):
        return Client().get('/api/auth/me/', **extra)

    def test_bearer_without_cookie_is_upgraded_to_httponly_cookie(self):
        r = self.me(HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.cookies['kg_portal_token'].value, self.raw)
        self.assertTrue(r.cookies['kg_portal_token']['httponly'])

    def test_cookie_session_not_reissued(self):
        c = Client()
        c.cookies['kg_portal_token'] = self.raw
        r = c.get('/api/auth/me/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('kg_portal_token', r.cookies)

    def test_anonymous_and_bogus_tokens_have_no_reason(self):
        self.assertEqual(self.me().json(), {'error': 'unauthorized'})
        r = self.me(HTTP_AUTHORIZATION='Bearer forged-token')
        self.assertEqual(r.status_code, 401)
        self.assertNotIn('reason', r.json())

    def _reason(self):
        r = self.me(HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(r.status_code, 401)
        return r.json().get('reason')

    def test_locked_session_reports_locked(self):
        PortalUser.objects.filter(pk=self.user.pk).update(locked=True)
        self.assertEqual(self._reason(), 'locked')

    def test_inactive_company_reports_inactive(self):
        Company.objects.filter(pk=self.user.company_id).update(active=False)
        self.assertEqual(self._reason(), 'inactive')

    def test_expired_access_reports_expired(self):
        PortalUser.objects.filter(pk=self.user.pk).update(
            access_expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertEqual(self._reason(), 'expired')

    def test_expired_token_reports_no_reason(self):
        AuthToken.objects.filter(user=self.user).update(
            expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertIsNone(self._reason())

    def test_logout_requires_post(self):
        self.assertEqual(self.client.get('/api/auth/logout/').status_code, 405)
        self.assertIsNotNone(AuthToken.resolve(self.raw))

    def test_anonymous_logout_still_clears_cookie(self):
        r = self.post('/api/auth/logout/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.cookies['kg_portal_token'].value, '')
        self.assertEqual(int(r.cookies['kg_portal_token']['max-age']), 0)
        self.assertIsNotNone(AuthToken.resolve(self.raw))


# ---------------------------------------------------------------------------
# Cloudflare Turnstile (only urlopen is faked)
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TurnstileTests(TestCase):

    def setUp(self):
        self.req = RequestFactory().post('/x', HTTP_CF_CONNECTING_IP='203.0.113.9',
                                         HTTP_X_FORWARDED_FOR='10.0.0.1')

    def _verify(self, payload=None, token='tok', env=None, exc=None, action='login'):
        env = {'TURNSTILE_SECRET': 's3cret', 'TURNSTILE_HOSTNAMES': '', **(env or {})}
        with mock.patch.dict('os.environ', env), \
                mock.patch.object(portal.urllib.request, 'urlopen') as uo:
            if exc:
                uo.side_effect = exc
            else:
                uo.return_value = _FakeResp(payload or {})
            ok = portal._verify_turnstile(self.req, token, action)
        return ok, uo

    @override_settings(DEBUG=False)
    def test_no_secret_fails_closed_in_production(self):
        with mock.patch.dict('os.environ', {'TURNSTILE_SECRET': ''}):
            self.assertFalse(portal._verify_turnstile(self.req, 'tok'))

    @override_settings(DEBUG=True)
    def test_no_secret_open_in_debug(self):
        with mock.patch.dict('os.environ', {'TURNSTILE_SECRET': ''}):
            self.assertTrue(portal._verify_turnstile(self.req, 'tok'))

    def test_valid_token_passes_and_sends_real_client_ip(self):
        ok, uo = self._verify({'success': True, 'action': 'login', 'hostname': 'kg.ir'})
        self.assertTrue(ok)
        sent = parse_qs(uo.call_args[0][0].data.decode())
        self.assertEqual(sent['secret'], ['s3cret'])
        self.assertEqual(sent['response'], ['tok'])
        self.assertEqual(sent['remoteip'], ['203.0.113.9'])

    def test_empty_or_oversized_token_rejected_without_network(self):
        for tok in ('', None, 'x' * 2049):
            ok, uo = self._verify({'success': True, 'action': 'login'}, token=tok)
            self.assertFalse(ok)
            uo.assert_not_called()

    def test_max_length_token_boundary_accepted(self):
        ok, uo = self._verify({'success': True, 'action': 'login'}, token='x' * 2048)
        self.assertTrue(ok)

    def test_success_false_rejected(self):
        self.assertFalse(self._verify({'success': False, 'error-codes': ['bad']})[0])

    def test_action_mismatch_rejected(self):
        self.assertFalse(self._verify({'success': True, 'action': 'signup'})[0])

    def test_hostname_allowlist_enforced(self):
        env = {'TURNSTILE_HOSTNAMES': 'kgtechvault.ir, www.kgtechvault.ir'}
        self.assertFalse(self._verify({'success': True, 'action': 'login',
                                       'hostname': 'evil.example'}, env=env)[0])
        self.assertTrue(self._verify({'success': True, 'action': 'login',
                                      'hostname': 'www.kgtechvault.ir'}, env=env)[0])

    def test_network_error_fails_closed(self):
        self.assertFalse(self._verify(exc=OSError('timeout'))[0])

    def test_client_ip_fallbacks(self):
        rf = RequestFactory()
        self.assertEqual(portal._client_ip(rf.get('/', HTTP_X_FORWARDED_FOR=' 1.1.1.1 , 2.2.2.2')), '1.1.1.1')
        self.assertEqual(portal._client_ip(rf.get('/', REMOTE_ADDR='9.9.9.9')), '9.9.9.9')


# ---------------------------------------------------------------------------
# Platform admin login + SMS factor
# ---------------------------------------------------------------------------
class AdminLoginTests(_SmsMixin, TestCase):

    def setUp(self):
        ratelimit._HITS.clear()
        self._start_sms_capture()
        p = mock.patch.object(portal, '_verify_turnstile', return_value=True)
        p.start()
        self.addCleanup(p.stop)
        # Per-IP limiter is exercised in test_qa_ratelimit; here it would only
        # mask the per-account OTP caps under test.
        e = mock.patch.dict('os.environ', {'KG_RL_DISABLE': '1'})
        e.start()
        self.addCleanup(e.stop)
        self.admin = PlatformAdmin(username='ops-admin', phone='09129998877')
        self.admin.set_password('admin-long-password')
        self.admin.save()
        self.client = Client(raise_request_exception=False)

    def post(self, path, body):
        return self.client.post(path, json.dumps(body), content_type='application/json')

    def login(self, username='ops-admin', password='admin-long-password'):
        return self.post('/api/admin/login/', {'username': username, 'password': password,
                                               'turnstile_token': 't'})

    def test_bad_credentials_identical_for_unknown_and_wrong_password(self):
        a, b = self.login(password='nope'), self.login(username='ghost')
        self.assertEqual((a.status_code, b.status_code), (401, 401))
        self.assertEqual(a.content, b.content)
        self.assertEqual(self.sms, [])

    def test_inactive_admin_refused(self):
        self.admin.active = False
        self.admin.save()
        self.assertEqual(self.login().status_code, 403)
        self.assertFalse(AdminAuthToken.objects.exists())

    def test_turnstile_failure_403(self):
        with mock.patch.object(portal, '_verify_turnstile', return_value=False):
            self.assertEqual(self.login().status_code, 403)

    def test_get_rejected(self):
        self.assertEqual(self.client.get('/api/admin/login/').status_code, 405)
        self.assertEqual(self.client.get('/api/admin/verify-otp/').status_code, 405)

    def test_phone_admin_gets_otp_not_token(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['otp_required'])
        self.assertNotIn('token', data)
        self.assertFalse(AdminAuthToken.objects.exists())
        self.assertEqual(data['phone_hint'], '091******77')

    def test_admin_otp_round_trip_and_no_replay(self):
        sid = self.login().json()['otp_session']
        code = self.last_code()
        r = self.post('/api/admin/verify-otp/', {'otp_session': sid, 'code': code})
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(AdminAuthToken.resolve(r.json()['token']))
        r = self.post('/api/admin/verify-otp/', {'otp_session': sid, 'code': code})
        self.assertEqual(r.status_code, 401)

    def test_admin_numeric_code_accepted(self):
        sid = self.login().json()['otp_session']
        r = self.post('/api/admin/verify-otp/', {'otp_session': sid, 'code': int(self.last_code())})
        self.assertEqual(r.status_code, 200)

    def test_admin_otp_locks_after_max_attempts(self):
        sid = self.login().json()['otp_session']
        good = self.last_code()
        bad = '000000' if good != '000000' else '111111'
        for _ in range(AdminOtpChallenge.MAX_ATTEMPTS):
            self.assertEqual(self.post('/api/admin/verify-otp/',
                                       {'otp_session': sid, 'code': bad}).status_code, 401)
        r = self.post('/api/admin/verify-otp/', {'otp_session': sid, 'code': good})
        self.assertEqual(r.status_code, 401)
        self.assertFalse(AdminAuthToken.objects.exists())

    def test_admin_otp_expired(self):
        sid = self.login().json()['otp_session']
        AdminOtpChallenge.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
        r = self.post('/api/admin/verify-otp/', {'otp_session': sid, 'code': self.last_code()})
        self.assertEqual(r.status_code, 401)

    def test_admin_deactivated_between_steps_refused(self):
        sid = self.login().json()['otp_session']
        PlatformAdmin.objects.filter(pk=self.admin.pk).update(active=False)
        r = self.post('/api/admin/verify-otp/', {'otp_session': sid, 'code': self.last_code()})
        self.assertEqual(r.status_code, 401)
        self.assertFalse(AdminAuthToken.objects.exists())

    def test_missing_session_rejected(self):
        self.login()
        r = self.post('/api/admin/verify-otp/', {'code': self.last_code()})
        self.assertEqual(r.status_code, 401)

    def test_second_login_while_code_live_is_throttled(self):
        self.login()
        r = self.login()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(len(self.otp_sms()), 1)

    def test_sms_failure_502_and_challenge_removed_for_retry(self):
        self.sms_ok = False
        self.assertEqual(self.login().status_code, 502)
        self.assertFalse(AdminOtpChallenge.objects.exists())
        self.sms_ok = True
        self.assertEqual(self.login().status_code, 200)

    def test_no_phone_with_2fa_required_refused(self):
        self.admin.phone = ''
        self.admin.save()
        with mock.patch.dict('os.environ', {'ADMIN_REQUIRE_2FA': '1'}):
            self.assertEqual(self.login().status_code, 403)
        self.assertFalse(AdminAuthToken.objects.exists())

    def test_no_phone_without_2fa_requirement_logs_in(self):
        self.admin.phone = ''
        self.admin.save()
        with mock.patch.dict('os.environ', {'ADMIN_REQUIRE_2FA': ''}):
            r = self.login()
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(AdminAuthToken.resolve(r.json()['token']))


# ---------------------------------------------------------------------------
# require_admin_token gate
# ---------------------------------------------------------------------------
@require_admin_token
def _gated(request):
    return JsonResponse({'ok': True})


class AdminGateTests(TestCase):

    def setUp(self):
        self.rf = RequestFactory()
        self.admin = PlatformAdmin.objects.create(username='gate-admin')
        self.session = AdminAuthToken.issue(self.admin).key

    def call(self, env_token='gate-secret', **meta):
        with mock.patch.dict('os.environ', {'KG_ADMIN_TOKEN': env_token}):
            return _gated(self.rf.get('/api/admin/x/', **meta))

    @override_settings(DEBUG=False)
    def test_unconfigured_secret_fails_closed_in_production(self):
        r = self.call(env_token='', HTTP_AUTHORIZATION=f'Bearer {self.session}')
        self.assertEqual(r.status_code, 503)

    @override_settings(DEBUG=True)
    def test_unconfigured_secret_in_debug_still_needs_credentials(self):
        self.assertEqual(self.call(env_token='').status_code, 401)
        self.assertEqual(self.call(env_token='', HTTP_AUTHORIZATION=f'Bearer {self.session}').status_code, 200)

    def test_static_secret_via_x_admin_token_header_from_loopback(self):
        self.assertEqual(self.call(HTTP_X_ADMIN_TOKEN='gate-secret', REMOTE_ADDR='::1').status_code, 200)

    def test_wrong_or_missing_secret_rejected(self):
        self.assertEqual(self.call(HTTP_X_ADMIN_TOKEN='gate-secreT').status_code, 401)
        self.assertEqual(self.call().status_code, 401)
        self.assertEqual(self.call(HTTP_AUTHORIZATION='Basic gate-secret').status_code, 401)

    def test_admin_session_works_from_internet(self):
        r = self.call(REMOTE_ADDR='198.51.100.7', HTTP_CF_CONNECTING_IP='198.51.100.7',
                      HTTP_AUTHORIZATION=f'Bearer {self.session}')
        self.assertEqual(r.status_code, 200)

    def test_expired_or_deactivated_admin_session_rejected(self):
        AdminAuthToken.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertEqual(self.call(HTTP_AUTHORIZATION=f'Bearer {self.session}').status_code, 401)
        fresh = AdminAuthToken.issue(self.admin).key
        PlatformAdmin.objects.filter(pk=self.admin.pk).update(active=False)
        self.assertEqual(self.call(HTTP_AUTHORIZATION=f'Bearer {fresh}').status_code, 401)

    def test_portal_user_token_is_not_an_admin_session(self):
        u = _user('sneaky')
        raw = AuthToken.issue(u).key
        self.assertEqual(self.call(HTTP_AUTHORIZATION=f'Bearer {raw}', REMOTE_ADDR='8.8.8.8').status_code, 401)

    def test_session_use_slides_idle_window(self):
        tok = AdminAuthToken.objects.get(admin=self.admin)
        old = timezone.now() - datetime.timedelta(hours=1)
        AdminAuthToken.objects.filter(pk=tok.pk).update(last_used_at=old,
                                                        expires_at=old + datetime.timedelta(hours=12))
        self.call(HTTP_AUTHORIZATION=f'Bearer {self.session}')
        tok.refresh_from_db()
        self.assertGreater(tok.expires_at, timezone.now() + datetime.timedelta(hours=11, minutes=50))
