"""The conversational desk: categorisation, read state, search and deflection.

A separate file from api/test_helpdesk.py on purpose. Acceptance criterion 30
of the spec is that the 90 tests in that file pass *with no edits* — if making
this feature work required changing one of them, the feature broke behaviour
somebody relies on. Keeping the new tests here makes that diff easy to check:
`git diff --stat origin/work -- api/test_helpdesk.py` must print nothing.

Spec: docs/superpowers/specs/2026-10-31-conversational-helpdesk-design.md
"""
import json
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from django.utils import timezone

from . import listing, reads
from .models import (Car, Company, CompanyRequest, KbSearchLog, KnowledgeArticle,
                     TicketMessage, TicketRead, UserCarAccess)
from .requests_api import awaiting_reply
from .test_helpdesk import URL, ADMIN_URL, METRICS_URL, DeskBase

# A list page must cost a bounded number of queries, not one per row. Before
# the 2026-10-31 review fixes a ten-row page cost 29 on the customer side and
# 28 on the admin side; it is 12 and 11 now. The ceiling is asserted rather
# than the exact count, because the contract is "does not grow with the page",
# not "is exactly this number" — pinning the number would make an extra
# select_related look like a regression.
QUERY_CEILING = 14


def assert_bounded_queries(case, fn):
    with CaptureQueriesContext(connection) as ctx:
        fn()
    case.assertLessEqual(len(ctx), QUERY_CEILING,
                         f'{len(ctx)} queries for a ten-row page; a per-row query is hiding')


class TopicFieldTests(TestCase):
    def test_every_topic_choice_has_a_persian_label(self):
        for value, label in CompanyRequest.TOPIC_CHOICES:
            self.assertTrue(value.islower() and value.isascii(), value)
            self.assertNotEqual(value, label)

    def test_the_seven_agreed_topics_exist(self):
        self.assertEqual(
            [v for v, _ in CompanyRequest.TOPIC_CHOICES],
            ['missing_document', 'content_wrong', 'access_problem',
             'assistant_wrong', 'error_or_slow', 'billing', 'other'])

    def test_a_ticket_defaults_to_no_topic_and_no_car(self):
        co = Company.objects.create(name='T')
        r = CompanyRequest.objects.create(company=co, subject='s')
        self.assertEqual(r.topic, '')
        self.assertIsNone(r.car_id)


class DeskCarBase(DeskBase):
    """DeskBase plus two vehicles: one the specialist may open, one they may not.

    The forbidden one is the point — `car` must not become a way to find out
    what exists in the catalogue.
    """
    def setUp(self):
        super().setUp()
        self.car = Car.objects.create(brand_name='Toyota', car_name='Corolla Cross',
                                      year=2024, db_address='cc.sqlite3')
        self.forbidden_car = Car.objects.create(brand_name='Lexus', car_name='LX 600',
                                                year=2025, db_address='lx.sqlite3')
        UserCarAccess.objects.create(user=self.spec, car=self.car,
                                     documents=['manual'], admin_granted=True)
        self.kb_article = KnowledgeArticle.objects.create(
            title='Resetting the reminder', slug='reset-reminder',
            body='Hold the trip button.', status='published', audience='customer',
            owner=self.admin, reviewed_at=timezone.now())


