"""Machine-assisted EN->FA terminology generation with layered QA gates.

    python manage.py translate_terms --dry-run --limit 300     # show batches + cost, no calls
    python manage.py translate_terms --limit 300               # pilot run
    python manage.py translate_terms --budget 600              # hard cap on Metis messages
    python manage.py translate_terms --variants                # colloquial symptom phrasings

Method (per batch of --batch-size queued gen_queue terms):
  1. TRANSLATE twice, in two independent Metis sessions, few-shot-anchored on
     curated pairs (5 token-matched + 5 stable). Strict JSON out, re-ask <=2.
  2. SELF-CONSISTENCY: samples agree on fa_norm -> agreement 1.0; else a third
     sample votes (2-of-3 -> 0.66); no majority -> human review.
  3. BACK-TRANSLATION: agreed fa -> English via Metis, then cosine similarity
     against the original English using the SAME bge-m3 model that serves
     retrieval. Pass >= --backtrans-min (default 0.82).
  4. Only terms passing BOTH gates enter terms.db as active (source=generated,
     confidence = 0.5*agreement + 0.5*backtrans_sim). Everything else goes to
     status=pending_review and _rag/terms_review.csv for the user.

Safety/ops: pid lockfile; yields at batch boundaries if a pipeline job is
active; every Metis call logged and counted; --budget is a hard stop; state
lives in gen_queue so an aborted run resumes without repeating spend.
Publish with `manage.py build_terms --export` (both artifacts hot-reload).
"""
import csv
import json
import os
import re
import time
import urllib.request
import urllib.error
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from api.rag import config, glossary, terms

METIS_BASE = 'https://api.metisai.ir/api/v1/chat'
LOCK = config.RAG_DIR / 'locks' / 'translate_terms.lock'
LOG = config.RAG_DIR / 'logs' / 'translate_terms.log'
REVIEW_CSV = config.RAG_DIR / 'terms_review.csv'


def _log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}\n')


def parse_env_file(path):
    """Tiny dotenv reader — the Metis credentials live in the frontend env and
    are NOT duplicated anywhere else."""
    out = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class BudgetExhausted(Exception):
    pass


class MetisClient:
    """Minimal Python port of the chat route's Metis integration."""

    def __init__(self, api_key, bot_id, budget=None):
        self.api_key, self.bot_id = api_key, bot_id
        self.budget = budget
        self.calls = 0

    def _post(self, path, payload, timeout=120):
        if self.budget is not None and self.calls >= self.budget:
            raise BudgetExhausted(f'budget of {self.budget} Metis messages reached')
        body = json.dumps(payload).encode()
        last = None
        for attempt in range(3):
            req = urllib.request.Request(
                f'{METIS_BASE}/{path}', data=body,
                headers={'Content-Type': 'application/json', 'X-Api-Key': self.api_key})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    self.calls += 1
                    return json.load(r)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                last = e
                _log(f'metis {path} attempt {attempt + 1} failed: {e}')
                time.sleep(2 ** attempt * 3)
        raise CommandError(f'Metis unreachable after retries: {last}')

    def new_session(self, tag):
        s = self._post('session', {'botId': self.bot_id,
                                   'user': {'id': f'terms-{tag}-{int(time.time())}', 'name': '_'}})
        self.calls -= 1          # session creation is not a billed message
        return s['id']

    def send(self, session_id, content):
        r = self._post(f'session/{session_id}/message',
                       {'message': {'type': 'USER', 'content': content}})
        return (r or {}).get('content') or ''


