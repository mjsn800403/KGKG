"""Regression tests for the 2026-08-05 security hardening.

Covers the three things that were fixed: session tokens stored in the clear and
never expiring, secrets with no rotation path, and logs that leaked credentials.
"""
import datetime
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.db import connection
from django.test import Client, TestCase
from django.utils import timezone

from api.models import (AdminAuthToken, AuthToken, Company, PlatformAdmin,
                        PortalUser)


def _company(**kw):
    # Company.name is unique, so each helper call needs its own — several tests
    # build two independent users to prove revocation doesn't bleed across them.
    kw.setdefault('name', f'شرکت آزمون {Company.objects.count() + 1}')
    return Company.objects.create(**kw)


def _user(company=None, username='tester', **kw):
    u = PortalUser.objects.create(
        company=company or _company(), username=username,
        display_name='کاربر آزمون', **kw)
    u.set_password('correct-horse-battery')
    u.save()
    return u


# ---------------------------------------------------------------------------
# Tokens are hashed at rest
# ---------------------------------------------------------------------------
class TokenHashingTests(TestCase):

    def test_raw_token_is_never_written_to_the_database(self):
        token = AuthToken.issue(_user())
        raw = token.key

        self.assertTrue(raw)
        row = AuthToken.objects.get(pk=token.pk)
        self.assertNotEqual(row.key_hash, raw)
        self.assertEqual(row.key_hash, AuthToken._hash(raw))

        # Belt and braces: scan the actual table bytes for the raw value, so a
        # future field addition that quietly persists it fails right here.
        with connection.cursor() as cur:
            cur.execute('SELECT * FROM api_authtoken')
            blob = json.dumps(cur.fetchall(), default=str)
        self.assertNotIn(raw, blob)

    def test_key_is_not_a_model_field_any_more(self):
        names = {f.name for f in AuthToken._meta.get_fields()}
        self.assertNotIn('key', names)
        self.assertIn('key_hash', names)

    def test_issue_returns_a_usable_raw_key_once(self):
        token = AuthToken.issue(_user())
        self.assertIs(AuthToken.resolve(token.key).pk, token.pk)

    def test_resolve_rejects_an_unknown_token(self):
        AuthToken.issue(_user())
        self.assertIsNone(AuthToken.resolve('not-a-real-token'))
        self.assertIsNone(AuthToken.resolve(''))
        self.assertIsNone(AuthToken.resolve(None))

    def test_tokens_are_long_enough_to_resist_guessing(self):
        self.assertGreaterEqual(len(AuthToken.issue(_user()).key), 43)


