"""QA audit: assistant structured lookups (api/assist_lookup.py).

The chat layer calls :func:`lookups` for a pinned car; it answers part-number
questions from the parts catalog and special-tool questions from the car's SST
pages. These tests build tiny real SQLite warehouses in a temp dir (a parts DB
with a ``part_rows`` table and a manual DB with SST leaf pages) and exercise:

  * question classification (PARTS_Q / TOOL_Q), Persian + English;
  * normalisation (zero-width chars, Arabic ي/ك, case) and stop-word removal;
  * matching (every content word must appear), dedupe, 5-5 PN formatting,
    the row limit, and per-user catalog authorization (other tenants get none);
  * SST ranking (systems named by manual hits before Persian job-word hints),
    the limit, and the never-raises contract of ``lookups``.
"""
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

from api import assist_lookup as AL
from api import cardb
from api.models import Car, Company, CompanyCarAccess, PortalUser, UserCarAccess

MANUAL = 'Camry LE'
PARTS = 'Camry LE (Parts 2021)'
BROKEN = 'Broken LE'
BROKEN_PARTS = 'Broken LE (Parts 2021)'


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
class ClassifierTests(SimpleTestCase):

    def test_parts_questions_detected(self):
        for q in ('شماره فنی لنت ترمز چیه؟', 'شماره قطعه فیلتر روغن', 'شمارهپارت',
                  'پارت نامبر کمک فنر', 'کد قطعه', 'Part number of oil filter',
                  'PART NO for pad', 'part # wiper', 'P/N of belt', 'pn for belt'):
            self.assertIsNotNone(AL.PARTS_Q.search(q), q)

    def test_non_parts_questions_not_detected(self):
        for q in ('چطور لنت ترمز را تعویض کنم', 'torque spec for caliper',
                  'spin the wheel', 'what is the opinion', 'part of the engine',
                  'شماره سریال موتور', ''):
            self.assertIsNone(AL.PARTS_Q.search(q), q)

    def test_tool_questions_detected(self):
        for q in ('ابزار مخصوص تعویض لنت', 'کدام ابزارها لازم است', 'SST for brake',
                  'which sst', 'special tool for caliper', 'Special Service Tool list'):
            self.assertIsNotNone(AL.TOOL_Q.search(q), q)

    def test_non_tool_questions_not_detected(self):
        for q in ('which tool', 'tools needed', 'SSTs', 'service manual', 'specialist'):
            self.assertIsNone(AL.TOOL_Q.search(q), q)


class NormaliseTests(SimpleTestCase):

    def test_zero_width_and_bidi_marks_become_spaces(self):
        self.assertEqual(AL._norm('لنت‌ترمز'), 'لنت ترمز')
        self.assertEqual(AL._norm('‏abc‎DEF'), ' abc def')

    def test_arabic_letters_map_to_persian(self):
        self.assertEqual(AL._norm('كمك فنر يك'), 'کمک فنر یک')

    def test_none_and_empty(self):
        self.assertEqual(AL._norm(None), '')
        self.assertEqual(AL._terms(None), [])
        self.assertEqual(AL._terms(''), [])

    def test_terms_drop_stop_words_punctuation_and_single_chars(self):
        self.assertEqual(AL._terms('شماره فنی لنت ترمز برای این خودرو چیست؟'), ['لنت', 'ترمز'])
        self.assertEqual(AL._terms('What is the part number for the FRONT brake pad, x?'),
                         ['front', 'brake', 'pad'])

    def test_terms_split_on_zero_width_joiner(self):
        self.assertEqual(AL._terms('لنت‌ترمز'), ['لنت', 'ترمز'])

    def test_only_framing_words_leaves_nothing(self):
        self.assertEqual(AL._terms('شماره فنی قطعه چیه؟ part number pn'), [])

    def test_zwnj_spelled_stop_word_is_removed(self):
        # Regression (fixed in this change): assist_lookup.py:22 lists 'می‌خواهم' (with ZWNJ) as a stop word, but _norm (line 38) turns ZWNJ into a space first, so 'می'/'خواهم' leak into the required terms.
        self.assertEqual(AL._terms('شماره فنی لنت می‌خواهم'), ['لنت'])


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------
def _parts_db(path, rows, broken=False):
    con = sqlite3.connect(path)
    if broken:
        con.execute('CREATE TABLE meta (k TEXT)')
    else:
        con.execute('CREATE TABLE part_rows (id INTEGER PRIMARY KEY, pn_display TEXT, '
                    'name_en TEXT, name_fa TEXT, qty_display TEXT, date_range TEXT)')
        con.executemany('INSERT INTO part_rows (pn_display, name_en, name_fa, qty_display, '
                        'date_range) VALUES (?,?,?,?,?)', rows)
    con.commit()
    con.close()