# ---------------------------------------------------------------------------
# Prompt construction + strict parsing
# ---------------------------------------------------------------------------
def few_shot_examples(con, batch_terms, n_matched=5, n_stable=5):
    """Curated exemplars: half sharing a token with the batch (domain anchor),
    half a stable deterministic sample (style anchor)."""
    toks = set()
    for t in batch_terms:
        toks.update(terms.norm_en(t).split())
    matched, stable = [], []
    rows = con.execute(
        "SELECT en, fa FROM terms WHERE source IN ('curated','reviewed') "
        "AND status='active' ORDER BY id").fetchall()
    for en, fa in rows:
        if len(matched) < n_matched and toks & set(terms.norm_en(en).split()):
            matched.append((en, fa))
    step = max(1, len(rows) // max(1, n_stable))
    for i in range(0, len(rows), step):
        if len(stable) >= n_stable:
            break
        if rows[i] not in matched:
            stable.append(rows[i])
    return matched + stable


def translation_prompt(examples, batch):
    ex = '\n'.join(f'- "{en}" => "{fa}"' for en, fa in examples)
    items = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(batch))
    return (
        'You are a senior Toyota/Lexus service-manual translator producing the official '
        'Persian (Farsi) terminology used by professional Iranian mechanics.\n'
        'Rules: translate each English part/procedure term to its standard Persian label; '
        'use accepted transliterations where that IS the standard (سنسور، کالیپر، اینورتر); '
        'use correct نیم‌فاصله (ZWNJ); keep it a short label, not a sentence; no explanations.\n'
        f'Examples of our approved style:\n{ex}\n\n'
        f'Translate these {len(batch)} terms. Reply with ONLY a JSON array, one object per '
        'term, SAME ORDER, format [{"en": "...", "fa": "..."}] and nothing else:\n'
        f'{items}'
    )


def adjudication_prompt(items):
    """items: [(en, [fa candidates])]. The judge only CHOOSES among existing
    candidates (it cannot introduce a new translation), which keeps this pass
    hallucination-free by construction."""
    lines = []
    for i, (en, cands) in enumerate(items):
        lines.append(f'{i + 1}. "{en}"')
        for j, fa in enumerate(cands):
            lines.append(f'   {j + 1}) {fa}')
    body = '\n'.join(lines)
    return (
        'You are the terminology arbiter for a Toyota/Lexus Persian service manual. '
        'For each English term below, CHOOSE the candidate that professional Iranian '
        'mechanics would use as the standard label (prefer established terminology and '
        'accepted transliterations; prefer the most natural, compact label).\n'
        f'Reply with ONLY a JSON array, one object per term, SAME ORDER, format '
        '[{"n": <term number>, "choice": <candidate number>}] and nothing else:\n'
        f'{body}'
    )


def parse_choices(reply, items):
    """[{'n','choice'}] -> list of 0-based choice indices; None on violations."""
    m = _JSON_ARR.search(reply or '')
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(arr, list) or len(arr) != len(items):
        return None
    out = []
    for k, item in enumerate(arr):
        if not isinstance(item, dict) or 'choice' not in item:
            return None
        try:
            c = int(item['choice']) - 1
        except (TypeError, ValueError):
            return None
        if not 0 <= c < len(items[k][1]):
            return None
        out.append(c)
    return out


def ask_choices(client, sid, items, retries=2):
    reply = client.send(sid, adjudication_prompt(items))
    parsed = parse_choices(reply, items)
    tries = 0
    while parsed is None and tries < retries:
        tries += 1
        reply = client.send(
            sid, 'Your reply was not a valid JSON array of {"n", "choice"} objects '
                 'covering every term. Reply again with ONLY the JSON array.')
        parsed = parse_choices(reply, items)
    return parsed


