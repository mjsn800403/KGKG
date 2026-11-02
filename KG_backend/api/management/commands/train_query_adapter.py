"""Train the KG query adapter: domain + Persian adaptation of bge-m3 on the query side.

    python manage.py train_query_adapter --data <dir>/train.jsonl --out <dir>

Fine-tuning bge-m3 itself would change every page vector, and re-embedding
the 305k-page index takes days on this CPU. The adapter instead learns a small
residual map on QUERY embeddings only,

    q' = normalize(q + U (V q))        (rank r, starts as the identity)

that moves technician questions (Persian and English) toward the pages that
answer them in the EXISTING vector space. No re-indexing; serving cost is one
small matrix product per question.

Training signal, all from our own data (no LLM calls):
  * question -> its correct page, against the pages our retrieval wrongly put
    near it (hard negatives) and the other questions' pages (in-batch), InfoNCE;
  * Persian term -> English term from the shop glossary (translation.db +
    curated map): pulls each Persian phrase onto its English equivalent, the
    cross-language gap the Persian gold sets measure;
  * a small penalty on the residual keeps English behaviour close to the base.

Questions are split by topic for a dev check; the gold evaluation topics were
already excluded from train.jsonl by build_reranker_trainset.
"""
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand

from api.rag import config, embed, glossary, store


def _page_vecs(blob_ids):
    """Served int8 page vectors (cosine ignores scale), L2-normalised."""
    idx = store.get_index_ro()
    out = {}
    for b in blob_ids:
        r = idx.execute('SELECT embedding FROM vec_blobs WHERE rowid = ?', (int(b),)).fetchone()
        if r:
            v = np.frombuffer(r[0], dtype=np.int8).astype(np.float32)
            n = np.linalg.norm(v)
            if n:
                out[int(b)] = v / n
    return out


