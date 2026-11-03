"""RBAC through the HTTP layer: scope, 404 versus 403, contact reveal, the three
modes, presence per intent and role-scoped event delivery.

Roles come from the (not yet existing) role table, so tests inject them through
``rbac._table_roles``; no migration is involved.
"""
import json
import os
import types
from unittest import mock

from django.test import Client, RequestFactory
from django.utils import timezone

from api import events
from api.models import AdminAuthToken, AuditLog, Event, PlatformAdmin

from . import rbac
from .helpers import SupportCase, admin_url, bearer
from .models import SupportPresence, SupportThread

LIST = '/api/admin/support-chat/threads/'
PRESENCE = '/api/admin/support-chat/presence/'


class RbacApiCase(SupportCase):
    MODE = 'enforce'

    def setUp(self):
        super().setUp()
        self.table = {}
        p = mock.patch.object(rbac, '_table_roles',
                              side_effect=lambda a: set(self.table.get(a.username, ())))
        p.start()
        self.addCleanup(p.stop)
        e = mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': self.MODE, 'KG_SUPPORT_OWNERS': ''})
        e.start()
        self.addCleanup(e.stop)
        self.who = {}
        for name in ('lead', 'sales', 'tech', 'aud', 'owner', 'nobody'):
            a = PlatformAdmin.objects.create(username=name, password_hash='x', active=True)
            self.who[name] = (a, bearer(AdminAuthToken.issue(a).key))
        self.table = {'lead': ['support_lead'], 'sales': ['sales_agent'], 'tech': ['support_agent'],
                      'aud': ['support_auditor'], 'owner': ['support_owner']}

    def hdr(self, name):
        return self.who[name][1]

    def adm(self, name):
        return self.who[name][0]

    def make(self, intent, message='hello', **extra):
        tid, _, _ = self.create(message=message, intent=intent, client_id=f'c-{os.urandom(4).hex()}', **extra)
        return tid

    def listing(self, name, **params):
        return self.c.get(LIST, params, **self.hdr(name))

    def ids(self, name, **params):
        r = self.listing(name, status='all', **params)
        self.assertEqual(r.status_code, 200, r.content)
        return {t['id'] for t in r.json()['threads']}

    def act(self, name, tid, action, body=None):
        return self.staff(tid, action, body, hdr=self.hdr(name))

    def get_detail(self, name, tid, **params):
        return self.c.get(f'{LIST}{tid}/', params, **self.hdr(name))


class ScopeTests(RbacApiCase):
    def test_a_person_without_a_role_is_forbidden_everywhere(self):
        tid = self.make('technical')
        self.assertEqual(self.listing('nobody').status_code, 403)
        self.assertEqual(self.listing('nobody').json()['code'], 'forbidden')
        self.assertEqual(self.get_detail('nobody', tid).status_code, 403)       # no READ at all
        self.assertEqual(self.act('nobody', tid, 'reply', {'message': 'x'}).status_code, 404)

    def test_enforce_with_no_owner_says_rbac_no_owner(self):
        self.table = {}
        r = self.listing('nobody')
        self.assertEqual((r.status_code, r.json()['code']), (403, 'rbac_no_owner'))

    def test_bootstrap_owner_from_the_environment_gets_in_without_any_table_row(self):
        self.table = {}
        with mock.patch.dict(os.environ, {'KG_SUPPORT_OWNERS': 'ann'}):
            self.assertEqual(self.c.get(LIST, **self.h_ann()).status_code, 200)
            self.assertEqual(self.listing('nobody').status_code, 403)

    def h_ann(self):
        return bearer(AdminAuthToken.issue(self.admin).key)

    def test_the_loopback_script_token_is_never_a_support_person_in_enforce(self):
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'loop-secret'}):
            r = Client(REMOTE_ADDR='127.0.0.1').get(LIST, **bearer('loop-secret'))
        self.assertEqual(r.status_code, 403)

    def test_agents_see_only_in_scope_own_or_unassigned_in_list_counts_and_detail(self):
        s_free, s_mine, s_theirs = self.make('sales'), self.make('sales'), self.make('sales')
        t_free = self.make('technical')
        SupportThread.objects.filter(pk=s_mine).update(assignee=self.adm('sales'))
        SupportThread.objects.filter(pk=s_theirs).update(assignee=self.adm('lead'))
        self.assertEqual(self.ids('sales'), {s_free, s_mine})
        self.assertEqual(self.ids('lead'), {s_free, s_mine, s_theirs, t_free})
        self.assertEqual(self.ids('aud'), {s_free, s_mine, s_theirs, t_free})
        counts = self.listing('sales').json()['counts']
        self.assertEqual((counts['all'], counts['active']), (2, 2))          # scoped, not global
        self.assertEqual(self.get_detail('sales', s_theirs).status_code, 404)   # not in scope: absent
        self.assertEqual(self.get_detail('sales', t_free).status_code, 404)     # other intent
        self.assertEqual(self.get_detail('sales', s_mine).status_code, 200)

    def test_search_cannot_be_used_to_find_out_of_scope_threads(self):
        tid = self.make('technical', contact={'name': 'Zahra', 'phone': '09123456789'})
        self.assertEqual(self.ids('sales', q='Zahra'), set())
        self.assertEqual(self.ids('sales', q=tid[:8]), set())
        self.assertEqual(self.ids('lead', q='Zahra'), {tid})


