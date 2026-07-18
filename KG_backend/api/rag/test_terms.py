"""Tests for the bilingual terminology store (api/rag/terms.py).

Covers: display-form cleaning (ZWNJ preserved, Arabic chars unified), noise-
prefix stripping, legacy import parsing + idempotency, upsert precedence,
artifact export (Book1.csv parseable by glossary._parse_csv; display JSON
shape), and an end-to-end glossary.expand() regression over a regenerated CSV.
"""
import csv
import json
import sqlite3
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from . import config, glossary, terms

ZWNJ = '‌'


def _mem_store():
    con = sqlite3.connect(':memory:')
    terms.ensure_schema(con)
    return con


class CleaningTest(SimpleTestCase):
    def test_arabic_chars_unified_for_display(self):
        self.assertEqual(terms.clean_fa_display('كيسه هوا'), 'کیسه هوا')

    def test_double_spaces_collapsed(self):
        self.assertEqual(terms.clean_fa_display('تقویت‌کننده  گلگیر جلو (چپ)'),
                         'تقویت‌کننده گلگیر جلو (چپ)')

    def test_zwnj_preserved_in_display_but_stripped_in_norm(self):
        s = f'کمک{ZWNJ}فنر'
        self.assertEqual(terms.clean_fa_display(s), s)
        self.assertNotIn(ZWNJ, terms.norm_fa(s))

    def test_edge_zwnj_and_space_trimmed(self):
        s = f'{ZWNJ} لنت ترمز {ZWNJ}'
        self.assertEqual(terms.clean_fa_display(s), 'لنت ترمز')

    def test_strip_noise_prefixes(self):
        cases = [
            ('standard part BOLT, SERRATION', 'BOLT, SERRATION'),
            ('standard partBOLT(FOR CYLINDER HEAD COVER)', 'BOLT(FOR CYLINDER HEAD COVER)'),
            ('standard part( BOLT, FLANGE)', 'BOLT, FLANGE'),
            ('SUPPORT, RADIATOR, LOWER', 'SUPPORT, RADIATOR, LOWER'),
        ]
        for raw, want in cases:
            got, _ = terms.strip_noise_prefixes(raw)
            self.assertEqual(got, want, raw)

    def test_header_artifact_detected(self):
        self.assertTrue(terms._is_header_artifact('english', 'فارسی'))
        self.assertFalse(terms._is_header_artifact('BOLT', 'پیچ'))

    def test_strip_noise_fa(self):
        self.assertEqual(terms.strip_noise_fa('قطعه استاندارد پیچ فلنجی'), 'پیچ فلنجی')
        self.assertEqual(terms.strip_noise_fa('پیچ فلنجی'), 'پیچ فلنجی')
        # kept whole if the prefix is the entire value
        self.assertEqual(terms.strip_noise_fa('قطعه استاندارد '), 'قطعه استاندارد')


class ImportTest(SimpleTestCase):
    SQL = (
        'BEGIN TRANSACTION;\n'
        'CREATE TABLE IF NOT EXISTS "Book1" ("field1" TEXT, "field2" TEXT);\n'
        "INSERT INTO \"Book1\" VALUES ('english','فارسی');\n"
        "INSERT INTO \"Book1\" VALUES ('SUPPORT, RADIATOR, LOWER','سینی زیر سپر جلو');\n"
        "INSERT INTO \"Book1\" VALUES ('DRIVER''S SEAT','صندلی راننده');\n"
        "INSERT INTO \"Book1\" VALUES ('standard part BOLT, SERRATION','پیچ  دندانه‌دار');\n"
        'COMMIT;\n'
    )

    def test_sql_parse_escapes_and_header(self):
        con = _mem_store()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'translation.sql'
            p.write_text(self.SQL, encoding='utf-8')
            stats = terms.import_translation_sql(con, p)
        self.assertEqual(stats['rows'], 4)
        self.assertEqual(stats['header_dropped'], 1)
        self.assertEqual(stats['inserted'], 3)
        self.assertEqual(stats['prefix_stripped'], 1)
        row = con.execute("SELECT en, fa FROM terms WHERE en LIKE 'DRIVER%'").fetchone()
        self.assertEqual(row[0], "DRIVER'S SEAT")
        # double space collapsed, prefix stripped
        row = con.execute("SELECT en, fa FROM terms WHERE en_norm LIKE 'bolt%'").fetchone()
        self.assertEqual(row[0], 'BOLT, SERRATION')
        self.assertEqual(row[1], 'پیچ دندانه‌دار')

    def test_import_idempotent(self):
        con = _mem_store()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'translation.sql'
            p.write_text(self.SQL, encoding='utf-8')
            terms.import_translation_sql(con, p)
            n1 = con.execute('SELECT COUNT(*) FROM terms').fetchone()[0]
            terms.import_translation_sql(con, p)
            n2 = con.execute('SELECT COUNT(*) FROM terms').fetchone()[0]
        self.assertEqual(n1, n2)

    def test_csv_import(self):
        con = _mem_store()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'Book1.csv'
            p.write_text('english,فارسی\nBRAKE PAD,لنت ترمز\n', encoding='utf-8-sig')
            stats = terms.import_book1_csv(con, p, source='curated')
        self.assertEqual(stats['inserted'], 1)
        self.assertEqual(stats['header_dropped'], 1)
        row = con.execute('SELECT source, confidence FROM terms').fetchone()
        self.assertEqual(row, ('curated', 1.0))


