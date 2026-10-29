"""Build the training set for KG-Reranker, our domain-adapted cross-encoder.

    python manage.py build_reranker_trainset --topics 2500 --out <dir>

The general-purpose reranker (bge-reranker-v2-m3) was trained on web text. It
has never seen a Toyota repair manual, where pages differ by one word ("Front
Drive Shaft Assembly > Removal" vs "> Installation") and the question is often
Persian while the page is English. This command mines training examples from
our own warehouse:

  * topics   = (system, component, action) pages from the RAG index, the same
               unit the evaluation uses;
  * queries  = technician questions about each topic, in English and in Persian
               (formal and colloquial), from templates DIFFERENT from the
               evaluation ones; Persian component names come from our own
               terminology (glossary + terms.db), never machine-translated;
  * positive = a page of that topic;
  * hard negatives = what our own production retrieval ranks highly for the
               question but is the wrong page: the near-misses the reranker
               exists to fix;
  * user feedback = per-source 👍/👎 ratings from the assistant (feedback.db,
               reason='source' only)
               are added as labelled pairs, so real technicians' judgements
               flow into the model.

No leakage into the evaluation: every topic whose pages OR component name
appear in ANY gold set (known_item_*, diagnosis, wrong_vehicle, ...) is
excluded before sampling, so the evaluation measures generalisation to unseen
components, not memorisation.

Output: <out>/train.jsonl, one row per (query, passage, label) plus provenance,
and <out>/manifest.json with counts, seed and the exclusion statistics.
"""
import json
import random
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand

from api.evalsuite import goldset
from api.rag import config, embed, glossary, retrieve, store

# Different wording from goldset.ACTIONS_EN / ACTIONS_FA on purpose.
TRAIN_EN = {
    "removal": ["{c} removal procedure", "taking out the {c}"],
    "installation": ["{c} installation steps", "install procedure for {c}"],
    "replacement": ["replace {c}", "{c} replacement procedure"],
    "remove & replace": ["{c} r&r", "procedure to remove and refit {c}"],
    "inspection": ["{c} inspection", "check the {c} for damage"],
    "on-vehicle inspection": ["{c} on-vehicle check", "inspect {c} without removing it"],
    "disassembly": ["{c} disassembly", "strip down the {c}"],
    "reassembly": ["{c} reassembly", "put the {c} back together"],
    "adjustment": ["{c} adjustment procedure", "adjust {c}"],
    "parts location": ["{c} location", "where can I find the {c}"],
    "precaution": ["{c} precautions", "safety notes for {c} work"],
    "system diagram": ["{c} wiring and system diagram", "{c} system layout"],
    "problem symptoms table": ["{c} symptoms table", "{c} trouble symptoms"],
    "terminals of ecu": ["{c} ecu terminals", "{c} ecu pin voltages"],
    "operation check": ["{c} operation check", "test that the {c} works"],
    "diagnosis system": ["{c} diagnosis system", "{c} self diagnosis"],
    "data list / active test": ["{c} data list", "{c} active test"],
}
TRAIN_FA = {
    "removal": ["روش باز کردن {c}", "{c} رو چطوری باز کنم"],
    "installation": ["مراحل نصب {c}", "{c} رو چطوری ببندم"],
    "replacement": ["تعویض {c}", "{c} رو چطوری عوض کنم"],
    "remove & replace": ["باز و بسته کردن {c}", "پیاده و سوار کردن {c}"],
    "inspection": ["بازرسی {c}", "{c} رو چطوری چک کنم"],
    "on-vehicle inspection": ["چک کردن {c} روی ماشین", "بازدید {c} بدون پیاده کردن"],
    "disassembly": ["دمونتاژ {c}", "{c} رو چطوری باز کنم و قطعاتش رو جدا کنم"],
    "reassembly": ["مونتاژ {c}", "سوار کردن دوباره {c}"],
    "adjustment": ["روش تنظیم {c}", "{c} رو چطوری تنظیم کنم"],
    "parts location": ["{c} کجای ماشینه", "جای {c} کجاست"],
    "precaution": ["نکات احتیاطی {c}", "موقع کار با {c} مراقب چی باشم"],
    "system diagram": ["نقشه سیستم {c}", "دیاگرام {c}"],
    "problem symptoms table": ["علائم خرابی {c}", "جدول ایرادات {c}"],
    "terminals of ecu": ["ترمینال‌های کامپیوتر {c}", "ولتاژ پایه‌های ای‌سی‌یو {c}"],
    "operation check": ["تست عملکرد {c}", "چطوری بفهمم {c} سالمه"],
    "diagnosis system": ["عیب‌یابی {c}", "سیستم تشخیص عیب {c}"],
    "data list / active test": ["دیتا لیست {c}", "اکتیو تست {c}"],
}


def passage(title, text):
    """Exactly what service._rerank shows the cross-encoder."""
    return f"{title or ''}\n{(text or '')[:800]}"


def _gold_exclusions(gold_dir):
    blobs, comps, keys = set(), set(), set()
    for f in sorted(Path(gold_dir).glob('*.jsonl')):
        for row in goldset.read_jsonl(f):
            blobs.update(int(b) for b in row.get('expected_blob_ids') or [])
            if row.get('component'):
                comps.add(goldset.norm_en(row['component']))
            if row.get('topic_key'):
                keys.add(row['topic_key'])
    return blobs, comps, keys


def _qvec(query):
    eng, _ = glossary.expand(query)
    return embed.encode([f"{query} {eng}".strip() if eng else query], is_query=True)[0]