class ActionTests(RbacApiCase):
    def test_taking_assigning_and_priority_follow_the_matrix(self):
        tid = self.make('technical')
        self.assertEqual(self.act('tech', tid, 'priority', {'priority': 'high'}).status_code, 403)   # not own yet
        self.assertEqual(self.act('tech', tid, 'assign', {'admin': 'me'}).status_code, 200)          # take
        self.assertEqual(self.act('tech', tid, 'priority', {'priority': 'high'}).status_code, 200)   # own now
        self.assertEqual(self.act('tech', tid, 'assign', {'admin': self.adm('lead').id}).status_code, 403)
        self.assertEqual(self.act('tech', tid, 'assign', {'admin': None}).status_code, 200)          # release own
        self.assertEqual(self.act('lead', tid, 'assign', {'admin': self.adm('tech').id}).status_code, 200)

    def test_an_agent_cannot_touch_a_colleagues_thread_or_another_intent(self):
        tid = self.make('technical')
        SupportThread.objects.filter(pk=tid).update(assignee=self.adm('lead'))
        for action, body in (('reply', {'message': 'x'}), ('close', {}), ('assign', {'admin': 'me'})):
            self.assertEqual(self.act('tech', tid, action, body).status_code, 404, action)   # not visible
        self.assertEqual(self.act('sales', tid, 'reply', {'message': 'x'}).status_code, 404)

    def test_spam_and_restore_are_lead_and_owner_only(self):
        tid = self.make('technical')
        for name in ('tech', 'sales', 'aud'):
            self.assertIn(self.act(name, tid, 'spam').status_code, (403, 404), name)
        self.assertEqual(self.act('lead', tid, 'spam').status_code, 200)
        self.assertEqual(self.act('owner', tid, 'restore').status_code, 200)

    def test_the_auditor_reads_everything_and_changes_nothing(self):
        tid = self.make('sales')
        self.assertEqual(self.get_detail('aud', tid).status_code, 200)
        for action, body in (('reply', {'message': 'x'}), ('assign', {'admin': 'me'}), ('close', {}),
                             ('priority', {'priority': 'high'}), ('intent', {'intent': 'other'}),
                             ('spam', {})):
            self.assertEqual(self.act('aud', tid, action, body).status_code, 403, action)
        self.assertEqual(self.act('aud', tid, 'seen').status_code, 200)       # reading marks seen

    def test_closing_and_reopening_need_ownership_for_agents(self):
        tid = self.make('technical')
        self.assertEqual(self.act('tech', tid, 'close').status_code, 403)       # visible (unassigned), not own
        self.act('tech', tid, 'assign', {'admin': 'me'})
        self.assertEqual(self.act('tech', tid, 'close').status_code, 200)
        self.assertEqual(self.act('tech', tid, 'reopen').status_code, 200)

    def test_denials_in_enforce_write_no_would_deny_rows_and_changes_nothing(self):
        tid = self.make('technical')
        before = SupportThread.objects.get(pk=tid).priority
        self.act('tech', tid, 'priority', {'priority': 'urgent'})
        self.assertEqual(SupportThread.objects.get(pk=tid).priority, before)
        self.assertFalse(AuditLog.objects.filter(action='support_chat.rbac_would_deny').exists())