class UpsertTest(SimpleTestCase):
    def test_generated_never_downgrades_curated(self):
        con = _mem_store()
        terms.upsert_term(con, 'BRAKE PAD', 'لنت ترمز', source='curated')
        r = terms.upsert_term(con, 'brake pad', 'لنت ترمز', source='generated',
                              confidence=0.6)
        self.assertEqual(r, 'kept')
        row = con.execute('SELECT en, source, confidence FROM terms').fetchone()
        self.assertEqual(row, ('BRAKE PAD', 'curated', 1.0))

    def test_reviewed_updates_generated(self):
        con = _mem_store()
        terms.upsert_term(con, 'INVERTER', 'اینورتر', source='generated',
                          confidence=0.7, status='pending_review')
        r = terms.upsert_term(con, 'INVERTER', 'اینورتر', source='reviewed',
                              confidence=1.0)
        self.assertEqual(r, 'updated')
        row = con.execute('SELECT source, confidence, status FROM terms').fetchone()
        self.assertEqual(row, ('reviewed', 1.0, 'active'))

    def test_multiple_fa_per_en_all_kept(self):
        con = _mem_store()
        terms.upsert_term(con, 'Wheel Alignment', 'میزان کردن چرخ', source='curated')
        terms.upsert_term(con, 'Wheel Alignment', 'تنظیمات چرخ', source='curated')
        n = con.execute('SELECT COUNT(*) FROM terms').fetchone()[0]
        self.assertEqual(n, 2)


