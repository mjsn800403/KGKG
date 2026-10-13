"""Copy a small, PII-light slice of the live Django DB into a separate SQLite
file that Grafana reads (ops/observability, datasource "bizdb").

Grafana never touches db.sqlite3 itself: no password hashes, chat text or
phones leave the app DB. Runs every 5 min from kgkg-bizsnap.timer; the target
is rewritten through the SQLite backup API so open readers stay consistent.
"""
import sqlite3

SRC = 'file:/opt/KGKG/KG_backend/db.sqlite3?mode=ro'
DST = '/opt/observability/bizdb/biz.sqlite'
TS = "CAST(strftime('%s', {c}) AS INTEGER)"

TABLES = {
    'users': f"""SELECT id, company_id, role, active, invite_status, otp_enabled,
                 {TS.format(c='created_at')} AS created_ts,
                 {TS.format(c='last_login_at')} AS last_login_ts FROM api_portaluser""",
    'audit': f"""SELECT {TS.format(c='created_at')} AS ts, action, actor_type, outcome,
                 status_code, ip FROM api_auditlog""",
    'chat': f"""SELECT {TS.format(c='created_at')} AS ts, company_id, mode, grounded, degraded,
                input_tokens, output_tokens, llm_cost, latency_ms, llm_latency_ms FROM api_chatlog""",
    'search': f"""SELECT {TS.format(c='created_at')} AS ts, company_id, query_norm, car,
                  results, latency_ms FROM api_searchlog""",
}

src = sqlite3.connect(SRC, uri=True)
mem = sqlite3.connect(':memory:')
for name, sql in TABLES.items():
    cur = src.execute(sql)
    cols = [d[0] for d in cur.description]
    mem.execute(f'CREATE TABLE {name} ({", ".join(cols)})')
    mem.executemany(f'INSERT INTO {name} VALUES ({", ".join("?" * len(cols))})', cur)
    if 'ts' in cols:
        mem.execute(f'CREATE INDEX {name}_ts ON {name}(ts)')
mem.commit()
dst = sqlite3.connect(DST)
mem.backup(dst)
dst.close()
