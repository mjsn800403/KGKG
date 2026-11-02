import os
from pathlib import Path

from django.test import SimpleTestCase

from api.safepath import safe_join, split_year_suffix


class SafeJoinTests(SimpleTestCase):
    """A name taken from a request, a row or a folder listing must never leave its base."""

    base = Path(os.path.join(os.sep, 'srv', 'warehouse'))

    def test_plain_names_stay_inside(self):
        p = safe_join(self.base, 'Corolla Cross LE, FWD (2023).db')
        self.assertEqual(p, self.base / 'Corolla Cross LE, FWD (2023).db')
        self.assertIsInstance(p, Path)

    def test_nested_relative_name_is_allowed(self):
        p = safe_join(self.base, 'Toyota/2023/Corolla.db')
        self.assertEqual(p, self.base / 'Toyota' / '2023' / 'Corolla.db')

    def test_parent_traversal_is_refused(self):
        for bad in ('../etc/passwd', 'a/../../etc/passwd', '..', 'x/../..'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                safe_join(self.base, bad)

    def test_absolute_name_is_refused(self):
        with self.assertRaises(ValueError):
            safe_join(self.base, os.sep + 'etc' + os.sep + 'passwd')

    def test_sibling_with_same_prefix_is_refused(self):
        # /srv/warehouse-evil starts with the string /srv/warehouse
        with self.assertRaises(ValueError):
            safe_join(self.base, '..' + os.sep + 'warehouse-evil' + os.sep + 'x')

    def test_nul_byte_is_refused(self):
        with self.assertRaises(ValueError):
            safe_join(self.base, 'a\x00b.db')

    def test_dots_inside_a_name_are_not_traversal(self):
        self.assertEqual(safe_join(self.base, 'Foo..Bar.db'), self.base / 'Foo..Bar.db')

    def test_the_base_itself_is_allowed(self):
        self.assertEqual(safe_join(self.base, '.'), self.base)


class SplitYearSuffixTests(SimpleTestCase):
    """Replaces the regex r'\\s*\\((\\d{4})\\)\\s*$' whose `\\s*` ends were quadratic on long
    whitespace runs; the behaviour has to stay identical."""

    def test_suffix_is_split_off(self):
        self.assertEqual(split_year_suffix('Corolla Cross LE, FWD (2023)'),
                         ('Corolla Cross LE, FWD', 2023))

    def test_whitespace_around_the_suffix_is_dropped(self):
        self.assertEqual(split_year_suffix('Corolla   (2023)  \t'), ('Corolla', 2023))

    def test_no_suffix_returns_the_input_unchanged(self):
        self.assertEqual(split_year_suffix('Corolla Cross'), ('Corolla Cross', None))

    def test_only_a_trailing_four_digit_year_counts(self):
        self.assertEqual(split_year_suffix('Corolla (2023) LE'), ('Corolla (2023) LE', None))
        self.assertEqual(split_year_suffix('Corolla (23)'), ('Corolla (23)', None))
        self.assertEqual(split_year_suffix('Corolla (20234)'), ('Corolla (20234)', None))

    def test_long_whitespace_runs_are_linear(self):
        import time
        s = 'Corolla' + ' ' * 200_000 + 'x'
        t = time.perf_counter()
        self.assertEqual(split_year_suffix(s), (s, None))
        self.assertLess(time.perf_counter() - t, 1.0)
