"""Deterministic helpers of the KG-Reranker training commands (#22, step 2).

They arrived with 536ac91 untested. None of this needs torch, a model or the
index: template coverage, gold-set exclusion, passage formatting and the
listwise grouping the trainer depends on.
"""
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from api.evalsuite import goldset
from api.management.commands import build_reranker_trainset as brt
from api.management.commands import train_kg_reranker as tkr


class TemplateTests(SimpleTestCase):
    def test_english_and_persian_cover_the_same_actions(self):
        self.assertEqual(set(brt.TRAIN_EN), set(brt.TRAIN_FA))

    def test_every_template_names_the_component(self):
        for table in (brt.TRAIN_EN, brt.TRAIN_FA):
            for action, tpls in table.items():
                self.assertTrue(tpls, action)
                for t in tpls:
                    self.assertIn('{c}', t, (action, t))
                    self.assertEqual(t.format(c='X').count('X'), 1)

    def test_training_wording_never_repeats_the_evaluation_wording(self):
        """Templates must differ from the gold-set ones, or the evaluation
        measures memorised phrasing rather than generalisation."""
        for action, tpls in brt.TRAIN_EN.items():
            if action in goldset.ACTIONS_EN:
                self.assertNotIn(goldset.ACTIONS_EN[action], tpls, action)
        for action, tpls in brt.TRAIN_FA.items():
            if action in goldset.ACTIONS_FA:
                self.assertNotIn(goldset.ACTIONS_FA[action], tpls, action)


class PassageTests(SimpleTestCase):
    def test_title_then_body_capped_at_800(self):
        out = brt.passage('Brake Fluid', 'x' * 2000)
        title, body = out.split('\n', 1)
        self.assertEqual(title, 'Brake Fluid')
        self.assertEqual(len(body), 800)

    def test_missing_parts_are_empty_not_none(self):
        self.assertEqual(brt.passage(None, None), '\n')


class GoldExclusionTests(SimpleTestCase):
    def test_collects_blobs_components_and_topic_keys_from_every_set(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'a.jsonl').write_text('\n'.join(json.dumps(r) for r in [
                {'expected_blob_ids': [1, '2'], 'component': 'Front Drive Shaft (2023)',
                 'topic_key': 'axle|front drive shaft|removal'},
                {'expected_blob_ids': [], 'component': ''},
            ]) + '\n', encoding='utf-8')
            Path(d, 'b.jsonl').write_text(json.dumps(
                {'expected_blob_ids': [3], 'topic_key': 'k2'}) + '\n', encoding='utf-8')
            Path(d, 'ignored.txt').write_text('{"expected_blob_ids": [99]}', encoding='utf-8')
            blobs, comps, keys = brt._gold_exclusions(d)
        self.assertEqual(blobs, {1, 2, 3})
        self.assertEqual(comps, {goldset.norm_en('Front Drive Shaft (2023)')})
        self.assertEqual(keys, {'axle|front drive shaft|removal', 'k2'})


class GroupTests(SimpleTestCase):
    def row(self, q, label, topic='t', source='mined'):
        return {'query': q, 'topic_key': topic, 'label': label, 'source': source}

    def test_listwise_groups_need_a_positive_and_a_negative(self):
        rows = [self.row('q1', 1.0), self.row('q1', 0.0), self.row('q1', 0.2),
                self.row('q2', 1.0),                       # no negative: dropped
                self.row('q3', 0.0),                       # no positive: dropped
                self.row('q4', 1.0, source='user_feedback')]
        groups, singles = tkr._groups(rows)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(g['key'], ('q1', 't'))
        self.assertEqual(g['topic'], 't')
        self.assertEqual(g['pos']['label'], 1.0)
        self.assertEqual(len(g['neg']), 2)
        self.assertEqual(singles, [rows[-1]])

    def test_same_query_on_two_topics_is_two_groups(self):
        rows = [self.row('q', 1.0, 'a'), self.row('q', 0.0, 'a'),
                self.row('q', 1.0, 'b'), self.row('q', 0.0, 'b')]
        groups, _ = tkr._groups(rows)
        self.assertEqual({g['topic'] for g in groups}, {'a', 'b'})
