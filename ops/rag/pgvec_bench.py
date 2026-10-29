"""sqlite-vec (exact scan) vs pgvector HNSW: recall@40 and latency.

Queries: 200 random page vectors from the index itself (the page is excluded
from its own result list). Ground truth = sqlite-vec exact top-40.
Also a concurrency run: N parallel clients, each its own connection.
"""
import json, random, sqlite3, statistics as st, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, psycopg, sqlite_vec

SRC = '/opt/KGKG/KG_backend/Database_warehouse/_rag/index.rag.db'
K = 40


def sconn():
    c = sqlite3.connect(f'file:{SRC}?mode=ro', uri=True, check_same_thread=False)
    c.enable_load_extension(True); sqlite_vec.load(c)
    return c


s = sconn()
maxid = s.execute('select max(rowid) from vec_blobs_rowids').fetchone()[0]
random.seed(7)
qs = []
while len(qs) < 200:
    r = s.execute('select rowid, embedding from vec_blobs where rowid=?', (random.randint(1, maxid),)).fetchone()
    if r:
        qs.append((r[0], np.frombuffer(r[1], dtype=np.int8).astype(np.float32)))


def s_knn(c, v):
    return [b for b, in c.execute(
        "select rowid from vec_blobs where embedding match vec_quantize_int8(vec_f32(?),'unit') and k=? order by distance",
        (v.tobytes(), K + 1)).fetchall()]


def p_conn(ef):
    c = psycopg.connect('dbname=kgkg_vec', autocommit=True)
    c.execute(f'SET hnsw.ef_search = {ef}')
    return c


def p_knn(c, v):
    lit = '[' + ','.join(str(int(x)) for x in v) + ']'
    return [b for b, in c.execute('select blob_id from blob_vec order by embedding <=> %s::vector limit %s', (lit, K + 1)).fetchall()]


def pct(xs, p):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(len(xs) * p))]


out = {'queries': len(qs), 'k': K}
truth, ts = {}, []
for bid, v in qs:
    t = time.perf_counter(); r = s_knn(s, v); ts.append((time.perf_counter() - t) * 1000)
    truth[bid] = [x for x in r if x != bid][:K]
out['sqlite_vec_exact'] = {'p50_ms': round(st.median(ts), 1), 'p95_ms': round(pct(ts, .95), 1)}
print(out, flush=True)

for ef in (40, 100, 200):
    c = p_conn(ef); ts = []; rec = []
    for bid, v in qs:
        t = time.perf_counter(); r = p_knn(c, v); ts.append((time.perf_counter() - t) * 1000)
        r = [x for x in r if x != bid][:K]
        rec.append(len(set(r) & set(truth[bid])) / K)
    out[f'pgvector_hnsw_ef{ef}'] = {'recall@40': round(st.mean(rec), 4),
                                   'p50_ms': round(st.median(ts), 1), 'p95_ms': round(pct(ts, .95), 1)}
    print(out, flush=True)


def load(name, mk, fn, n):
    def worker(i):
        c = mk(); lat = []
        for bid, v in qs[i::n]:
            t = time.perf_counter(); fn(c, v); lat.append((time.perf_counter() - t) * 1000)
        return lat
    t0 = time.perf_counter()
    with ThreadPoolExecutor(n) as ex:
        lat = sum(ex.map(worker, range(n)), [])
    wall = time.perf_counter() - t0
    return {'clients': n, 'qps': round(len(lat) / wall, 1), 'p95_ms': round(pct(lat, .95), 1)}


out['concurrency'] = []
for n in (1, 4, 8):
    out['concurrency'].append({'sqlite_vec': load('s', sconn, s_knn, n),
                               'pgvector_ef100': load('p', lambda: p_conn(100), p_knn, n)})
    print(out['concurrency'][-1], flush=True)
json.dump(out, open('/root/pgvec/bench.json', 'w'), indent=2)
print('DONE', flush=True)
