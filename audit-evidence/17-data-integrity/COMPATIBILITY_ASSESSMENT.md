# Production compatibility and presentation

Question: if analytics stop reading reconstructed and unverified activity as before, what changes for users and operators, and how is uncertain data shown without passing it off as genuine?

All figures are read-only counts from production on 2026-11-02, by provenance class (see `FINDINGS.md`). Percentages are of rows.

## 1. Why `strict` cannot be the default

`strict` includes only attested rows. Today that set is empty. Making it the default for any reader would:

| Reader | Effect of `strict` as default |
|---|---|
| Admin traffic and usage, 7-day and 30-day windows | 82 and 670 rows drop to 0 (every row in those windows is unverified) |
| Recommendations | no history for any seat; empty or non-personalised output |
| Onboarding "has this seat done X" | every seat looks as if it has done nothing; every nudge fires |

That would trade a misleading chart for a broken product. `strict` is therefore for evaluator-facing and adoption-evidence reporting only, where "no verified data" is the correct answer.

## 2. What `operational` changes

`operational` excludes `reconstructed`, `backfilled` and rule-based `not_human` rows and includes `unknown` rows, labelled.

**This table is a reference reading, not an acceptance limit.** The counts were read from production on 2026-11-02 between about 16:05 and 16:27 UTC. Each window was a trailing window measured from the moment of its own query (`now()` minus N days), so the figures moved while they were being collected (the 90-day total read 4,267 in one query and 4,263 in a later one) and they will move again with every new row and every day that passes. A later snapshot, or a moving window, can legitimately fall outside these ranges through normal activity. They illustrate the **shape** of the change (nothing in the short windows, a drop of about 91% to 96% in the long ones); they must not be used as pass or fail limits. The acceptance criterion uses fixed boundaries and is defined in "Fixed boundaries for acceptance" below.

The table nets out **all** three exclusions. Two of them are exact; the third (demo-company and administrative rows) is bounded rather than exact, because its distribution across windows was not read and no production access was made for this revision.

| Window (trailing, at the reading) | Rows at the reading | Reconstructed and back-filled removed (exact) | Left before demo/administrative rule | `operational` after that rule (range) |
|---|---:|---:|---:|---:|
| 7 days | 82 | 0 | 82 | 55 to 82 |
| 30 days | 670 | 0 | 670 | 643 to 670 |
| 90 days | about 4,263 | 1,963 (1,946 + 17) | about 2,300 | 2,273 to 2,300 |
| 180 days | 28,910 | 26,205 (26,184 + 21) | 2,705 | 2,678 to 2,687 |
| 365 days | 73,949 | 71,244 (71,223 + 21) | 2,705 | 2,678 to 2,687 |

How the last column is bounded. Among the 2,705 unmarked, non-back-filled rows, the rule-based `not_human` exclusions are the 9 rows of seats in demo companies and the 18 administrative rows (`account_created`, `team_add`, `role_add`, `role_apply`, `role_delete`, `password_reset`, not counting the 21 back-filled rows already removed). They can overlap, so between 18 and 27 rows are excluded in total (all-time, hence the 180 and 365-day ranges of 2,678 to 2,687). In a shorter window an unknown number of them, between 0 and 27 but never more than the window's rows, falls inside, which gives the wider lower bound. The 90-day base of about 2,300 is 27 pre-batch rows plus 181 plus 2,092; it drifts by a few rows with the clock.

Change at the reading: 7 and 30 days, 0 to 27 rows (up to about 33% and 4%); 90 days, about -46% to -47%; 180 days, about -91%; 365 days, about -96%.

### Prerequisite: staging equivalence (step 0 of any shadow comparison)

The shadow comparison is meaningful only if the staging copy holds the same rows and the same classification inputs as its source at the recorded cutoff. This is **verified, not assumed**. Until it passes, no shadow comparison is run and no acceptance figure is recorded.

