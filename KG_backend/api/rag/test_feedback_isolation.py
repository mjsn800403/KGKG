"""Staging and QA stacks must never write into production's feedback store.

Staging runs a copy of the production database, but the RAG warehouse
(Database_warehouse/_rag) is bind-mounted from production. Every assistant
query is logged to _rag/feedback.db and every rating feeds blob_boost_map(),
which re-ranks production search results. Without an override a staging smoke
test or a load test would write rows into production's store and skew live
ranking. RAG_FEEDBACK_DB points the store somewhere else.
"""
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api.rag import config, feedback

REPO = Path(__file__).resolve().parents[3]


class FeedbackDbOverrideTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop('RAG_FEEDBACK_DB', None)
        importlib.reload(config)
        feedback.invalidate_boost_cache()

    def test_default_is_the_rag_dir(self):
        os.environ.pop('RAG_FEEDBACK_DB', None)
        importlib.reload(config)
        self.assertEqual(config.FEEDBACK_DB, config.RAG_DIR / 'feedback.db')

    def test_env_override_redirects_every_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'staging-feedback.db'
            with mock.patch.dict(os.environ, {'RAG_FEEDBACK_DB': str(target)}):
                importlib.reload(config)
                self.assertEqual(config.FEEDBACK_DB, target)
                self.assertNotEqual(config.FEEDBACK_DB.parent, config.RAG_DIR)
                config.LOG_QUERIES = True
                feedback.log_query('brake fluid', {'model': 'Corolla'},
                                   {'hits': []}, latency_ms=3)
                feedback.rate('brake fluid', {'model': 'Corolla'}, 'assist',
                              [1], verdict=-1)
            self.assertTrue(target.exists(), 'writes did not land in the override')
            self.assertEqual(len(feedback.recent_downvotes(limit=5)), 1)


class StagingIsolationConfigTest(unittest.TestCase):
    """deploy.sh starts staging with the production warehouse mounted; it has
    to pass the override, or the fix above protects nothing."""

    def test_staging_backend_gets_its_own_feedback_db(self):
        deploy = (REPO / 'ops' / 'deploy' / 'deploy.sh').read_text()
        nosec = deploy[deploy.index('NOSEC=('):]
        nosec = nosec[:nosec.index(')')]
        self.assertIn('RAG_FEEDBACK_DB=/data/db/', nosec)