# ---------------------------------------------------------------------------
# Expiry: idle window + absolute ceiling
# ---------------------------------------------------------------------------
class TokenExpiryTests(TestCase):

    def test_fresh_token_has_an_expiry_set(self):
        token = AuthToken.issue(_user())
        self.assertIsNotNone(token.expires_at)
        self.assertGreater(token.expires_at, timezone.now())

    def test_expired_token_does_not_resolve(self):
        token = AuthToken.issue(_user())
        raw = token.key
        AuthToken.objects.filter(pk=token.pk).update(
            expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertIsNone(AuthToken.resolve(raw))

    def test_expired_token_is_rejected_by_the_api(self):
        user = _user()
        token = AuthToken.issue(user)
        client = Client()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.key}'}

        self.assertEqual(client.get('/api/auth/me/', **auth).status_code, 200)

        AuthToken.objects.filter(pk=token.pk).update(
            expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertEqual(client.get('/api/auth/me/', **auth).status_code, 401)

    def test_touch_slides_the_idle_window_forward(self):
        token = AuthToken.issue(_user())
        old_expiry = token.expires_at
        # Backdate last_used_at past TOUCH_INTERVAL so the refresh isn't skipped.
        AuthToken.objects.filter(pk=token.pk).update(
            last_used_at=timezone.now() - datetime.timedelta(hours=1),
            expires_at=old_expiry - datetime.timedelta(hours=1))

        fresh = AuthToken.objects.get(pk=token.pk)
        fresh.touch()

        self.assertGreater(AuthToken.objects.get(pk=token.pk).expires_at,
                           old_expiry - datetime.timedelta(hours=1))

    def test_touch_is_write_throttled(self):
        """A just-used token must not write to the DB on every request."""
        token = AuthToken.issue(_user())
        before = AuthToken.objects.get(pk=token.pk).last_used_at
        AuthToken.objects.get(pk=token.pk).touch()
        self.assertEqual(AuthToken.objects.get(pk=token.pk).last_used_at, before)

    def test_touch_never_exceeds_the_absolute_ceiling(self):
        token = AuthToken.issue(_user())
        # Pretend the session was created just shy of its hard limit.
        created = timezone.now() - AuthToken.ABSOLUTE_TTL + datetime.timedelta(hours=2)
        AuthToken.objects.filter(pk=token.pk).update(
            created_at=created,
            last_used_at=timezone.now() - datetime.timedelta(hours=1))

        fresh = AuthToken.objects.get(pk=token.pk)
        fresh.touch()

        ceiling = created + AuthToken.ABSOLUTE_TTL
        self.assertLessEqual(AuthToken.objects.get(pk=token.pk).expires_at, ceiling)

    def test_admin_sessions_expire_sooner_than_user_sessions(self):
        self.assertLess(AdminAuthToken.ABSOLUTE_TTL, AuthToken.ABSOLUTE_TTL)
        self.assertLess(AdminAuthToken.IDLE_TTL, AuthToken.IDLE_TTL)

    def test_prune_removes_only_expired_rows(self):
        live = AuthToken.issue(_user(username='live'))
        dead = AuthToken.issue(_user(username='dead'))
        AuthToken.objects.filter(pk=dead.pk).update(
            expires_at=timezone.now() - datetime.timedelta(days=1))

        self.assertEqual(AuthToken.prune(), 1)
        self.assertEqual(list(AuthToken.objects.values_list('pk', flat=True)), [live.pk])


# ---------------------------------------------------------------------------
# Admin session tokens
# ---------------------------------------------------------------------------
class AdminTokenTests(TestCase):

    def setUp(self):
        self.admin = PlatformAdmin.objects.create(username='root-admin', active=True)
        self.admin.set_password('a-very-long-admin-password')
        self.admin.save()

    def test_admin_token_hashed_and_resolvable(self):
        token = AdminAuthToken.issue(self.admin)
        self.assertEqual(AdminAuthToken.objects.get(pk=token.pk).key_hash,
                         AdminAuthToken._hash(token.key))
        self.assertIsNotNone(AdminAuthToken.resolve(token.key))

    def test_expired_admin_token_is_refused(self):
        from api.admin_auth import _admin_session_valid
        token = AdminAuthToken.issue(self.admin)
        self.assertTrue(_admin_session_valid(token.key))

        AdminAuthToken.objects.filter(pk=token.pk).update(
            expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertFalse(_admin_session_valid(token.key))

    def test_deactivated_admin_token_is_refused(self):
        from api.admin_auth import _admin_session_valid
        token = AdminAuthToken.issue(self.admin)
        self.admin.active = False
        self.admin.save(update_fields=['active'])
        self.assertFalse(_admin_session_valid(token.key))

    def test_login_returns_a_working_token(self):
        client = Client()
        resp = client.post('/api/admin/login/',
                           data=json.dumps({'username': 'root-admin',
                                            'password': 'a-very-long-admin-password'}),
                           content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        raw = resp.json()['token']
        self.assertIsNotNone(AdminAuthToken.resolve(raw))
        # ...and the wire value is not what's on disk.
        self.assertFalse(AdminAuthToken.objects.filter(key_hash=raw).exists())


# ---------------------------------------------------------------------------
# Login / logout round trip
# ---------------------------------------------------------------------------
class SessionLifecycleTests(TestCase):

    def setUp(self):
        self.user = _user(username='specialist')

    def _login(self):
        resp = Client().post('/api/auth/login/',
                             data=json.dumps({'username': 'specialist',
                                              'password': 'correct-horse-battery'}),
                             content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        return resp.json()['token']

    def test_login_token_authenticates_then_logout_revokes_it(self):
        raw = self._login()
        client = Client()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {raw}'}

        self.assertEqual(client.get('/api/auth/me/', **auth).status_code, 200)
        self.assertEqual(client.post('/api/auth/logout/', **auth).status_code, 200)
        self.assertEqual(client.get('/api/auth/me/', **auth).status_code, 401)

    def test_logout_also_works_for_a_cookie_session(self):
        """SSR sessions arrive as a cookie, not a header — they must log out too."""
        raw = self._login()
        client = Client()
        client.cookies['kg_portal_token'] = raw

        self.assertEqual(client.get('/api/auth/me/').status_code, 200)
        self.assertEqual(client.post('/api/auth/logout/').status_code, 200)
        self.assertEqual(client.get('/api/auth/me/').status_code, 401)

    def test_revoking_one_user_does_not_touch_another(self):
        other = _user(username='colleague')
        mine, theirs = self._login(), AuthToken.issue(other).key

        call_command('rotate_tokens', revoke_user='specialist', verbosity=0)

        self.assertIsNone(AuthToken.resolve(mine))
        self.assertIsNotNone(AuthToken.resolve(theirs))


# ---------------------------------------------------------------------------
# Management commands
# ---------------------------------------------------------------------------
class RotateTokensCommandTests(TestCase):

    def test_prune_reports_and_deletes(self):
        dead = AuthToken.issue(_user())
        AuthToken.objects.filter(pk=dead.pk).update(
            expires_at=timezone.now() - datetime.timedelta(days=2))
        call_command('rotate_tokens', prune=True, verbosity=0)
        self.assertEqual(AuthToken.objects.count(), 0)

    def test_revoke_all_requires_explicit_confirmation(self):
        AuthToken.issue(_user())
        with self.assertRaises(CommandError):
            call_command('rotate_tokens', revoke_all=True, verbosity=0)
        self.assertEqual(AuthToken.objects.count(), 1)

        call_command('rotate_tokens', revoke_all=True, yes=True, verbosity=0)
        self.assertEqual(AuthToken.objects.count(), 0)

    def test_revoke_unknown_user_errors(self):
        with self.assertRaises(CommandError):
            call_command('rotate_tokens', revoke_user='nobody', verbosity=0)


class RotateSecretsCommandTests(TestCase):
    """The env-file rewriter — the part where a bug means the site won't boot."""

    ENV = ('# production settings\n'
           'DJANGO_DEBUG=0\n'
           'DJANGO_SECRET_KEY=old-secret-value\n'
           'KG_ADMIN_TOKEN=old-admin-token\n'
           'KG_TRUST_PROXY=1\n')

    def setUp(self):
        fd, self.path = tempfile.mkstemp(prefix='env.test.')
        with os.fdopen(fd, 'w') as fh:
            fh.write(self.ENV)
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))

    def _read(self):
        from api.management.commands.rotate_secrets import parse_env
        with open(self.path) as fh:
            return parse_env(fh.read())

    def test_rotating_the_django_key_retires_the_old_one(self):
        call_command('rotate_secrets', what='django-key', env_file=self.path, verbosity=0)
        env = self._read()
        self.assertNotEqual(env['DJANGO_SECRET_KEY'], 'old-secret-value')
        self.assertEqual(env['DJANGO_SECRET_KEY_FALLBACKS'], 'old-secret-value')

    def test_fallback_list_is_pruned_to_the_requested_depth(self):
        for _ in range(3):
            call_command('rotate_secrets', what='django-key',
                         env_file=self.path, prune_fallbacks=1, verbosity=0)
        self.assertEqual(len(self._read()['DJANGO_SECRET_KEY_FALLBACKS'].split(',')), 1)

    def test_unrelated_settings_and_comments_survive_a_rotation(self):
        call_command('rotate_secrets', what='all', env_file=self.path, verbosity=0)
        with open(self.path) as fh:
            text = fh.read()
        self.assertIn('# production settings', text)
        self.assertEqual(self._read()['KG_TRUST_PROXY'], '1')
        self.assertEqual(self._read()['DJANGO_DEBUG'], '0')

    def test_rewritten_env_file_is_not_world_readable(self):
        call_command('rotate_secrets', what='admin-token', env_file=self.path, verbosity=0)
        self.assertEqual(os.stat(self.path).st_mode & 0o077, 0,
                         'rotated env file must not be group/other readable')

    def test_admin_token_actually_changes(self):
        call_command('rotate_secrets', what='admin-token', env_file=self.path, verbosity=0)
        self.assertNotEqual(self._read()['KG_ADMIN_TOKEN'], 'old-admin-token')

    def test_a_backup_of_the_previous_file_is_kept(self):
        call_command('rotate_secrets', what='django-key', env_file=self.path, verbosity=0)
        backups = [f for f in os.listdir(os.path.dirname(self.path))
                   if f.startswith(os.path.basename(self.path) + '.bak.')]
        self.addCleanup(lambda: [
            os.unlink(os.path.join(os.path.dirname(self.path), f)) for f in backups])
        self.assertEqual(len(backups), 1)

    def test_missing_env_file_is_an_error_not_a_new_file(self):
        with self.assertRaises(CommandError):
            call_command('rotate_secrets', what='django-key',
                         env_file=self.path + '.nope', verbosity=0)
        self.assertFalse(os.path.exists(self.path + '.nope'))


# ---------------------------------------------------------------------------
# Log scrubbing
# ---------------------------------------------------------------------------
class LogScrubbingTests(TestCase):

    def test_secret_looking_keys_are_redacted(self):
        from KG_backend.jsonlog import REDACTED, scrub
        out = scrub({'password': 'hunter2', 'api_key': 'abc', 'METIS_API_KEY': 'xyz',
                     'Authorization': 'Bearer zzz', 'username': 'ahmadi'})
        self.assertEqual(out['password'], REDACTED)
        self.assertEqual(out['api_key'], REDACTED)
        self.assertEqual(out['METIS_API_KEY'], REDACTED)
        self.assertEqual(out['Authorization'], REDACTED)
        self.assertEqual(out['username'], 'ahmadi', 'non-secrets must survive')

    def test_inline_credentials_in_free_text_are_redacted(self):
        from KG_backend.jsonlog import scrub
        text = scrub('GET /api/x?token=s3cr3tvalue99 failed')
        self.assertNotIn('s3cr3tvalue99', text)

    def test_bearer_headers_in_free_text_are_redacted(self):
        from KG_backend.jsonlog import scrub
        self.assertNotIn('eyJhbGciOiJIUzI1',
                         scrub('auth failed for Bearer eyJhbGciOiJIUzI1NiJ9'))

    def test_scrub_is_depth_capped_on_self_referential_input(self):
        from KG_backend.jsonlog import scrub
        loop = {}
        loop['self'] = loop
        scrub(loop)   # must terminate rather than recurse forever

    def test_formatter_emits_one_json_object_per_record(self):
        import logging
        from KG_backend.jsonlog import JsonFormatter
        record = logging.LogRecord('kgkg', logging.ERROR, __file__, 10,
                                   'token=abcdef123456 exploded', None, None)
        line = JsonFormatter().format(record)
        parsed = json.loads(line)
        self.assertEqual(parsed['level'], 'ERROR')
        self.assertNotIn('abcdef123456', line)
        self.assertNotIn('\n', line, 'a record must stay on one line')

    def test_formatter_records_exception_details(self):
        import logging
        import sys
        from KG_backend.jsonlog import JsonFormatter
        try:
            raise ValueError('boom')
        except ValueError:
            record = logging.LogRecord('kgkg', logging.ERROR, __file__, 10,
                                       'failed', None, sys.exc_info())
        parsed = json.loads(JsonFormatter().format(record))
        self.assertEqual(parsed['error']['type'], 'ValueError')
        self.assertIn('boom', parsed['error']['value'])


# ---------------------------------------------------------------------------
# Settings hardening
# ---------------------------------------------------------------------------
class SecuritySettingsTests(TestCase):

    def test_transport_agnostic_headers_are_on(self):
        from django.conf import settings
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(settings.X_FRAME_OPTIONS, 'DENY')
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SECURE_REFERRER_POLICY, 'same-origin')

    def test_secret_key_fallbacks_are_configurable(self):
        from django.conf import settings
        self.assertIsInstance(settings.SECRET_KEY_FALLBACKS, list)

    def test_nosniff_and_frame_headers_reach_real_responses(self):
        resp = Client().get('/api/health/')
        self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(resp.headers.get('X-Frame-Options'), 'DENY')

    def test_debug_is_off(self):
        from django.conf import settings
        self.assertFalse(settings.DEBUG)
