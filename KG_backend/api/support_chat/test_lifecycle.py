"""C4/C6: close, explicit reopen, rating history, read state, staff identity."""
import json
import os
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from .helpers import SupportCase, msgs_url
from .models import SupportMessage, SupportRating, SupportThread

LABEL = 'پشتیبانی'


def _url(tid, action):
    return f'/api/support-chat/threads/{tid}/{action}/'


class CloseAndClosedTests(SupportCase):
    def test_staff_close_sets_status_and_leaves_a_visible_system_message(self):
        tid, tok, _ = self.create()
        r = self.staff(tid, 'close')
        self.assertEqual(r.status_code, 200)
        t = SupportThread.objects.get(pk=tid)
        self.assertEqual(t.status, 'closed')
        self.assertIsNotNone(t.closed_at)
        got = self.poll(tid, tok).json()
        self.assertEqual(got['status'], 'closed')
        self.assertEqual(got['messages'][-1]['author_kind'], 'system')
        self.assertTrue(got['can_reopen'])

    def test_a_visitor_message_to_a_closed_thread_is_refused_with_a_reason(self):
        tid, tok, _ = self.create()
        self.staff(tid, 'close')
        r = self.send(msgs_url(tid), {'message': 'one more thing'}, tok)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['code'], 'closed')
        self.assertTrue(r.json()['can_reopen'])
        self.assertEqual(SupportMessage.objects.filter(body='one more thing').count(), 0)

    def test_a_staff_reply_to_a_closed_thread_does_not_reopen_it(self):
        tid, _, _ = self.create()
        self.staff(tid, 'close')
        before = SupportMessage.objects.count()
        r = self.staff(tid, 'reply', {'message': 'following up'})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['code'], 'closed')
        self.assertEqual(SupportMessage.objects.count(), before)
        self.assertEqual(SupportThread.objects.get(pk=tid).status, 'closed')

    def test_closing_twice_is_refused(self):
        tid, _, _ = self.create()
        self.assertEqual(self.staff(tid, 'close').status_code, 200)
        self.assertEqual(self.staff(tid, 'close').status_code, 409)


class ReopenTests(SupportCase):
    def test_staff_reopen_is_explicit_counted_and_recorded_in_the_thread(self):
        tid, tok, _ = self.create()
        self.staff(tid, 'close')
        r = self.staff(tid, 'reopen')
        self.assertEqual(r.status_code, 200)
        t = SupportThread.objects.get(pk=tid)
        self.assertEqual((t.status, t.reopen_count, t.closed_at), ('open', 1, None))
        kinds = [m['author_kind'] for m in self.poll(tid, tok).json()['messages']]
        self.assertEqual(kinds.count('system'), 2)       # closed, reopened
        self.assertEqual(self.staff(tid, 'reopen').status_code, 409)   # already open

    def test_visitor_reopen_within_the_window(self):
        tid, tok, _ = self.create()
        self.staff(tid, 'close')
        r = self.send(_url(tid, 'reopen'), {}, tok)
        self.assertEqual(r.status_code, 200)
        t = SupportThread.objects.get(pk=tid)
        self.assertEqual((t.status, t.reopen_count), ('waiting_staff', 1))

    def test_visitor_reopen_after_the_window_is_refused(self):
        tid, tok, _ = self.create()
        self.staff(tid, 'close')
        SupportThread.objects.filter(pk=tid).update(closed_at=timezone.now() - timedelta(days=15))
        r = self.send(_url(tid, 'reopen'), {}, tok)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['code'], 'reopen_window_expired')
        self.assertFalse(self.poll(tid, tok).json()['can_reopen'])

    def test_the_window_is_configurable_with_a_14_day_default(self):
        tid, tok, _ = self.create()
        self.staff(tid, 'close')
        SupportThread.objects.filter(pk=tid).update(closed_at=timezone.now() - timedelta(days=13))
        self.assertTrue(self.poll(tid, tok).json()['can_reopen'])
        SupportThread.objects.filter(pk=tid).update(closed_at=timezone.now() - timedelta(days=20))
        with mock.patch.dict(os.environ, {'KG_SUPPORT_REOPEN_DAYS': '30'}):
            self.assertEqual(self.send(_url(tid, 'reopen'), {}, tok).status_code, 200)

    def test_reopening_an_open_thread_is_refused(self):
        tid, tok, _ = self.create()
        self.assertEqual(self.send(_url(tid, 'reopen'), {}, tok).status_code, 409)

    def test_wrong_token_cannot_reopen(self):
        tid, _, _ = self.create()
        self.staff(tid, 'close')
        self.assertEqual(self.send(_url(tid, 'reopen'), {}, 'B' * 43).status_code, 404)


