import json
import os
from unittest import mock

from django.test import Client, TestCase

from .flags import arm, bucket, clean_flags, flags_for, _two_prop_p
from .models import AuthToken, ChatLog, Company, FeatureFlag, PortalUser


class FlagMathTests(TestCase):
    def test_bucket_is_stable_and_in_range(self):
        self.assertEqual(bucket('x', 7), bucket('x', 7))
        self.assertTrue(all(0 <= bucket('mq_translate', u) < 100 for u in range(500)))

    def test_bucket_splits_roughly_evenly(self):
        on = sum(1 for u in range(2000) if bucket('mq_translate', u) < 50)
        self.assertTrue(850 < on < 1150, on)

    def test_flags_are_independent(self):
        same = sum(1 for u in range(1000) if (bucket('a_flag', u) < 50) == (bucket('b_flag', u) < 50))
        self.assertTrue(400 < same < 600, same)

    def test_arm_rules(self):
        f = FeatureFlag(key='t', enabled=False, rollout_pct=100)
        self.assertFalse(arm(f, 1))
        f.enabled = True
        self.assertTrue(arm(f, 1))
        f.rollout_pct = 0
        self.assertFalse(arm(f, 1))
        f.force_on = [1]
        self.assertTrue(arm(f, 1))
        f.force_off = [1]
        self.assertFalse(arm(f, 1))   # force_off wins

    def test_forced_users_ignore_disabled(self):
        f = FeatureFlag(key='t', enabled=False, rollout_pct=0, force_on=[5])
        self.assertTrue(arm(f, 5))

    def test_clean_flags(self):
        self.assertEqual(clean_flags({'mq_translate': 1, 'Bad Key': True, 'x': 0}), {'mq_translate': True})
        self.assertEqual(clean_flags(['nope']), {})

    def test_two_prop_p(self):
        self.assertIsNone(_two_prop_p(1, 0, 1, 10))
        self.assertGreater(_two_prop_p(50, 100, 50, 100), 0.99)
        self.assertLess(_two_prop_p(80, 100, 40, 100), 0.001)


class FlagApiTests(TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'test-admin-token'})
        env.start()
        self.addCleanup(env.stop)
        self.company = Company.objects.create(name='Flag Co', ai_assistant_enabled=True, plan='annual')
        self.user = PortalUser.objects.create(company=self.company, username='flaguser',
                                              password_hash='x', role='tech', ai_assistant_enabled=True)
        self.token = AuthToken.issue(self.user).key
        self.c = Client()
        self.auth = {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}
        self.admin = {'HTTP_AUTHORIZATION': 'Bearer test-admin-token'}

    def _post_admin(self, body):
        return self.c.post('/api/admin/flags/', json.dumps(body), content_type='application/json', **self.admin)

    def test_user_flags_need_auth(self):
        self.assertEqual(self.c.get('/api/auth/flags/').status_code, 401)

    def test_user_flags_follow_rollout(self):
        FeatureFlag.objects.update_or_create(key='mq_translate', defaults={'enabled': True, 'rollout_pct': 100})
        FeatureFlag.objects.update_or_create(key='other', defaults={'enabled': False, 'rollout_pct': 100})
        r = self.c.get('/api/auth/flags/', **self.auth)
        self.assertEqual(r.json()['flags'], {'mq_translate': True, 'other': False})

    def test_ai_usage_carries_flags(self):
        FeatureFlag.objects.update_or_create(key='mq_translate', defaults={'enabled': True, 'rollout_pct': 100})
        r = self.c.get('/api/auth/ai-usage/', **self.auth)
        self.assertIn(r.status_code, (200, 429))
        self.assertEqual(r.json().get('flags'), {'mq_translate': True})

    def test_admin_gated(self):
        self.assertEqual(self.c.get('/api/admin/flags/').status_code, 401)
        r = self.c.post('/api/admin/flags/', '{}', content_type='application/json')
        self.assertEqual(r.status_code, 401)

    def test_admin_create_update_delete(self):
        r = self._post_admin({'key': 'exp_one', 'description': 'd', 'enabled': True, 'rollout_pct': 50})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(FeatureFlag.objects.get(key='exp_one').rollout_pct, 50)
        self.assertEqual(self._post_admin({'key': 'exp_one', 'rollout_pct': 101}).status_code, 400)
        self.assertEqual(self._post_admin({'key': 'Bad-Key'}).status_code, 400)
        self.assertEqual(self._post_admin({'key': 'exp_one', 'force_on': ['x']}).status_code, 400)
        self.assertEqual(self._post_admin({'key': 'exp_one', 'force_on': [self.user.id]}).status_code, 200)
        r = self.c.get('/api/admin/flags/', **self.admin)
        row = [f for f in r.json()['flags'] if f['key'] == 'exp_one'][0]
        self.assertEqual(row['arm_sizes']['on'], 1)
        self.assertEqual(self._post_admin({'key': 'exp_one', 'delete': True}).status_code, 200)
        self.assertFalse(FeatureFlag.objects.filter(key='exp_one').exists())

    def test_chat_log_stores_flags_and_results_split_arms(self):
        for i, (on, grounded) in enumerate([(True, True), (True, True), (False, False), (False, True)]):
            r = self.c.post('/api/auth/chat-log/', json.dumps({
                'question': f'q{i}', 'answer': 'a', 'mode': 'assist', 'grounded': grounded,
                'session_id': f's{i}', 'flags': {'mq_translate': on}}),
                content_type='application/json', **self.auth)
            self.assertEqual(r.status_code, 201)
        self.assertEqual(ChatLog.objects.filter(flags__mq_translate=True).count(), 2)
        r = self.c.get('/api/admin/flags/mq_translate/results/?days=7', **self.admin)
        body = r.json()
        self.assertEqual(body['arms']['on']['answers'], 2)
        self.assertEqual(body['arms']['off']['answers'], 2)
        self.assertEqual(body['tests']['grounded']['on_rate'], 1.0)
        self.assertEqual(body['tests']['grounded']['off_rate'], 0.5)
        self.assertFalse(body['enough_data'])

    def test_flags_for_anonymous(self):
        self.assertEqual(flags_for(None), {})

    def test_seeded_translation_flag_is_off(self):
        # Migration 0034 seeds mq_translate disabled, so behaviour is unchanged until an admin acts.
        f = FeatureFlag.objects.filter(key='mq_translate').first()
        if f:   # created by the data migration in the test DB
            self.assertFalse(f.enabled)
            self.assertEqual(f.rollout_pct, 0)