def run_adjudication(con, client, encode, opts, out=print):
    """Resolve state='review' rows by judge-vote among their existing candidate
    phrasings + the usual back-translation gate. Rows failing any gate stay in
    review (nothing unverified is ever published)."""
    batch_size = opts.get('batch_size', 20)
    limit = opts.get('limit')
    backtrans_min = opts.get('backtrans_min', 0.82)
    stats = {'accepted': 0, 'kept_review': 0, 'processed': 0, 'batches': 0}

    j1 = client.new_session('judge-a')
    j2 = client.new_session('judge-b')
    j3 = None

    processed = 0
    seen_rids = set()      # gate-failed rows stay 'review' — never refetch in this run
    while True:
        if opts.get('pipeline_check') and opts['pipeline_check']():
            out('pipeline job active — yielding (rerun to resume)')
            break
        take = batch_size if limit is None else min(batch_size, limit - processed)
        if take <= 0:
            break
        exclude = f"AND id NOT IN ({','.join(map(str, seen_rids))}) " if seen_rids else ''
        rows = con.execute(
            "SELECT id, en, samples_json FROM gen_queue WHERE state='review' "
            "AND samples_json IS NOT NULL AND samples_json != '[]' "
            f'{exclude}'
            'ORDER BY freq DESC, id LIMIT ?', (take,)).fetchall()
        if not rows:
            break
        seen_rids.update(r[0] for r in rows)
        items, meta = [], []
        for rid, en, sj in rows:
            try:
                raw = json.loads(sj)
            except json.JSONDecodeError:
                raw = []
            cands, seen = [], set()
            for fa in raw:
                fa_d = terms.clean_fa_display(fa)
                key = terms.norm_fa(fa_d)
                if fa_d and key and key not in seen:
                    seen.add(key)
                    cands.append(fa_d)
            if cands:
                items.append((en, cands))
                meta.append(rid)
        if not items:
            break
        stats['batches'] += 1

        # only multi-candidate terms need judging; a collapsed single form is
        # its own winner (it still faces the back-translation gate below)
        multi = [i for i, (_, cands) in enumerate(items) if len(cands) > 1]
        c1 = c2 = None
        if multi:
            try:
                judged = [items[i] for i in multi]
                c1 = ask_choices(client, j1, judged)
                c2 = ask_choices(client, j2, judged)
            except BudgetExhausted as e:
                out(f'STOP: {e}')
                break
        pos = {i: k for k, i in enumerate(multi)}

        picks = {}          # rid -> (fa, judge_conf)
        needs_third = []    # (idx, rid)
        for i, rid in enumerate(meta):
            en, cands = items[i]
            if len(cands) == 1:
                picks[rid] = (cands[0], 1.0)     # samples collapsed to one form
                continue
            a = c1[pos[i]] if c1 else None
            b = c2[pos[i]] if c2 else None
            if a is not None and a == b:
                picks[rid] = (cands[a], 1.0)
            elif a is not None or b is not None:
                needs_third.append((i, rid))
            # both judges unparseable -> term silently stays review this round

        if needs_third:
            if j3 is None:
                try:
                    j3 = client.new_session('judge-c')
                except BudgetExhausted:
                    j3 = None
            third = None
            if j3 is not None:
                try:
                    third = ask_choices(client, j3, [items[i] for i, _ in needs_third])
                except BudgetExhausted:
                    third = None
            for k, (i, rid) in enumerate(needs_third):
                en, cands = items[i]
                votes = [v for v in (c1[pos[i]] if c1 else None,
                                     c2[pos[i]] if c2 else None,
                                     third[k] if third else None) if v is not None]
                counts = {}
                for v in votes:
                    counts[v] = counts.get(v, 0) + 1
                best, n_votes = max(counts.items(), key=lambda kv: kv[1]) if counts else (None, 0)
                if best is not None and n_votes >= 2:
                    picks[rid] = (cands[best], 0.7)

        # back-translation gate on the picked candidates
        picked = [(rid, items[meta.index(rid)][0], fa, jc) for rid, (fa, jc) in picks.items()]
        back_sims = {}
        if picked:
            try:
                back = ask_batch(client, j1, backtranslation_prompt(
                    [fa for _, _, fa, _ in picked]), len(picked), 'fa', 'en')
            except BudgetExhausted:
                back = None
            if back:
                ov = encode([en for _, en, _, _ in picked])
                bv = encode([b[1] for b in back])
                for k, (rid, en, fa, jc) in enumerate(picked):
                    back_sims[rid] = (cosine(ov[k], bv[k]), back[k][1])

        for i, rid in enumerate(meta):
            processed += 1
            stats['processed'] += 1
            en, _ = items[i]
            pick = picks.get(rid)
            sim, back_en = back_sims.get(rid, (None, None))
            if pick and sim is not None and sim >= backtrans_min:
                fa, jc = pick
                conf = round(0.5 * jc + 0.5 * sim, 3)
                terms.upsert_term(con, en, fa, domain='part', source='generated',
                                  confidence=conf, status='active',
                                  notes=f'adjudicated jc={jc} back={sim:.2f}')
                con.execute(
                    "UPDATE gen_queue SET state='accepted', fa_result=?, agreement=?,"
                    " backtrans_en=?, backtrans_sim=?, confidence=?,"
                    " updated_at=datetime('now') WHERE id=?",
                    (fa, jc, back_en, sim, conf, rid))
                stats['accepted'] += 1
            else:
                # keep in review; bump attempts so repeated passes can be spotted
                con.execute("UPDATE gen_queue SET attempts=attempts+1,"
                            " updated_at=datetime('now') WHERE id=?", (rid,))
                stats['kept_review'] += 1
        con.commit()
        out(f"adjudicate batch {stats['batches']}: accepted={stats['accepted']} "
            f"kept_review={stats['kept_review']} metis_calls={client.calls}")
        _log(f'adjudicate batch done: {stats} calls={client.calls}')
    return stats


