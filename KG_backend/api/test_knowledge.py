"""Knowledge-base tests: the capabilities the evaluation's knowledge-transfer
finding needs (api/knowledge.py, models KnowledgeArticle / KnowledgeRevision /
KbSearchLog).

Root causes these address — see
audit-evidence/16-improvement-programme/ROOT_CAUSE_ANALYSIS.md, Finding 3:

  * knowledge existed only as developer-shaped Markdown in docs/, unreachable
    by a customer or by whoever answers a ticket;
  * no document had a named owner or a review date, so staleness was invisible;
  * a solution written into a ticket's admin_note was never searchable and
    never became reusable knowledge — the same question was answered from
    scratch every time.

Real HTTP stack, real models, nothing mocked.

Run:  python manage.py test api.test_knowledge
"""
import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from .models import (AdminAuthToken, AuthToken, Company, CompanyRequest,
                     KbSearchLog, KnowledgeArticle, KnowledgeRevision,
                     PlatformAdmin, PortalUser)

KB = '/api/kb/'
ADMIN_KB = '/api/admin/kb/'
ADMIN_REQ = '/api/admin/company-requests/'
SUPPORT_METRICS = '/api/admin/support/metrics/'


def _bearer(key):
    return {'HTTP_AUTHORIZATION': f'Bearer {key}'}


class KbBase(TestCase):
    def setUp(self):
        self.c = Client()
        self.co = Company.objects.create(name='KB Co')
        self.user = PortalUser.objects.create(company=self.co, username='kb_user',
                                              role='after_sales_specialist',
                                              display_name='Spec')
        self.admin = PlatformAdmin.objects.create(username='kb_admin', password_hash='x',
                                                  active=True)
        self.h_user = _bearer(AuthToken.issue(self.user).key)
        self.h_admin = _bearer(AdminAuthToken.issue(self.admin).key)

    def post(self, url, body, hdr):
        return self.c.post(url, json.dumps(body), content_type='application/json', **hdr)

    def article(self, **kw):
        kw.setdefault('title', 'Resetting the service reminder')
        kw.setdefault('slug', 'reset-service-reminder')
        kw.setdefault('body', 'Hold the trip button for ten seconds.')
        kw.setdefault('status', 'published')
        kw.setdefault('audience', 'customer')
        kw.setdefault('owner', self.admin)
        kw.setdefault('reviewed_at', timezone.now())
        return KnowledgeArticle.objects.create(**kw)


# ---------------------------------------------------------------------------
# Reading: who sees what
# ---------------------------------------------------------------------------

class KbReadTests(KbBase):
    def test_a_seat_can_list_published_customer_articles(self):
        self.article()
        r = self.c.get(KB, **self.h_user)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([a['slug'] for a in r.json()['articles']],
                         ['reset-service-reminder'])

    def test_signed_out_cannot_read_the_knowledge_base(self):
        self.article()
        self.assertEqual(self.c.get(KB).status_code, 401)

    def test_a_draft_or_archived_article_is_not_served_to_a_seat(self):
        self.article(slug='draft-one', status='draft')
        self.article(slug='archived-one', status='archived')
        self.assertEqual(self.c.get(KB, **self.h_user).json()['articles'], [])

    def test_an_internal_article_is_never_served_to_a_seat(self):
        self.article(slug='runbook', audience='internal')
        self.assertEqual(self.c.get(KB, **self.h_user).json()['articles'], [])
        got = self.c.get(f'{KB}runbook/', **self.h_user)
        self.assertEqual(got.status_code, 404)

    def test_an_admin_sees_internal_articles_in_the_admin_list(self):
        self.article(slug='runbook', audience='internal')
        got = self.c.get(ADMIN_KB, **self.h_admin).json()['articles']
        self.assertEqual([a['slug'] for a in got], ['runbook'])

    def test_detail_returns_the_body_and_counts_the_view(self):
        a = self.article()
        r = self.c.get(f'{KB}{a.slug}/', **self.h_user)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['article']['body'], a.body)
        a.refresh_from_db()
        self.assertEqual(a.views, 1)

    def test_an_unknown_slug_is_a_404(self):
        self.assertEqual(self.c.get(f'{KB}nope/', **self.h_user).status_code, 404)


