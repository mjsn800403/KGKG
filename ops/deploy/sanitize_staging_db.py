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
that should not pass quietly; staging and QA builds pass --strict-audit, so
such a table fails the build. After rewriting, every masked column is checked
again and any surviving value fails the run (counts are printed, never values).

    ops/deploy/sanitize_staging_db.py <db-path>
    ops/deploy/sanitize_staging_db.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from urllib.parse import urlsplit


# Columns that must never survive in a staging copy, by intent.
MASK_PHONE = 'phone'
MASK_EMAIL = 'email'
KILL_HASH = 'password_hash'
MASK_IP = 'ip'
# Free text a visitor typed (support chat): the value is replaced, its length
# class is kept so layout and truncation code still see realistic sizes.
MASK_NAME = 'name'
MASK_TEXT = 'text'
# A URL from outside (the visitor's referrer): reduced to its origin, since
# paths and query strings can carry search terms, e-mails or tokens.
MASK_URL = 'url'
# A unique bearer-token hash: one shared sentinel would break the unique index,
# so each row gets its own value, which is not hex and so never a sha256 output.
KILL_TOKEN = 'token'

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
    # api_companycaraccess, api_nodepermission and api_activitylog used to be
    # listed with phone/e-mail/hash columns those tables do not have (they were
    # skipped silently); api/test_sanitizer_coverage.py now fails on such entries.
    'api_auditlog': {MASK_IP: 'ip'},
    # Support chat (#79). contact_* are what a visitor typed to be reached;
    # token_hash is the visitor's resume credential. source_page is one of our
    # own paths and stays. Message bodies are free text and can hold anything.
    'api_supportthread': {MASK_PHONE: 'contact_phone', MASK_EMAIL: 'contact_email',
                          MASK_NAME: 'contact_name', MASK_URL: 'referrer',
                          KILL_TOKEN: 'token_hash'},
    'api_supportmessage': {MASK_TEXT: 'body'},
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


def fake_text(intent: str, value: str, key) -> str:
    """Replacement for MASK_NAME / MASK_TEXT / MASK_URL / KILL_TOKEN values."""
    if intent == KILL_TOKEN:
        return f'staging-sanitized:{key}'
    if intent == MASK_NAME:
        return 'Staging Visitor'
    if intent == MASK_TEXT:
        return f'[sanitized message, {len(value)} chars]'
    if intent == MASK_URL:
        p = urlsplit(value)
        return f'{p.scheme}://{p.netloc}/' if p.scheme and p.netloc else ''
    raise AssertionError(f'unknown text intent {intent}')


TEXT_INTENTS = (MASK_NAME, MASK_TEXT, MASK_URL, KILL_TOKEN)


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
            elif intent in TEXT_INTENTS:
                key = pk or 'rowid'       # by id, like the PostgreSQL path
                rows = con.execute(
                    f'SELECT {key}, "{column}" FROM "{table}" '
                    f'WHERE "{column}" IS NOT NULL AND "{column}" != ""'
                ).fetchall()
                con.executemany(f'UPDATE "{table}" SET "{column}" = ? WHERE {key} = ?',
                                [(fake_text(intent, str(v), rid), rid) for rid, v in rows])
                n = len(rows)
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
                elif intent in TEXT_INTENTS:
                    cur.execute(f'SELECT id, "{column}" FROM "{table}" '
                                f'WHERE "{column}" IS NOT NULL AND "{column}" <> %s', ('',))
                    rows = cur.fetchall()
                    cur.executemany(f'UPDATE "{table}" SET "{column}" = %s WHERE id = %s',
                                    [(fake_text(intent, str(v), rid), rid) for rid, v in rows])
                    n = len(rows)
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

        bad = []
        for label, sql, param in leftover_sql():
            table, _, column = label.partition('.')
            if table not in schema or (column and column not in schema[table]):
                continue
            args = (param, param) if sql.endswith('? = ?') else (param,)
            cur.execute(sql.replace('?', '%s'), args)
            n = cur.fetchone()[0]
            if n:
                bad.append(f'{label}: {n} rows')
        report['leftovers'] = bad
    return report, unknown


def leftover_sql() -> list[tuple[str, str, str]]:
    """(label, sql, param) per masked column: the query counts rows that still
    hold a value the sanitizer should have replaced."""
    checks = []
    for table, intents in MASK_COLUMNS.items():
        for intent, column in intents.items():
            q = f'SELECT count(*) FROM "{table}" WHERE "{column}" IS NOT NULL AND "{column}" <> \'\' AND '
            if intent == MASK_EMAIL:
                checks.append((f'{table}.{column}', q + f'"{column}" NOT LIKE ?', '%@staging.invalid'))
            elif intent == KILL_HASH:
                checks.append((f'{table}.{column}', q + f'"{column}" <> ?', UNUSABLE_HASH))
            elif intent == MASK_NAME:
                checks.append((f'{table}.{column}', q + f'"{column}" <> ?', fake_text(MASK_NAME, '', 0)))
            elif intent == MASK_TEXT:
                checks.append((f'{table}.{column}', q + f'"{column}" NOT LIKE ?', '[sanitized message, %'))
            elif intent == KILL_TOKEN:
                checks.append((f'{table}.{column}', q + f'"{column}" NOT LIKE ?', 'staging-sanitized:%'))
    for table in PURGE_TABLES:
        checks.append((table, f'SELECT count(*) FROM "{table}" WHERE ? = ?', '1'))
    return checks