def backtranslation_prompt(fa_terms):
    items = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(fa_terms))
    return (
        'Translate each Persian automotive term back to a plain English part/procedure name. '
        'Reply with ONLY a JSON array, one object per term, SAME ORDER, format '
        '[{"fa": "...", "en": "..."}] and nothing else:\n'
        f'{items}'
    )


_JSON_ARR = re.compile(r'\[.*\]', re.DOTALL)


def parse_json_array(reply, n_expected, key_in, key_out):
    """Extract [{key_in, key_out}] pairs; None on any shape violation."""
    m = _JSON_ARR.search(reply or '')
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(arr, list) or len(arr) != n_expected:
        return None
    out = []
    for item in arr:
        if not isinstance(item, dict) or key_in not in item or key_out not in item:
            return None
        out.append((str(item[key_in]).strip(), str(item[key_out]).strip()))
    return out


def ask_batch(client, sid, prompt_text, n, key_in, key_out, retries=2):
    """Send + strict-parse, re-asking up to `retries` times on shape violations."""
    reply = client.send(sid, prompt_text)
    parsed = parse_json_array(reply, n, key_in, key_out)
    tries = 0
    while parsed is None and tries < retries:
        tries += 1
        reply = client.send(
            sid, 'Your reply was not a valid JSON array of the required shape. '
                 'Reply again with ONLY the JSON array, nothing else.')
        parsed = parse_json_array(reply, n, key_in, key_out)
    return parsed


# ---------------------------------------------------------------------------
# Core run (client/embedder injected -> unit-testable without network)
# ---------------------------------------------------------------------------
def cosine(a, b):
    return float(sum(x * y for x, y in zip(a, b)))


