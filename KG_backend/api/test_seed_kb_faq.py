"""seed_kb_faq: publishes every FAQ once, owned and reviewed, and never
overwrites an article a person has edited."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from api.management.commands.seed_kb_faq import ARTICLES
from api.models import KnowledgeArticle, KnowledgeRevision, PlatformAdmin


class SeedKbFaqTests(TestCase):
    def setUp(self):
        self.admin = PlatformAdmin.objects.create(username='kb-owner')

    def test_publishes_each_article_once_with_owner_review_and_revision(self):
        call_command('seed_kb_faq', stdout=StringIO())
        qs = KnowledgeArticle.objects.filter(status='published', audience='customer')
        self.assertEqual(qs.count(), len(ARTICLES))
        self.assertFalse(qs.filter(owner__isnull=True).exists())
        self.assertFalse(any(a.is_stale for a in qs))
        self.assertEqual(KnowledgeRevision.objects.count(), len(ARTICLES))
        call_command('seed_kb_faq', stdout=StringIO())
        self.assertEqual(KnowledgeArticle.objects.count(), len(ARTICLES))

    def test_an_edited_article_is_left_alone(self):
        slug, cat, title, _ = ARTICLES[0]
        KnowledgeArticle.objects.create(slug=slug, title=title, category=cat, body='edited')
        call_command('seed_kb_faq', stdout=StringIO())
        self.assertEqual(KnowledgeArticle.objects.get(slug=slug).body, 'edited')

    def test_dry_run_writes_nothing(self):
        out = StringIO()
        call_command('seed_kb_faq', '--dry-run', stdout=out)
        self.assertEqual(KnowledgeArticle.objects.count(), 0)
        self.assertIn(f'would create {len(ARTICLES)}', out.getvalue())

    def test_slugs_are_unique_and_valid(self):
        from api.knowledge import SLUG_RE
        slugs = [a[0] for a in ARTICLES]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertTrue(all(SLUG_RE.match(s) for s in slugs))
        self.assertGreaterEqual(len(ARTICLES), 20)