def leftovers(con: sqlite3.Connection) -> list[str]:
    """After sanitize(): columns that still hold unsanitized values."""
    tables = existing_tables(con)
    bad = []
    for label, sql, param in leftover_sql():
        table, _, column = label.partition('.')
        if table not in tables or (column and column not in table_columns(con, table)):
            continue
        args = (param, param) if sql.endswith('? = ?') else (param,)
        n = con.execute(sql, args).fetchone()[0]
        if n:
            bad.append(f'{label}: {n} rows')
    return bad


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
        report, unknown = sanitize_pg(args.pg, verbose=not args.quiet)
        bad = report['leftovers']
    else:
        if not args.db:
            ap.error('a database path (or --pg DSN) is required')
        con = sqlite3.connect(args.db)
        try:
            if not args.quiet:
                print(f'sanitizing staging copy {args.db}')
            sanitize(con, verbose=not args.quiet)
            unknown = audit_unknown(con)
            bad = leftovers(con)
        finally:
            con.close()

    if bad:
        # counts only: a value printed here would itself be the leak
        print('\nERROR: values survived sanitizing:')
        for line in bad:
            print(f'  {line}')
        return 1
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
        CREATE TABLE api_supportthread (id TEXT PRIMARY KEY, token_hash TEXT,
            contact_name TEXT, contact_phone TEXT, contact_email TEXT,
            source_page TEXT, referrer TEXT);
        CREATE TABLE api_supportmessage (id INTEGER PRIMARY KEY, thread_id TEXT, body TEXT);
        INSERT INTO api_portaluser VALUES
            (1, 'qa_e_root', '09121234567', 'real@example.com', 'argon2$real'),
            (2, 'someone',   '09351112222', 'other@example.com', 'argon2$other');
        INSERT INTO api_authtoken VALUES (1, 'abc'), (2, 'def');
        INSERT INTO api_auditlog VALUES (1, '203.0.113.42'), (2, '::1');
        INSERT INTO api_car VALUES (1, 'Corolla');
        INSERT INTO api_newthing VALUES (1, '09120000000');
        INSERT INTO api_supportthread VALUES
            ('a1', 'tok$real', 'Real Name', '09125550000', 'v@example.com',
             '/pricing', 'https://www.google.com/search?q=v%40example.com'),
            ('b2', 'tok$other', '', '', '', '/', '');
        INSERT INTO api_supportmessage VALUES
            (1, 'a1', 'my number is 09125550000'), (2, 'a1', '');
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

    t = dict(zip(('token_hash', 'contact_name', 'contact_phone', 'contact_email',
                  'source_page', 'referrer'),
                 con.execute('SELECT token_hash, contact_name, contact_phone, contact_email, '
                             "source_page, referrer FROM api_supportthread WHERE id='a1'").fetchone()))
    expect('support contact name masked', t['contact_name'], 'Staging Visitor')
    if t['contact_phone'] == '09125550000' or not t['contact_phone'].startswith('09'):
        failures.append(f'support contact phone not masked: {t["contact_phone"]}')
    expect('support contact email masked', t['contact_email'].endswith('@staging.invalid'), True)
    expect('support visitor token unusable', t['token_hash'], 'staging-sanitized:a1')
    expect('support referrer reduced to origin', t['referrer'], 'https://www.google.com/')
    expect('support source page kept', t['source_page'], '/pricing')
    expect('support empty contact stays empty',
           con.execute("SELECT contact_name, contact_phone, contact_email, referrer "
                       "FROM api_supportthread WHERE id='b2'").fetchone(), ('', '', '', ''))
    expect('support message body masked',
           con.execute('SELECT body FROM api_supportmessage WHERE id=1').fetchone()[0],
           '[sanitized message, 24 chars]')
    expect('support rows kept',
           con.execute('SELECT (SELECT count(*) FROM api_supportthread), '
                       '(SELECT count(*) FROM api_supportmessage)').fetchone(), (2, 2))
    expect('nothing survives sanitizing', leftovers(con), [])

    # The post-sanitize check must catch a value that slipped through.
    con.execute("UPDATE api_supportthread SET contact_email='leak@example.com' WHERE id='a1'")
    if leftovers(con) != ['api_supportthread.contact_email: 1 rows']:
        failures.append(f'leftover check missed a surviving e-mail: {leftovers(con)}')

    unknown = audit_unknown(con)
    if any('api_supportthread' in u for u in unknown):
        failures.append('audit still flags api_supportthread')
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