def run_translation(con, client, encode, opts, out=print):
    """Process queued gen_queue rows in QA-gated batches. Returns stats."""
    batch_size = opts.get('batch_size', 25)
    limit = opts.get('limit')
    backtrans_min = opts.get('backtrans_min', 0.82)
    stats = {'accepted': 0, 'review': 0, 'failed': 0, 'processed': 0, 'batches': 0}

    s1 = client.new_session('a')
    s2 = client.new_session('b')
    s3 = None

    processed = 0
    while True:
        if opts.get('pipeline_check') and opts['pipeline_check']():
            out('pipeline job active — yielding (state saved; rerun to resume)')
            break
        take = batch_size if limit is None else min(batch_size, limit - processed)
        if take <= 0:
            break
        rows = con.execute(
            "SELECT id, en, en_norm FROM gen_queue WHERE state='queued' "
            'ORDER BY freq DESC, id LIMIT ?', (take,)).fetchall()
        if not rows:
            break
        batch = [r[1] for r in rows]
        stats['batches'] += 1
        examples = few_shot_examples(con, batch)
        prompt_text = translation_prompt(examples, batch)

        try:
            p1 = ask_batch(client, s1, prompt_text, len(batch), 'en', 'fa')
            p2 = ask_batch(client, s2, prompt_text, len(batch), 'en', 'fa')
        except BudgetExhausted as e:
            out(f'STOP: {e}')
            break
        if p1 is None and p2 is None:
            for rid, en, _ in rows:
                con.execute("UPDATE gen_queue SET state='failed', attempts=attempts+1,"
                            " updated_at=datetime('now') WHERE id=?", (rid,))
            con.commit()
            stats['failed'] += len(rows)
            processed += len(rows)
            continue

        # per-term agreement
        verdicts = []      # (rid, en, fa, agreement, samples)
        needs_third = []
        for i, (rid, en, _) in enumerate(rows):
            fa1 = p1[i][1] if p1 else None
            fa2 = p2[i][1] if p2 else None
            samples = [s for s in (fa1, fa2) if s]
            if fa1 and fa2 and terms.norm_fa(fa1) == terms.norm_fa(fa2):
                verdicts.append((rid, en, fa1, 1.0, samples))
            elif fa1 or fa2:
                needs_third.append((i, rid, en, samples))
            else:
                verdicts.append((rid, en, None, 0.0, samples))

        if needs_third:
            if s3 is None:
                try:
                    s3 = client.new_session('c')
                except BudgetExhausted:
                    s3 = None
            third = None
            if s3 is not None:
                try:
                    third = ask_batch(client, s3, translation_prompt(
                        examples, [en for _, _, en, _ in needs_third]),
                        len(needs_third), 'en', 'fa')
                except BudgetExhausted:
                    third = None
            for j, (i, rid, en, samples) in enumerate(needs_third):
                fa3 = third[j][1] if third else None
                pool = samples + ([fa3] if fa3 else [])
                counts = {}
                for s in pool:
                    counts[terms.norm_fa(s)] = counts.get(terms.norm_fa(s), 0) + 1
                best_norm, best_n = max(counts.items(), key=lambda kv: kv[1]) if counts else (None, 0)
                if best_n >= 2:
                    fa = next(s for s in pool if terms.norm_fa(s) == best_norm)
                    verdicts.append((rid, en, fa, 0.66, pool))
                else:
                    verdicts.append((rid, en, None, 0.0, pool))

        # back-translation gate for agreed terms
        agreed = [(rid, en, fa, ag, smp) for rid, en, fa, ag, smp in verdicts if fa]
        back_sims = {}
        if agreed:
            try:
                back = ask_batch(client, s1, backtranslation_prompt(
                    [fa for _, _, fa, _, _ in agreed]), len(agreed), 'fa', 'en')
            except BudgetExhausted:
                back = None
            if back:
                orig_vecs = encode([en for _, en, _, _, _ in agreed])
                back_vecs = encode([b[1] for b in back])
                for k, (rid, en, fa, ag, smp) in enumerate(agreed):
                    back_sims[rid] = (cosine(orig_vecs[k], back_vecs[k]), back[k][1])

        for rid, en, fa, agreement, samples in verdicts:
            processed += 1
            stats['processed'] += 1
            if fa is None:
                con.execute(
                    "UPDATE gen_queue SET state='review', samples_json=?, agreement=0,"
                    " attempts=attempts+1, updated_at=datetime('now') WHERE id=?",
                    (json.dumps(samples, ensure_ascii=False), rid))
                terms.upsert_term(con, en, samples[0] if samples else '?',
                                  domain='part', source='generated', confidence=0.0,
                                  status='pending_review', notes='no-consensus')
                stats['review'] += 1
                continue
            sim, back_en = back_sims.get(rid, (None, None))
            if sim is not None and sim >= backtrans_min:
                conf = round(0.5 * agreement + 0.5 * sim, 3)
                terms.upsert_term(con, en, fa, domain='part', source='generated',
                                  confidence=conf, status='active',
                                  notes=f'agr={agreement} back={sim:.2f}')
                con.execute(
                    "UPDATE gen_queue SET state='accepted', fa_result=?, agreement=?,"
                    " backtrans_en=?, backtrans_sim=?, confidence=?, samples_json=?,"
                    " updated_at=datetime('now') WHERE id=?",
                    (fa, agreement, back_en, sim, conf,
                     json.dumps(samples, ensure_ascii=False), rid))
                stats['accepted'] += 1
            else:
                terms.upsert_term(con, en, fa, domain='part', source='generated',
                                  confidence=round(0.5 * agreement, 3),
                                  status='pending_review',
                                  notes=f'backtrans={"%.2f" % sim if sim is not None else "n/a"}')
                con.execute(
                    "UPDATE gen_queue SET state='review', fa_result=?, agreement=?,"
                    " backtrans_en=?, backtrans_sim=?, samples_json=?,"
                    " updated_at=datetime('now') WHERE id=?",
                    (fa, agreement, back_en, sim,
                     json.dumps(samples, ensure_ascii=False), rid))
                stats['review'] += 1
        con.commit()
        out(f"batch {stats['batches']}: accepted={stats['accepted']} "
            f"review={stats['review']} failed={stats['failed']} "
            f"metis_calls={client.calls}")
        _log(f'batch done: {stats} calls={client.calls}')
    return stats


