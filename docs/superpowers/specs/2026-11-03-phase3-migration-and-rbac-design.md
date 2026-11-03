# Phase 3: migration A, migration B and the RBAC rollout (design for approval)

**Date:** 2026-11-03. **Status:** DESIGN ONLY. No migration file exists, none has been run, no role has been created, RBAC does not exist in code beyond the `permissions.can` seam. Labels: *verified* = read or run this session; *proposed* = awaiting your decision; *unresolved* = cannot be verified from here.

## 0. Honest scope: this is two new tables and one added column

The earlier summary said "two additive tables". The approved requirements also need **one column on an existing table** (`SupportThread.excluded`, section 1.4). Migration A is therefore `CreateModel` + one `AddField`; B is a single `CreateModel`. Everything else listed under "existing models affected" is code, not schema. Nothing is dropped, renamed or altered; `ops/deploy/check_migrations.py` accepts `CreateModel` and `AddField` with a `db_default` (verified by reading its rules), so no `# deploy-safety: reviewed` opt-out is needed.

Dependency line: both depend on the latest api migration at generation time (`0041_support_chat_core`, itself unmerged). Numbers are **unresolved** (section 5).

## 1. Migration A: `SupportThreadEvent` (+ `SupportThread.excluded`)

### 1.1 Model `api.SupportThreadEvent` (table `api_supportthreadevent`)

| Column | Type | Null / default | Why |
|---|---|---|---|
| `id` | BigAutoField, PK | | order and cursor |
| `thread_ref` | UUIDField | NOT NULL, no FK | links to `SupportThread.id` while it exists; deliberately not a foreign key so a content purge or erasure of the thread does not cascade into history, and so the deletion boundary is explicit |
| `kind` | CharField(24), choices | NOT NULL | closed set below |
| `at` | DateTimeField | NOT NULL, `db_default=Now()` | event time (server clock) |
| `actor_admin_id` | PositiveIntegerField | NULL | staff-initiated kinds only; plain int so deleting an admin neither cascades nor blocks; staff identity is personal data about staff |
| `intent` | CharField(10) | NOT NULL, `db_default=''` | segment for sales/technical separation without reading the thread |
| `mode` | CharField(5) | NOT NULL, `db_default=''` | `live` / `async` at the time (created, first reply) |
| `closure` | PositiveSmallIntegerField | NULL | pairs close, rating and reopen of one closure cycle |
| `score` | PositiveSmallIntegerField | NULL | CSAT 1-5 on `rated`, so satisfaction survives thread deletion |
| `dedupe_key` | CharField(80) | NULL, unique | idempotence, e.g. `closed:<thread>:<closure>`, `first_reply:<thread>:<closure>` |

No text, contact, IP, user agent, page or referrer column exists. A schema-guard test enumerates the columns against this table, so adding a free-form column fails CI.

**Kinds (closed):** `created`, `first_visitor_message`, `first_staff_reply`, `assigned`, `unassigned`, `priority_changed`, `intent_changed`, `closed`, `reopened`, `rated`, `spam_marked`, `restored`, `excluded`, `included`, `fallback_to_async`. `first_*` are one per closure (dedupe key), not one per message: this keeps write volume near the number of lifecycle changes instead of doubling message writes, and still lets V-metrics for first response survive a content purge.

**Indexes:** `(kind, at)` for metric windows; `(thread_ref, at)` for a thread timeline; unique on `dedupe_key`. No other index. **Constraints:** `CHECK mode IN ('', 'live', 'async')`; `CHECK score IS NULL OR score BETWEEN 1 AND 5`. No CHECK on `kind` (adding a kind must not need a table rewrite; the guard is a test).

### 1.2 Append-only and consistency
Written only through `events_log.record()`, inside the caller's `transaction.atomic()` and after the row lock the view already holds (`select_for_update` on the thread), so a rolled-back change leaves no event and two concurrent identical changes produce one (`dedupe_key` unique + `IntegrityError` caught inside a savepoint, treated as "already recorded"). The model refuses `save()` on an existing pk and `delete()`; the manager exposes `record()` only; the retention command is the single deleter (`QuerySet.delete` is reachable only from it). This is application-level protection; a DB trigger was rejected as unnecessary complexity for SQLite/PostgreSQL parity.

