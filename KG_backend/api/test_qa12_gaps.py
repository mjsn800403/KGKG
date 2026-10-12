"""QA 2026-09-27 gaps that could not be exercised on production without writing
live data: 👍/👎 rating + admin review queue, and the admin SSE live push."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, Client

from . import events
from .models import AuthToken, Company, PortalUser


class FeedbackRatingTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from .rag import config
        self.p = mock.patch.multiple(
            config, FEEDBACK_DB=Path(self.tmp.name) / 'fb.sqlite3',
            RAG_DIR=Path(self.tmp.name), LOG_QUERIES=True)
        self.p.start()
        co = Company.objects.create(name='FbCo', active=True)
        self.user = PortalUser.objects.create(company=co, username='fb', password_hash='x', active=True)

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def _rate(self, verdict, auth=True):
        h = {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(self.user).key}'} if auth else {}
        return Client().post('/api/feedback/rate/', json.dumps({
            'query': 'hub nut torque', 'verdict': verdict, 'car': 'Corolla Cross LE, FWD',
            'top_blobs': [11, 12], 'reason': 'wrong'}), content_type='application/json', **h)

    def test_rating_needs_login(self):
        self.assertEqual(self._rate(-1, auth=False).status_code, 401)

    def test_downvote_reaches_review_queue_upvote_does_not(self):
        from .rag import feedback
        self.assertEqual(self._rate(1).status_code, 200)
        self.assertEqual(self._rate(-1).status_code, 200)
        rows = feedback.recent_downvotes(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['query'], 'hub nut torque')


class AdminLivePushTests(TestCase):
    def test_admin_stream_pushes_change_made_after_connect(self):
        # An admin is connected at the live edge; a user is edited in another
        # tab one tail tick later; the open stream must deliver that change.
        def later(_s):
            later.n += 1
            if later.n == 1:
                events.emit('admin_changed', {'entity': 'user', 'id': 7, 'action': 'update'})
        later.n = 0
        with mock.patch.object(events, '_resolve_viewer', return_value={'is_admin': True}), \
                mock.patch.object(events.time, 'sleep', later), \
                mock.patch.object(events, 'connection'):
            resp = Client().get('/api/events/stream/')
            self.assertEqual(resp.status_code, 200)
            frames = []
            for chunk in resp.streaming_content:
                frames.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
                if 'admin_changed' in frames[-1] or len(frames) > 10:
                    break
        self.assertIn('event: ready', ''.join(frames[:2]))
        self.assertIn('admin_changed', frames[-1])
        self.assertIn('"action": "update"', frames[-1])