class Command(BaseCommand):
    help = 'Mine (query, passage, label) training data for the domain reranker.'

    def add_arguments(self, p):
        p.add_argument('--topics', type=int, default=2500)
        p.add_argument('--negatives', type=int, default=4)
        p.add_argument('--seed', type=int, default=2026)
        p.add_argument('--out', required=True)

    def handle(self, topics, negatives, seed, out, **o):
        t0 = time.time()
        rng = random.Random(seed)
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        index = store.open_index(config.INDEX_DB, write=False)
        gold_blobs, gold_comps, gold_keys = _gold_exclusions(config.RAG_DIR / 'eval' / 'gold')
        lex = goldset.build_fa_lexicon()
        allowed = set(goldset.indexed_cars(index))

        all_topics = goldset._topics_from_blobs(index)
        excluded = 0
        cands = []
        for key, rec in all_topics.items():
            if not (1 <= len(rec['blobs']) <= 8):
                continue
            if (key in gold_keys or rec['blobs'] & gold_blobs
                    or goldset.norm_en(rec['component']) in gold_comps):
                excluded += 1
                continue
            cands.append((key, rec))
        rng.shuffle(cands)
        # stratify over (system, action), like the gold sets
        buckets = defaultdict(list)
        for key, rec in cands:
            buckets[(goldset.norm_en(rec['system']), rec['action'])].append((key, rec))
        picked, order = [], sorted(buckets)
        rng.shuffle(order)
        while len(picked) < topics and any(buckets[b] for b in order):
            for b in order:
                if buckets[b] and len(picked) < topics:
                    picked.append(buckets[b].pop())

        def blob_row(bid):
            return index.execute('SELECT title, text, comp_readable FROM blobs WHERE blob_id=?',
                                 (bid,)).fetchone()

        rows, n_q = [], 0
        for i, (key, rec) in enumerate(picked, 1):
            cars = goldset._cars_for(index, sorted(rec['blobs']), allowed)
            if not cars:
                continue
            car = rng.choice(cars)
            comp_en = rec['component'].strip()
            queries = [(rng.choice(TRAIN_EN[rec['action']]).format(c=comp_en), 'en')]
            fa_comp = goldset.translate_component(goldset.norm_en(rec['component']), lex)
            if fa_comp and rec['action'] in TRAIN_FA:
                q = rng.choice(TRAIN_FA[rec['action']]).format(c=fa_comp)
                if not goldset.has_ascii_leak(q):
                    queries.append((q, 'fa'))
            for query, lang in queries:
                res = retrieve.assist(query, brand=None, model=None, car_stem=car,
                                      k=20, qvec=_qvec(query), expand=False)
                hits = res.get('hits') or []
                pos_id = sorted(rec['blobs'])[0]
                pr = blob_row(pos_id)
                if pr is None:
                    continue
                n_q += 1
                base = {'query': query, 'lang': lang, 'topic_key': key, 'car': car}
                rows.append({**base, 'blob_id': pos_id, 'label': 1.0, 'source': 'topic',
                             'passage': passage(pr['title'], pr['text'])})
                pos_topic = goldset.topic_of(pr['comp_readable'] or '')
                negs = []
                for h in hits:
                    if h.get('blob_id') in rec['blobs']:
                        continue
                    hr = blob_row(h['blob_id'])
                    # a duplicate page of the same topic is not a negative
                    if hr is None or (pos_topic and goldset.topic_of(hr['comp_readable'] or '') == pos_topic):
                        continue
                    negs.append(h)
                for h in negs[:negatives]:
                    rows.append({**base, 'blob_id': h['blob_id'], 'label': 0.0, 'source': 'hard_negative',
                                 'passage': passage(h.get('title'), h.get('text'))})
            if i % 100 == 0:
                self.stdout.write(f'  {i}/{len(picked)} topics, {n_q} queries, {len(rows)} pairs '
                                  f'({time.time() - t0:.0f}s)')

        # real technician judgements: per-source ratings with their question
        n_fb = 0
        try:
            fb = sqlite3.connect(f'file:{config.FEEDBACK_DB}?mode=ro', uri=True)
            fb.row_factory = sqlite3.Row
            # only per-source votes: an answer-level vote says nothing about
            # one particular page (older clients filed it under the first source)
            for r in fb.execute("SELECT * FROM ratings WHERE blob_id IS NOT NULL AND reason = 'source'"):
                q = (r['query'] if 'query' in r.keys() else '') or ''
                br = blob_row(int(r['blob_id'])) if q else None
                if br is None or int(r['blob_id']) in gold_blobs:
                    continue
                rows.append({'query': q, 'lang': 'fa' if glossary.has_persian(q) else 'en',
                             'topic_key': None, 'car': None, 'blob_id': int(r['blob_id']),
                             'label': 1.0 if int(r['verdict']) > 0 else 0.0, 'source': 'user_feedback',
                             'passage': passage(br['title'], br['text'])})
                n_fb += 1
        except sqlite3.Error as e:
            self.stdout.write(f'  feedback store unavailable: {e}')

        with open(out / 'train.jsonl', 'w', encoding='utf-8') as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + '\n')
        manifest = {
            'seed': seed, 'topics_requested': topics, 'topics_used': len(picked),
            'topics_excluded_for_eval_overlap': excluded, 'queries': n_q,
            'pairs': len(rows), 'positives': sum(r['label'] == 1.0 for r in rows),
            'feedback_pairs': n_fb,
            'by_lang': {l: sum(r['lang'] == l for r in rows) for l in ('en', 'fa')},
            'seconds': round(time.time() - t0, 1),
        }
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        self.stdout.write(self.style.SUCCESS(json.dumps(manifest)))