### 1.3 Classification, privacy, retention (summary; detail in the reconciliation file)
Pseudonymous operational data, never described as anonymous: a thread id plus actor id plus time can identify indirectly. Access: staff with read permission for that intent (timeline) or metrics permission (aggregates), never the public API, never application logs. Retention is **not approved**: no period is fixed, purge stays report-only, rollup-to-aggregates and erasure-by-`thread_ref` are designed but not built. Backups keep erased data until their own expiry (unverified).

### 1.4 The exclusion marker (the "additional column")
**DECIDED by the owner (2026-11-03): A1.** `SupportThread.excluded` is part of migration A; the events-only option A2 is dropped and kept below for the record only. Requirement: QA/test conversations must be excludable from every metric and reversible. Two options were considered:

| Option | Schema | Effect |
|---|---|---|
| **A1 (recommended)** | `SupportThread.excluded BooleanField(default=False, db_default=False)` plus `excluded`/`included` events | list/metrics filter is a plain indexed-free boolean (table is small), survives as the single source for "currently excluded"; events record who and when |
| A2 | no column; "excluded" = latest `excluded`/`included` event for the thread | no change to an existing table, but every list and metric needs a latest-event subquery and exclusion disappears from the list once events are rolled up |

A1 alters an existing table, but additively: NOT NULL with `db_default`, so **old code inserting threads without the column keeps working** (the exact failure `check_migrations.py` exists to prevent). On PostgreSQL a constant-default `ADD COLUMN` is metadata-only, so the table lock is momentary. Decision needed from you: A1 or A2.

### 1.5 Existing code affected (no schema)
`lifecycle.close/reopen`, `views_admin.*` (assign, priority, intent, spam, restore, reply for `first_staff_reply`), `views_public.create_view/_send/csat_view`, plus one new endpoint the widget calls once to record `fallback_to_async`. The inbox detail adds an event timeline built from this table.

### 1.6 Compatibility, rollback, recovery
- *Phase 2 / current app:* new table and a defaulted column; Phase 2 code ignores both. `deploy.sh --rollback` leaves the schema in place and the old code runs.
- *Reverse migration:* drops the table and the column. Safe schema-wise; it destroys history, so it is a last resort used only before any real data exists.
- *Recovery:* events are derived facts; if the table were lost, thread rows, messages and `AuditLog` remain the source of the lifecycle, only time-based metrics for lost periods would be unrecoverable (and would be reported as absent, never estimated).

### 1.7 PostgreSQL tests required (CI)
Two concurrent closes write one `closed` event; concurrent first replies write one `first_staff_reply`; rolled-back reply leaves no event; unique `dedupe_key` collision does not abort the outer transaction (savepoint); schema-guard (no text-like columns); CHECK constraints reject bad `mode`/`score`; a query on `(kind, at)` uses the index (`enable_seqscan=off` plan); `migrate api <prev>` and forward again round-trips; old-code compatibility test inserts a `SupportThread` row via raw SQL without `excluded`; thread deletion leaves events; erase-by-ref removes only that thread's events.

### 1.8 Operational risks
Brief lock on `ADD COLUMN` (mitigated above); new write per lifecycle change (small); if event writes fail the action must still succeed or fail atomically (they share a transaction, so they fail together by design: a deliberate choice, since an unrecorded transition would corrupt KPIs).

## 2. Migration B: `SupportStaffRole`

### 2.1 Model `api.SupportStaffRole` (table `api_supportstaffrole`)