# ---------------------------------------------------------------------------
# Search — and the misses, which are the useful signal
# ---------------------------------------------------------------------------

class KbSearchTests(KbBase):
    def test_search_matches_the_title_and_the_body(self):
        self.article(slug='a', title='Service reminder', body='nothing relevant')
        self.article(slug='b', title='Something else', body='the service reminder resets')
        self.article(slug='c', title='Door lock', body='unrelated text')
        got = self.c.get(f'{KB}?q=service reminder', **self.h_user).json()['articles']
        self.assertEqual(sorted(a['slug'] for a in got), ['a', 'b'])

    def test_search_is_case_insensitive(self):
        self.article(slug='a', title='Service Reminder')
        got = self.c.get(f'{KB}?q=SERVICE', **self.h_user).json()['articles']
        self.assertEqual([a['slug'] for a in got], ['a'])

    def test_a_category_filter_narrows_the_list(self):
        self.article(slug='a', category='maintenance')
        self.article(slug='b', category='billing')
        got = self.c.get(f'{KB}?category=billing', **self.h_user).json()['articles']
        self.assertEqual([a['slug'] for a in got], ['b'])

    def test_every_search_is_logged_with_its_result_count(self):
        self.article(slug='a', title='Service reminder')
        self.c.get(f'{KB}?q=service', **self.h_user)
        self.c.get(f'{KB}?q=gearbox oil capacity', **self.h_user)
        rows = list(KbSearchLog.objects.order_by('id').values('query', 'results'))
        self.assertEqual(rows, [{'query': 'service', 'results': 1},
                                {'query': 'gearbox oil capacity', 'results': 0}])
        self.assertEqual(KbSearchLog.objects.first().user_id, self.user.id)

    def test_listing_without_a_query_is_not_logged_as_a_search(self):
        self.article()
        self.c.get(KB, **self.h_user)
        self.assertFalse(KbSearchLog.objects.exists())


# ---------------------------------------------------------------------------
# Usefulness votes
# ---------------------------------------------------------------------------

class KbVoteTests(KbBase):
    def test_a_seat_can_mark_an_article_helpful_or_not(self):
        a = self.article()
        self.assertEqual(self.post(f'{KB}{a.slug}/vote/', {'helpful': True},
                                   self.h_user).status_code, 200)
        self.assertEqual(self.post(f'{KB}{a.slug}/vote/', {'helpful': False},
                                   self.h_user).status_code, 200)
        a.refresh_from_db()
        self.assertEqual((a.helpful, a.unhelpful), (1, 1))

    def test_a_vote_needs_the_helpful_flag(self):
        a = self.article()
        self.assertEqual(self.post(f'{KB}{a.slug}/vote/', {}, self.h_user).status_code, 400)

    def test_voting_signed_out_is_401(self):
        a = self.article()
        self.assertEqual(self.c.post(f'{KB}{a.slug}/vote/', '{}',
                                     content_type='application/json').status_code, 401)


# ---------------------------------------------------------------------------
# Authoring, ownership and revisions
# ---------------------------------------------------------------------------

