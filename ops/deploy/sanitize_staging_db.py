#!/usr/bin/env python3
"""Sanitize the staging copy of the production database.

Staging exists to run the real code against real data shapes, which means it
holds a copy of real customers: phone numbers, e-mail addresses, password
hashes and live session tokens. The copy already runs with SMS, Sentry, Metis
and host jobs disabled, so it cannot message anyone — but a staging box that
holds usable credentials is a second copy of the thing most worth stealing,
and a session token lifted from it would work against production.

This rewrites the copy in place before anything is served from it:

  * phone numbers  -> a deterministic fake that keeps the format and length,
                      so code that validates or formats them still exercises
                      the same paths
  * e-mail addresses -> user<id>@staging.invalid (.invalid can never resolve)
  * password hashes  -> an unusable sentinel; nobody can authenticate as a
                      real user on staging, by password or by old token
  * session tokens, OTP challenges, invites, known devices -> deleted
  * audit/activity IP addresses -> masked to the /24

What it deliberately keeps: row counts, foreign keys, grants, company
structure, vehicle data, traffic rollups. Staging has to stay representative;
the point is to remove what identifies a person or opens a door, not to
produce an empty database.

It is written against the schema as it is, not as it was assumed to be: every
table and column is checked before it is touched, so a model change makes this
skip that table rather than crash a deploy. Tables it has never heard of are
reported, because an unknown table holding a phone column is exactly the thing
that should not pass quietly.

    ops/deploy/sanitize_staging_db.py <db-path>
    ops/deploy/sanitize_staging_db.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys


# Columns that must never survive in a staging copy, by intent.
MASK_PHONE = 'phone'
MASK_EMAIL = 'email'
KILL_HASH = 'password_hash'
MASK_IP = 'ip'

# Tables whose whole purpose is to hold a credential or a one-time secret.
PURGE_TABLES = (
    'api_authtoken',
    'api_adminauthtoken',
    'api_otpchallenge',
    'api_adminotpchallenge',
    'api_invitetoken',
    'api_nodeinvite',
    'api_knowndevice',
    'api_retireddevice',
)

# Columns to rewrite, per table. Checked against the live schema first.
MASK_COLUMNS = {
    'api_portaluser': {MASK_PHONE: 'phone', MASK_EMAIL: 'email', KILL_HASH: 'password_hash'},
    'api_platformadmin': {MASK_PHONE: 'phone', KILL_HASH: 'password_hash'},
    'api_companycaraccess': {MASK_PHONE: 'phone', MASK_EMAIL: 'email'},
    'api_nodepermission': {MASK_EMAIL: 'email'},
    'api_activitylog': {MASK_PHONE: 'phone', KILL_HASH: 'password_hash'},
    'api_auditlog': {MASK_IP: 'ip'},
    # Django's own user table: the admin site's superusers live here, and its
    # hash column is called `password`, not `password_hash`.
    'auth_user': {MASK_EMAIL: 'email', KILL_HASH: 'password'},
}

UNUSABLE_HASH = 'staging-sanitized-no-login'


def fake_phone(seed: str, length: int = 11) -> str:
    """Deterministic, format-preserving, and never a real number.

    Iranian mobile numbers start 09; keeping that prefix means validation and
    formatting code still takes its normal path. The digits after it are a
    hash of the row id, so the same row sanitizes to the same value on every
    deploy — which keeps staging diffs readable.
    """
    digest = hashlib.sha256(f'kgkg-staging:{seed}'.encode()).hexdigest()
    digits = ''.join(ch for ch in digest if ch.isdigit())
    while len(digits) < length:
        digits += digits or '0'
    return '09' + digits[: max(length - 2, 0)]


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = con.execute(f'PRAGMA table_info("{table}")').fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {r[1] for r in rows}


def existing_tables(con: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def sanitize(con: sqlite3.Connection, verbose: bool = True) -> dict[str, int]:
    """Rewrite the copy in place. Returns a per-action row count."""
    report: dict[str, int] = {}
    tables = existing_tables(con)

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    # 1. Credential tables: emptied, not masked. Nothing in them has any
    #    legitimate use on staging, and the QA token is minted after this runs.
    for table in PURGE_TABLES:
        if table not in tables:
            continue
        n = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        con.execute(f'DELETE FROM "{table}"')
        report[f'purged:{table}'] = n
        log(f'  purged {n:>7} rows from {table}')

    # 2. Identifying columns, masked in place.
    for table, intents in MASK_COLUMNS.items():
        if table not in tables:
            continue
        cols = table_columns(con, table)
        pk = 'id' if 'id' in cols else None
        for intent, column in intents.items():
            if column not in cols:
                continue
            if intent == MASK_PHONE:
                rows = con.execute(
                    f'SELECT rowid, "{column}" FROM "{table}" '
                    f'WHERE "{column}" IS NOT NULL AND "{column}" != ""'
                ).fetchall()
                for rowid, value in rows:
                    con.execute(
                        f'UPDATE "{table}" SET "{column}" = ? WHERE rowid = ?',
                        (fake_phone(f'{table}:{rowid}', max(len(str(value)), 11)), rowid),
                    )
                n = len(rows)
            elif intent == MASK_EMAIL:
                key = pk or 'rowid'
                n = con.execute(
                    f'UPDATE "{table}" SET "{column}" = '
                    f"'user' || {key} || '@staging.invalid' "
                    f'WHERE "{column}" IS NOT NULL AND "{column}" != ""'
                ).rowcount
            elif intent == KILL_HASH:
                n = con.execute(
                    f'UPDATE "{table}" SET "{column}" = ? '
                    f'WHERE "{column}" IS NOT NULL AND "{column}" != ""',
                    (UNUSABLE_HASH,),
                ).rowcount
            elif intent == MASK_IP:
                # Keep the /24 so traffic-shape debugging still works: strip
                # the trailing octet's digits and put a zero back. Guarded to
                # dotted-quad values, so IPv6 is left alone rather than
                # mangled.
                n = con.execute(
                    f'UPDATE "{table}" SET "{column}" = '
                    f"rtrim(\"{column}\", '0123456789') || '0' "
                    f"WHERE \"{column}\" LIKE '%.%.%.%'"
                ).rowcount
            else:                                  # pragma: no cover - guarded by dict
                raise AssertionError(f'unknown intent {intent}')
            report[f'{intent}:{table}.{column}'] = n
            log(f'  {intent:14} {n:>7} rows in {table}.{column}')

    con.commit()
    return report


def sanitize_pg(dsn: str, verbose: bool = True) -> tuple[dict[str, int], list[str]]:
    """The same rules against a PostgreSQL staging copy (KG_DB_ENGINE=postgres).

    Same tables, same columns, same deterministic fake phones as the SQLite
    path, so staging looks the same whichever engine production runs on.
    Returns (report, unknown-identifying-columns)."""
    import psycopg

    report: dict[str, int] = {}

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    with psycopg.connect(dsn) as con, con.cursor() as cur:
        cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public'")
        schema: dict[str, set[str]] = {}
        for t, c in cur.fetchall():
            schema.setdefault(t, set()).add(c)

        for table in PURGE_TABLES:
            if table not in schema:
                continue
            cur.execute(f'DELETE FROM "{table}"')
            report[f'purged:{table}'] = cur.rowcount
            log(f'  purged {cur.rowcount:>7} rows from {table}')

        for table, intents in MASK_COLUMNS.items():
            cols = schema.get(table)
            if not cols or 'id' not in cols:
                continue
            for intent, column in intents.items():
                if column not in cols:
                    continue
                if intent == MASK_PHONE:
                    cur.execute(f'SELECT id, "{column}" FROM "{table}" '
                                f'WHERE "{column}" IS NOT NULL AND "{column}" <> %s', ('',))
                    rows = cur.fetchall()
                    # seeded by id: the SQLite path seeds by rowid, which is id there
                    cur.executemany(f'UPDATE "{table}" SET "{column}" = %s WHERE id = %s',
                                    [(fake_phone(f'{table}:{rid}', max(len(str(v)), 11)), rid)
                                     for rid, v in rows])
                    n = len(rows)
                elif intent == MASK_EMAIL:
                    cur.execute(f'UPDATE "{table}" SET "{column}" = %s::text || id::text || %s::text '
                                f'WHERE "{column}" IS NOT NULL AND "{column}" <> %s',
                                ('user', '@staging.invalid', ''))
                    n = cur.rowcount
                elif intent == KILL_HASH:
                    cur.execute(f'UPDATE "{table}" SET "{column}" = %s '
                                f'WHERE "{column}" IS NOT NULL AND "{column}" <> %s', (UNUSABLE_HASH, ''))
                    n = cur.rowcount
                elif intent == MASK_IP:
                    # keep the /24, like the SQLite path; dotted quads only
                    cur.execute(f'UPDATE "{table}" SET "{column}" = '
                                f'regexp_replace("{column}", %s, %s) WHERE "{column}" ~ %s',
                                (r'\.[0-9]+$', '.0', r'^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'))
                    n = cur.rowcount
                else:                              # pragma: no cover
                    raise AssertionError(f'unknown intent {intent}')
                report[f'{intent}:{table}.{column}'] = n
                log(f'  {intent:14} {n:>7} rows in {table}.{column}')

        known = set(MASK_COLUMNS) | set(PURGE_TABLES)
        unknown = []
        for table in sorted(schema):
            if table in known:
                continue
            risky = {c for c in schema[table]
                     if c in ('phone', 'email', 'password', 'password_hash', 'key_hash')
                     or c.endswith('_phone') or c.endswith('_email')}
            if risky:
                unknown.append(f'{table}: {", ".join(sorted(risky))}')
        con.commit()
    return report, unknown


def audit_unknown(con: sqlite3.Connection) -> list[str]:
    """Tables with an identifying column that this script does not handle.

    A new model holding a phone number is exactly the kind of change that
    should not reach staging unnoticed.
    """
    known = set(MASK_COLUMNS) | set(PURGE_TABLES)
    suspicious = []
    for table in sorted(existing_tables(con)):
        if table in known or table.startswith('sqlite_'):
            continue
        cols = table_columns(con, table)
        risky = {c for c in cols
                 if c in ('phone', 'email', 'password', 'password_hash', 'key_hash')
                 or c.endswith('_phone') or c.endswith('_email')}
        if risky:
            suspicious.append(f'{table}: {", ".join(sorted(risky))}')
    return suspicious


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('db', nargs='?', help='path to the staging database copy')
    ap.add_argument('--pg', metavar='DSN',
                    help='sanitize a PostgreSQL staging copy instead (libpq DSN, e.g. "dbname=kgkg_staging")')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--strict-audit', action='store_true',
                    help='fail if an unhandled identifying column exists')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.pg:
        if not args.quiet:
            print(f'sanitizing PostgreSQL staging copy {args.pg}')
        _, unknown = sanitize_pg(args.pg, verbose=not args.quiet)
    else:
        if not args.db:
            ap.error('a database path (or --pg DSN) is required')
        con = sqlite3.connect(args.db)
        try:
            if not args.quiet:
                print(f'sanitizing staging copy {args.db}')
            sanitize(con, verbose=not args.quiet)
            unknown = audit_unknown(con)
        finally:
            con.close()

    if unknown:
        print('\nWARNING: identifying columns this script does not handle:')
        for line in unknown:
            print(f'  {line}')
        print('Add them to MASK_COLUMNS in ops/deploy/sanitize_staging_db.py.')
        if args.strict_audit:
            return 1
    if not args.quiet:
        print('staging copy sanitized')
    return 0


def selftest() -> int:
    """Build a miniature of the real schema, sanitize it, and assert on the
    result. Runs in CI, so a regression here fails before a deploy does."""
    failures: list[str] = []

    def expect(label, got, want):
        if got != want:
            failures.append(f'{label}: got {got!r}, want {want!r}')

    con = sqlite3.connect(':memory:')
    con.executescript(
        """
        CREATE TABLE api_portaluser (id INTEGER PRIMARY KEY, username TEXT,
            phone TEXT, email TEXT, password_hash TEXT);
        CREATE TABLE api_authtoken (id INTEGER PRIMARY KEY, key_hash TEXT);
        CREATE TABLE api_auditlog (id INTEGER PRIMARY KEY, ip TEXT);
        CREATE TABLE api_car (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE api_newthing (id INTEGER PRIMARY KEY, phone TEXT);
        INSERT INTO api_portaluser VALUES
            (1, 'qa_e_root', '09121234567', 'real@example.com', 'argon2$real'),
            (2, 'someone',   '09351112222', 'other@example.com', 'argon2$other');
        INSERT INTO api_authtoken VALUES (1, 'abc'), (2, 'def');
        INSERT INTO api_auditlog VALUES (1, '203.0.113.42'), (2, '::1');
        INSERT INTO api_car VALUES (1, 'Corolla');
        INSERT INTO api_newthing VALUES (1, '09120000000');
        """
    )
    sanitize(con, verbose=False)

    rows = dict(con.execute('SELECT id, phone FROM api_portaluser'))
    for user_id, phone in rows.items():
        if phone in ('09121234567', '09351112222'):
            failures.append(f'user {user_id} kept a real phone number')
        if not phone.startswith('09'):
            failures.append(f'user {user_id} phone lost its format: {phone}')
        expect(f'user {user_id} phone length', len(phone), 11)

    # Deterministic across runs, so staging diffs stay readable.
    con2 = sqlite3.connect(':memory:')
    con2.executescript(
        """CREATE TABLE api_portaluser (id INTEGER PRIMARY KEY, username TEXT,
               phone TEXT, email TEXT, password_hash TEXT);
           INSERT INTO api_portaluser VALUES
               (1, 'qa_e_root', '09121234567', 'real@example.com', 'argon2$real');"""
    )
    sanitize(con2, verbose=False)
    expect('phone masking is deterministic',
           con2.execute('SELECT phone FROM api_portaluser WHERE id=1').fetchone(),
           con.execute('SELECT phone FROM api_portaluser WHERE id=1').fetchone())

    expect('emails replaced',
           con.execute('SELECT email FROM api_portaluser WHERE id=1').fetchone()[0],
           'user1@staging.invalid')
    expect('password hashes unusable',
           {r[0] for r in con.execute('SELECT password_hash FROM api_portaluser')},
           {UNUSABLE_HASH})
    expect('session tokens purged',
           con.execute('SELECT count(*) FROM api_authtoken').fetchone()[0], 0)
    expect('users kept (staging must stay representative)',
           con.execute('SELECT count(*) FROM api_portaluser').fetchone()[0], 2)
    expect('usernames kept (the QA user must still exist)',
           con.execute(
               "SELECT count(*) FROM api_portaluser WHERE username='qa_e_root'"
           ).fetchone()[0], 1)
    expect('business data untouched',
           con.execute('SELECT name FROM api_car').fetchone()[0], 'Corolla')
    expect('ipv4 masked to the /24',
           con.execute('SELECT ip FROM api_auditlog WHERE id=1').fetchone()[0],
           '203.0.113.0')
    expect('non-ipv4 left alone',
           con.execute('SELECT ip FROM api_auditlog WHERE id=2').fetchone()[0], '::1')

    unknown = audit_unknown(con)
    if not any('api_newthing' in u for u in unknown):
        failures.append('audit missed an unhandled table with a phone column')
    if any('api_car' in u for u in unknown):
        failures.append('audit flagged a table with no identifying column')

    # A missing table must be skipped, not fatal.
    con3 = sqlite3.connect(':memory:')
    con3.executescript('CREATE TABLE api_car (id INTEGER PRIMARY KEY, name TEXT);')
    try:
        sanitize(con3, verbose=False)
    except Exception as exc:                       # noqa: BLE001
        failures.append(f'sanitizing a partial schema raised {exc!r}')

    if failures:
        for f in failures:
            print(f'SELFTEST FAIL: {f}')
        return 1
    print('sanitizer selftest: all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