class CapabilityTests(RbacApiCase):
    def caps(self, name, tid):
        r = self.get_detail(name, tid)
        self.assertEqual(r.status_code, 200)
        return r.json()['capabilities']

    def test_capabilities_match_what_the_server_would_allow(self):
        tid = self.make('technical')
        tech = self.caps('tech', tid)                         # unassigned, in scope
        self.assertTrue(tech['reply'] and tech['take'])
        self.assertFalse(tech['assign'] or tech['spam'] or tech['priority'] or tech['reveal_contact'])
        aud = self.caps('aud', tid)
        self.assertEqual({k for k, v in aud.items() if v}, set())
        lead = self.caps('lead', tid)
        self.assertTrue(all(lead.values()))

    def test_every_advertised_capability_is_honoured_and_every_denied_one_is_refused(self):
        tid = self.make('technical')
        caps = self.caps('tech', tid)
        self.assertEqual(caps['reply'], self.act('tech', tid, 'reply', {'message': 'x'}).status_code == 201)
        self.assertEqual(caps['priority'], self.act('tech', tid, 'priority', {'priority': 'high'}).status_code == 200)
        self.assertEqual(caps['spam'], self.act('tech', tid, 'spam').status_code == 200)

    def test_in_off_mode_everything_is_offered_and_audit_records_nothing_for_it(self):
        tid = self.make('technical')
        with mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': 'audit'}):
            self.assertTrue(all(self.caps('aud', tid).values()))
            self.assertFalse(AuditLog.objects.filter(action='support_chat.rbac_would_deny').exists())
        with mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': 'off'}):
            self.assertTrue(all(self.caps('nobody', tid).values()))


class ContactRevealTests(RbacApiCase):
    def setUp(self):
        super().setUp()
        self.tid = self.make('technical', contact={'name': 'Z', 'phone': '09123456789', 'email': 'z@example.com'})

    def reveal(self, name):
        return self.get_detail(name, self.tid, reveal_contact='1')

    def test_masked_for_everyone_by_default(self):
        for name in ('lead', 'aud', 'owner'):
            c = self.get_detail(name, self.tid).json()['thread']['contact']
            self.assertNotIn('09123456789', str(c))
            self.assertIn('•', c['phone'])

    def test_agent_may_reveal_only_on_an_owned_thread_and_every_reveal_is_audited(self):
        self.assertEqual(self.reveal('tech').status_code, 403)                  # unassigned: no
        self.assertFalse(AuditLog.objects.filter(action='support_chat.reveal_contact').exists())
        self.act('tech', self.tid, 'assign', {'admin': 'me'})
        r = self.reveal('tech')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['thread']['contact']['email'], 'z@example.com')
        row = AuditLog.objects.get(action='support_chat.reveal_contact')
        self.assertEqual((row.actor_id, row.target_id), (self.adm('tech').id, self.tid))
        self.assertNotIn('example.com', str(row.detail))

    def test_lead_and_owner_reveal_anything_and_auditor_never(self):
        self.assertEqual(self.reveal('lead').status_code, 200)
        self.assertEqual(self.reveal('owner').status_code, 200)
        self.assertEqual(self.reveal('aud').status_code, 403)
        self.assertEqual(AuditLog.objects.filter(action='support_chat.reveal_contact').count(), 2)

    def test_an_out_of_scope_agent_cannot_even_ask(self):
        self.assertEqual(self.reveal('sales').status_code, 404)


