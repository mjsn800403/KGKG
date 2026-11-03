"""Email validation for the visitor contact card.

The previous check was the regex ``^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$``, which CodeQL
flags as polynomial on user input (backtracking over the dots of the domain). The
replacement is a linear scan. These tests pin that it accepts and rejects exactly
what the old rule did, keeps the 254-character limit and the Persian message, and
stays fast on adversarial input.
"""
import random
import re
import time

from django.test import SimpleTestCase

from . import limits

#: The rule as it was before the fix; used only to prove equivalence.
LEGACY = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
INVALID_MESSAGE = 'ایمیل معتبر نیست.'


class ValidEmailTests(SimpleTestCase):
    def test_ordinary_addresses_are_accepted(self):
        for e in ('a@example.com', 'visitor@example.com', 'first.last@sub.example.co.uk',
                  'user+tag@example.org', 'x@y.z', 'a_b-c@d-e.fg', 'علی@example.ir',
                  'a@b.c.d', "o'neil@example.com", 'a@1.2'):
            self.assertTrue(limits.valid_email(e), e)

    def test_malformed_addresses_are_rejected(self):
        for e in ('', 'nope', 'x', '@', '@example.com', 'a@', 'a@b', 'a@.com', 'a@b.', 'a@.',
                  'a@@b.c', 'a@b@c.d', 'a b@c.d', 'a@b .c', 'a@b.c d', ' a@b.c', 'a@b.c ',
                  'a@b\n.c', 'a@b.c\n', 'a\t@b.c', 'a@b. c', 'a@b .c'):
            self.assertFalse(limits.valid_email(e), repr(e))

    def test_dot_must_have_text_on_both_sides_inside_the_domain(self):
        self.assertTrue(limits.valid_email('a@b.c'))
        self.assertFalse(limits.valid_email('a@.bc'))      # dot at the start of the domain
        self.assertFalse(limits.valid_email('a@bc.'))      # dot at the end of the domain
        self.assertTrue(limits.valid_email('a@b..c'))      # old rule accepted this; unchanged
        self.assertFalse(limits.valid_email('a.b@cd'))     # a dot in the local part does not count

    def test_non_strings_are_rejected_not_raised(self):
        for e in (None, 5, 1.5, [], {}, b'a@b.c'):
            self.assertFalse(limits.valid_email(e))


class EquivalenceWithTheOldRuleTests(SimpleTestCase):
    """Differential test: same verdict as the old regex on a large generated corpus."""

    ALPHABET = ['a', 'b', 'Z', '1', '.', '.', '@', '@', ' ', '\n', '\t', '-', '_', '+', '!', 'é', 'ع', ' ']

    def corpus(self):
        rnd = random.Random(20261103)                      # fixed seed: deterministic
        for _ in range(20000):
            n = rnd.randint(0, 14)
            yield ''.join(rnd.choice(self.ALPHABET) for _ in range(n))
        for local in ('a', 'a.b', '', 'x y'):
            for domain in ('b.c', 'b', '.c', 'b.', 'b..c', '.', '..', 'b.c.d', 'b c.d', 'b@c.d', ''):
                yield f'{local}@{domain}'

    def test_same_verdict_as_the_old_regex_everywhere(self):
        """Compared on stripped values, which is all the endpoint ever validates
        (``clean_contact`` strips first). The old regex's ``$`` also matched before a
        trailing newline, a quirk that was unreachable for that reason and is
        deliberately not preserved: the new check rejects any whitespace."""
        mismatches = [s for s in self.corpus()
                      if limits.valid_email(s.strip()) != bool(LEGACY.match(s.strip()))]
        self.assertEqual(mismatches[:10], [])

    def test_equivalence_on_adversarial_shapes(self):
        shapes = ['!@' + '!.' * n for n in (1, 5, 50, 120)] + ['a@' + '.' * n for n in (1, 3, 60)] \
            + ['a@' + 'b.' * n + 'c' for n in (1, 5, 50)] + ['@' * 5, 'a' * 50 + '@' + 'b' * 50]
        for s in shapes:
            self.assertEqual(limits.valid_email(s), bool(LEGACY.match(s)), s[:30])


class PerformanceTests(SimpleTestCase):
    # Wall-clock limits are a flake source (CI runs under coverage tracing), so the
    # timing checks are about GROWTH, not absolute speed, plus one very generous
    # guard that only a catastrophic (exponential) regression could trip.

    def test_adversarial_input_far_beyond_the_endpoint_cap_does_not_blow_up(self):
        """The endpoint caps input at 254 characters, but the validator itself must not
        be super-linear: 200k characters of the pattern CodeQL named."""
        cases = ['!@' + '!.' * 100_000, 'a@' + '.' * 200_000, 'a@' + 'b.' * 100_000,
                 '!@!.' * 50_000, '@' * 200_000, 'a' * 200_000 + '@b']
        start = time.perf_counter()
        for s in cases:
            limits.valid_email(s)
        self.assertLess(time.perf_counter() - start, 30)    # exponential would never finish

    def test_time_grows_linearly_not_quadratically(self):
        def cost(n):
            s = '!@' + '!.' * n
            best = float('inf')
            for _ in range(5):                              # best-of-5 damps runner noise
                t = time.perf_counter()
                limits.valid_email(s)
                best = min(best, time.perf_counter() - t)
            return best
        small, large = cost(20_000), cost(160_000)          # 8x the input
        # Linear is ~8x; quadratic would be ~64x. Allow wide slack for timer noise.
        self.assertLess(large, max(small, 2e-4) * 40)


class CleanContactEmailTests(SimpleTestCase):
    def test_accepts_a_valid_email_and_trims_whitespace(self):
        out, err = limits.clean_contact({'email': '  visitor@example.com  '})
        self.assertEqual((out, err), ({'contact_email': 'visitor@example.com'}, None))

    def test_invalid_email_returns_the_persian_message_and_no_data(self):
        for bad in ('nope', 'a@b', 'a b@c.d', '!@!.', 'x'):
            out, err = limits.clean_contact({'email': bad})
            self.assertEqual((out, err), ({}, INVALID_MESSAGE), bad)

    def test_length_limit_is_254_inclusive(self):
        ok = 'a' * (254 - len('@example.com')) + '@example.com'
        self.assertEqual(len(ok), 254)
        self.assertEqual(limits.clean_contact({'email': ok}), ({'contact_email': ok}, None))
        too_long = 'a' + ok
        self.assertEqual(len(too_long), 255)
        self.assertEqual(limits.clean_contact({'email': too_long}), ({}, INVALID_MESSAGE))

    def test_length_is_checked_on_the_trimmed_value(self):
        ok = 'a' * (254 - len('@example.com')) + '@example.com'
        self.assertEqual(limits.clean_contact({'email': f'   {ok}   '}), ({'contact_email': ok}, None))

    def test_a_far_too_long_adversarial_email_is_rejected_quickly(self):
        t = time.perf_counter()
        out, err = limits.clean_contact({'email': '!@' + '!.' * 100_000})
        self.assertEqual((out, err), ({}, INVALID_MESSAGE))
        self.assertLess(time.perf_counter() - t, 0.2)

    def test_other_contact_fields_still_validate_alongside(self):
        out, err = limits.clean_contact({'name': ' Zahra ', 'phone': '09123456789',
                                         'email': 'z@example.com'})
        self.assertIsNone(err)
        self.assertEqual((out['contact_name'], out['contact_email']), ('Zahra', 'z@example.com'))
        self.assertEqual(limits.clean_contact({'phone': '09123456789', 'email': 'bad'}),
                         ({}, INVALID_MESSAGE))