PART_ROWS = [
    ('0446502390', 'PAD KIT, DISC BRAKE, FRONT', 'لنت ترمز جلو', '1', ''),
    ('0446502390', 'PAD KIT, DISC BRAKE, FRONT', 'لنت ترمز جلو', '1', ''),       # dup
    ('0446502390', 'PAD KIT, DISC BRAKE, FRONT', 'لنت ترمز جلو', '1', '2022-'),  # other window
    ('04466-02140', 'PAD KIT, DISC BRAKE, REAR', 'لنت ترمز عقب', '1', ''),
    ('90915YZZD1', 'FILTER, OIL', 'فیلتر روغن', '1', ''),
    ('4851009X00', 'ABSORBER, SHOCK', 'كمك فنر', '2', ''),         # Arabic kaf in source data
    (None, 'PIPE, BRAKE', None, '', ''),
] + [(f'90119{i:05d}', f'BOLT, FLANGE {i}', 'پیچ', '1', '') for i in range(12)]


def _sst_page(rows):
    tr = ''.join(f'<tr><td><img src="img/{n}.png"></td><td>{n}</td><td>{name}</td>'
                 f'<td></td></tr>' for n, name in rows)
    return f'<table><tr><th>a</th><th>b</th><th>c</th><th>d</th></tr>{tr}</table>'


def _manual_db(path, stem):
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE nodes (id INTEGER PRIMARY KEY, path TEXT, title TEXT, '
                'node_type TEXT, content TEXT)')
    rd = f'{stem}/Repair and Diagnosis'
    pages = [
        (f'{rd}/Brake/Brake (Front)/SST [01⁄2021 - ]/SST [01⁄2021 - ]',
         [('09709-29018', 'Brake Caliper Tool'), ('(09709-29019)', 'Caliper Adapter')]),
        (f'{rd}/Engine/Engine Mechanical/SST/SST',
         [('09223-15030', 'Oil Seal Replacer')]),
        (f'{rd}/General/Maintenance/SST/SST',
         [('09999-00001', 'Disc Brake Piston Spreader')]),
        (f'{rd}/Drivetrain/Transaxle/SST/SST',
         [('09950-60010', 'Replacer Set')]),
        (f'{rd}/Steering/Steering Column/SST/SST',
         [('09612-00012', 'Steering Wheel Puller')]),
    ]
    for p, rows in pages:
        con.execute('INSERT INTO nodes (path, title, node_type, content) VALUES (?,?,?,?)',
                    (p, p.rsplit('/', 1)[-1], 'leaf', _sst_page(rows)))
    con.execute("INSERT INTO nodes (path, title, node_type, content) VALUES "
                "(?, 'Brake', 'folder', '')", (f'{rd}/Brake',))
    con.commit()
    con.close()