class TopicAndCarApiTests(DeskCarBase):
    def test_a_ticket_round_trips_its_topic(self):
        t = self.create(topic='missing_document')
        self.assertEqual(t['topic'], 'missing_document')
        self.assertTrue(t['topic_label'])

    def test_an_unknown_topic_is_rejected_and_writes_nothing(self):
        r = self.post(URL, {'kind': 'support', 'subject': 's', 'topic': 'nope'}, self.h_spec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(CompanyRequest.objects.count(), 0)

    def test_a_ticket_round_trips_a_car_the_filer_can_open(self):
        t = self.create(car_id=self.car.id)
        self.assertEqual(t['car']['id'], self.car.id)
        self.assertIn('Corolla Cross', t['car']['name'])

    def test_a_car_the_filer_cannot_open_is_rejected_and_writes_nothing(self):
        r = self.post(URL, {'kind': 'support', 'subject': 's',
                            'car_id': self.forbidden_car.id}, self.h_spec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(CompanyRequest.objects.count(), 0)

    def test_an_unknown_car_id_is_rejected(self):
        r = self.post(URL, {'kind': 'support', 'subject': 's', 'car_id': 999999}, self.h_spec)
        self.assertEqual(r.status_code, 400)

    def test_a_ticket_without_either_is_uncategorised(self):
        t = self.create()
        self.assertEqual(t['topic'], '')
        self.assertIsNone(t['car'])

    def test_a_ticket_whose_car_was_deleted_still_serialises(self):
        """Review Focus 1: SET_NULL must leave a readable ticket, not a 500."""
        t = self.create(car_id=self.car.id)
        self.car.delete()
        r = self.c.get(f'{URL}{t["id"]}/', **self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNone(r.json()['request']['car'])

    def test_the_desk_may_log_a_call_about_any_vehicle(self):
        """An admin is not bound by one seat's grants."""
        r = self.post(ADMIN_URL, {'company_id': self.co_a.id, 'subject': 'call',
                                  'car_id': self.forbidden_car.id,
                                  'source': 'phone'}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['request']['car']['id'], self.forbidden_car.id)


class ReadStateTests(DeskCarBase):
    """Acceptance criteria 7-15. The whole point of this model is that every
    unread badge in the product is DERIVED from it: nothing is stored that
    could be left behind, so no badge can go stale."""

    def _unread(self, req, *, user=None, admin=None):
        return reads.unread_count(req, user=user, admin=admin)

    def test_an_unopened_ticket_counts_every_message_the_viewer_did_not_write(self):
        t = self.create(body='opening')                      # authored by spec
        r = CompanyRequest.objects.get(id=t['id'])
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'first'}, self.h_admin)
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'second'}, self.h_admin)
        self.assertEqual(self._unread(r, user=self.spec), 2)

    def test_marking_read_zeroes_the_count(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        reads.mark_read(r, user=self.spec)
        self.assertEqual(self._unread(r, user=self.spec), 0)

    def test_a_message_after_reading_is_unread_again(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        reads.mark_read(r, user=self.spec)
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'later'}, self.h_admin)
        self.assertEqual(self._unread(r, user=self.spec), 1)

    def test_your_own_message_is_never_unread(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        self.assertEqual(self._unread(r, user=self.spec), 0)

    def test_an_internal_note_is_unread_for_an_admin_and_invisible_to_the_customer(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        reads.mark_read(r, user=self.spec)
        self.post(f'{ADMIN_URL}{t["id"]}/',
                  {'message': 'ask licensing', 'internal': True}, self.h_admin)
        self.assertEqual(self._unread(r, user=self.spec), 0)
        self.assertEqual(self._unread(r, admin=self.admin2), 2)

    def test_two_seats_in_one_company_have_independent_read_state(self):
        t = self.create(hdr=self.h_mgr, body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        reads.mark_read(r, user=self.mgr)
        self.assertEqual(self._unread(r, user=self.mgr), 0)
        self.assertEqual(self._unread(r, user=self.spec), 2)

    def test_an_admin_read_mark_does_not_touch_a_seat(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        reads.mark_read(r, admin=self.admin)
        self.assertEqual(self._unread(r, admin=self.admin), 0)
        self.assertEqual(self._unread(r, user=self.spec), 1)

    def test_a_read_ticket_can_still_be_awaiting_our_reply(self):
        """The distinction the old single 'open' signal could not express."""
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        reads.mark_read(r, admin=self.admin)
        self.assertEqual(self._unread(r, admin=self.admin), 0)
        self.assertTrue(awaiting_reply(r))

    def test_a_get_does_not_mark_anything_read(self):
        t = self.create(body='opening')
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        self.c.get(f'{URL}{t["id"]}/', **self.h_spec)
        self.assertEqual(TicketRead.objects.count(), 0)

    def test_the_read_action_marks_it_read_for_the_caller(self):
        t = self.create(body='opening')
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        r = self.post(f'{URL}{t["id"]}/', {'action': 'read'}, self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['request']['unread_count'], 0)

    def test_marking_read_twice_does_not_error_or_duplicate(self):
        """Review Focus 4: two tabs, one ticket, same instant."""
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        for _ in range(2):
            reads.mark_read(r, user=self.spec)
        self.assertEqual(TicketRead.objects.filter(request=r, user=self.spec).count(), 1)

    def test_a_read_mark_belongs_to_exactly_one_viewer(self):
        t = self.create()
        r = CompanyRequest.objects.get(id=t['id'])
        with self.assertRaises(Exception):
            TicketRead.objects.create(request=r, user=self.spec, admin=self.admin,
                                      last_read_at=timezone.now())

    def test_unread_counts_answers_for_a_whole_page_at_once(self):
        a = self.create(body='one')
        b = self.create(body='two')
        for t in (a, b):
            self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        counts = reads.unread_counts([a['id'], b['id']], user=self.spec)
        self.assertEqual(counts, {a['id']: 1, b['id']: 1})

    def test_last_message_names_who_spoke_last(self):
        t = self.create(body='opening')
        r = CompanyRequest.objects.get(id=t['id'])
        self.assertEqual(reads.last_message(r)['by'], 'customer')
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'answer'}, self.h_admin)
        r.refresh_from_db()
        self.assertEqual(reads.last_message(r)['by'], 'platform')

    def test_a_ticket_with_no_messages_has_no_last_message(self):
        t = self.create()
        r = CompanyRequest.objects.get(id=t['id'])
        self.assertIsNone(reads.last_message(r))

    def test_the_admin_read_action_marks_it_read_for_that_admin(self):
        t = self.create(body='opening')
        r = self.post(f'{ADMIN_URL}{t["id"]}/', {'action': 'read'}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['request']['unread_count'], 0)
        self.assertEqual(reads.unread_count(CompanyRequest.objects.get(id=t['id']),
                                            admin=self.admin2), 1)


class CursorTests(TestCase):
    """The cursor is opaque to the client and never trusted on the way back in."""

    def test_a_cursor_round_trips(self):
        now = timezone.now()
        self.assertEqual(listing.decode_cursor(listing.encode_cursor(now, 42)),
                         (now, 42))

    def test_garbage_decodes_to_none(self):
        for raw in ['', 'x', 'YWJj', '!!!!', 'MTIzfA==', None]:
            self.assertIsNone(listing.decode_cursor(raw), raw)

    def test_a_limit_is_clamped_to_the_maximum(self):
        self.assertEqual(listing.clamp_limit('5000'), listing.LIMIT_MAX)
        self.assertEqual(listing.clamp_limit('0'), listing.LIMIT_DEFAULT)
        self.assertEqual(listing.clamp_limit('abc'), listing.LIMIT_DEFAULT)
        self.assertEqual(listing.clamp_limit(None), listing.LIMIT_DEFAULT)
        self.assertEqual(listing.clamp_limit('7'), 7)


class SearchAndPaginationTests(DeskCarBase):
    """Acceptance criteria 16-23, plus Review Focus 2 (a literal %), 3 (a
    forged cursor) and 5 (an unbounded thread)."""

    def _get(self, qs='', hdr=None):
        r = self.c.get(f'{URL}{qs}', **(hdr or self.h_mgr))
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_q_matches_a_word_in_the_subject(self):
        self.create(subject='brake chapter will not open')
        self.create(subject='seat count')
        rows = self._get('?q=brake')['requests']
        self.assertEqual([r['subject'] for r in rows], ['brake chapter will not open'])

    def test_q_matches_a_word_in_a_message_body_and_returns_the_ticket_once(self):
        t = self.create(subject='something vague', body='the handbrake is wrong')
        self.post(f'{URL}{t["id"]}/', {'action': 'message', 'message': 'handbrake again'},
                  self.h_spec)
        rows = self._get('?q=handbrake')['requests']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], t['id'])

    def test_q_never_crosses_a_company_boundary(self):
        self.post(URL, {'kind': 'support', 'subject': 'brake chapter'}, self.h_other)
        self.assertEqual(self._get('?q=brake')['requests'], [])

    def test_a_percent_sign_in_q_is_matched_literally(self):
        """Review Focus 2: a wildcard in the query must not match everything."""
        self.create(subject='coverage is 100% wrong')
        self.create(subject='unrelated ticket')
        rows = self._get('?q=100%25')['requests']
        self.assertEqual([r['subject'] for r in rows], ['coverage is 100% wrong'])

    def test_an_underscore_in_q_is_matched_literally(self):
        self.create(subject='file_name is odd')
        self.create(subject='fileXname is odd')
        rows = self._get('?q=file_name')['requests']
        self.assertEqual([r['subject'] for r in rows], ['file_name is odd'])

    def test_topic_kind_status_and_car_each_filter_and_compose(self):
        a = self.create(subject='a', topic='missing_document', car_id=self.car.id,
                        hdr=self.h_spec)
        self.create(subject='b', topic='billing', hdr=self.h_spec)
        self.assertEqual([r['id'] for r in self._get('?topic=missing_document')['requests']],
                         [a['id']])
        self.assertEqual([r['id'] for r in self._get(f'?car_id={self.car.id}')['requests']],
                         [a['id']])
        self.assertEqual(
            [r['id'] for r in
             self._get(f'?topic=missing_document&car_id={self.car.id}&status=pending'
                       )['requests']],
            [a['id']])
        self.assertEqual(self._get('?topic=billing&car_id=%d' % self.car.id)['requests'], [])

    def test_unread_returns_only_the_viewers_unread_tickets(self):
        answered = self.create(subject='answered', hdr=self.h_mgr, body='x')
        self.post(f'{ADMIN_URL}{answered["id"]}/', {'message': 'reply'}, self.h_admin)
        quiet = self.create(subject='quiet', hdr=self.h_mgr, body='y')
        rows = self._get('?unread=1')['requests']
        self.assertEqual([r['id'] for r in rows], [answered['id']])
        self.post(f'{URL}{answered["id"]}/', {'action': 'read'}, self.h_mgr)
        self.assertEqual(self._get('?unread=1')['requests'], [])
        self.assertTrue(quiet)

    def test_a_page_returns_a_cursor_that_yields_the_next_rows_exactly_once(self):
        made = [self.create(subject=f't{i}', hdr=self.h_mgr)['id'] for i in range(7)]
        first = self._get('?limit=3')
        self.assertEqual(len(first['requests']), 3)
        self.assertTrue(first['next_cursor'])
        seen = [r['id'] for r in first['requests']]
        cursor = first['next_cursor']
        while cursor:
            page = self._get(f'?limit=3&cursor={cursor}')
            seen += [r['id'] for r in page['requests']]
            cursor = page['next_cursor']
        self.assertEqual(sorted(seen), sorted(made))
        self.assertEqual(len(seen), len(set(seen)))

    def test_a_row_inserted_between_pages_neither_duplicates_nor_hides_a_row(self):
        made = [self.create(subject=f't{i}', hdr=self.h_mgr)['id'] for i in range(5)]
        first = self._get('?limit=2')
        seen = [r['id'] for r in first['requests']]
        self.create(subject='arrived late', hdr=self.h_mgr)   # newest of all
        cursor = first['next_cursor']
        while cursor:
            page = self._get(f'?limit=2&cursor={cursor}')
            seen += [r['id'] for r in page['requests']]
            cursor = page['next_cursor']
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(sorted(set(seen)), sorted(made))

    def test_an_oversized_limit_is_clamped_not_an_error(self):
        self.create(hdr=self.h_mgr)
        d = self._get('?limit=99999')
        self.assertEqual(len(d['requests']), 1)

    def test_a_forged_cursor_is_a_400_not_a_500(self):
        """Review Focus 3."""
        r = self.c.get(f'{URL}?cursor=not-a-cursor', **self.h_mgr)
        self.assertEqual(r.status_code, 400)

    def test_a_thread_is_capped_and_says_so(self):
        """Review Focus 5: a long conversation must not be fetched whole."""
        t = self.create(hdr=self.h_mgr, body='first')
        r = CompanyRequest.objects.get(id=t['id'])
        TicketMessage.objects.bulk_create([
            TicketMessage(request=r, author_user=self.mgr, body=f'm{i}')
            for i in range(listing.MAX_THREAD + 5)])
        d = self.c.get(f'{URL}{t["id"]}/', **self.h_mgr).json()['request']
        self.assertEqual(len(d['messages']), listing.MAX_THREAD)
        self.assertTrue(d['messages_truncated'])


