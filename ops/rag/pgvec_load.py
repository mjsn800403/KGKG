"""Mirror the served RAG vectors (sqlite-vec int8[1024]) into PostgreSQL/pgvector.

Cosine is scale-invariant, so the int8 codes are stored as-is (no dequantize).
Then builds an HNSW index (vector_cosine_ops) and records timings.
"""
import json, sqlite3, sys, time
import numpy as np
import psycopg
import sqlite_vec

SRC = '/opt/KGKG/KG_backend/Database_warehouse/_rag/index.rag.db'
src = sqlite3.connect(f'file:{SRC}?mode=ro', uri=True)
src.enable_load_extension(True); sqlite_vec.load(src)

pg = psycopg.connect('dbname=kgkg_vec', autocommit=True)
pg.execute('DROP TABLE IF EXISTS blob_vec')
pg.execute('CREATE TABLE blob_vec (blob_id integer PRIMARY KEY, embedding vector(1024) NOT NULL)')
t0 = time.time(); n = 0
with pg.cursor().copy('COPY blob_vec (blob_id, embedding) FROM STDIN') as cp:
    for bid, emb in src.execute('SELECT rowid, embedding FROM vec_blobs'):
        v = np.frombuffer(emb, dtype=np.int8)
        cp.write_row((bid, '[' + ','.join(map(str, v.tolist())) + ']'))
        n += 1
        if n % 50000 == 0:
            print(f'{n} rows {time.time()-t0:.0f}s', flush=True)
load_s = time.time() - t0
print(f'loaded {n} in {load_s:.0f}s', flush=True)

t1 = time.time()
pg.execute("SET maintenance_work_mem = '3GB'")
pg.execute('SET max_parallel_maintenance_workers = 4')
pg.execute('CREATE INDEX blob_vec_hnsw ON blob_vec USING hnsw (embedding vector_cosine_ops) WITH (m = 32, ef_construction = 200)')
idx_s = time.time() - t1
pg.execute('ANALYZE blob_vec')
pg.execute('GRANT SELECT ON blob_vec TO kgkg')
size = pg.execute("select pg_size_pretty(pg_total_relation_size('blob_vec'))").fetchone()[0]
out = {'rows': n, 'load_s': round(load_s), 'hnsw_build_s': round(idx_s), 'size': size}
print(json.dumps(out), flush=True)
json.dump(out, open('/root/pgvec/load.json', 'w'))