def write_review_csv(con, path=REVIEW_CSV):
    rows = con.execute(
        "SELECT q.en, COALESCE(q.fa_result,''), COALESCE(q.agreement,0),"
        " COALESCE(q.backtrans_sim,''), COALESCE(q.backtrans_en,''), q.freq,"
        " COALESCE(q.samples_json,'')"
        " FROM gen_queue q WHERE q.state='review' ORDER BY q.freq DESC").fetchall()
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['en', 'fa_best_guess', 'agreement', 'backtrans_sim',
                    'backtrans_en', 'frequency', 'all_samples'])
        w.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------------------
class Command(BaseCommand):
    help = 'Generate EN->FA terminology via Metis with self-consistency + back-translation QA.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None,
                            help='Max queued terms to process this run.')
        parser.add_argument('--budget', type=int, default=None,
                            help='HARD cap on Metis messages (clean stop).')
        parser.add_argument('--batch-size', type=int, default=25)
        parser.add_argument('--backtrans-min', type=float, default=0.82)
        parser.add_argument('--dry-run', action='store_true',
                            help='Print batch/cost plan; no Metis calls.')
        parser.add_argument('--env-file', default=None,
                            help='Env file holding METIS_API_KEY/METIS_BOT_ID '
                                 '(default: <root>/kg_frontend/.env.production).')
        parser.add_argument('--adjudicate', action='store_true',
                            help="Resolve state='review' rows by judge-voting among their "
                                 'EXISTING candidate phrasings (choice-only, so nothing new '
                                 'can be hallucinated) + the back-translation gate.')

    def handle(self, *args, **opts):
        state = 'review' if opts['adjudicate'] else 'queued'
        con = terms.connect()
        try:
            queued = con.execute(
                'SELECT COUNT(*) FROM gen_queue WHERE state=?', (state,)).fetchone()[0]
            n = min(queued, opts['limit']) if opts['limit'] else queued
            est = (n // max(1, opts['batch_size']) + 1) * 3 + 2
            if opts['dry_run']:
                self.stdout.write(f'{state}={queued}, would process n={n}, '
                                  f'~{est} Metis messages')
                rows = con.execute('SELECT en, freq FROM gen_queue WHERE state=? '
                                   'ORDER BY freq DESC, id LIMIT 10', (state,)).fetchall()
                for en, freq in rows:
                    self.stdout.write(f'   {freq:>8,}  {en}')
                return
            if not n:
                self.stdout.write(f"gen_queue has no {state} terms — nothing to do")
                return

            # lock
            LOCK.parent.mkdir(parents=True, exist_ok=True)
            if LOCK.exists():
                pid = LOCK.read_text().strip()
                if pid and Path(f'/proc/{pid}').exists():
                    raise CommandError(f'another translate_terms run is active (pid {pid})')
                LOCK.unlink()
            LOCK.write_text(str(os.getpid()))
            try:
                env_path = Path(opts['env_file']) if opts['env_file'] else \
                    config.BASE_DIR.parent / 'kg_frontend' / '.env.production'
                env = parse_env_file(env_path)
                api_key, bot_id = env.get('METIS_API_KEY'), env.get('METIS_BOT_ID')
                if not api_key or not bot_id:
                    raise CommandError(f'METIS_API_KEY/METIS_BOT_ID not found in {env_path}')
                client = MetisClient(api_key, bot_id, budget=opts['budget'])

                from api.rag import embed as embed_mod

                def encode(texts):
                    return [list(map(float, v)) for v in
                            embed_mod.encode(texts, is_query=True)]

                def pipeline_active():
                    try:
                        from api.models import ProcessingJob
                        return ProcessingJob.objects.filter(
                            status__in=('pending', 'running')).exists()
                    except Exception:
                        return False

                runner = run_adjudication if opts['adjudicate'] else run_translation
                stats = runner(
                    con, client, encode,
                    dict(batch_size=opts['batch_size'], limit=opts['limit'],
                         backtrans_min=opts['backtrans_min'],
                         pipeline_check=pipeline_active),
                    out=self.stdout.write)
                n_review = write_review_csv(con)
                self.stdout.write(self.style.SUCCESS(
                    f"done: {stats} | review rows -> {REVIEW_CSV} ({n_review}) | "
                    f"Metis messages used: {client.calls} | "
                    f"publish with: manage.py build_terms --export"))
            finally:
                try:
                    LOCK.unlink()
                except OSError:
                    pass
        finally:
            con.close()