class _Warehouse(TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='kg_qa_assist_'))
        cls.parts_dir = cls.tmp / 'parts'
        cls.parts_dir.mkdir()
        _parts_db(cls.parts_dir / f'{PARTS}.db', PART_ROWS)
        _parts_db(cls.parts_dir / f'{BROKEN_PARTS}.db', [], broken=True)
        cls.manual_db = cls.tmp / 'camry_le.db'
        _manual_db(cls.manual_db, MANUAL)
        cls._ovr = override_settings(KG_PARTS_DIR=str(cls.parts_dir))
        cls._ovr.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._ovr.disable()
        cardb.invalidate_ready_cache()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        cardb.invalidate_ready_cache()
        self.addCleanup(cardb.invalidate_ready_cache)
        self.manual = Car.objects.create(brand_name='Toyota', car_name=MANUAL, year=2021,
                                         db_address=str(self.manual_db))
        self.pcar = Car.objects.create(brand_name='Toyota', car_name=PARTS, year=2021,
                                       db_address='')
        self.broken = Car.objects.create(brand_name='Toyota', car_name=BROKEN, year=2021,
                                         db_address=str(self.tmp / 'missing.db'))
        self.bpcar = Car.objects.create(brand_name='Toyota', car_name=BROKEN_PARTS, year=2021,
                                        db_address='')
        self.co = Company.objects.create(name='QA-Assist-Co')
        self.co2 = Company.objects.create(name='QA-Assist-Other')
        for car in (self.pcar, self.bpcar):
            CompanyCarAccess.objects.create(company=self.co, car=car, documents=[])
        self.alice = self.mk(self.co, 'qa_al_alice', {self.pcar: ['parts'], self.bpcar: []})
        self.manual_only = self.mk(self.co, 'qa_al_manual', {self.pcar: ['manual']})
        self.nogrant = self.mk(self.co, 'qa_al_nogrant', {})
        # Other tenant: a stray per-user row, but its company never bought the car.
        self.mallory = self.mk(self.co2, 'qa_al_mallory', {self.pcar: ['parts']})

    @staticmethod
    def mk(company, username, grants):
        u = PortalUser.objects.create(company=company, username=username,
                                      role='after_sales_specialist')
        for car, docs in grants.items():
            UserCarAccess.objects.create(user=u, car=car, documents=docs)
        return u


