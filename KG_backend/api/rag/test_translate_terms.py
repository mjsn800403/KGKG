"""Tests for the QA-gated Metis translation pipeline (translate_terms).

The Metis client and the embedder are injected, so every gate is exercised
with a scripted fake — no network, no spend.
"""
import json
import sqlite3

from django.test import SimpleTestCase

from api.management.commands.translate_terms import (
    BudgetExhausted, parse_env_file, parse_json_array, run_translation,
)
from . import terms


def _store(queued):
    con = sqlite3.connect(':memory:')
    terms.ensure_schema(con)
    terms.upsert_term(con, 'BRAKE PAD', 'لنت ترمز', source='curated')
    terms.upsert_term(con, 'WATER PUMP', 'واتر پمپ', source='curated')
    for i, en in enumerate(queued):
        con.execute('INSERT INTO gen_queue(en, en_norm, freq) VALUES(?,?,?)',
                    (en, terms.norm_en(en), 100 - i))
    con.commit()
    return con


class FakeMetis:
    """Replays scripted replies; counts messages like the real client."""

    def __init__(self, replies, budget=None):
        self.replies = list(replies)
        self.budget = budget
        self.calls = 0
        self.sessions = 0

    def new_session(self, tag):
        self.sessions += 1
        return f's{self.sessions}'

    def send(self, sid, content):
        if self.budget is not None and self.calls >= self.budget:
            raise BudgetExhausted('budget reached')
        self.calls += 1
        if not self.replies:
            return '[]'
        return self.replies.pop(0)


def fake_encode_same(texts):
    return [[1.0, 0.0] for _ in texts]        # everything similar (cos=1)


def fake_encode_orthogonal(texts):
    # first call = originals, second = back-translations; force cos=0 by axis
    fake_encode_orthogonal.n += 1
    axis = [1.0, 0.0] if fake_encode_orthogonal.n % 2 == 1 else [0.0, 1.0]
    return [list(axis) for _ in texts]


def arr(pairs, k1='en', k2='fa'):
    return json.dumps([{k1: a, k2: b} for a, b in pairs], ensure_ascii=False)


class ParseTest(SimpleTestCase):
    def test_strict_shapes(self):
        good = arr([('OIL PAN', 'کارتل روغن')])
        self.assertEqual(parse_json_array(good, 1, 'en', 'fa'),
                         [('OIL PAN', 'کارتل روغن')])
        self.assertIsNone(parse_json_array('no json here', 1, 'en', 'fa'))
        self.assertIsNone(parse_json_array(good, 2, 'en', 'fa'))      # wrong count
        self.assertIsNone(parse_json_array('[{"x": 1}]', 1, 'en', 'fa'))

    def test_json_inside_prose(self):
        wrapped = f'Sure! Here is the JSON:\n{arr([("OIL PAN", "کارتل روغن")])}\nDone.'
        self.assertEqual(parse_json_array(wrapped, 1, 'en', 'fa'),
                         [('OIL PAN', 'کارتل روغن')])