**What the repository shows**, read from the code and not from any live copy: `ops/deploy/deploy.sh` builds the staging copy in the PostgreSQL workflow with `pg_clone_staging` (`pg_dump -Fc` piped into `pg_restore` into a `<name>_staging` database) and then sanitizes it with `ops/deploy/sanitize_staging_db.py --pg`; a separate SQLite path exists for the older engine. The PostgreSQL sanitizer purges the credential and one-time-secret tables and masks phone, e-mail, password-hash and IP columns; by its code it does not delete rows from `api_activitylog`, `api_portaluser` or `api_company`. **What the code does not show:** which path built the copy that will actually be used, whether the sanitizer ran on it, whether anything else changed its rows, and the source instant of the clone (`pg_dump` takes its own snapshot when it starts, and no fingerprint of the source is recorded). In particular, **the existing deploy path does not use an exported snapshot**, so it is not a basis for same-instant fingerprints (see Method A and Method B in step 2 of the verification). The SQLite sanitizer is not evidence about the PostgreSQL workflow, and the PostgreSQL sanitizer's code is not evidence about any particular copy. **Further facts from the repository that shape the design below** (read from `ops/deploy/deploy.sh` and `ops/docker/containers.sh`, not from any live host): (a) the existing staging database `${PG_NAME}_staging` is created `-O "$PG_USER"`, owned by the application role, and is dropped with `dropdb --if-exists --force` on every staging run, including the CI `stage` job; (b) the existing staging containers are started with `--network host`, `--env-file "$KG_BE_DIR/.env.prod"` (the production environment file) and the production warehouse directories bind-mounted read-write; `deploy.sh` overrides only the database name (`-e KG_PG_NAME`), so the staging backend connects with the **production application role and password**, and `deploy.sh` blanks only a few variables (`SENTRY_DSN`, the SMS and Turnstile keys, alert phones); (c) the application reads its database settings from `KG_PG_NAME`, `KG_PG_USER`, `KG_PG_PASSWORD`, `KG_PG_HOST`, `KG_PG_PORT` and refuses to start in production mode without `DJANGO_SECRET_KEY`. Fact (b) is an observation for the project, outside this PR: the existing staging instance can reach and write production. It is **not** copied into the design below.

**Verification.**

