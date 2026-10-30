"""Is the site search instrumented?

`SearchLog` had zero rows on production on 2026-10-30, across four months and
34 active seats. Either nobody has ever used the search box, or the search is
not recording — and the two have opposite consequences. If nothing is
recorded, then `insights.admin_search_view`, the `zero_result_rate` it
publishes and the "Top zero-result searches" panel on the Grafana business
dashboard are all reporting on an empty table while believing they are
reporting on user behaviour. Worse, a feature-discovery checklist item built on
`SearchLog` would never complete for anyone.

These tests answer the question instead of assuming it, and then stay as the
regression guard.

Run:  python manage.py test api.test_qa_search_instrumentation
"""
import sys
import types
import unittest
from unittest import mock

from django.test import Client, TestCase

from . import rag as rag_pkg
from .models import SearchLog  # user_id is a plain integer column, not a FK
from .test_qa_catalog import CAMRY, QAUsersMixin


class _stub_service:
    """Stand in for api.rag.service without importing it.

    `views.search_view` does `from .rag import service` inside the function.
    That resolves through `sys.modules` OR through the package attribute
    depending on whether the submodule was ever imported, so both are replaced
    — patching only the attribute silently did nothing here, the real module
    was imported, and the view took its FileNotFoundError fallback instead of
    the path under test.

    Stubbing also keeps these tests runnable on a machine with no model stack,
    where importing the real module fails on torch. What is under test is the
    view's recording behaviour, not the retrieval engine.
    """

    def __init__(self, **attrs):
        self.module = types.ModuleType('api.rag.service')
        for k, v in attrs.items():
            setattr(self.module, k, v)
        self._patches = []

    def __enter__(self):
        self._patches = [
            mock.patch.dict(sys.modules, {'api.rag.service': self.module}),
            mock.patch.object(rag_pkg, 'service', self.module, create=True),
        ]
        for p in self._patches:
            p.start()
        return self.module

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


class SearchIsInstrumentedTests(QAUsersMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.make_world()

    def setUp(self):
        self.make_rows()
        self.c = Client()

    def _search(self, **extra):
        return self.c.get('/api/search/', {'q': 'brake fluid', 'car': CAMRY,
                                           'brand': 'Toyota'},
                          **self.auth(self.alice), **extra)

    def test_a_search_served_by_the_index_is_recorded(self):
        hit = [{'title': 'Brake fluid', 'segments': [], 'path': '/x'}]
        with _stub_service(search=lambda *a, **k: hit):
            r = self._search()
        self.assertEqual(r.status_code, 200, r.content)
        row = SearchLog.objects.get(user_id=self.alice.id)
        self.assertEqual(row.query, 'brake fluid')
        self.assertEqual(row.results, 1)

    def test_a_search_that_found_nothing_is_recorded_as_a_miss(self):
        """The zero-result rate is the whole point of the log: a query that
        found nothing is the most actionable row in the table."""
        with _stub_service(search=lambda *a, **k: []):
            r = self._search()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(SearchLog.objects.get(user_id=self.alice.id).results, 0)

    @unittest.expectedFailure   # mjsn800403/KGKG#48 — fallback records nothing
    def test_a_search_served_by_the_keyword_fallback_is_recorded_too(self):
        """KNOWN DEFECT, issue #48. Kept as an executable description of the
        bug rather than deleted: when it starts passing, the marker fails the
        build and whoever fixed it is told to remove it.

        When the semantic index is missing the view degrades to the old SQL
        LIKE search. That is still a search the person performed: if it is not
        recorded, the content-gap reporting silently under-counts, and it
        under-counts exactly on the installations whose index is broken — the
        ones whose users are most likely to find nothing."""
        def _no_index(*a, **k):
            raise FileNotFoundError('no index')
        with _stub_service(search=_no_index):
            r = self._search()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(SearchLog.objects.filter(user_id=self.alice.id).count(), 1)