class RunTest(SimpleTestCase):
    def test_agreement_and_backtrans_accept(self):
        con = _store(['OIL PAN'])
        fake = FakeMetis([
            arr([('OIL PAN', 'کارتل روغن')]),          # sample 1
            arr([('OIL PAN', 'کارتل روغن')]),          # sample 2 (agrees)
            arr([('کارتل روغن', 'oil pan')], 'fa', 'en'),  # back-translation
        ])
        stats = run_translation(con, fake, fake_encode_same,
                                dict(batch_size=5), out=lambda s: None)
        self.assertEqual(stats['accepted'], 1)
        row = con.execute("SELECT fa, source, status, confidence FROM terms "
                          "WHERE en='OIL PAN'").fetchone()
        self.assertEqual(row[0], 'کارتل روغن')
        self.assertEqual(row[1], 'generated')
        self.assertEqual(row[2], 'active')
        self.assertGreaterEqual(row[3], 0.9)
        state = con.execute("SELECT state FROM gen_queue").fetchone()[0]
        self.assertEqual(state, 'accepted')

    def test_disagreement_third_sample_majority(self):
        con = _store(['OIL PAN'])
        fake = FakeMetis([
            arr([('OIL PAN', 'کارتل روغن')]),           # sample 1
            arr([('OIL PAN', 'سینی روغن')]),            # sample 2 (differs)
            arr([('OIL PAN', 'کارتل روغن')]),           # third sample -> majority
            arr([('کارتل روغن', 'oil pan')], 'fa', 'en'),
        ])
        stats = run_translation(con, fake, fake_encode_same,
                                dict(batch_size=5), out=lambda s: None)
        self.assertEqual(stats['accepted'], 1)
        conf = con.execute("SELECT confidence FROM terms WHERE en='OIL PAN'").fetchone()[0]
        self.assertLess(conf, 0.9)          # 0.5*0.66 + 0.5*1.0

    def test_no_majority_goes_to_review(self):
        con = _store(['OIL PAN'])
        fake = FakeMetis([
            arr([('OIL PAN', 'کارتل روغن')]),
            arr([('OIL PAN', 'سینی روغن')]),
            arr([('OIL PAN', 'تشتک روغن')]),            # three distinct -> no majority
        ])
        stats = run_translation(con, fake, fake_encode_same,
                                dict(batch_size=5), out=lambda s: None)
        self.assertEqual(stats['review'], 1)
        self.assertEqual(stats['accepted'], 0)
        status = con.execute("SELECT status FROM terms WHERE en='OIL PAN'").fetchone()[0]
        self.assertEqual(status, 'pending_review')

    def test_backtrans_gate_rejects(self):
        con = _store(['OIL PAN'])
        fake_encode_orthogonal.n = 0
        fake = FakeMetis([
            arr([('OIL PAN', 'کارتل روغن')]),
            arr([('OIL PAN', 'کارتل روغن')]),
            arr([('کارتل روغن', 'wrong thing')], 'fa', 'en'),
        ])
        stats = run_translation(con, fake, fake_encode_orthogonal,
                                dict(batch_size=5), out=lambda s: None)
        self.assertEqual(stats['review'], 1)
        self.assertEqual(stats['accepted'], 0)
        state = con.execute('SELECT state, backtrans_sim FROM gen_queue').fetchone()
        self.assertEqual(state[0], 'review')
        self.assertLess(state[1], 0.82)

    def test_parse_retry_then_success(self):
        con = _store(['OIL PAN'])
        fake = FakeMetis([
            'gibberish',                                 # sample 1, attempt 1
            arr([('OIL PAN', 'کارتل روغن')]),           # sample 1, re-ask
            arr([('OIL PAN', 'کارتل روغن')]),           # sample 2
            arr([('کارتل روغن', 'oil pan')], 'fa', 'en'),
        ])
        stats = run_translation(con, fake, fake_encode_same,
                                dict(batch_size=5), out=lambda s: None)
        self.assertEqual(stats['accepted'], 1)

    def test_budget_stops_cleanly_and_resumes(self):
        con = _store(['OIL PAN', 'DRAIN PLUG'])
        # budget lets only sample 1 through -> clean stop, nothing consumed
        fake = FakeMetis([arr([('OIL PAN', 'کارتل روغن'), ('DRAIN PLUG', 'پیچ تخلیه')])],
                         budget=1)
        stats = run_translation(con, fake, fake_encode_same,
                                dict(batch_size=5), out=lambda s: None)
        self.assertEqual(stats['accepted'], 0)
        queued = con.execute(
            "SELECT COUNT(*) FROM gen_queue WHERE state='queued'").fetchone()[0]
        self.assertEqual(queued, 2)          # still queued -> resumable
        # resume with full replies -> both processed
        fake2 = FakeMetis([
            arr([('OIL PAN', 'کارتل روغن'), ('DRAIN PLUG', 'پیچ تخلیه')]),
            arr([('OIL PAN', 'کارتل روغن'), ('DRAIN PLUG', 'پیچ تخلیه')]),
            arr([('کارتل روغن', 'oil pan'), ('پیچ تخلیه', 'drain plug')], 'fa', 'en'),
        ])
        stats2 = run_translation(con, fake2, fake_encode_same,
                                 dict(batch_size=5), out=lambda s: None)
        self.assertEqual(stats2['accepted'], 2)

    def test_pipeline_yield(self):
        con = _store(['OIL PAN'])
        fake = FakeMetis([])
        stats = run_translation(con, fake, fake_encode_same,
                                dict(batch_size=5, pipeline_check=lambda: True),
                                out=lambda s: None)
        self.assertEqual(stats['processed'], 0)
        queued = con.execute(
            "SELECT COUNT(*) FROM gen_queue WHERE state='queued'").fetchone()[0]
        self.assertEqual(queued, 1)


class EnvParseTest(SimpleTestCase):
    def test_parse_env_file(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / '.env'
            p.write_text('# comment\nMETIS_API_KEY="k123"\nMETIS_BOT_ID=b456\nX=1\n',
                         encoding='utf-8')
            env = parse_env_file(p)
        self.assertEqual(env['METIS_API_KEY'], 'k123')
        self.assertEqual(env['METIS_BOT_ID'], 'b456')