1. **Identify the copy actually used**: database name, engine, build time and the commit of the deploy script that built it. A SQLite copy is not acceptable for this comparison.
2. **Take the source fingerprints at the same instant as the copy, by a method that is named, not implied.** The existing deploy path cannot do this, so the verification builds the acceptance copy by **Method B** below and records exactly which method was used.

   - **Method A, the repository's deploy path as it exists (not sufficient here).** `pg_clone_staging` in `ops/deploy/deploy.sh` is `dropdb --if-exists --force`, `createdb`, then `pg_dump -Fc "$PG_NAME" | pg_restore --no-owner --role="$PG_USER" --exit-on-error -d "$PG_STAGING"` (lines 72 to 76 at the checked commit), followed by `sanitize_staging_db.py --pg` (around line 395). It takes its own snapshot when `pg_dump` starts and **uses no exported snapshot and no held session**. Source fingerprints taken before or after it are not same-instant, so a copy built this way cannot pass the pass rule below, however the figures happen to compare. This document does not claim the deploy path does anything more.
   - **Method B, a manual, named command sequence (the one this verification requires), into a dedicated equivalence database.** The acceptance copy is **not** the existing `${PG_NAME}_staging` database: that one is owned by the application role (fact (a)), is dropped and rebuilt by every staging run, and is shared with QA and dashboards. It is a new database `<equiv-db>`, designed in the subsection "The equivalence database and the disposable application instance" below; wherever this document says "the staging copy" for acceptance, it means `<equiv-db>`. Three database roles take part, deliberately separate (authorization item 2): a **production read-only role** `<prod-read-role>`, an **equivalence administration role** `<equiv-admin-role>` that is a member of an **equivalence owner role** `<equiv-owner-role>`. Open the held, read-only `REPEATABLE READ` exporter session as `<prod-read-role>` (`EVIDENCE_PRESERVATION.md` section 4.1); inside it run the approved fingerprint query files (step 3) and read `T` (below); then run, as separate recorded commands, with `set -o pipefail` and the exit status of every command, and of both sides of the pipe, recorded:
     ```
     createdb --username=<equiv-admin-role> -O <equiv-owner-role> <equiv-db>
     pg_dump  --username=<prod-read-role> -Fc --snapshot=<id> <production-db> | pg_restore --username=<equiv-admin-role> --no-owner --role=<equiv-owner-role> --exit-on-error -d <equiv-db>
     <venv-python> -I ops/deploy/sanitize_staging_db.py --pg "dbname=<equiv-db> user=<equiv-admin-role>" --quiet
     ```
     preceded by the name and collision checks, with the isolation statements of the subsection below run **between `createdb` and the restore** (so that unsanitized data never sits in a database that others can connect to), and then run the same approved fingerprint query files on `<equiv-db>`. There is **no `dropdb` and no `--force`** in the creation: `createdb` fails if the name exists, and an existing database is never overwritten (a refresh is a new name). Method B differs from `pg_clone_staging` in four respects: the `--snapshot` option; the explicit roles (the repository's functions use whatever connection the script runs under, and **which role that is is not shown in the repository**); an equivalence owner instead of `$PG_USER`, because membership in `$PG_USER`, which owns the production tables, would give the operator write access to production; and a new database name instead of `$PG_STAGING`. Row data and the fingerprints do not depend on object ownership. Method B is **not in the repository**: it is an operator-run sequence, not a script, and nothing here changes `deploy.sh`. If it is later wanted as code, that is a separate, reviewed change with its own tests, outside this PR. `<production-db>` and `<equiv-db>` are different names, and the authorization names both.
   - **The exact command text and script versions are part of the authorization and of the evidence entry:** the full text of every command above with the real names filled in, the commit of `work` that the sanitizer and the deploy script were read from, and the Git blob identifiers (or SHA-256) of `ops/deploy/deploy.sh` and `ops/deploy/sanitize_staging_db.py` at that commit, so the entry shows which sanitizer ran. A command that differs from the authorized text is a different operation and needs its own authorization.
   - **Alternative path, not designed here.** The alternative to production access is a G2 amendment that extends the evidence snapshot to the seat and company tables (classification columns only) and builds the copy from that verified evidence. It is **not authorized and not designed** in this PR, for these reasons: `pg_dump --table` dumps whole tables, so it would carry the personal-data columns, and a column-limited export would be a different method that has not been designed or rehearsed; it would put decrypted copies of personal data wherever the staging copy is built, which the verification-scratch-location rules (`EVIDENCE_PRESERVATION.md` section 3) forbid unless that place also qualifies; and it needs the same encryption, custodians, retention and rehearsal as G2. Choosing it requires a new revision of these documents and a new review before any authorization.

   Record the cutoff `T` as defined below. This needs three roles in the production cluster (read-only on the production database; administration and ownership of the equivalence database only), is a separate authorization (scope, privileges, consequences and the exact commands below), is not part of PR #65, has not been requested or granted, and nothing in this document performs it.
3. **Fingerprints, by exact query files.** Non-personal, classification-relevant columns only. Each fingerprint is the output of an **approved query file** saved byte for byte by the rehearsal below, whose SHA-256 is recorded there and named in the authorization. **The same files are run, unchanged, on the source snapshot and on the staging copy**; a changed character is a different query and needs the rehearsal repeated.
   - **Files:** `fp-activitylog.sql`, `fp-portaluser.sql`, `fp-company.sql`, `fp-actions.sql`.
   - **Deterministic serialization** (the same rules as the content checksum, `EVIDENCE_PRESERVATION.md` section 4.2): `client_encoding` UTF8 and `TimeZone` UTC set identically on both sides; every value rendered with `quote_nullable(...)` (NULL differs from the empty string; quotes and backslashes are escaped); timestamps with `to_char(col, 'YYYY-MM-DD"T"HH24:MI:SS.US')`; booleans through their text form; a row string is its values joined by commas; each row string is hashed (`sha256` of its UTF-8 bytes, hex); the row hashes are joined with commas in ascending `id` order (`id` is a unique integer, so no collation is involved) and hashed again; the output is one line `count|min id|max id|hash`. `fp-actions.sql` outputs the counts by `action`, ordered by `action COLLATE "C"`, as one line, followed by the SHA-256 of that line.
   - **Content:** `api_activitylog`: `(id, user_id, action, created_at, marker present)`, where "marker present" is `(detail LIKE '%بازسازی%')::text`; `api_portaluser`: `(id, company_id, role, active, created_at)`; `api_company`: `(id, is_demo, active)`. Column names and types come from the repository's migrations for the rehearsal, and are confirmed on the source inside the exporter by a column list compared byte for byte with the approved list (as in `EVIDENCE_PRESERVATION.md` section 4.1, step 1). A difference **stops** the operation; it does not change a query.
   - **Format is validated before use:** exactly one line (`fp-actions.sql`: two), and for the four-field lines count, min and max are digits and the hash is 64 hexadecimal characters.
   - **The rehearsal must show:** equal values on a faithful restore; a different value after a one-value change in each included column, after NULL versus empty string, and after a one-microsecond change; unchanged values after the sanitizer runs on the rehearsal copy (so that the masked columns are demonstrably excluded); and the same value on repeated runs.

   The masked columns (phone, e-mail, password hash, IP) and the free text of `detail`, apart from the marker, are excluded, so masking cannot cause a false mismatch and cannot hide a real change to the inputs that drive classification.
4. **Pass rule.** Every fingerprint on the staging copy equals its source fingerprint. Any difference blocks the comparison until it is explained and the copy is rebuilt. There is no tolerance.
5. **After the registry migration exists**, the class counts on the staging copy (reconstructed rows in the registered range, back-filled rows, demo-company seats' rows, administrative actions) must equal the counts computed from the source fingerprints.
6. **Do not compare a staging copy with the live production table later.** Seats can be deleted (the ORM cascade removes their activity) and new rows arrive, so a later difference says nothing about the copy. Only same-instant source fingerprints count.
7. If the staging copy is refreshed, the verification is repeated.

The outcome (copy identity, `T`, every fingerprint pair) is recorded in the evidence entry.

**Definition of the cutoff `T`.** `T` is the value of `transaction_timestamp()` (the same as `now()` inside that transaction) of the held exporter transaction, read in that transaction with a session `TimeZone` of UTC, written to a file with `\g` like the other snapshot values, and recorded to the microsecond with its time zone. Consequences that are stated rather than assumed:

- It is the **start time of the transaction, not the instant of the snapshot**: the snapshot is taken at the first query after `BEGIN`, a moment later. `T` is therefore a window boundary, not a claim about which rows the snapshot contains.
- It does not make the window complete or clean. `created_at` may be assigned by the application server's clock, not the database's, so a row visible in the snapshot can carry a `created_at` after `T` (it is outside every window and not counted in `W`), and a row stamped before `T` may have committed after the snapshot (it is absent from the snapshot and from the copy, which is correct for both sides).
- Both sides of every comparison use the same `T` and the same snapshot, so these effects cancel; they would not cancel if `T` were taken from a different transaction, from `now()` at query time, or from the clone's finishing time, so none of those is allowed.
- `T` is a recorded input of the evidence entry; when the copy is refreshed, a new `T` is taken in a new exporter transaction.

**Scope and prerequisites of the separate production-read authorization.** Reading production for the staging-equivalence check is a different act from the evidence preservation (G2) and from the review of this PR (G1); an approval of either does not cover it. It is requested in GitHub #64 by the product owner, as a single-use authorization, and states all of:

1. **What is read and written:** (a) the read-only exporter transaction and the dump of the **whole production database** (personal data is read), and the approved non-personal fingerprint query files; (b) in the **same PostgreSQL cluster**, creating one **new** database `<equiv-db>` (never dropping or overwriting an existing one), restoring into it, sanitizing it, and, at the end, dropping it; (c) the cluster-level changes listed in item 11, and no others. No write to any production database object, no migration, no change to production data, and no change to any backup. Production, staging and equivalence database names differ, and all three are named.
2. **Roles and privileges: three, separate.** A named operator; connection details outside the repository; no credentials in commands, logs or the evidence entry. Each role has its own password, generated for this purpose and kept outside the repository in a `0600` file; none is the production application password.
   - `<prod-read-role>`: login role; not a superuser; no CREATEDB, CREATEROLE, REPLICATION or BYPASSRLS; read access only, for example membership in the predefined role `pg_read_all_data` (PostgreSQL 14 and later); no write privileges anywhere; no membership in any other role. Verified before use by catalog queries (attributes, memberships, privilege checks on the production tables), and recorded. **Unverified:** that this is enough for `pg_dump` of the whole database (for example large objects, or objects that need other privileges); the rehearsal must show `pg_dump` runs with exactly this role and nothing more, and the authorization is not requested until it has.
   - `<equiv-admin-role>`: login role with CREATEDB; a member of `<equiv-owner-role>` and of nothing else; not a superuser; **no privileges on any production object** beyond the default public ones (verified by privilege checks on the production tables, recorded).
   - `<equiv-owner-role>`: login role; owner of `<equiv-db>` only; the role the disposable application instance connects as; no privileges on production.
   - **Why not the application role:** `createdb -O` and `pg_restore --role` require membership in the target owner role (or a superuser). Membership in `$PG_USER`, which owns the production tables, would give the operator write access to production; a superuser cannot be bounded. Neither is used.
   - **Unverified assumptions:** whether these roles exist; under which role `deploy.sh` runs; whether a database owner's role member may drop the database (expected from the documentation of `DROP DATABASE`, to be shown by the rehearsal); and whether the cluster's `pg_hba.conf` already allows these roles to connect over the loopback TCP address the containers use. Creating the roles is a write to the cluster's catalogs, and any change to `pg_hba.conf` is a change to cluster configuration: both need their own explicit entries in item 11, and without them Method B is unavailable and the check is not run.
3. **Window and freeze.** A stated off-peak window for the creation (exporter, dump, restore, sanitizer, fingerprints), with a maximum life for the exporter transaction (the 15-minute idle timeout is a ceiling, section 4.1 of `EVIDENCE_PRESERVATION.md`), and a **freeze for that window**: no deploy (`deploy.sh`, `kgkg-promote`; a push or merge to `work` starts the CI `stage` job, which is a deploy-like run), no migration on production, and no scheduled job that dumps or rebuilds databases. The freeze does not need to cover the later life of `<equiv-db>`: no repository workflow touches that name (the staging runs touch `$PG_STAGING` only), and its removal uses no `--force`.
4. **Destination:** `<equiv-db>`, named in advance (rules in the subsection below), on a host and with access control approved for **unsanitized personal data for the time between restore and sanitization**, and for sanitized-but-still-personal data (usernames, display names and activity remain after sanitizing) for its whole life; nobody queries the copy before the sanitizer has run and its result is checked.
5. **Method and versions:** Method B as written in step 2, with the exact command text (real names filled in), the commit of `work` and the blob identifiers or SHA-256 of `ops/deploy/deploy.sh` and `ops/deploy/sanitize_staging_db.py` that the commands mirror and the sanitizer run uses, all recorded in the authorization, together with the approved fingerprint query files and their SHA-256 (step 3). Neither script is changed for this purpose, and the operation is **not** the unmodified deploy path.
6. **Capacity:** free space on the destination and on the production host for the transaction's side effects, read at execution time.
7. **Prerequisites met first:** the rehearsal of the snapshot method on a non-production database (`EVIDENCE_PRESERVATION.md` section 4.1) and **the rehearsal of Method B and of the fingerprint query files (below)** have passed, with their records and the SHA-256 of each approved query file attached; the roles of item 2 exist and are verified; the equivalence database is not shared with other work.
8. **Stop conditions:** any error, a failed name or collision check, a failed privilege or isolation check, a column list that differs from the approved one, a fingerprint mismatch, an unexpected write or a lock wait on production, a failed side of the pipe, insufficient free space, or the window closing ends the operation; a half-built `<equiv-db>` is dropped (without `--force`) and not used; it is repeated only under a new authorization.
9. **Afterwards:** the exporter transaction is committed or rolled back and confirmed gone, temporary files are removed, the outcome (copy identity, `T`, every fingerprint pair, pass or fail) is recorded, and the authorization lapses.
10. **Consequences accepted explicitly, because the equivalence database shares the cluster with production:**
    - **Locks.** The whole-database `pg_dump` holds ACCESS SHARE locks on every table for its duration. That does not block ordinary reads and writes, but a statement that needs ACCESS EXCLUSIVE (many `ALTER TABLE` forms, `DROP`, `TRUNCATE`, some migrations) waits for it, and ordinary queries that arrive after the waiting statement queue behind it. This is why migrations and deploys are frozen (item 3) and why an unexpected lock wait is a stop condition. The rehearsal observes it.
    - **Vacuum.** The held transaction holds back cleanup of dead rows in the whole cluster for its life.
    - **Temporary unsanitized data.** From the end of the restore until the sanitizer has finished, the staging database holds unsanitized personal data, credential tables and secrets inside the production cluster, visible to anyone with access to the cluster. Sanitizing deletes or masks rows but does not erase the earlier bytes: they remain in WAL, in dead tuples and free space until vacuum and reuse, and in any cluster-level or physical backup, WAL archive or replica taken in that period. The repository's own backups are per-database (`pg_dump -Fc "$PG_NAME"` in `deploy.sh`, `pg_backup`) and do not include the staging database; whether any cluster-level backup, WAL archive or replica exists is **not shown in the repository** and must be established and named in the authorization, with their retention. Dropping the staging database later does not remove WAL or backups.
    - **Disk and WAL volume.** A second copy of the database, its sanitization (which rewrites rows) and the WAL that all of it generates, on the data and the WAL volumes. The size of the production database is not stated in the repository: it is read at execution time (`pg_database_size`), and the operation stops unless free space on each volume is at least three times that size (an assumption to be checked by the rehearsal, which records the actual peak).
    - **No forced disconnections of other users.** Nothing else connects to `<equiv-db>`, and it is removed with plain `dropdb` (no `--force`), which fails while a session is connected: the disposable instance is stopped first. The existing staging containers and QA are untouched.
    - **Lifetime.** The owner of `<equiv-db>` and its deletion date are named in the authorization (default at most 7 days, because the shadow comparison is run once; an extension is a recorded decision), and the removal steps below are executed and recorded.
11. **Exact commands and application configuration, and cluster-level changes.** The authorization contains, with the real names filled in: the commands of Method B; the name and collision checks, the isolation statements, the removal commands and the instance's `docker run` command and environment file **as written in the subsection below**; and the complete list of cluster-level changes it permits: creating `<prod-read-role>`, `<equiv-admin-role>` and `<equiv-owner-role>` and their memberships (only if they do not exist), any `pg_hba.conf` change (only if needed), and creating, restricting and dropping `<equiv-db>`. A command that differs from the authorized text is a different operation and needs its own authorization.

Without this authorization, the staging-equivalence prerequisite stays **unverified** and no shadow comparison is run. The alternative path in step 2 is not an authorization route today: it is undesigned and needs a revision and a review first.

### The equivalence database and the disposable application instance (design, not executed)

**Why a dedicated database.** The existing staging database is owned by the application role, is dropped and rebuilt by every staging run, and is used by other work; Method B cannot drop it without the very membership it must avoid, and must not disturb it. A new database with its own owner needs no `--force`, cannot collide with a staging run, and can be removed without touching anything else.

**Name and collision checks** (before anything is created; any failure stops the operation):
```
PG_NAME=<production-db>; PG_STAGING=${PG_NAME}_staging
EQUIV=<equiv-db>                                                   # form: ${PG_NAME}_equiv_YYYYMMDD
case "$EQUIV" in "${PG_NAME}_equiv_"[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;; *) echo "bad name"; exit 1;; esac
[ "$EQUIV" != "$PG_NAME" ] && [ "$EQUIV" != "$PG_STAGING" ]
test "$(psql --username=<equiv-admin-role> -d postgres -Atc "SELECT count(*) FROM pg_database WHERE datname = '$EQUIV'")" = 0
docker ps -a --filter name=kgkg-equiv-backend --format '{{.Names}}' | grep -q . && exit 1     # container name unused
ss -ltn "sport = :<equiv-port>" | grep -q LISTEN && exit 1                                   # loopback port unused (not 8000, 3000, 8110, 3107)
test ! -e /opt/KGKG_equiv/<date>                                                              # instance directory unused
```
`<equiv-port>` is chosen from 8120 to 8129 after the check (a range the repository does not use: production 8000/3000, staging `STG_BE`=8110 / `STG_FE`=3107, health ports 18100 to 18199). `createdb` itself fails if the name exists; the check is there to stop earlier and to catch a similar name.

**Creation and isolation** (run by `<equiv-admin-role>` right after `createdb`, on the new database only):
```
REVOKE CONNECT ON DATABASE "<equiv-db>" FROM PUBLIC;
GRANT  CONNECT ON DATABASE "<equiv-db>" TO <equiv-owner-role>;
```
A new database grants `CONNECT` to everyone by default, so the revoke is what keeps other roles, including the production application role, out of it. The statements touch only `<equiv-db>`. After restore and before the sanitizer has finished nobody else connects (and no instance is running). Privilege checks, recorded: `<equiv-owner-role>` and `<equiv-admin-role>` have no `SELECT` on any production table; the production application role cannot connect to `<equiv-db>`.

**Disposable application instance.** It is **not** started with the repository's `be_args`/`run_backend`/`be_run` helpers, because those add the production environment file, the production warehouses (read-write) and the production application credentials (fact (b)). It is a separate `docker run`, built from an image the repository's own pipeline has already built for the commit under test (`img_be "$SHA"`), with a minimal environment file written for this purpose in a new `0700` directory `/opt/KGKG_equiv/<date>/`:
```
# /opt/KGKG_equiv/<date>/equiv.env   (0600, outside git; values shown as names only)
KG_DB_ENGINE=postgres
KG_PG_NAME=<equiv-db>
KG_PG_USER=<equiv-owner-role>
KG_PG_PASSWORD=<generated for this role>
KG_PG_HOST=127.0.0.1
KG_PG_PORT=<cluster port>
DJANGO_SECRET_KEY=<newly generated; not production's>
SENTRY_DSN=
SMS_API_KEY=
SMS_USERNAME=
SMS_FROM=
TURNSTILE_SECRET=
KG_ALERT_PHONES=
METIS_API_KEY=
```
```
# /opt/KGKG_equiv/<date>/stagecfg/staging_settings.py   (the text deploy.sh writes for staging, unchanged)
from KG_backend.settings import *  # noqa
ALLOWED_HOSTS = ["*"]
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
```
```
docker run -d --name kgkg-equiv-backend --label kgkg.role=equiv-backend --restart no --stop-timeout 40 \
  --network host --cap-drop ALL --security-opt no-new-privileges \
  --env-file /opt/KGKG_equiv/<date>/equiv.env \
  -e DJANGO_SETTINGS_MODULE=staging_settings -e PYTHONPATH=/stagecfg \
  -e KG_PORT=<equiv-port> -e KG_HEALTH_PORT=<free port in 18100-18199> -e KG_WARMUP=0 \
  -v /opt/KGKG_equiv/<date>/stagecfg:/stagecfg:ro -v /opt/KGKG_equiv/<date>/logs:/var/log/kgkg \
  <image of the commit under test>
```
The shadow comparison and any migration run inside this instance (`docker exec kgkg-equiv-backend python manage.py migrate --noinput`, then the comparison command that the implementation PR provides, called with `as_of = T`). Configuration rules: no production environment file, no production secret, no production warehouse mount (if the analytics under comparison need warehouse files, a **read-only** mount of the warehouse directory is the only permitted exception and is named in the authorization), no hostjobs spool, no nginx route; it listens on loopback only and the operator reaches it from the host (or by SSH port forwarding); it is not restarted automatically. The fingerprints are taken **before** the instance starts: once it runs it writes to `<equiv-db>` (sessions, tokens, activity rows, migrations), so the equivalence verdict refers to the state right after the sanitizer, and later rows fall outside every window `[T - N days, T]`.

**Assumptions that stay unverified until rehearsed:** that `-e`/`--env-file` precedence and the minimal environment above are enough for the settings to start (any addition is recorded and may not carry a production secret); that the image starts and passes its health check without the warehouses and the spool; that `--network host` is acceptable (the container then shares the host's loopback; isolation rests on the role's lack of privileges on production, not on the network, and a bridge network would need the cluster to listen on a non-loopback address, a configuration change); that `--cap-drop ALL` and `no-new-privileges` do not stop it; and that the operator running Docker (root on the host today) is itself outside this isolation.

**Removal after use** (all recorded; each step checks the previous):
```
docker rm -f kgkg-equiv-backend
dropdb --username=<equiv-admin-role> <equiv-db>            # no --force: fails while anyone is connected
rm -rf /opt/KGKG_equiv/<date>                               # env file with the password, logs, settings
```
then confirm: no container of that name, no database of that name in `pg_database`, no directory. The three roles are kept for a later check only if the authorization says so; otherwise a separate, recorded step drops them. The backend **image is not removed** by this procedure (it belongs to the release pipeline). Removal does not remove WAL, cluster-level backups or replicas.

**Capacity** is read at execution time (item 10). **Sensitive data**: `<equiv-db>` holds real customers' data (sanitized of credentials and masked contact details, but display names, usernames, company data and activity remain); access is limited to the operator, the instance is loopback-only, nothing is exported from it except the non-personal fingerprint and comparison outputs, and its logs (which can contain request paths and usernames) stay inside the `0700` directory until removal.

**Not established, listed so that nobody assumes it:** `pg_dump` privileges for `<prod-read-role>`; the availability of the roles; whether `pg_hba.conf` already permits them; whether the cluster archives WAL, has replicas or takes cluster-level or physical backups (the repository shows only per-database `pg_dump -Fc "$PG_NAME"` backups, which do not include `<equiv-db>`); the production database's size; and the host's free space.

### Rehearsal of Method B, the equivalence database and the fingerprint queries (required before the authorization is requested; not executed)

Nothing here has been run. It is done on a **non-production** PostgreSQL 16 cluster, in the same kind of shell (bash, Ubuntu 24) as the production host, with synthetic data, the repository's own `sanitize_staging_db.py --pg` at the commit named in the authorization, and an image built by the repository's pipeline. A failed item is a finding. The record, with the SHA-256 of each approved query file, the exact command texts, the environment file's variable names and the `docker run` command, is attached to the authorization request, and **no production read is requested before it exists**.

1. **Roles.** The three roles of authorization item 2 are created in the rehearsal cluster. `pg_dump` runs as `<prod-read-role>` with the proposed privileges and nothing more (including a database that has a large object, a sequence and an extension); that role cannot write; `<equiv-admin-role>` can neither read nor write the rehearsal "production" tables; `createdb -O`, `pg_restore --role` and plain `dropdb` by a member of the owner role work as written; membership in the application role is shown to give write access to the rehearsal "production" tables (the reason for not using it).
2. **Name and collision checks.** Each check of the subsection above stops the operation on a bad name, an existing database, an existing container, a busy port and an existing directory. `createdb` fails on an existing name and nothing is overwritten.
3. **Pipeline.** With `set -o pipefail`, a failure on either side of `pg_dump | pg_restore` is detected, the half-built database is dropped without `--force` and not used, and the exit statuses are recorded. With the exporter held, concurrent writes during the dump do not appear in the copy.
4. **Isolation.** After the `REVOKE`/`GRANT`, the rehearsal "application" role cannot connect to `<equiv-db>`; the equivalence roles have no `SELECT` on any rehearsal "production" table; the `pg_hba` assumption is tested by connecting over loopback TCP as each role.
5. **Sanitizer.** `sanitize_staging_db.py --pg` runs on the restored copy as `<equiv-admin-role>`; its result is checked; the copy is not queried before it has finished.
6. **Fingerprints.** The four query files give equal values on the source snapshot and on the sanitized copy; the detection tests of step 3 pass; the format checks pass and fail on the negative controls; fingerprints are taken before any instance starts.
7. **Disposable instance.** The environment file and `docker run` command are used exactly as written: the container starts and passes its health check; `docker inspect` shows no production environment variable, secret or mount; `-e`/`--env-file` precedence is as assumed; a connection attempt by the instance's role to the rehearsal "production" database is refused; the image runs without the warehouses and the spool, or the minimal read-only exception is recorded; `--cap-drop ALL` and `no-new-privileges` are accepted; and a migration and a write through the instance change only `<equiv-db>`.
8. **Removal.** The removal commands run in order, `dropdb` without `--force` fails while the instance is connected and succeeds after it is stopped, and the checks afterwards find no container, no database and no directory.
9. **Locks and capacity.** While the dump runs, a conflicting `ALTER TABLE` is observed to wait and later queries to queue (with the duration recorded); the peak data and WAL volume of creation and sanitization are recorded against the three-times rule.
10. **Persistence.** What remains of the pre-sanitization values in WAL and free space of the rehearsal cluster after sanitizing and dropping the copy is observed, or recorded as not checked.

### Fixed boundaries for acceptance

Acceptance is evaluated on one **staging snapshot** that has passed the prerequisite above, with the snapshot and the windows fixed in advance, so that normal activity cannot move the result.

1. **One fixed cutoff `T`**: the cutoff defined above (the `transaction_timestamp()` of the exporter transaction that the copy was made from), recorded by the staging-equivalence verification. Every count uses the explicit window `created_at >= T - N days AND created_at <= T`, for N in 7, 30, 90, 180 and 365. No query in the shadow comparison uses `now()`.
2. **Both code paths are evaluated at `T`.** The old behaviour and the new `operational` behaviour are run with the analytics code's `as_of` input set to `T` (the design adds an `as_of` parameter, default the current time, so the comparison is reproducible).
3. **The bounds are recomputed from that snapshot**, not copied from this document. For each window, from the staging copy: `W` all rows, `R` reconstructed, `B` back-filled, `D` rows of demo-company seats and `A` administrative rows, each counted only if not already in `R` or `B`, and `O` rows in both `D` and `A`.
4. **Bounds:** `W - R - B - (D + A) <= operational <= W - R - B - max(D, A)`. Once `O` is read the value is exact: `operational = W - R - B - (D + A - O)`.
5. **Pass criterion:** for every window, the measured `operational` count equals `W - R - B - (D + A - O)` computed by a separate query from the same snapshot (exact equality), and lies inside the bounds in step 4. The recorded `T`, the six counts per window and the measured values go into the evidence entry. Nothing is compared with the 2026-11-02 reference table.
6. **If the staging copy is refreshed**, `T` and every figure are recomputed; the previous result is not reused.

Consequences to plan for:

- **Wide-window charts fall off a cliff.** On the 2026-11-02 reading, a 365-day engagement chart goes from 73,949 rows to between 2,678 and 2,687. Without annotation this reads as a collapse in usage. Each affected view needs a visible note: "N reconstructed rows are excluded; history before 2026-07-04 has no application data."
- **Feature discovery.** Seats with any manual view: 26 including reconstructed rows, 12 without. 14 seats would flip from "has read the manuals" to "has not", and their nudges would start to fire. That is the correct behaviour and it will look like a sudden change in onboarding traffic.
- **Recommendations.** Peer history shrinks from 71,888 to at most 1,354 manual views from 12 seats (fewer by any made by demo-company seats). Seats with no recent history fall back to non-personalised suggestions; this fallback must be tested (it is part of `TEST_PLAN.md`).
- **Operators.** Reads only; no write path changes. A search of `ops/` found no alert, watchdog, exporter or dashboard that reads `api_activitylog`; the only references are the staging sanitizer and the restore verifier. Anything outside the repository was not searched. Disk, locks and migrations are unaffected (nullable column, no rewrite).
- **Concentrated use.** In the last 30 days five seats produced all activity and the top-manager role accounts for 302 of 670 rows. Dashboards built on such a small base will be volatile; the note on small samples belongs in the UI.

## 3. Presentation

Never one unlabelled number called "genuine".

| Element | Behaviour |
|---|---|
| Headline KPI | "n unverified application events (excluding m reconstructed)", with "verified: v" beside it, v being 0 until attestations exist |
| Charts | stacked series: verified, unverified; excluded classes shown as a separate, muted line or a footnote count, never summed in |
| Tables | a class column in the admin audit view; filter by class |
| API | additive `provenance` object: `mode`, `included` classes, `counts` per class, `excluded` per class; existing keys unchanged |
| Wide windows | banner when the window reaches back into a registered range |
| Evaluator exports | `strict` only; states the attested scope and "no verified data" when empty |
| Small samples | "based on n events from k seats" when k is under 10 |

## 4. Per-reader policy

| Reader | Mode | Notes |
|---|---|---|
| `adminops` traffic, today and recent feeds | operational | composition shown |
| `portal` usage report | operational | composition and wide-window banner |
| `insights` funnel | operational for activity; `dormant_accounts` unchanged (reads `last_login_at`) | do not back-fill `last_login_at` |
| `recommend` | operational, excluding administrative actions and demo seats | fallback when history is empty |
| `team` reports | operational | |
| `onboarding` `exists()` | operational | an `unknown` row counts as done; a reconstructed row never does |
| evaluator-facing adoption figures | strict | empty until attested |
| `quota`, writers, `behavior` | unchanged | different action or table |

## 5. Rollout

1. Implement behind a flag per reader (`KG_ACTIVITY_PROVENANCE_<READER>`), default off.
2. **Shadow mode** on staging, only after the staging-equivalence prerequisite (section 2) has passed for that copy: compute old and new values, log the difference, show nothing new.
3. **Recompute and compare on the fixed staging snapshot**, as defined in "Fixed boundaries for acceptance" (section 2): use the recorded cutoff `T` and windows `[T - N days, T]` for 7, 30, 90, 180 and 365 days, recompute `W`, `R`, `B`, `D`, `A` and `O` from that snapshot, and compare each dashboard's measured `operational` count with `W - R - B - (D + A - O)`. The 2026-11-02 reference table is not used for this comparison.
4. Enable readers one at a time; each with its annotation and its test.
5. Production promotion only by a person (`kgkg-promote <sha>`).
6. Rollback is the previous image tag plus turning the flag off; no data to restore.

## 6. What has not been assessed

User-visible impact on customers' own dashboards if any are exposed outside the admin and team roles; this must be checked reader by reader during step 2 of the rollout. The count of Grafana or other external dashboards reading the table directly is not known (none was found in the repository).