# ---------------------------------------------------------------------------
# parts_rows
# ---------------------------------------------------------------------------
class PartsRowsTests(_Warehouse):

    def pns(self, rows):
        return [(r['pn'], r['date_range']) for r in rows]

    def test_persian_question_matches_all_words_and_formats_pn(self):
        rows = AL.parts_rows(self.alice, self.manual, 'شماره فنی لنت ترمز جلو چیه؟')
        self.assertEqual(self.pns(rows), [('04465-02390', ''), ('04465-02390', '2022-')])
        self.assertEqual(rows[0]['catalog'], PARTS)
        self.assertEqual(rows[0]['name_fa'], 'لنت ترمز جلو')
        self.assertEqual(rows[0]['qty'], '1')

    def test_english_question_is_case_insensitive(self):
        rows = AL.parts_rows(self.alice, self.manual, 'Part number for the REAR brake PAD')
        self.assertEqual(self.pns(rows), [('04466-02140', '')])     # already dashed: kept

    def test_every_content_word_is_required(self):
        both = AL.parts_rows(self.alice, self.manual, 'شماره فنی لنت ترمز')
        self.assertEqual(len(both), 3)                              # front x2 windows + rear
        self.assertEqual(AL.parts_rows(self.alice, self.manual, 'شماره فنی لنت موتور'), [])

    def test_zero_width_joined_words_still_match(self):
        rows = AL.parts_rows(self.alice, self.manual, 'شماره فنی لنت‌ترمز عقب')
        self.assertEqual(self.pns(rows), [('04466-02140', '')])

    def test_non_ten_digit_pn_is_not_reformatted(self):
        rows = AL.parts_rows(self.alice, self.manual, 'part number oil filter')
        self.assertEqual(self.pns(rows), [('90915YZZD1', '')])

    def test_null_pn_and_persian_name_are_safe(self):
        rows = AL.parts_rows(self.alice, self.manual, 'part number brake pipe')
        self.assertEqual(rows, [{'pn': '', 'name_en': 'PIPE, BRAKE', 'name_fa': None,
                                 'qty': '', 'date_range': '', 'catalog': PARTS}])

    def test_limit_default_and_explicit(self):
        self.assertEqual(len(AL.parts_rows(self.alice, self.manual, 'part number bolt')), 8)
        self.assertEqual(len(AL.parts_rows(self.alice, self.manual, 'part number bolt',
                                           limit=3)), 3)
        self.assertEqual(len(AL.parts_rows(self.alice, self.manual, 'part number bolt',
                                           limit=50)), 12)

    def test_framing_only_question_returns_nothing(self):
        self.assertEqual(AL.parts_rows(self.alice, self.manual, 'شماره فنی قطعه چیه؟'), [])

    def test_no_match_returns_empty(self):
        self.assertEqual(AL.parts_rows(self.alice, self.manual, 'part number turbocharger'), [])

    def test_user_without_parts_layer_gets_nothing(self):
        self.assertEqual(AL.parts_rows(self.manual_only, self.manual, 'part number oil filter'), [])
        self.assertEqual(AL.parts_rows(self.nogrant, self.manual, 'part number oil filter'), [])

    def test_other_tenant_gets_nothing(self):
        self.assertEqual(AL.parts_rows(self.mallory, self.manual, 'part number oil filter'), [])

    def test_arabic_letters_in_query_are_normalised(self):
        # 'فيلتر' typed with Arabic ye still finds the Persian-spelled row.
        rows = AL.parts_rows(self.alice, self.manual, 'شماره فنی فيلتر روغن')
        self.assertEqual(self.pns(rows), [('90915YZZD1', '')])

    def test_arabic_letters_in_catalog_name_are_normalised(self):
        # Regression (fixed in this change): assist_lookup.py:66-68 pre-filters with SQL LIKE on the raw name_fa using the normalised first term, so a catalog name stored with Arabic ك (e.g. 'كمك فنر') never reaches the Python-side _norm comparison at line 69.
        rows = AL.parts_rows(self.alice, self.manual, 'شماره فنی کمک فنر')
        self.assertEqual(self.pns(rows), [('4851009X00', '')])

    def test_polite_persian_question_with_zwnj_verb_matches(self):
        # Regression (fixed in this change): 'می‌خواهم' is not removed as a stop word (assist_lookup.py:22 vs :38), so a natural "I want the part number of the front brake pad" question finds nothing.
        rows = AL.parts_rows(self.alice, self.manual, 'شماره فنی لنت ترمز جلو را می‌خواهم')
        self.assertEqual(len(rows), 2)


