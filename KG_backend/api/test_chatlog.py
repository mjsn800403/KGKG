"""Chat logs: recording, manager scope (org reach only), platform-admin view."""
import json
from unittest import mock

from django.test import Client, TestCase

from .models import (AdminAuthToken, AuthToken, ChatLog, Company, PlatformAdmin,
                     PortalUser)


def _user(co, name):
    return PortalUser.objects.create(company=co, username=name, password_hash='x', active=True)


class ChatLogTest(TestCase):
    def setUp(self):
        self.c = Client()
        self.co = Company.objects.create(name='Co', active=True)
        self.other_co = Company.objects.create(name='Other', active=True)
        self.boss = _user(self.co, 'boss')
        self.tech = _user(self.co, 'tech')
        self.peer = _user(self.co, 'peer')          # outside boss's reach
        self.stranger = _user(self.other_co, 'x')

    def _auth(self, user):
        return {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(user).key}'}

    def _record(self, user, q):
        return self.c.post('/api/auth/chat-log/', json.dumps({
            'question': q, 'answer': 'A', 'mode': 'assist', 'grounded': True,
            'session_id': 's1', 'vehicle': 'Toyota Hilux',
            'sources': [{'title': 'T', 'href': '/x'}, 'junk']}),
            content_type='application/json', **self._auth(user))

    def test_record_requires_login_and_stores_row(self):
        r = self.c.post('/api/auth/chat-log/', '{"question":"q"}', content_type='application/json')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self._record(self.tech, 'oil?').status_code, 201)
        row = ChatLog.objects.get()
        self.assertEqual((row.user, row.company, row.vehicle), (self.tech, self.co, 'Toyota Hilux'))
        self.assertEqual(row.sources, [{'title': 'T', 'href': '/x'}])

    def test_manager_sees_only_their_reach(self):
        for u in (self.boss, self.tech, self.peer, self.stranger):
            self._record(u, f'q-{u.username}')
        reach = {self.boss.id, self.tech.id, self.stranger.id}   # stranger: other company
        with mock.patch('api.orggraph.user_can_view_team', return_value=True), \
             mock.patch('api.chatlog.manageable_user_ids', return_value=reach):
            r = self.c.get(f'/api/team/chat-logs/?company_id={self.other_co.id}', **self._auth(self.boss))
        self.assertEqual(r.status_code, 200)
        got = {i['user'] for i in r.json()['items']}
        self.assertEqual(got, {'boss', 'tech'})

    def test_leaf_user_is_denied(self):
        with mock.patch('api.orggraph.user_can_view_team', return_value=False):
            r = self.c.get('/api/team/chat-logs/', **self._auth(self.tech))
        self.assertEqual(r.status_code, 403)

    def test_admin_sees_all_and_filters(self):
        for u in (self.tech, self.stranger):
            self._record(u, f'q-{u.username}')
        admin = PlatformAdmin.objects.create(username='root', password_hash='x')
        h = {'HTTP_AUTHORIZATION': f'Bearer {AdminAuthToken.issue(admin).key}'}
        r = self.c.get('/api/admin/chat-logs/', **h)
        self.assertEqual(r.json()['total'], 2)
        r = self.c.get(f'/api/admin/chat-logs/?company_id={self.other_co.id}', **h)
        self.assertEqual([i['user'] for i in r.json()['items']], ['x'])
        r = self.c.get('/api/admin/chat-logs/?q=q-tech', **h)
        self.assertEqual(r.json()['total'], 1)
        self.assertEqual(self.c.get('/api/admin/chat-logs/', **self._auth(self.tech)).status_code, 401)
