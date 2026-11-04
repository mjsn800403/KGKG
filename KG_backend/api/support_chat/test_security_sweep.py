"""Security regression sweep, driven by the URL table so a new route cannot be forgotten.

* every staff route refuses callers without a staff session, with the same answer for a
  real and an unknown thread (no way to probe which ids exist);
* every visitor route refuses a missing or wrong token with one identical answer for a
  real and an unknown thread;
* nothing written to any log during a full visitor+staff flow contains message text,
  contact details or the visitor token.
"""
import logging
import os
import uuid
from unittest import mock

from django.urls import URLPattern, URLResolver, get_resolver

from .helpers import SupportCase, bearer, visitor_hdr
from .models import SupportMessage

ADMIN_PREFIX = 'api/admin/support-chat/'
VISITOR_PREFIX = 'api/support-chat/threads/'
METHODS = ('get', 'post', 'patch', 'put', 'delete')


def _patterns(resolver, prefix=''):
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            yield from _patterns(p, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern)


def _routes(prefix):
    return sorted({r for r in _patterns(get_resolver()) if r.startswith(prefix)})


def _fill(route, tid):
    return '/' + route.replace('<str:thread_id>', tid)


class StaffRouteSweep(SupportCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'loop-secret'})   # as configured in production
        env.start()
        self.addCleanup(env.stop)

    def test_the_sweep_actually_finds_the_routes(self):
        self.assertGreaterEqual(len(_routes(ADMIN_PREFIX)), 10)

    def test_every_staff_route_needs_a_staff_session_for_every_method(self):
        real, _ = self.create()[0], None
        fake = uuid.uuid4().hex
        offences = []
        for route in _routes(ADMIN_PREFIX):
            for method in METHODS:
                for label, hdr in (('none', {}), ('junk', bearer('junk')), ('empty', bearer(''))):
                    answers = set()
                    for tid in (real, fake):
                        r = getattr(self.c, method)(_fill(route, tid), **hdr)
                        answers.add((r.status_code, r.content))
                    if {s for s, _ in answers} != {401} or len(answers) != 1:
                        offences.append((route, method, label, sorted(s for s, _ in answers)))
        self.assertEqual(offences, [])


class VisitorRouteSweep(SupportCase):
    def test_the_sweep_actually_finds_the_routes(self):
        self.assertGreaterEqual(len([r for r in _routes(VISITOR_PREFIX) if '<str:thread_id>' in r]), 4)

    def test_missing_or_wrong_token_gets_one_answer_for_real_and_unknown_threads(self):
        real, token, _ = self.create()
        other_token = self.create(client_id='c-other')[1]
        fake = uuid.uuid4().hex
        offences = []
        for route in (r for r in _routes(VISITOR_PREFIX) if '<str:thread_id>' in r):   # create is public by design
            for method in METHODS:
                for label, tok in (('none', None), ('junk', 'x' * 40), ('other', other_token)):
                    answers = set()
                    for tid in (real, fake):
                        url = _fill(route, tid)
                        if method in ('get', 'delete'):
                            r = getattr(self.c, method)(url, **visitor_hdr(tok))
                        else:
                            r = self.send(url, {'message': 'hi', 'client_id': 'z'}, tok, method=method)
                        answers.add((r.status_code, r.content))
                    codes = {s for s, _ in answers}
                    if len(answers) != 1 or codes & {200, 201, 500}:
                        offences.append((route, method, label, sorted(codes)))
        self.assertEqual(offences, [])
        # and the real owner still gets in, so the sweep is not passing by refusing everyone
        self.assertEqual(self.poll(real, token).status_code, 200)