# ---------------------------------------------------------------------------
# sst_tools
# ---------------------------------------------------------------------------
class SstToolsTests(_Warehouse):

    def numbers(self, tools):
        return [t['number'] for t in tools]

    def test_persian_job_word_hints_select_brake_tools_by_label_and_name(self):
        tools = AL.sst_tools(self.manual, 'ابزار مخصوص تعویض لنت', hits=None)
        self.assertEqual(sorted(self.numbers(tools)),
                         ['09709-29018', '09709-29019', '09999-00001'])
        spreader = next(t for t in tools if t['number'] == '09999-00001')
        self.assertEqual(spreader['used_in'], ['General › Maintenance'])   # matched by name
        comp = next(t for t in tools if t['number'] == '09709-29019')
        self.assertEqual(comp['kit_of'], '09709-29018')
        self.assertEqual(set(tools[0]), {'number', 'name', 'kit_of', 'used_in'})

    def test_systems_named_by_manual_hits_rank_before_hints(self):
        hits = [{'title_path': 'Camry LE › Repair and Diagnosis › Engine Mechanical'}]
        tools = AL.sst_tools(self.manual, 'ابزار لنت', hits)
        self.assertEqual(tools[0]['number'], '09223-15030')
        self.assertEqual(set(self.numbers(tools[1:])),
                         {'09709-29018', '09709-29019', '09999-00001'})

    def test_section_root_segment_alone_selects_nothing(self):
        hits = [{'title_path': 'Camry LE › Repair and Diagnosis'}]
        self.assertEqual(AL.sst_tools(self.manual, 'SST', hits), [])

    def test_only_top_five_hits_are_considered(self):
        filler = [{'title_path': 'Camry LE › Nothing'}] * 5
        hits = filler + [{'title_path': 'Camry LE › Engine Mechanical'}]
        self.assertEqual(AL.sst_tools(self.manual, 'SST', hits), [])

    def test_hits_without_title_path_are_tolerated(self):
        hits = [{'title_path': 'Camry LE › Steering Column'}, {'title_path': None}, {}]
        self.assertEqual(self.numbers(AL.sst_tools(self.manual, 'SST', hits)), ['09612-00012'])

    def test_limit(self):
        tools = AL.sst_tools(self.manual, 'ابزار لنت', None, limit=1)
        self.assertEqual(len(tools), 1)

    def test_unrelated_question_returns_nothing(self):
        self.assertEqual(AL.sst_tools(self.manual, 'special tool for the radio', []), [])

    def test_car_without_database_returns_nothing(self):
        self.assertEqual(AL.sst_tools(self.broken, 'ابزار لنت', None), [])

    def test_wheel_hint_does_not_pull_in_transaxle_tools(self):
        # Regression (fixed in this change): assist_lookup.py:111 substring-matches hints, so 'چرخ' (wheel) -> 'axle' matches the 'Transaxle' system and returns gearbox tools for a wheel question.
        tools = AL.sst_tools(self.manual, 'ابزار مخصوص چرخ', None)
        self.assertNotIn('09950-60010', self.numbers(tools))


# ---------------------------------------------------------------------------
# lookups (the entry point used by /api/assist)
# ---------------------------------------------------------------------------
class LookupsTests(_Warehouse):

    EMPTY = {'parts': [], 'sst_tools': []}

    def test_no_pinned_car_or_unknown_car(self):
        self.assertEqual(AL.lookups(self.alice, '', 'part number oil filter', []), self.EMPTY)
        self.assertEqual(AL.lookups(self.alice, None, 'part number oil filter', []), self.EMPTY)
        self.assertEqual(AL.lookups(self.alice, 'No Such Car', 'part number oil filter', []),
                         self.EMPTY)

    def test_plain_question_triggers_no_lookup(self):
        self.assertEqual(AL.lookups(self.alice, MANUAL, 'چطور لنت ترمز را تعویض کنم', []),
                         self.EMPTY)
        self.assertEqual(AL.lookups(self.alice, MANUAL, None, None), self.EMPTY)

    def test_parts_question(self):
        out = AL.lookups(self.alice, MANUAL, 'part number oil filter', [])
        self.assertEqual([r['pn'] for r in out['parts']], ['90915YZZD1'])
        self.assertEqual(out['sst_tools'], [])
        self.assertNotIn('error', out)

    def test_tool_question(self):
        out = AL.lookups(self.alice, MANUAL, 'ابزار مخصوص تعویض لنت', [])
        self.assertEqual(out['parts'], [])
        self.assertEqual(len(out['sst_tools']), 3)

    def test_combined_question_fills_both(self):
        out = AL.lookups(self.alice, MANUAL, 'شماره فنی و ابزار مخصوص لنت ترمز', [])
        self.assertEqual(len(out['parts']), 3)
        self.assertEqual(len(out['sst_tools']), 3)

    def test_other_tenant_gets_tools_of_manual_but_no_catalog_rows(self):
        out = AL.lookups(self.mallory, MANUAL, 'شماره فنی و ابزار مخصوص لنت ترمز', [])
        self.assertEqual(out['parts'], [])

    def test_broken_catalog_is_reported_not_raised(self):
        out = AL.lookups(self.alice, BROKEN, 'part number oil filter', [])
        self.assertEqual(out['parts'], [])
        self.assertIn('part_rows', out['error'])
        self.assertLessEqual(len(out['error']), 200)