| Column | Type | Null / default | Notes |
|---|---|---|---|
| `id` | BigAutoField, PK | | |
| `admin` | FK `PlatformAdmin`, `on_delete=CASCADE`, `related_name='support_roles'` | NOT NULL | a deleted admin loses roles |
| `role` | CharField(20), choices | NOT NULL | `support_agent`, `sales_agent`, `support_lead`, `support_auditor`, `support_owner` |
| `granted_by_admin_id` | PositiveIntegerField | NULL | plain int (history survives); NULL = granted by a bootstrap owner or management command |
| `granted_at` | DateTimeField | NOT NULL, `db_default=Now()` | |

**Constraint:** `UniqueConstraint(admin, role)`. **Index:** the unique constraint covers `admin` lookups. Intent scope is **derived from the role** (no scope column): sales agent = `sales`,`demo`; support agent = `technical`,`other`; lead, auditor, owner = all. A per-person scope override would be a later, separate decision.

No existing table is touched. **No data migration** and no permission-granting step: the table is created empty. Dependencies: `PlatformAdmin` (exists since early migrations). Conflicts: only numbering.

### 2.2 Transactions and concurrency
Role changes are single-row insert/delete in one transaction with their `AuditLog` row; the last-owner guard (section 3.4) takes `select_for_update` on the owner rows so two simultaneous revocations cannot remove the final owner.

### 2.3 Privacy
Roles are staff data, not customer data. Role grants, revocations and every contact reveal are audited by ids (`support_chat.role_granted`, `role_revoked`, `reveal_contact`).

### 2.4 Rollback and recovery
Reverse drops the table (no other table references it). Operational rollback does not need a migration at all: `KG_SUPPORT_RBAC=off`. Recovery from a bad mapping: bootstrap owners (section 3).

### 2.5 PostgreSQL tests required
Unique pair enforced; FK cascade on admin delete; concurrent last-owner revocation cannot leave zero owners; table empty after migrate (no grants); reverse/forward round trip; old code runs with the table present.

## 3. RBAC rollout and lockout analysis (answers the checklist)

**Bootstrap owners.** `KG_SUPPORT_OWNERS` is a comma-separated list of PlatformAdmin usernames set by a person on the server. Each name is matched case-insensitively against **active** admins at call time; matches hold `support_owner` regardless of the table.

**Is it validated at startup? Not yet; here is the design.** (Nothing exists today.) A registered Django system check reports a *Warning* when `KG_SUPPORT_RBAC` is not one of `off|audit|enforce` (an unknown value is treated as `off`, never as `enforce`), for each owner name that matches no active admin, and when the mode is `enforce` with no resolvable owner. It is a Warning, not an Error, because an Error would make `migrate` and every deploy fail over a role setting. A read-only command `support_roles check` gives the same answer on demand and belongs in the pre-enable checklist.

**Strict enforcement: never silently bypassed (owner decision 2026-11-03).** This replaces the earlier fail-open idea. In `enforce` there is no implicit allow, no degraded mode and no fallback to `audit`:
- a request without a matching permission and scope is denied (403 for actions, 404 for out-of-scope threads), always;
- if `enforce` is set but **no active support owner resolves**, support endpoints answer 403 with code `rbac_no_owner` and an audit row; nobody gets in by accident. This can lock out *support* (never any other admin feature) until a person recovers it, which is why the recovery paths below exist and why `support_roles check` is mandatory before switching to `enforce`;
- `audit` mode is not enforcement: it allows and records would-be denials, is a deliberate staging step, and the response and logs say so.