class RatingHistoryTests(SupportCase):
    def _close_and_rate(self, tid, tok, score):
        self.staff(tid, 'close')
        return self.send(_url(tid, 'csat'), {'score': score}, tok)

    @mock.patch.dict(os.environ, {'KG_SC_CSAT': '0/0'})
    def test_rating_needs_a_closed_thread_and_a_valid_score(self):
        tid, tok, _ = self.create()
        self.assertEqual(self.send(_url(tid, 'csat'), {'score': 5}, tok).status_code, 409)
        self.staff(tid, 'close')
        for bad in (0, 6, 'x', True, None):
            self.assertEqual(self.send(_url(tid, 'csat'), {'score': bad}, tok).status_code, 400, bad)

    def test_one_rating_per_closure_and_a_duplicate_does_not_overwrite(self):
        tid, tok, _ = self.create()
        self.assertEqual(self._close_and_rate(tid, tok, 4).status_code, 201)
        self.assertEqual(self.send(_url(tid, 'csat'), {'score': 1}, tok).status_code, 409)
        self.assertEqual(list(SupportRating.objects.values_list('score', flat=True)), [4])

    def test_a_later_closure_can_be_rated_again_and_the_history_is_kept(self):
        tid, tok, _ = self.create()
        self._close_and_rate(tid, tok, 2)
        self.staff(tid, 'reopen')
        self.assertEqual(self._close_and_rate(tid, tok, 5).status_code, 201)
        rows = list(SupportRating.objects.filter(thread_id=tid).order_by('id'))
        self.assertEqual([(r.score, r.closure) for r in rows], [(2, 0), (5, 1)])

    def test_reopening_a_rated_thread_keeps_its_rating(self):
        tid, tok, _ = self.create()
        self._close_and_rate(tid, tok, 3)
        self.send(_url(tid, 'reopen'), {}, tok)
        self.assertEqual(SupportRating.objects.filter(thread_id=tid).count(), 1)


class StaffAuthorisationTests(SupportCase):
    ACTIONS = ('reply', 'close', 'reopen', 'seen')

    def test_unauthenticated_requests_are_rejected(self):
        tid, _, _ = self.create()
        for action in self.ACTIONS:
            self.assertEqual(self.staff(tid, action, {'message': 'x'}, hdr={}).status_code, 401, action)

    def test_the_visitor_token_is_not_a_staff_credential(self):
        tid, tok, _ = self.create()
        for action in self.ACTIONS:
            r = self.staff(tid, action, {'message': 'x'}, hdr={'HTTP_AUTHORIZATION': f'Bearer {tok}'})
            self.assertEqual(r.status_code, 401, action)

    def test_the_loopback_script_token_is_not_a_person(self):
        tid, _, _ = self.create()
        with mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': 'script-token'}):
            for action in self.ACTIONS:
                r = self.staff(tid, action, {'message': 'x'},
                               hdr={'HTTP_AUTHORIZATION': 'Bearer script-token'})
                self.assertEqual(r.status_code, 403, action)
        self.assertEqual(SupportMessage.objects.filter(author_kind='admin').count(), 0)

    def test_an_inactive_staff_session_is_rejected(self):
        tid, _, _ = self.create()
        self.admin.active = False
        self.admin.save()
        self.assertEqual(self.staff(tid, 'reply', {'message': 'x'}).status_code, 401)

    def test_unknown_thread_is_404(self):
        for action in self.ACTIONS:
            self.assertEqual(self.staff('00000000-0000-0000-0000-000000000000', action,
                                        {'message': 'x'}).status_code, 404, action)


class ReadStateAndIdentityTests(SupportCase):
    def test_staff_seen_is_unset_until_a_staff_member_opens_the_thread(self):
        tid, tok, _ = self.create()
        self.assertIsNone(self.poll(tid, tok).json()['staff_seen_at'])
        self.assertEqual(self.staff(tid, 'seen').status_code, 200)
        self.assertIsNotNone(self.poll(tid, tok).json()['staff_seen_at'])

    def test_visitors_see_the_generic_label_never_the_staff_member(self):
        tid, tok, _ = self.create()
        self.staff(tid, 'reply', {'message': 'Hello, this is the team.'})
        self.staff(tid, 'reply', {'message': 'a private note', 'internal': True})
        body = self.poll(tid, tok).json()
        by_kind = {m['author_kind']: m for m in body['messages']}
        self.assertEqual(by_kind['admin']['author_label'], LABEL)
        self.assertIsNone(by_kind['visitor']['author_label'])
        self.assertNotIn('ann', json.dumps(body))
        self.assertNotIn('private note', json.dumps(body))

    def test_the_internal_record_keeps_the_real_author(self):
        tid, _, _ = self.create()
        self.staff(tid, 'reply', {'message': 'Hello'})
        self.assertEqual(SupportMessage.objects.get(author_kind='admin').author_admin, self.admin)