class _Collector(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.text = []

    def emit(self, record):
        try:
            self.text.append(record.getMessage())
        except Exception:
            self.text.append(str(record.msg))
        if record.exc_text:
            self.text.append(record.exc_text)
        self.text.append(repr(getattr(record, 'args', '')))


class LogPrivacy(SupportCase):
    SECRETS = ('confidential sales question 7731', '09123334455', 'private.person@example.com',
               'a confidential staff reply 9912')

    def test_no_log_line_carries_message_text_contact_details_or_the_token(self):
        collector = _Collector()
        root = logging.getLogger()
        old = root.level
        root.addHandler(collector)
        root.setLevel(logging.DEBUG)
        try:
            tid, token, _ = self.create(
                message=self.SECRETS[0], contact={'phone': self.SECRETS[1], 'email': self.SECRETS[2]})
            self.send(f'/api/support-chat/threads/{tid}/contact/',
                      {'phone': self.SECRETS[1], 'email': self.SECRETS[2]}, token, method='patch')
            self.poll(tid, token)
            self.send(f'/api/support-chat/threads/{tid}/messages/',
                      {'message': self.SECRETS[0], 'client_id': 'c-2'}, token)
            self.staff(tid, 'reply', {'message': self.SECRETS[3]})
            self.c.get('/api/admin/support-chat/threads/', **self.h)
            self.c.get(f'/api/admin/support-chat/threads/{tid}/', **self.h)
            self.send(f'/api/support-chat/threads/{tid}/messages/', {'message': 'x'}, 'bad-token')
        finally:
            root.removeHandler(collector)
            root.setLevel(old)
        dump = '\n'.join(collector.text)
        for secret in self.SECRETS + (token,):
            self.assertNotIn(secret, dump)

    def test_the_collector_would_catch_a_leak(self):
        # Hand-built record, not a logger call: proves the collector reads message args.
        collector = _Collector()
        marker = 'marker-for-the-collector-selfcheck'
        collector.emit(logging.LogRecord('selfcheck', logging.WARNING, __file__, 1,
                                         'visitor said %s', (marker,), None))
        self.assertIn(marker, ' '.join(collector.text))


class CookiesAndCsrf(SupportCase):
    """Ties the support chat to the CSRF work (#83, api/csrf_registry.py): its views opt out of
    CSRF only because nothing here authenticates by cookie, so that must stay true."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'loop-secret'})
        env.start()
        self.addCleanup(env.stop)

    def test_every_support_chat_view_is_classified_as_header_token_or_pre_auth(self):
        from api.csrf_registry import EXEMPT
        mine = {k: v for k, v in EXEMPT.items() if k.startswith('api/support_chat/')}
        self.assertGreaterEqual(len(mine), 10)
        self.assertEqual({v[0] for v in mine.values()} - {'admin-header', 'token-header', 'pre-auth'}, set(),
                         'a support-chat view classified as cookie-authenticated would need CSRF protection')

    def test_a_portal_cookie_grants_nothing_on_any_support_route(self):
        real, token, _ = self.create()
        fake = uuid.uuid4().hex
        self.c.cookies['kg_portal_token'] = 'any-portal-session-value'
        self.c.cookies['sessionid'] = 'any-django-session-value'
        offences = []
        for route in _routes(ADMIN_PREFIX):
            for method in METHODS:
                for tid in (real, fake):
                    r = getattr(self.c, method)(_fill(route, tid))
                    if r.status_code != 401:
                        offences.append((route, method, r.status_code))
        for route in (r for r in _routes(VISITOR_PREFIX) if '<str:thread_id>' in r):
            for method in ('get', 'post', 'patch'):
                answers = set()
                for tid in (real, fake):
                    url = _fill(route, tid)
                    r = (getattr(self.c, method)(url) if method == 'get'
                         else self.send(url, {'message': 'x', 'client_id': 'z'}, None, method=method))
                    answers.add((r.status_code, r.content))
                if len(answers) != 1 or {s for s, _ in answers} & {200, 201}:
                    offences.append((route, method, sorted(s for s, _ in answers)))
        self.assertEqual(offences, [])
        self.assertEqual(self.poll(real, token).status_code, 200, 'the token header still works')

    def test_a_cross_origin_request_cannot_borrow_the_cookie_for_a_write(self):
        """The Origin guard (#83) covers cookie writes; a support write with only a cookie is refused anyway."""
        real, _, _ = self.create()
        self.c.cookies['kg_portal_token'] = 'any-portal-session-value'
        r = self.send(f'/api/support-chat/threads/{real}/messages/', {'message': 'x', 'client_id': 'q'}, None,
                      HTTP_ORIGIN='https://evil.example')
        self.assertIn(r.status_code, (403, 404))
        self.assertEqual(SupportMessage.objects.filter(thread_id=real).count(), 1)