**Recovery (all are explicit actions by a person with server access; none is automatic):**
1. Set or correct `KG_SUPPORT_OWNERS` in the server environment and reload: effective on the next request, independent of the table.
2. Run `manage.py support_roles grant --admin <username> --role support_owner --apply` on the server (dry-run by default, audited, works in any mode because it is not an HTTP endpoint).
3. As the last resort, set `KG_SUPPORT_RBAC=off` (documented emergency switch; reverts to today's flat model; the change is logged at startup).

**Unrelated administration is untouched.** Permissions are read only by `permissions.can` called from `api/support_chat/*`. A test statically asserts no module outside `support_chat` imports it and that representative non-support admin endpoints behave identically under `enforce`. The loopback `KG_ADMIN_TOKEN` is never a person and keeps all non-support behaviour; it gets no support permission.

**Backend enforcement.** Scope is applied by one function, `scoped_threads(admin, queryset)`, used by list, detail, every action and (later) the metrics queries, so out-of-scope threads are absent from counts and 404 on direct access (not 403, no existence oracle). Frontend hiding is cosmetic only.

**Transition `off` to `audit` to `enforce`:** in `audit`, each request that would be denied writes an audit row (admin id, permission, thread id) and is allowed; the owner reviews the would-be-denials, adjusts roles, then sets `enforce`. Tests run the same table-driven matrix in all three modes and check the `off`/`audit` outputs equal today's behaviour. **Rollback:** set `KG_SUPPORT_RBAC=off` (instant; no migration, no data change). **Last-owner guard:** revoking the final remaining role-based owner is refused unless an env owner exists.

### 3.1 Authorization matrix (proposed, for approval)

Scope: SA = support_agent (technical, other); SL = sales_agent (sales, demo); LD = support_lead; AU = support_auditor; OW = support_owner. "own" = thread assigned to the person; "unassigned" = no assignee.

| Capability | SA | SL | LD | AU | OW |
|---|---|---|---|---|---|
| See thread list/detail in scope | own + unassigned | own + unassigned | all | all (read-only) | all |
| Reply / internal note | own + unassigned | own + unassigned | all | no | all |
| Take (assign to self) an unassigned thread | yes | yes | yes | no | yes |
| Assign or reassign to others, unassign | no | no | yes | no | yes |
| Priority, intent change | own | own | all | no | all |
| Close / reopen | own | own | all | no | all |
| Spam / restore | no | no | yes | no | yes |
| Reveal full contact (audited) | own | own | all | no | all |
| Exclude from metrics (QA marker) | no | no | yes | no | yes |
| Metrics and dashboard (aggregates only) | no | no | yes | yes | yes |
| Notification health / outbox status | no | no | yes | yes | yes |
| Declare availability; counts toward live | yes (scope) | yes (scope) | yes (all) | no | yes (all) |
| Manage roles (grant/revoke), see role audit | no | no | no | no | yes |

Contact is masked by default for everyone; "reveal" is a deliberate action with an audit row. Live-mode eligibility requires reply permission covering the thread's intent.

### 3.2 Role-scoped event visibility (owner decision 2026-11-03: required; design, built in M2)
Today `events.emit(..., audience='admin')` delivers `support_chat.*` events (thread id, intent, kind) to **every** platform admin stream. In `enforce` that must narrow:
- **Filter at the stream, not the client.** `events._scoped_qs` gains one rule for admin viewers: events whose type starts with `support_chat.` are returned only when the viewer holds a support permission, and only for intents inside that viewer's role scope (`payload.intent` in the allowed set; `support_auditor`, `support_lead`, `support_owner` see all intents). An admin with no support role receives none. No schema change: it filters the existing JSON payload.
- **Payload gets `intent` on every `support_chat.*` event** (`updated` currently carries only `thread_id` and `kind`; `message` and `reopened` already carry `intent`). Still ids and enums only, never text or contact.
- **Computed at connect time.** The viewer's allowed intents are resolved when the stream opens (and it reconnects at least every 300 s), so a role change takes effect within five minutes at most; documented, and a role revocation additionally closes nothing mid-stream (unmeasured limitation).
- **Granularity limit, stated honestly:** events are scoped by intent only. An agent still receives the id/intent/kind of events for in-scope threads assigned to a colleague; message content, contact and the thread itself remain protected by the own-or-unassigned rule on the REST endpoints.
- **Tests (PostgreSQL and SQLite):** a sales agent's stream never yields a technical-intent event; an admin without a role yields none in `enforce` and all in `off`/`audit`; auditor yields all; role change observed after reconnect; the payload schema test asserts no text/contact keys.

### 3.3 The `support_roles check` safety gate (design only; approved in principle 2026-11-03; no tooling changed yet)

**Purpose:** make it impossible to *knowingly* switch to `enforce` with a configuration that would lock support out, without ever making an ordinary deploy depend on role data.

**Shape.** A read-only management command `manage.py support_roles check [--for-enforce]`. It changes nothing, calls no network service, and runs against whatever database the environment points at.
- Exit `0` = pass, `1` = a blocking problem under `--for-enforce`, `2` = unexpected error (never treated as a pass).
- **Without `--for-enforce`** it only reports and always exits `0` (warnings printed). With `--for-enforce` it exits `1` if any blocking check fails.

**Checks.** *Blocking under `--for-enforce`:* at least one **active** support owner resolves (from `KG_SUPPORT_OWNERS` or a `support_owner` row for an active admin); every name in `KG_SUPPORT_OWNERS` is spelled as an existing admin username (typos are the main lockout cause); the role table exists and is readable (migration B applied); `KG_SUPPORT_RBAC` is a recognised value. *Warnings only:* no sales agent or support agent exists (live mode would never trigger for that intent); an active admin has no role while in `audit` (they would be denied after `enforce`); recent `audit` would-be-denials exist for named people (listed by admin id and permission, no content).

**Where it runs, so it never blocks ordinary work:**
1. Always available by hand for a person: `support_roles check --for-enforce` before they set `KG_SUPPORT_RBAC=enforce`.
2. Later, an **opt-in** gate step: `ops/deploy/gate.sh` would run it *only when the target environment's `KG_SUPPORT_RBAC` is `enforce`* (that is, when a person has already chosen enforcement). With `off` or `audit` (the default) the step is skipped, so ordinary deployments, CI, local development and the loopback `KG_ADMIN_TOKEN` are unaffected. If the check fails in an `enforce` environment, the gate refuses *that deploy* and names the missing owner; it never edits roles or flips the mode.
3. CI never runs it against a real database (CI has an empty throwaway DB); CI only runs the command's own unit tests.

**Why it cannot lock out developers or administrators:** it is read-only, never invoked by an HTTP request, and inert when the mode is `off`/`audit`; the emergency recovery path (`KG_SUPPORT_RBAC=off`, or `support_roles grant` on the server) does not go through the gate. **Tests (when built):** exit codes for each failing check, pass with env-only owner, pass with table-only owner, typo detection, skipped when mode is `off`/`audit`, never writes (database snapshot equal before/after).
**Not done:** the command, the gate step, any change to `ops/deploy/*`. It is design only until you approve building it.

## 4. Decisions
**Settled by the owner (2026-11-03):** A1 (`SupportThread.excluded`) and the `SupportStaffRole` table; five roles; strict enforcement with no silent bypass; role-scoped event visibility; bootstrap owners with a recovery mechanism; migrations are generated only after the other developer confirms numbering and compatibility.
**Still open:**
1. Final sign-off on the exact schemas in sections 1 and 2 as written (including the `first_*` events and the `score` column).
2. Final sign-off on the matrix in 3.1 (agents reveal contact only for own threads; lead can reassign and spam; auditor never replies or reveals).
3. Whether `support_roles check` must pass (exit 0) as a gate in `ops/deploy/gate.sh` before `KG_SUPPORT_RBAC=enforce` may be set (recommended; touches deploy tooling, so it is your call).

## 5. Developer coordination (unresolved, cannot be verified from here)
Visible state (verified): the highest migration on every remote branch and open PR except Phase 2 is `0039`; `rag-db-improvements` (86 commits behind `work`) adds none. **Unresolved:** the other developer's local, unpublished database work. Required before generating anything: written confirmation from them that they hold no pending `0040`-`0043` and which branch they will merge first; then `git fetch`, `check_migrations.py origin/work`, `makemigrations --check`. If they hold migrations, the later one is renumbered with its dependency line corrected before any merge, and never edited after merge.