class AdminInboxFilterTests(DeskCarBase):
    """The desk searches with the same vocabulary the customer does."""

    def _inbox(self, qs=''):
        r = self.c.get(f'{ADMIN_URL}{qs}', **self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_the_inbox_searches_subjects_and_message_bodies(self):
        t = self.create(subject='vague', body='the handbrake again')
        self.create(subject='unrelated')
        self.assertEqual([r['id'] for r in self._inbox('?q=handbrake')['requests']],
                         [t['id']])

    def test_the_inbox_filters_by_topic_and_vehicle(self):
        a = self.create(subject='a', topic='access_problem', car_id=self.car.id)
        self.create(subject='b')
        self.assertEqual([r['id'] for r in self._inbox('?topic=access_problem')['requests']],
                         [a['id']])
        self.assertEqual([r['id'] for r in self._inbox(f'?car_id={self.car.id}')['requests']],
                         [a['id']])

    def test_the_inbox_can_show_only_what_awaits_us(self):
        waiting = self.create(subject='waiting', body='help')
        answered = self.create(subject='answered', body='help')
        self.post(f'{ADMIN_URL}{answered["id"]}/', {'message': 'done'}, self.h_admin)
        self.assertEqual([r['id'] for r in self._inbox('?awaiting=1')['requests']],
                         [waiting['id']])

    def test_the_inbox_paginates_with_a_cursor(self):
        made = [self.create(subject=f't{i}')['id'] for i in range(5)]
        first = self._inbox('?limit=2')
        seen = [r['id'] for r in first['requests']]
        cursor = first['next_cursor']
        while cursor:
            page = self._inbox(f'?limit=2&cursor={cursor}')
            seen += [r['id'] for r in page['requests']]
            cursor = page['next_cursor']
        self.assertEqual(sorted(seen), sorted(made))
        self.assertEqual(len(seen), len(set(seen)))

    def test_a_forged_cursor_on_the_inbox_is_a_400(self):
        r = self.c.get(f'{ADMIN_URL}?cursor=nonsense', **self.h_admin)
        self.assertEqual(r.status_code, 400)

    def test_the_inbox_reports_how_many_await_us(self):
        self.create(subject='waiting', body='help')
        self.assertEqual(self._inbox()['counts']['awaiting_reply'], 1)


class DeskMetricsTests(DeskCarBase):
    """Acceptance criteria 27-29. Every rate here is None, not 0, when its
    denominator is empty — the module's existing convention, and the reason a
    quiet month cannot be read as a perfect one."""

    def _metrics(self):
        r = self.c.get(METRICS_URL, **self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_by_topic_counts_uncategorised_separately(self):
        self.create(topic='missing_document')
        self.create(topic='missing_document')
        self.create()                                     # no topic
        d = self._metrics()['by_topic']
        self.assertEqual(d['missing_document'], 2)
        self.assertEqual(d['uncategorised'], 1)

    def test_by_topic_labels_every_entry(self):
        self.create(topic='billing')
        rows = self._metrics()['by_topic_labelled']
        self.assertTrue(any(r['id'] == 'billing' and r['label'] for r in rows))

    def test_by_vehicle_counts_only_tickets_with_a_car(self):
        self.create(car_id=self.car.id)
        self.create()
        rows = self._metrics()['by_vehicle']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['car_id'], self.car.id)
        self.assertEqual(rows[0]['count'], 1)
        self.assertIn('Corolla Cross', rows[0]['name'])

    def test_the_deflection_rate_is_none_when_nothing_was_suggested(self):
        d = self._metrics()['deflections']
        self.assertEqual(d['suggested'], 0)
        self.assertEqual(d['deflected'], 0)
        self.assertIsNone(d['rate'])

    def test_a_deflection_is_counted_and_rated(self):
        KbSearchLog.objects.create(user=self.spec, company=self.co_a, query='a',
                                   query_norm='a', results=1, context='compose')
        KbSearchLog.objects.create(user=self.spec, company=self.co_a, query='b',
                                   query_norm='b', results=1, context='compose',
                                   deflected_article=self.kb_article)
        d = self._metrics()['deflections']
        self.assertEqual((d['suggested'], d['deflected']), (2, 1))
        self.assertAlmostEqual(d['rate'], 0.5, places=3)

    def test_search_reports_the_zero_result_share(self):
        KbSearchLog.objects.create(user=self.spec, company=self.co_a, query='hit',
                                   query_norm='hit', results=3, context='compose')
        KbSearchLog.objects.create(user=self.spec, company=self.co_a, query='miss',
                                   query_norm='miss', results=0, context='compose')
        d = self._metrics()['search']
        self.assertEqual(d['compose_searches'], 2)
        self.assertAlmostEqual(d['zero_result_share'], 0.5, places=3)

    def test_the_zero_result_share_is_none_with_no_searches(self):
        self.assertIsNone(self._metrics()['search']['zero_result_share'])


class ReviewFixTests(DeskCarBase):
    """Findings from the 2026-10-31 whole-branch review. Each test here failed
    before its fix; together they are the proof the findings were real."""

    # I4 — the read action silently discarded the rest of the body.
    def test_a_read_action_carrying_other_changes_is_refused(self):
        t = self.create(body='x')
        r = self.post(f'{ADMIN_URL}{t["id"]}/',
                      {'action': 'read', 'status': 'completed', 'message': 'we fixed it'},
                      self.h_admin)
        self.assertEqual(r.status_code, 400)
        again = self.c.get(f'{ADMIN_URL}{t["id"]}/', **self.h_admin).json()['request']
        self.assertEqual(again['status'], 'pending')
        self.assertEqual(len(again['messages']), 1)

    def test_a_read_action_on_its_own_still_works(self):
        t = self.create(body='x')
        r = self.post(f'{ADMIN_URL}{t["id"]}/', {'action': 'read'}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)

    # I1 — the list claimed to be ordered by activity and was not.
    def test_the_list_is_ordered_by_last_activity_not_creation(self):
        old = self.create(subject='old with a fresh reply', hdr=self.h_mgr, body='q')
        CompanyRequest.objects.filter(id=old['id']).update(
            created_at=timezone.now() - timedelta(days=30))
        self.create(subject='new and silent', hdr=self.h_mgr)
        self.post(f'{ADMIN_URL}{old["id"]}/', {'message': 'answered just now'}, self.h_admin)
        rows = self.c.get(URL, **self.h_mgr).json()['requests']
        self.assertEqual(rows[0]['id'], old['id'],
                         'a ticket replied to seconds ago must outrank a silent new one')

    def test_the_admin_inbox_is_ordered_by_last_activity_too(self):
        old = self.create(subject='old', hdr=self.h_mgr, body='q')
        CompanyRequest.objects.filter(id=old['id']).update(
            created_at=timezone.now() - timedelta(days=30))
        self.create(subject='new', hdr=self.h_mgr)
        self.post(f'{ADMIN_URL}{old["id"]}/', {'message': 'answered'}, self.h_admin)
        rows = self.c.get(ADMIN_URL, **self.h_admin).json()['requests']
        self.assertEqual(rows[0]['id'], old['id'])

    def test_activity_ordering_still_paginates_without_duplicates(self):
        made = [self.create(subject=f't{i}', hdr=self.h_mgr)['id'] for i in range(7)]
        # Give the middle one fresh activity so the order is not creation order.
        self.post(f'{ADMIN_URL}{made[3]}/', {'message': 'bump'}, self.h_admin)
        seen, cursor = [], None
        while True:
            qs = f'?limit=3{f"&cursor={cursor}" if cursor else ""}'
            d = self.c.get(f'{URL}{qs}', **self.h_mgr).json()
            seen += [r['id'] for r in d['requests']]
            cursor = d['next_cursor']
            if not cursor:
                break
        self.assertEqual(sorted(seen), sorted(made))
        self.assertEqual(len(seen), len(set(seen)))

    # I6 — "only what is late" must be a server filter, not a page filter.
    def test_breached_is_a_server_side_filter(self):
        late = self.create(subject='late', hdr=self.h_mgr)
        CompanyRequest.objects.filter(id=late['id']).update(
            sla_response_due_at=timezone.now() - timedelta(hours=1))
        self.create(subject='on time', hdr=self.h_mgr)
        rows = self.c.get(f'{ADMIN_URL}?breached=1', **self.h_admin).json()['requests']
        self.assertEqual([r['id'] for r in rows], [late['id']])

    def test_a_met_response_target_is_not_breached(self):
        t = self.create(subject='answered in time', hdr=self.h_mgr, body='q')
        self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'quick'}, self.h_admin)
        CompanyRequest.objects.filter(id=t['id']).update(
            sla_response_due_at=timezone.now() - timedelta(hours=1))
        rows = self.c.get(f'{ADMIN_URL}?breached=1', **self.h_admin).json()['requests']
        self.assertEqual(rows, [])

    # I7/I8/I9 — the page must not cost a query per row.
    def test_a_customer_page_of_ten_costs_a_bounded_number_of_queries(self):
        for i in range(10):
            t = self.create(subject=f'q{i}', hdr=self.h_mgr, body='body')
            self.post(f'{ADMIN_URL}{t["id"]}/', {'message': 'reply'}, self.h_admin)
        assert_bounded_queries(self, lambda: self.c.get(f'{URL}?limit=10', **self.h_mgr))

    def test_an_admin_page_of_ten_costs_a_bounded_number_of_queries(self):
        for i in range(10):
            self.create(subject=f'q{i}', hdr=self.h_mgr, body='body')
        assert_bounded_queries(self, lambda: self.c.get(f'{ADMIN_URL}?limit=10', **self.h_admin))

    def test_awaiting_filter_does_not_cost_a_query_per_open_ticket(self):
        for i in range(10):
            self.create(subject=f'q{i}', hdr=self.h_mgr, body='body')
        assert_bounded_queries(
            self, lambda: self.c.get(f'{ADMIN_URL}?awaiting=1&limit=10', **self.h_admin))