class KbAuthoringTests(KbBase):
    def test_an_admin_can_create_an_article_and_owns_it(self):
        r = self.post(ADMIN_KB, {'title': 'Seat invitations', 'slug': 'seat-invitations',
                                 'body': 'Invite from the team page.',
                                 'category': 'accounts', 'status': 'published'},
                      self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        a = KnowledgeArticle.objects.get(slug='seat-invitations')
        self.assertEqual(a.owner_id, self.admin.id)
        self.assertEqual(a.version, 1)
        self.assertIsNotNone(a.reviewed_at)
        self.assertEqual(KnowledgeRevision.objects.filter(article=a).count(), 1)

    def test_a_seat_cannot_author(self):
        self.assertEqual(self.post(ADMIN_KB, {'title': 'x', 'slug': 'x', 'body': 'y'},
                                   self.h_user).status_code, 401)

    def test_a_title_body_and_slug_are_required(self):
        for body in ({'slug': 'a', 'body': 'b'}, {'title': 't', 'body': 'b'},
                     {'title': 't', 'slug': 'a'}):
            self.assertEqual(self.post(ADMIN_KB, body, self.h_admin).status_code, 400, body)

    def test_a_duplicate_slug_is_rejected(self):
        self.article(slug='dup')
        r = self.post(ADMIN_KB, {'title': 't', 'slug': 'dup', 'body': 'b'}, self.h_admin)
        self.assertEqual(r.status_code, 400)

    def test_an_edit_bumps_the_version_and_keeps_the_previous_text(self):
        a = self.article(body='old text')
        r = self.post(f'{ADMIN_KB}{a.id}/', {'body': 'new text', 'note': 'clarified'},
                      self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        a.refresh_from_db()
        self.assertEqual((a.body, a.version), ('new text', 2))
        revs = list(KnowledgeRevision.objects.filter(article=a).order_by('version')
                    .values_list('version', 'body'))
        self.assertEqual(revs, [(1, 'old text'), (2, 'new text')])
        self.assertEqual(KnowledgeRevision.objects.filter(article=a, version=2)
                         .first().editor_id, self.admin.id)

    def test_an_edit_that_changes_nothing_does_not_create_a_revision(self):
        a = self.article(body='same')
        self.post(f'{ADMIN_KB}{a.id}/', {'body': 'same'}, self.h_admin)
        a.refresh_from_db()
        self.assertEqual(a.version, 1)

    def test_reviewing_an_article_stamps_the_review_date_without_a_new_version(self):
        a = self.article()
        KnowledgeArticle.objects.filter(id=a.id).update(
            reviewed_at=timezone.now() - timedelta(days=400))
        r = self.post(f'{ADMIN_KB}{a.id}/', {'reviewed': True}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        a.refresh_from_db()
        self.assertEqual(a.version, 1)
        self.assertFalse(a.is_stale)

    def test_the_owner_can_be_reassigned_to_another_admin(self):
        other = PlatformAdmin.objects.create(username='kb_admin2', password_hash='x')
        a = self.article()
        r = self.post(f'{ADMIN_KB}{a.id}/', {'owner_id': other.id}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        a.refresh_from_db()
        self.assertEqual(a.owner_id, other.id)
        self.assertEqual(self.post(f'{ADMIN_KB}{a.id}/', {'owner_id': 9999},
                                   self.h_admin).status_code, 400)


class KbStalenessTests(KbBase):
    def test_an_article_past_its_review_interval_is_stale(self):
        a = self.article(review_interval_days=180)
        KnowledgeArticle.objects.filter(id=a.id).update(
            reviewed_at=timezone.now() - timedelta(days=181))
        self.assertTrue(KnowledgeArticle.objects.get(id=a.id).is_stale)

    def test_an_article_inside_its_interval_is_not_stale(self):
        a = self.article(review_interval_days=180)
        KnowledgeArticle.objects.filter(id=a.id).update(
            reviewed_at=timezone.now() - timedelta(days=179))
        self.assertFalse(KnowledgeArticle.objects.get(id=a.id).is_stale)

    def test_a_never_reviewed_article_is_stale(self):
        a = self.article()
        KnowledgeArticle.objects.filter(id=a.id).update(reviewed_at=None)
        self.assertTrue(KnowledgeArticle.objects.get(id=a.id).is_stale)


# ---------------------------------------------------------------------------
# The loop that makes transfer happen: a solved ticket becomes an article
# ---------------------------------------------------------------------------

class PromoteTicketTests(KbBase):
    def _ticket(self):
        return CompanyRequest.objects.create(
            company=self.co, created_by=self.user, kind='support',
            subject='Service reminder will not reset',
            body='It stays on after an oil change.', status='completed',
            admin_note='Hold the trip button for ten seconds.')

    def test_an_admin_can_promote_a_resolved_ticket_into_a_draft_article(self):
        t = self._ticket()
        r = self.post(f'{ADMIN_REQ}{t.id}/promote-to-article/',
                      {'slug': 'reset-reminder', 'category': 'maintenance'}, self.h_admin)
        self.assertEqual(r.status_code, 200, r.content)
        a = KnowledgeArticle.objects.get(slug='reset-reminder')
        # The draft starts from what the ticket already contains, so writing an
        # article is an edit rather than a blank page.
        self.assertEqual(a.title, t.subject)
        self.assertIn('Hold the trip button', a.body)
        self.assertEqual(a.status, 'draft')
        self.assertEqual(a.source_request_id, t.id)
        self.assertEqual(a.owner_id, self.admin.id)

    def test_the_draft_is_not_visible_to_seats_until_published(self):
        t = self._ticket()
        self.post(f'{ADMIN_REQ}{t.id}/promote-to-article/', {'slug': 's'}, self.h_admin)
        self.assertEqual(self.c.get(KB, **self.h_user).json()['articles'], [])
        a = KnowledgeArticle.objects.get(slug='s')
        self.post(f'{ADMIN_KB}{a.id}/', {'status': 'published'}, self.h_admin)
        self.assertEqual([x['slug'] for x in
                          self.c.get(KB, **self.h_user).json()['articles']], ['s'])

    def test_an_open_ticket_cannot_be_promoted(self):
        t = self._ticket()
        CompanyRequest.objects.filter(id=t.id).update(status='pending')
        r = self.post(f'{ADMIN_REQ}{t.id}/promote-to-article/', {'slug': 's'}, self.h_admin)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(KnowledgeArticle.objects.exists())

    def test_promoting_the_same_ticket_twice_is_rejected(self):
        t = self._ticket()
        self.post(f'{ADMIN_REQ}{t.id}/promote-to-article/', {'slug': 's1'}, self.h_admin)
        r = self.post(f'{ADMIN_REQ}{t.id}/promote-to-article/', {'slug': 's2'}, self.h_admin)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(KnowledgeArticle.objects.count(), 1)

    def test_a_seat_cannot_promote(self):
        t = self._ticket()
        self.assertEqual(self.post(f'{ADMIN_REQ}{t.id}/promote-to-article/',
                                   {'slug': 's'}, self.h_user).status_code, 401)

    def test_an_unknown_ticket_is_a_404(self):
        self.assertEqual(self.post(f'{ADMIN_REQ}99999/promote-to-article/',
                                   {'slug': 's'}, self.h_admin).status_code, 404)


# ---------------------------------------------------------------------------
# Knowledge metrics, reported beside the support metrics
# ---------------------------------------------------------------------------

class KnowledgeMetricsTests(KbBase):
    def test_the_knowledge_block_counts_articles_staleness_and_misses(self):
        self.article(slug='live')
        stale = self.article(slug='old')
        KnowledgeArticle.objects.filter(id=stale.id).update(reviewed_at=None)
        self.article(slug='unpublished', status='draft')
        self.c.get(f'{KB}?q=service', **self.h_user)       # hits 'live' and 'old'
        self.c.get(f'{KB}?q=no such thing', **self.h_user)
        self.c.get(f'{KB}?q=no such thing', **self.h_user)

        k = self.c.get(SUPPORT_METRICS, **self.h_admin).json()['knowledge']
        self.assertEqual(k['articles'], 3)
        self.assertEqual(k['published'], 2)
        self.assertEqual(k['stale'], 1)
        self.assertEqual(k['unowned'], 0)
        self.assertEqual(k['searches'], 3)
        self.assertEqual(k['zero_result_searches'], 2)   # the two 'no such thing' hits
        self.assertAlmostEqual(k['zero_result_rate'], 2 / 3, places=4)
        self.assertEqual(k['top_misses'][0], {'query': 'no such thing', 'count': 2})

    def test_the_knowledge_block_is_honest_when_nothing_was_searched(self):
        k = self.c.get(SUPPORT_METRICS, **self.h_admin).json()['knowledge']
        self.assertEqual(k['searches'], 0)
        self.assertIsNone(k['zero_result_rate'])

    def test_articles_promoted_from_tickets_are_counted(self):
        t = CompanyRequest.objects.create(company=self.co, subject='s', status='completed')
        self.post(f'{ADMIN_REQ}{t.id}/promote-to-article/', {'slug': 'p'}, self.h_admin)
        k = self.c.get(SUPPORT_METRICS, **self.h_admin).json()['knowledge']
        self.assertEqual(k['from_tickets'], 1)
