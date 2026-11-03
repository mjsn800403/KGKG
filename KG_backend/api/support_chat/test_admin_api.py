"""Staff reply path (lifecycle and authorisation are in test_lifecycle)."""
import uuid
from datetime import timedelta

from django.utils import timezone

from .helpers import SupportCase
from .models import SupportMessage, SupportThread


class ReplyTests(SupportCase):
    def test_public_reply_appears_in_visitor_poll_and_sets_waiting_customer(self):
        tid, tok, _ = self.create(message='hello')
        r = self.staff(tid, 'reply', {'message': 'Our plans start at ...'})
        self.assertEqual(r.status_code, 201)
        got = self.poll(tid, tok).json()
        self.assertEqual([(m['author_kind'], m['body']) for m in got['messages']],
                         [('visitor', 'hello'), ('admin', 'Our plans start at ...')])
        self.assertEqual(got['status'], 'waiting_customer')

    def test_internal_note_never_appears_in_visitor_poll_and_keeps_status(self):
        tid, tok, _ = self.create(message='hello')
        self.staff(tid, 'reply', {'message': 'looks like a duplicate lead', 'internal': True})
        got = self.poll(tid, tok).json()
        self.assertEqual([m['body'] for m in got['messages']], ['hello'])
        self.assertEqual(got['status'], 'waiting_staff')
        self.assertTrue(SupportMessage.objects.get(internal=True).internal)

    def test_empty_reply_rejected(self):
        tid, _, _ = self.create()
        self.assertEqual(self.staff(tid, 'reply', {'message': ' ​ '}).status_code, 400)

    def test_reply_to_junk_ids_is_404(self):
        self.assertEqual(self.staff(str(uuid.uuid4()), 'reply', {'message': 'x'}).status_code, 404)
        self.assertEqual(self.staff('junk', 'reply', {'message': 'x'}).status_code, 404)

    def test_a_public_reply_updates_last_activity(self):
        tid, _, _ = self.create()
        before = timezone.now() - timedelta(hours=1)       # a coarse clock cannot hide the update
        SupportThread.objects.filter(pk=tid).update(last_activity_at=before)
        self.staff(tid, 'reply', {'message': 'hi'})
        self.assertGreater(SupportThread.objects.get(pk=tid).last_activity_at, before)
