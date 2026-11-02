import hashlib
import uuid

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from . import tokens
from .models import SupportThread


def _make():
    raw, h = tokens.new_token()
    return raw, SupportThread.objects.create(token_hash=h)


class TokenTests(TestCase):
    def test_new_token_hash_matches_sha256_and_is_unique(self):
        raw, h = tokens.new_token()
        self.assertEqual(h, hashlib.sha256(raw.encode()).hexdigest())
        self.assertTrue(tokens.valid_format(raw))
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

    def test_format_accepts_exactly_32_url_safe_bytes(self):
        self.assertTrue(tokens.valid_format('A' * 43))
        for bad in ('', None, 'A' * 42, 'A' * 44, 'A' * 42 + '!', 'A' * 42 + ' ', 5, b'A' * 43):
            self.assertFalse(tokens.valid_format(bad), repr(bad))

    def test_malformed_input_never_reaches_the_database(self):
        _, t = _make()
        with CaptureQueriesContext(connection) as q:
            self.assertIsNone(tokens.authorise(str(t.id), 'short'))
            self.assertIsNone(tokens.authorise('junk', 'A' * 43))
            self.assertIsNone(tokens.find_by_token('nope'))
        self.assertEqual(len(q), 0)

    def test_find_by_token_returns_the_owner(self):
        raw, t = _make()
        self.assertEqual(tokens.find_by_token(raw), t)
        self.assertIsNone(tokens.find_by_token('B' * 43))