class ModeTransitionTests(RbacApiCase):
    MODE = 'off'

    def test_off_behaves_exactly_like_before_for_every_admin_including_no_role(self):
        tid = self.make('technical')
        for name in ('nobody', 'sales', 'aud'):
            self.assertEqual(self.listing(name).status_code, 200, name)
            self.assertEqual(self.act(name, tid, 'priority', {'priority': 'high'}).status_code, 200, name)
        self.assertEqual(self.ids('nobody'), {tid})
        self.assertFalse(AuditLog.objects.filter(action='support_chat.rbac_would_deny').exists())

    def test_audit_allows_everything_and_records_each_would_be_denial_without_content(self):
        with mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': 'audit'}):
            tid = self.make('technical', message='SECRET-TEXT')
            self.assertEqual(self.ids('sales'), {tid})                              # not narrowed in audit
            self.assertEqual(self.act('aud', tid, 'priority', {'priority': 'high'}).status_code, 200)
            rows = AuditLog.objects.filter(action='support_chat.rbac_would_deny')
            self.assertTrue(rows.exists())
            for r in rows:
                self.assertNotIn('SECRET-TEXT', str(r.detail))
                self.assertEqual(set(r.detail), {'permission', 'intent'})
            who = set(rows.values_list('actor_id', flat=True))
            self.assertIn(self.adm('aud').id, who)

    def test_the_same_request_goes_off_audit_enforce_with_the_expected_outcomes(self):
        tid = self.make('technical')
        outcomes = []
        for m in ('off', 'audit', 'enforce'):
            with mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': m}):
                outcomes.append(self.act('aud', tid, 'priority', {'priority': 'low' if m != 'audit' else 'high'}).status_code)
        self.assertEqual(outcomes, [200, 200, 403])

    def test_an_unrecognised_mode_fails_closed_over_http_and_names_the_cause(self):
        for raw in ('enforc', 'enforced', 'ON', 'true', '1'):
            with mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': raw}):
                r = self.listing('nobody')
                self.assertEqual((r.status_code, r.json()['code']), (403, 'rbac_invalid_mode'), raw)
                self.assertEqual(self.listing('owner').status_code, 200, raw)    # a real owner still works

    def test_blank_and_explicit_off_spellings_keep_the_flat_model(self):
        for raw in ('', ' ', '0', 'false', 'no', 'disabled', 'none', 'off'):
            with mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': raw}):
                self.assertEqual(self.listing('nobody').status_code, 200, repr(raw))

    def test_rollback_to_off_restores_access_instantly(self):
        with mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': 'enforce'}):
            self.assertEqual(self.listing('nobody').status_code, 403)
        self.assertEqual(self.listing('nobody').status_code, 200)

    def test_non_support_admin_endpoints_are_unaffected_by_enforce(self):
        """RBAC governs only /api/admin/support-chat/*: another admin endpoint answers
        the same for a role-less admin in enforce as in off."""
        url = '/api/admin/feedback/'
        off = self.c.get(url, **self.hdr('nobody')).status_code
        with mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': 'enforce'}):
            self.assertEqual(self.c.get(url, **self.hdr('nobody')).status_code, off)


class PresenceTests(RbacApiCase):
    def available(self, name):
        a = self.adm(name)
        SupportPresence.objects.update_or_create(
            admin=a, defaults={'manual_status': 'available', 'last_heartbeat_at': timezone.now()})

    def status(self, **params):
        return self.c.get('/api/support-chat/status/', params).json()

    def test_availability_needs_the_permission_but_stepping_away_does_not(self):
        put = lambda name, s: self.c.put(PRESENCE, json.dumps({'status': s}),
                                         content_type='application/json', **self.hdr(name))
        self.assertEqual(put('aud', 'available').status_code, 403)
        self.assertEqual(put('nobody', 'available').status_code, 403)
        self.assertEqual(put('aud', 'away').status_code, 200)
        self.assertEqual(put('tech', 'available').status_code, 200)

    def test_live_is_per_intent_in_enforce(self):
        self.available('sales')
        self.assertEqual(self.status(intent='sales')['mode'], 'live')
        self.assertEqual(self.status(intent='demo')['mode'], 'live')
        self.assertEqual(self.status(intent='technical')['mode'], 'async')
        self.assertEqual(self.status()['mode'], 'live')                           # any intent
        self.assertEqual(self.c.get('/api/support-chat/status/', {'intent': 'x'}).status_code, 400)

    def test_an_available_auditor_or_role_less_admin_never_makes_it_live(self):
        self.available('aud')
        self.available('nobody')
        self.assertEqual(self.status()['mode'], 'async')
        self.assertEqual(self.status(intent='sales')['mode'], 'async')

    def test_off_keeps_the_flat_rule_regardless_of_intent(self):
        with mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': 'off'}):
            self.available('nobody')
            self.assertEqual(self.status(intent='technical')['mode'], 'live')