class DeflectionDenominatorTests(DeskCarBase):
    """I10 from the review: `suggested` counted one row per debounced
    keystroke pause and counted searches that showed nothing, so the published
    rate moved with typing speed rather than with deflection.

    A compose session is the unit. The client sends one id per opened form.
    """

    def setUp(self):
        super().setUp()
        self.article = self.kb_article

    def _log(self, query, *, results=1, compose_id='', deflected=None):
        return KbSearchLog.objects.create(
            user=self.spec, company=self.co_a, query=query, query_norm=query.lower(),
            results=results, context='compose', compose_id=compose_id,
            deflected_article=deflected)

    def _deflections(self):
        r = self.c.get(METRICS_URL, **self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['deflections']

    def test_one_compose_session_counts_once_however_much_was_typed(self):
        for q in ['br', 'bra', 'brak', 'brake']:
            self._log(q, compose_id='session-a')
        self.assertEqual(self._deflections()['suggested'], 1)

    def test_two_sessions_count_twice(self):
        self._log('brake', compose_id='session-a')
        self._log('seat', compose_id='session-b')
        self.assertEqual(self._deflections()['suggested'], 2)

    def test_a_session_that_was_shown_nothing_is_not_a_suggestion(self):
        self._log('nothing matches this', results=0, compose_id='session-a')
        d = self._deflections()
        self.assertEqual(d['suggested'], 0)
        self.assertIsNone(d['rate'])

    def test_a_session_counts_once_even_if_only_one_search_showed_something(self):
        self._log('zz', results=0, compose_id='session-a')
        self._log('brake', results=2, compose_id='session-a')
        self.assertEqual(self._deflections()['suggested'], 1)

    def test_the_rate_is_deflected_sessions_over_shown_sessions(self):
        self._log('brake', compose_id='session-a', deflected=self.article)
        self._log('seat', compose_id='session-b')
        d = self._deflections()
        self.assertEqual((d['suggested'], d['deflected']), (2, 1))
        self.assertAlmostEqual(d['rate'], 0.5, places=3)

    def test_a_deflection_counts_once_per_session_not_per_row(self):
        self._log('br', compose_id='session-a', deflected=self.article)
        self._log('brake', compose_id='session-a', deflected=self.article)
        d = self._deflections()
        self.assertEqual((d['suggested'], d['deflected']), (1, 1))
        self.assertEqual(d['rate'], 1.0)

    def test_a_row_with_no_session_id_still_counts_as_one(self):
        """An older row, or a client that did not send one: counted, not lost."""
        self._log('brake', compose_id='')
        self.assertEqual(self._deflections()['suggested'], 1)

    def test_the_zero_result_share_counts_searches_not_sessions(self):
        """A miss names an article that should exist, so every miss matters —
        this one is deliberately per search, and says so."""
        self._log('hit', results=3, compose_id='s')
        self._log('miss', results=0, compose_id='s')
        d = self.c.get(METRICS_URL, **self.h_admin).json()['search']
        self.assertEqual(d['compose_searches'], 2)
        self.assertAlmostEqual(d['zero_result_share'], 0.5, places=3)

    def test_the_compose_endpoint_stores_the_session_id(self):
        self.c.get('/api/kb/?q=brake&context=compose&compose_id=abc123', **self.h_spec)
        self.assertEqual(KbSearchLog.objects.latest('id').compose_id, 'abc123')

    def test_a_deflection_annotates_the_session_not_just_one_query(self):
        self.c.get('/api/kb/?q=br&context=compose&compose_id=abc', **self.h_spec)
        self.c.get('/api/kb/?q=brake&context=compose&compose_id=abc', **self.h_spec)
        r = self.post(f'/api/kb/{self.article.slug}/deflect/',
                      {'query': 'brake', 'compose_id': 'abc'}, self.h_spec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(
            KbSearchLog.objects.filter(compose_id='abc',
                                       deflected_article=self.article).count(), 1)
