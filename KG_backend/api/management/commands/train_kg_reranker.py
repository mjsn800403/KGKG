"""Fine-tune KG-Reranker: the cross-encoder adapted to Toyota manuals.

    python manage.py train_kg_reranker --data <dir>/train.jsonl --out <model-dir>

Starts from the general multilingual reranker (config.RERANK_MODEL,
bge-reranker-v2-m3) and continues training on the pairs mined by
build_reranker_trainset. CPU-only by design (the production server has no GPU):
plain PyTorch, no extra libraries.

Objective: listwise softmax cross-entropy per question. Each question comes
with its correct page and the pages our own retrieval wrongly ranked near it;
the model is pushed to score the correct one above all of those near-misses at
once, which is exactly the decision it makes in production (reorder the top
candidates of one query). Isolated pairs (per-source user votes) are trained
with binary cross-entropy in the same steps.

A held-out slice of TRAINING topics (by topic, never by row) is scored before
and after, so a run that makes things worse is visible before anyone points
production at it. The real evaluation is separate: run_evalsuite on the gold
sets, whose topics were excluded from the training data.
"""
import json
import math
import os
import random
import time
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand

from api.rag import config


def _groups(rows):
    by_q = defaultdict(list)
    singles = []
    for r in rows:
        if r.get('source') == 'user_feedback':
            singles.append(r)
        else:
            by_q[(r['query'], r.get('topic_key'))].append(r)
    groups = []
    for key, rs in by_q.items():
        pos = [r for r in rs if r['label'] >= 0.5]
        neg = [r for r in rs if r['label'] < 0.5]
        if pos and neg:
            groups.append({'key': key, 'topic': key[1], 'pos': pos[0], 'neg': neg})
    return groups, singles


class Command(BaseCommand):
    help = 'Fine-tune the domain cross-encoder (KG-Reranker) on mined data.'

    def add_arguments(self, p):
        p.add_argument('--data', required=True)
        p.add_argument('--out', required=True)
        p.add_argument('--base', default=config.RERANK_MODEL)
        p.add_argument('--epochs', type=float, default=1.0)
        p.add_argument('--lr', type=float, default=1e-5)
        p.add_argument('--groups-per-step', type=int, default=4)
        p.add_argument('--max-length', type=int, default=256)
        p.add_argument('--freeze-layers', type=int, default=12,
                       help='keep the embeddings and the lowest N transformer layers fixed '
                            '(CPU budget; the upper layers and the head adapt to the domain)')
        p.add_argument('--max-neg', type=int, default=4)
        p.add_argument('--dev-frac', type=float, default=0.08)
        p.add_argument('--threads', type=int, default=8)
        p.add_argument('--seed', type=int, default=2026)

    def handle(self, **o):
        import torch
        from sentence_transformers import CrossEncoder

        torch.set_num_threads(o['threads'])
        torch.manual_seed(o['seed'])
        rng = random.Random(o['seed'])
        out = Path(o['out'])
        out.mkdir(parents=True, exist_ok=True)

        rows = [json.loads(l) for l in open(o['data'], encoding='utf-8')]
        groups, singles = _groups(rows)
        topics = sorted({g['topic'] for g in groups if g['topic']})
        rng.shuffle(topics)
        dev_topics = set(topics[:max(1, int(len(topics) * o['dev_frac']))])
        train = [g for g in groups if g['topic'] not in dev_topics]
        dev = [g for g in groups if g['topic'] in dev_topics]
        self.stdout.write(f'groups: train {len(train)}  dev {len(dev)}  feedback pairs {len(singles)}')

        ce = CrossEncoder(o['base'], device='cpu', max_length=o['max_length'])
        model, tok = ce.model, ce.tokenizer
        base = getattr(model, model.base_model_prefix)
        frozen = 0
        if o['freeze_layers'] > 0:
            for prm in base.embeddings.parameters():
                prm.requires_grad = False
            for layer in base.encoder.layer[:o['freeze_layers']]:
                for prm in layer.parameters():
                    prm.requires_grad = False
            frozen = o['freeze_layers']
        n_train = sum(p.numel() for p in model.parameters() if p.requires_grad)
        self.stdout.write(f'trainable params: {n_train / 1e6:.0f}M '
                          f'(frozen: embeddings + {frozen}/{len(base.encoder.layer)} layers)')

        def logits(pairs):
            enc = tok([q for q, _ in pairs], [p for _, p in pairs], truncation=True,
                      max_length=o['max_length'], padding=True, return_tensors='pt')
            return model(**enc).logits.view(-1)

        @torch.no_grad()
        def dev_metrics():
            model.eval()
            hit1 = mrr = 0.0
            for g in dev:
                cands = [g['pos']] + g['neg'][:o['max_neg']]
                s = logits([(g['pos']['query'], c['passage']) for c in cands]).tolist()
                rank = 1 + sum(x > s[0] for x in s[1:])
                hit1 += rank == 1
                mrr += 1.0 / rank
            n = max(1, len(dev))
            return {'hit1': round(hit1 / n, 4), 'mrr': round(mrr / n, 4), 'n': len(dev)}

        before = dev_metrics()
        self.stdout.write(f'dev before: {before}')

        model.train()
        opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                                lr=o['lr'], weight_decay=0.01)
        steps = math.ceil(len(train) * o['epochs'] / o['groups_per_step'])
        warm = max(1, steps // 10)
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt, lambda s: min(1.0, (s + 1) / warm) * max(0.0, (steps - s) / max(1, steps - warm)))
        ce_loss = torch.nn.CrossEntropyLoss()
        bce = torch.nn.BCEWithLogitsLoss()
        order = []
        while len(order) < steps * o['groups_per_step']:
            chunk = train[:]
            rng.shuffle(chunk)
            order += chunk
        t0 = time.time()
        for step in range(steps):
            batch = order[step * o['groups_per_step']:(step + 1) * o['groups_per_step']]
            loss = 0.0
            for g in batch:
                negs = g['neg'][:]
                rng.shuffle(negs)
                cands = [g['pos']] + negs[:o['max_neg']]
                z = logits([(g['pos']['query'], c['passage']) for c in cands])
                loss = loss + ce_loss(z.unsqueeze(0), torch.zeros(1, dtype=torch.long))
            if singles:
                s = rng.choice(singles)
                z = logits([(s['query'], s['passage'])])
                loss = loss + bce(z, torch.tensor([float(s['label'])]))
            loss = loss / len(batch)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            if (step + 1) % 20 == 0 or step == 0:
                el = time.time() - t0
                self.stdout.write(f'  step {step + 1}/{steps}  loss {float(loss):.4f}  '
                                  f'{el / (step + 1):.1f}s/step  eta {el / (step + 1) * (steps - step - 1) / 60:.0f}m')

        after = dev_metrics()
        self.stdout.write(f'dev after: {after}')
        model.eval()
        ce.save(str(out))
        (out / 'kg_training.json').write_text(json.dumps({
            'base': o['base'], 'data': os.path.abspath(o['data']), 'steps': steps,
            'epochs': o['epochs'], 'lr': o['lr'], 'max_length': o['max_length'],
            'frozen_layers': frozen, 'trainable_params': n_train,
            'groups_train': len(train), 'groups_dev': len(dev), 'feedback_pairs': len(singles),
            'dev_before': before, 'dev_after': after, 'seconds': round(time.time() - t0, 1),
        }, indent=2))
        self.stdout.write(self.style.SUCCESS(f'saved -> {out}'))
