"""Load the RAG search index (pages, occurrences, graph) into PostgreSQL and build
the BM25 keyword index used by api/rag/pgfts.py (RAG_FTS_BACKEND=pg).

    /root/pgmig/venv/bin/python ops/rag/pgfts_load.py [/path/to/index.rag.db]

Target: database kgkg_vec (same as pgvector), schema rag, built under rag_new
and swapped in at the end so a running site never sees a half-built index.

BM25 = SQLite FTS5's own formula, so rankings stay comparable: per term,
  idf = max(1e-6, ln((N - df + 0.5) / (df + 0.5)))
  tf  = w_comp*tf_comp + w_title*tf_title + w_text*tf_text   (column weights)
  score += idf * tf*(k1+1) / (tf + k1*(1 - b + b*dl/avgdl))   k1=1.2 b=0.75
with df = pages containing the term in any column and dl = the page's token count.
Tokenising: PostgreSQL 'english' (Snowball) in place of FTS5's porter.
"""
import json, sqlite3, sys, time
import psycopg

SRC = sys.argv[1] if len(sys.argv) > 1 else '/opt/KGKG/KG_backend/Database_warehouse/_rag/index.rag.db'
S = 'rag_new'


def clean(v):
    return v.replace('\x00', '') if isinstance(v, str) else v


def main():
    t0 = time.time()
    src = sqlite3.connect(f'file:{SRC}?mode=ro', uri=True)
    pg = psycopg.connect('dbname=kgkg_vec', autocommit=True)
    pg.execute(f'DROP SCHEMA IF EXISTS {S} CASCADE')
    pg.execute(f'CREATE SCHEMA {S}')
    pg.execute(f"""CREATE TABLE {S}.blobs (blob_id integer PRIMARY KEY, content_hash text, kind text,
        title text, comp_readable text, text text NOT NULL, n_occ integer)""")
    pg.execute(f"""CREATE TABLE {S}.occurrences (occ_id integer PRIMARY KEY, blob_id integer NOT NULL,
        car_stem text NOT NULL, brand text, model text, variant text, year integer, node_id text NOT NULL,
        title text, title_path text, system_tags text, href text)""")
    pg.execute(f"""CREATE TABLE {S}.cars (car_stem text PRIMARY KEY, brand text, model text, variant text,
        year integer, n_occ integer, built_at text)""")
    pg.execute(f"""CREATE TABLE {S}.edges (src_blob integer NOT NULL, dst_blob integer NOT NULL,
        relation text NOT NULL, weight double precision)""")
    counts = {}
    for t, cols in (('blobs', 'blob_id, content_hash, kind, title, comp_readable, text, n_occ'),
                    ('occurrences', 'occ_id, blob_id, car_stem, brand, model, variant, year, node_id, title, title_path, system_tags, href'),
                    ('cars', 'car_stem, brand, model, variant, year, n_occ, built_at'),
                    ('edges', 'src_blob, dst_blob, relation, weight')):
        n = 0
        with pg.cursor().copy(f'COPY {S}.{t} ({cols}) FROM STDIN') as cp:
            for r in src.execute(f'SELECT {cols} FROM {t}'):
                cp.write_row([clean(v) for v in r]); n += 1
        counts[t] = [src.execute(f'SELECT count(*) FROM {t}').fetchone()[0], n]
        print(t, n, f'{time.time() - t0:.0f}s', flush=True)
    pg.execute(f'CREATE INDEX ON {S}.occurrences (car_stem, blob_id)')
    pg.execute(f'CREATE INDEX ON {S}.occurrences (blob_id)')
    pg.execute(f'CREATE INDEX ON {S}.edges (src_blob)')
    pg.execute('SET max_parallel_workers_per_gather = 4')
    pg.execute("SET work_mem = '256MB'")
    pg.execute(f"""CREATE UNLOGGED TABLE {S}.tv AS SELECT blob_id,
        to_tsvector('english', coalesce(comp_readable, '')) c,
        to_tsvector('english', coalesce(title, '')) t,
        to_tsvector('english', left(text, 400000)) x FROM {S}.blobs""")
    print('tsvectors', f'{time.time() - t0:.0f}s', flush=True)
    pg.execute(f"""CREATE TABLE {S}.terms AS
        SELECT lexeme, blob_id, sum(tc)::smallint tf_comp, sum(tt)::smallint tf_title, sum(tx)::smallint tf_text FROM (
          SELECT blob_id, (unnest(c)).lexeme, array_length((unnest(c)).positions, 1) tc, 0 tt, 0 tx FROM {S}.tv
          UNION ALL SELECT blob_id, (unnest(t)).lexeme, 0, array_length((unnest(t)).positions, 1), 0 FROM {S}.tv
          UNION ALL SELECT blob_id, (unnest(x)).lexeme, 0, 0, array_length((unnest(x)).positions, 1) FROM {S}.tv
        ) z GROUP BY lexeme, blob_id""")
    print('terms', f'{time.time() - t0:.0f}s', flush=True)
    pg.execute(f'CREATE INDEX terms_lexeme ON {S}.terms (lexeme) INCLUDE (blob_id, tf_comp, tf_title, tf_text)')
    pg.execute(f"""CREATE TABLE {S}.doclen AS SELECT blob_id,
        sum(tf_comp + tf_title + tf_text)::real dl FROM {S}.terms GROUP BY blob_id""")
    pg.execute(f'ALTER TABLE {S}.doclen ADD PRIMARY KEY (blob_id)')
    pg.execute(f'CREATE TABLE {S}.df AS SELECT lexeme, count(*)::integer df FROM {S}.terms GROUP BY lexeme')
    pg.execute(f'ALTER TABLE {S}.df ADD PRIMARY KEY (lexeme)')
    pg.execute(f"CREATE TABLE {S}.stats AS SELECT count(*)::float8 n, avg(dl)::float8 avgdl FROM {S}.doclen")
    pg.execute(f'DROP TABLE {S}.tv')
    pg.execute(f'ANALYZE')
    for t in ('blobs', 'occurrences', 'cars', 'edges'):
        counts[t][1] = pg.execute(f'SELECT count(*) FROM {S}.{t}').fetchone()[0]
        assert counts[t][0] == counts[t][1], (t, counts[t])
    # swap in atomically
    with pg.transaction():
        pg.execute('DROP SCHEMA IF EXISTS rag CASCADE')
        pg.execute(f'ALTER SCHEMA {S} RENAME TO rag')
    pg.execute('GRANT USAGE ON SCHEMA rag TO kgkg')
    pg.execute('GRANT SELECT ON ALL TABLES IN SCHEMA rag TO kgkg')
    out = {'counts_sqlite_vs_pg': counts,
           'terms': pg.execute('SELECT count(*) FROM rag.terms').fetchone()[0],
           'lexemes': pg.execute('SELECT count(*) FROM rag.df').fetchone()[0],
           'size': pg.execute("SELECT pg_size_pretty(sum(pg_total_relation_size(c.oid))) FROM pg_class c "
                              "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rag'").fetchone()[0],
           'seconds': round(time.time() - t0)}
    print(json.dumps(out, indent=2), flush=True)


if __name__ == '__main__':
    main()
