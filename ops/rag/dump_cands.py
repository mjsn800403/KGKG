"""Dump, for every gold question: the live pipeline's top-20 (retrieval order)
and the KG-Reranker score of each candidate. Fusion weights are then swept
offline (fusion_sweep.py) instead of one 2-hour eval run per weight.

    cd KG_backend && python /root/novelty_eval/dump_cands.py <out.jsonl>
"""
import json, os, sys, time
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KG_backend.settings')
import django; django.setup()

from sentence_transformers import CrossEncoder
from api.rag import config, store
from api.evalsuite import goldset, baselines
from api.management.commands.run_evalsuite import _embed_for

N = config.RERANK_CANDIDATES
ce = CrossEncoder(os.environ['RAG_RERANK_MODEL'], device='cpu', max_length=512)
from pathlib import Path
gold_dir = Path(config.INDEX_DB).parent / 'eval' / 'gold'
index = store.get_index_ro()
# resumable: questions already in the file are skipped, new ones appended
done = set()
if os.path.exists(sys.argv[1]):
    for l in open(sys.argv[1], encoding='utf-8'):
        try:
            r = json.loads(l); done.add((r['set'], r['query'], r['car']))
        except ValueError:
            pass
out = open(sys.argv[1], 'a', encoding='utf-8')
t0 = time.time()
for name in ('known_item_en', 'known_item_fa', 'known_item_fa_rev'):
    for i, row in enumerate(goldset.read_jsonl(gold_dir / f'{name}.jsonl'), 1):
        rel = row.get('expected_blob_ids') or []
        if not rel or (name, row['query'], row['car']) in done:
            continue
        res = baselines.run_hybrid(index, row['query'], row['car'], k=N,
                                   qvec=_embed_for(row['query'], True))
        hits = res['hits'][:N]
        pairs = [(row['query'], f"{h.get('title') or ''}\n{(h.get('text') or '')[:800]}") for h in hits]
        sc = ce.predict(pairs).tolist() if pairs else []
        out.write(json.dumps({'set': name, 'query': row['query'], 'car': row['car'], 'rel': rel,
                              'cands': [{'blob_id': h['blob_id'], 'score': h.get('score'), 'ce': s}
                                        for h, s in zip(hits, sc)]}, ensure_ascii=False) + '\n')
        out.flush()
        if i % 25 == 0:
            print(f'{name} {i} {time.time() - t0:.0f}s', flush=True)
print('DONE', flush=True)