class Command(BaseCommand):
    help = 'Train the query-side adapter for bge-m3 (no re-indexing needed).'

    def add_arguments(self, p):
        p.add_argument('--data', required=True)
        p.add_argument('--out', required=True)
        p.add_argument('--rank', type=int, default=64)
        p.add_argument('--epochs', type=int, default=30)
        p.add_argument('--lr', type=float, default=2e-3)
        p.add_argument('--temp', type=float, default=0.05)
        p.add_argument('--gloss-weight', type=float, default=0.5)
        p.add_argument('--reg', type=float, default=1e-3)
        p.add_argument('--batch', type=int, default=64)
        p.add_argument('--dev-frac', type=float, default=0.1)
        p.add_argument('--threads', type=int, default=4)
        p.add_argument('--seed', type=int, default=2026)

    def handle(self, **o):
        import torch
        torch.set_num_threads(o['threads'])
        torch.manual_seed(o['seed'])
        rng = random.Random(o['seed'])
        out = Path(o['out'])
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        # ---- question groups ------------------------------------------------
        groups = defaultdict(lambda: {'pos': None, 'neg': []})
        for line in open(o['data'], encoding='utf-8'):
            r = json.loads(line)
            if r.get('source') == 'user_feedback':
                continue
            g = groups[(r['query'], r.get('topic_key'))]
            if r['label'] >= 0.5:
                g['pos'] = r['blob_id']
            else:
                g['neg'].append(r['blob_id'])
        groups = [(q, t, g['pos'], g['neg']) for (q, t), g in groups.items() if g['pos']]
        topics = sorted({t for _, t, _, _ in groups})
        rng.shuffle(topics)
        dev_t = set(topics[:max(1, int(len(topics) * o['dev_frac']))])
        train = [g for g in groups if g[1] not in dev_t]
        dev = [g for g in groups if g[1] in dev_t]

        # ---- glossary pairs (Persian phrase -> English phrase) ---------------
        # raw phrases (the served glossary keeps only an English token bag)
        import sqlite3
        gl = {}
        try:
            con = sqlite3.connect(f'file:{config.PARTS_DB}?mode=ro', uri=True)
            for en, fa in con.execute('SELECT field1, field2 FROM Book1'):
                if en and fa:
                    gl.setdefault(fa.strip(), en.strip())
            con.close()
        except Exception as e:
            self.stdout.write(f'  glossary db unavailable: {e}')
        gl.update(glossary.GLOSSARY)
        gpairs = []
        for fa, en in gl.items():
            en = en if isinstance(en, str) else ' '.join(en)
            if fa and en and len(fa) <= 60 and len(en) <= 80:
                gpairs.append((fa, en))
        rng.shuffle(gpairs)
        self.stdout.write(f'questions: train {len(train)} dev {len(dev)}  glossary pairs {len(gpairs)}')

        # ---- embeddings (base model, computed once) --------------------------
        qtexts = sorted({g[0] for g in groups})
        qv = dict(zip(qtexts, embed.encode(qtexts, is_query=True)))
        fa_v = embed.encode([fa for fa, _ in gpairs], is_query=True)
        en_v = embed.encode([en for _, en in gpairs], is_query=True)
        pv = _page_vecs({b for g in groups for b in [g[2]] + g[3]})
        self.stdout.write(f'embedded in {time.time() - t0:.0f}s')

        d = config.EMBED_DIM
        V = torch.nn.Parameter(torch.randn(o['rank'], d) * 0.01)
        U = torch.nn.Parameter(torch.zeros(d, o['rank']))

        def adapt(q):
            z = q + (q @ V.T) @ U.T
            return torch.nn.functional.normalize(z, dim=-1)

        def T(x):
            return torch.tensor(np.asarray(x), dtype=torch.float32)

        def rows(gs):
            q = T([qv[g[0]] for g in gs])
            pos = T([pv[g[2]] for g in gs])
            negs = [[pv[b] for b in g[3] if b in pv][:4] for g in gs]
            return q, pos, negs

        @torch.no_grad()
        def dev_eval(use):
            """Hit@1 / MRR of the correct page among its hard negatives."""
            hit = mrr = 0.0
            for g in dev:
                c = [g[2]] + [b for b in g[3] if b in pv]
                q = T([qv[g[0]]])
                if use:
                    q = adapt(q)
                s = (q @ T([pv[b] for b in c]).T)[0]
                rank = 1 + int((s[1:] > s[0]).sum())
                hit += rank == 1
                mrr += 1 / rank
            n = max(1, len(dev))
            fa = [g for g in dev if any('؀' <= ch <= 'ۿ' for ch in g[0])]
            return {'hit1': round(hit / n, 4), 'mrr': round(mrr / n, 4), 'n': n, 'n_fa': len(fa)}

        before = dev_eval(False)
        self.stdout.write(f'dev before: {before}')
        opt = torch.optim.Adam([U, V], lr=o['lr'])
        gfa, gen = T(fa_v), T(en_v)
        for ep in range(o['epochs']):
            rng.shuffle(train)
            tot = 0.0
            for i in range(0, len(train), o['batch']):
                gs = train[i:i + o['batch']]
                q, pos, negs = rows(gs)
                a = adapt(q)
                # in-batch positives + own hard negatives
                logits_ib = a @ pos.T                                   # (B, B)
                hn = torch.full((len(gs), 4), -1e4)
                for j, nl in enumerate(negs):
                    if nl:
                        hn[j, :len(nl)] = a[j] @ T(nl).T
                logits = torch.cat([logits_ib, hn], 1) / o['temp']
                loss = torch.nn.functional.cross_entropy(logits, torch.arange(len(gs)))
                # glossary: Persian phrase -> its English phrase (in-batch contrastive)
                k = rng.randrange(0, max(1, len(gpairs) - o['batch']))
                fa_a = adapt(gfa[k:k + o['batch']])
                en_t = torch.nn.functional.normalize(gen[k:k + o['batch']], dim=-1)
                gl_loss = torch.nn.functional.cross_entropy(fa_a @ en_t.T / o['temp'],
                                                            torch.arange(fa_a.shape[0]))
                loss = loss + o['gloss_weight'] * gl_loss + o['reg'] * (U.pow(2).sum() + V.pow(2).sum())
                opt.zero_grad(); loss.backward(); opt.step()
                tot += float(loss)
            if ep % 5 == 4 or ep == o['epochs'] - 1:
                self.stdout.write(f'  epoch {ep + 1}/{o["epochs"]} loss {tot:.3f} dev {dev_eval(True)}')
        after = dev_eval(True)
        self.stdout.write(f'dev after: {after}')

        np.savez(out / 'adapter.npz', U=U.detach().numpy(), V=V.detach().numpy())
        (out / 'adapter.json').write_text(json.dumps({
            'base_model': config.EMBED_MODEL, 'rank': o['rank'], 'epochs': o['epochs'],
            'lr': o['lr'], 'temp': o['temp'], 'gloss_weight': o['gloss_weight'],
            'questions_train': len(train), 'questions_dev': len(dev), 'glossary_pairs': len(gpairs),
            'dev_before': before, 'dev_after': after, 'seconds': round(time.time() - t0),
        }, indent=2))
        self.stdout.write(self.style.SUCCESS(f'saved -> {out}'))