class _Clock:
    def __init__(self):
        self._ticks = [0, 0, 10 ** 6]

    def monotonic(self):
        return self._ticks.pop(0)

    def sleep(self, _s):
        pass


class EventScopeTests(RbacApiCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(events, 'connection')        # do not close the test DB connection
        p.start()
        self.addCleanup(p.stop)
        self.sentinel = events.emit('support_chat.updated', {'thread_id': 'anchor', 'kind': 'x', 'intent': 'other'}).id
        self.tech = events.emit('support_chat.message', {'thread_id': 'a', 'intent': 'technical'})
        self.sales = events.emit('support_chat.updated', {'thread_id': 'b', 'kind': 'reply', 'intent': 'sales'})
        self.plain = events.emit('admin_changed', {})                                # not a support event

    def stream_body(self, **request_kw):
        fake = types.SimpleNamespace(monotonic=_Clock().monotonic, sleep=lambda s: None)   # fresh clock per stream
        with mock.patch.object(events, 'time', fake):
            resp = events.stream_view(RequestFactory().get(
                f'/api/events/stream/?after={self.sentinel}', **request_kw))
            return ''.join(c.decode() if isinstance(c, bytes) else c for c in resp.streaming_content)

    def seen(self, name=None):
        key = AdminAuthToken.issue(self.adm(name)).key
        body = self.stream_body(HTTP_AUTHORIZATION=f'Bearer {key}')
        return {e for e in (self.tech, self.sales, self.plain) if f'id: {e.id}\n' in body}

    def test_sales_agent_gets_sales_events_but_not_technical_ones(self):
        self.assertEqual(self.seen('sales'), {self.sales, self.plain})

    def test_support_agent_gets_technical_but_not_sales(self):
        self.assertEqual(self.seen('tech'), {self.tech, self.plain})

    def test_lead_auditor_and_owner_get_every_support_event(self):
        for name in ('lead', 'aud', 'owner'):
            self.assertEqual(self.seen(name), {self.tech, self.sales, self.plain}, name)

    def test_a_role_less_admin_gets_no_support_events_but_other_admin_events_still_flow(self):
        self.assertEqual(self.seen('nobody'), {self.plain})

    def test_the_loopback_token_gets_no_support_events_in_enforce(self):
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'loop-secret'}):
            body = self.stream_body(HTTP_AUTHORIZATION='Bearer loop-secret', REMOTE_ADDR='127.0.0.1')
        self.assertNotIn('support_chat', body)
        self.assertIn('admin_changed', body)

    def test_off_and_audit_deliver_everything_to_every_admin(self):
        for m in ('off', 'audit'):
            with mock.patch.dict(os.environ, {'KG_SUPPORT_RBAC': m}):
                self.assertEqual(self.seen('nobody'), {self.tech, self.sales, self.plain}, m)

    def test_the_recent_events_endpoint_is_scoped_the_same_way(self):
        r = self.c.get('/api/events/recent/', {'after': self.sentinel}, **self.hdr('sales'))
        types_ = [(e['type'], e['payload'].get('intent')) for e in r.json()['events']]
        self.assertIn(('support_chat.updated', 'sales'), types_)
        self.assertNotIn(('support_chat.message', 'technical'), types_)

    def test_event_payloads_carry_ids_and_enums_only(self):
        tid = self.make('technical', message='PRIVATE-WORDS')
        self.act('lead', tid, 'reply', {'message': 'ANSWER-WORDS'})
        for e in Event.objects.filter(type__startswith='support_chat.', id__gt=self.sentinel):
            flat = json.dumps(e.payload)
            self.assertNotIn('PRIVATE-WORDS', flat)
            self.assertNotIn('ANSWER-WORDS', flat)
