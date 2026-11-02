import hashlib
import uuid

from django.test import TestCase

from . import tokens
from .models import ChatThread


def _make():
    raw, h = tokens.new_token()
    return raw, ChatThread.objects.create(token_hash=h)


class TokenTests(TestCase):
    def test_new_token_hash_matches_sha256_and_is_unique(self):
        raw, h = tokens.new_token()
        self.assertEqual(h, hashlib.sha256(raw.encode()).hexdigest())
        self.assertGreaterEqual(len(raw), 40)
        self.assertNotEqual(raw, tokens.new_token()[0])

    def test_authorise_accepts_correct_pair(self):
        raw, t = _make()
        self.assertEqual(tokens.authorise(str(t.id), raw), t)

    def test_authorise_rejects_wrong_token_other_thread_empty_and_malformed_id(self):
        raw, t = _make()
        raw2, t2 = _make()
        self.assertIsNone(tokens.authorise(str(t.id), raw2))
        self.assertIsNone(tokens.authorise(str(t2.id), raw))
        self.assertIsNone(tokens.authorise(str(t.id), ''))
        self.assertIsNone(tokens.authorise(str(t.id), None))
        self.assertIsNone(tokens.authorise('not-a-uuid', raw))
        self.assertIsNone(tokens.authorise(str(uuid.uuid4()), raw))