class ExportTest(SimpleTestCase):
    def _store(self):
        con = _mem_store()
        terms.upsert_term(con, 'BRAKE PAD', 'لنت ترمز', source='curated')
        terms.upsert_term(con, 'Water Pump', 'واتر پمپ', source='curated')
        terms.upsert_term(con, 'Oxygen Sensor', 'سنسور اکسیژن', source='generated',
                          confidence=0.9)
        terms.upsert_term(con, 'Oxygen Sensor', 'حسگر اکسیژن', source='generated',
                          confidence=0.7)
        terms.upsert_term(con, 'Hidden Term', 'مخفی برای نمایش', source='generated',
                          confidence=0.5, status='pending_review')
        con.execute("UPDATE terms SET use_query=0 WHERE en='Water Pump'")
        con.commit()
        return con

    def test_book1_export_parseable_and_filtered(self):
        con = self._store()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'Book1.csv'
            n = terms.export_book1(con, p)
            self.assertTrue(p.exists())
            rows = list(csv.reader(open(p, encoding='utf-8-sig')))
        ens = {r[0] for r in rows}
        self.assertIn('BRAKE PAD', ens)
        self.assertNotIn('Water Pump', ens)          # use_query=0
        self.assertNotIn('Hidden Term', ens)         # pending_review
        self.assertEqual(n, len(rows))
        # glossary must be able to parse the artifact
        with tempfile.TemporaryDirectory() as d2:
            p2 = Path(d2) / 'Book1.csv'
            terms.export_book1(con, p2)
            data = glossary._parse_csv(p2)
        self.assertIn('لنت ترمز', data)
        self.assertEqual(set(data['لنت ترمز'].split()), {'brake', 'pad'})

    def test_display_json_shape_and_best_pick(self):
        con = self._store()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'terms_en_fa.json'
            n = terms.export_display_json(con, p)
            payload = json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual(payload['version'], 1)
        self.assertEqual(payload['count'], n)
        entries = dict((e[0].lower(), e[1]) for e in payload['entries'])
        # one best fa per en: higher confidence wins between the two generated
        self.assertEqual(entries['oxygen sensor'], 'سنسور اکسیژن')
        self.assertNotIn('hidden term', entries)     # pending_review excluded
        self.assertIn('واتر پمپ'.split()[0], entries['water pump'])  # use_display honoured
        self.assertTrue(all(isinstance(t, str) for t in payload['fa_terms']))
        # entries sorted longest-first so greedy matchers can rely on order
        lens = [len(e[0]) for e in payload['entries']]
        self.assertEqual(lens, sorted(lens, reverse=True))

    def test_display_quality_gates(self):
        con = _mem_store()
        terms.upsert_term(con, 'Bar', 'میله، شمش، میله گرد', source='curated')
        terms.upsert_term(con, 'FAN', 'پره فن رادیاتور', source='curated')
        terms.upsert_term(con, 'Nut', 'مهره', source='curated')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 't.json'
            terms.export_display_json(con, p)
            entries = dict((e[0].lower(), e[1])
                           for e in json.loads(p.read_text(encoding='utf-8'))['entries'])
        self.assertEqual(entries.get('bar'), 'میله')       # first alternative only
        self.assertNotIn('fan', entries)                   # 1-word EN -> 3-word FA excluded
        self.assertEqual(entries.get('nut'), 'مهره')
        # query side unaffected: all three still present in Book1 export
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'Book1.csv'
            n = terms.export_book1(con, p)
        self.assertEqual(n, 3)


class ServiceSeedTest(SimpleTestCase):
    def test_seed_idempotent_and_display_only(self):
        con = _mem_store()
        s1 = terms.seed_service_pairs(con)
        self.assertGreater(s1['inserted'], 100)
        s2 = terms.seed_service_pairs(con)
        self.assertEqual(s2['inserted'], 0)
        # display artifact carries them; Book1.csv does not (query side is
        # served by glossary.GLOSSARY, keeping the CSV a pure parts dictionary)
        with tempfile.TemporaryDirectory() as d:
            j = Path(d) / 't.json'
            terms.export_display_json(con, j)
            entries = dict((e[0].lower(), e[1])
                           for e in json.loads(j.read_text(encoding='utf-8'))['entries'])
            b = Path(d) / 'Book1.csv'
            n_csv = terms.export_book1(con, b)
        self.assertEqual(entries.get('removal'), 'باز کردن')
        self.assertEqual(entries.get('procedure'), 'رویه')
        self.assertEqual(n_csv, 0)


class GlossaryRoundTripTest(SimpleTestCase):
    """End-to-end: a store-exported CSV drives glossary.expand() exactly like a
    hand-maintained Book1.csv would (the hot-reload contract)."""

    def setUp(self):
        self._old_csv = config.PARTS_CSV
        self._old_cache = dict(glossary._CSV_CACHE)
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        config.PARTS_CSV = self._old_csv
        glossary._CSV_CACHE.update(self._old_cache)
        self._tmp.cleanup()

    def test_expand_over_regenerated_csv(self):
        con = _mem_store()
        terms.upsert_term(con, 'RADIATOR GRILLE MOULDING', 'زه جلو پنجره', source='curated')
        terms.upsert_term(con, 'BRAKE PAD KIT', 'لنت ترمز جلو', source='curated')
        p = Path(self._tmp.name) / 'Book1.csv'
        terms.export_book1(con, p)
        config.PARTS_CSV = p
        glossary._CSV_CACHE.update(mtime=None, data={}, tokens={})
        got, matched = glossary.expand('قیمت زه جلو پنجره ماشین')
        self.assertIn('grille', matched)
        self.assertIn('radiator', matched)
        got2, matched2 = glossary.expand('لنت ترمز جلو را چطور عوض کنم؟')
        self.assertIn('pad', matched2)
