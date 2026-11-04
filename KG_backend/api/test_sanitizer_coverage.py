"""Every model column that identifies a person is handled by the staging
sanitizer (#79).

ops/deploy/sanitize_staging_db.py masks MASK_COLUMNS and empties PURGE_TABLES;
its own audit only sees the tables of the copy it is run on. This walks the
Django models instead, so a new model with a phone or e-mail column fails CI
before it ever reaches a staging copy.
"""
import importlib.util
import pathlib

from django.apps import apps
from django.test import SimpleTestCase

SANITIZER = pathlib.Path(__file__).resolve().parents[2] / 'ops' / 'deploy' / 'sanitize_staging_db.py'


def _load():
    spec = importlib.util.spec_from_file_location('sanitize_staging_db', SANITIZER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _identifying(column):
    return (column in ('phone', 'email', 'password', 'password_hash', 'key_hash')
            or column.endswith('_phone') or column.endswith('_email'))


class SanitizerCoversModelsTests(SimpleTestCase):
    def setUp(self):
        self.assertTrue(SANITIZER.exists(), f'sanitizer not found at {SANITIZER}')
        self.san = _load()

    def test_every_identifying_column_is_masked_or_purged(self):
        purged = set(self.san.PURGE_TABLES)
        missing = []
        for model in apps.get_models():
            table = model._meta.db_table
            if table in purged:
                continue
            handled = set(self.san.MASK_COLUMNS.get(table, {}).values())
            for field in model._meta.concrete_fields:
                if _identifying(field.column) and field.column not in handled:
                    missing.append(f'{table}.{field.column}')
        self.assertFalse(missing, f'add these to MASK_COLUMNS or PURGE_TABLES in {SANITIZER.name}: {missing}')

    def test_support_chat_contact_fields_are_masked(self):
        cols = self.san.MASK_COLUMNS['api_supportthread']
        self.assertEqual(cols[self.san.MASK_PHONE], 'contact_phone')
        self.assertEqual(cols[self.san.MASK_EMAIL], 'contact_email')
        self.assertEqual(cols[self.san.MASK_NAME], 'contact_name')
        self.assertEqual(self.san.MASK_COLUMNS['api_supportmessage'][self.san.MASK_TEXT], 'body')

    def test_masked_columns_exist_on_the_models(self):
        """A renamed column would make the sanitizer skip it silently."""
        by_table = {m._meta.db_table: {f.column for f in m._meta.concrete_fields}
                    for m in apps.get_models()}
        stale = [f'{t}.{c}' for t, intents in self.san.MASK_COLUMNS.items()
                 if t in by_table for c in intents.values() if c not in by_table[t]]
        self.assertFalse(stale, stale)
