"""Copy a small, PII-light slice of the live Django DB into a separate SQLite
file that Grafana reads (ops/observability, datasource "bizdb").

Grafana never touches db.sqlite3 itself: no password hashes, chat text or
phones leave the app DB. Runs every 5 min from kgkg-bizsnap.timer; the target
is rewritten through the SQLite backup API so open readers stay consistent.
"""
import sqlite3

ENV_FILE = '/opt/KGKG/KG_backend/.env.prod'
SRC = 'file:/opt/KGKG/KG_backend/db.sqlite3?mode=ro'
DST = '/opt/observability/bizdb/biz.sqlite'


def _env(name, default=''):
    try:
        with open(ENV_FILE) as fh:
            for line in fh:
                if line.startswith(name + '='):
                    return line.split('=', 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return default


# The portal DB is PostgreSQL once KG_DB_ENGINE=postgres (read here through
# the local socket as root, peer auth); before that it is the SQLite file.
PG = _env('KG_DB_ENGINE', 'sqlite').lower() in ('postgres', 'postgresql')

def _ensure_psycopg():
    """System python3 has no psycopg; the backend venv does. Re-run under it."""
    try:
        import psycopg  # noqa: F401
    except ImportError:
        import os, sys
        venv = '/opt/KGKG/KG_backend/.venv/bin/python'
        if sys.executable != venv and os.path.exists(venv):
            os.execv(venv, [venv, *sys.argv])
        raise


TS = ("CAST(EXTRACT(EPOCH FROM {c}) AS BIGINT)" if PG
      else "CAST(strftime('%s', {c}) AS INTEGER)")

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

if PG:
    _ensure_psycopg()
    import psycopg
    src = psycopg.connect(dbname=_env('KG_PG_NAME', 'kgkg'))
    src.read_only = True
else:
    src = sqlite3.connect(SRC, uri=True)
mem = sqlite3.connect(':memory:')
for name, sql in TABLES.items():
    cur = src.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    mem.execute(f'CREATE TABLE {name} ({", ".join(cols)})')
    # PostgreSQL returns real booleans/Decimals; SQLite stores ints/floats
    rows = ([int(v) if isinstance(v, bool) else (float(v) if v.__class__.__name__ == 'Decimal' else v)
             for v in r] for r in cur.fetchall())
    mem.executemany(f'INSERT INTO {name} VALUES ({", ".join("?" * len(cols))})', rows)
    if 'ts' in cols:
        mem.execute(f'CREATE INDEX {name}_ts ON {name}(ts)')
mem.commit()
dst = sqlite3.connect(DST)
mem.backup(dst)
dst.close()
