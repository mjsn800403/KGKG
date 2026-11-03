# Phase 3: architecture reconciliation (revision 3)

**Date:** 2026-11-03
**Status:** the owner's conditional approval of the Phase 3 direction, with three corrections. This file **supersedes** the following passages of the revision-2 design and plan: spec 6.2 (event table), 8.2 (role rollout), 12.3 (retention wording) and plan "Migrations" and "Global Constraints" (branching). Everything else in revision 2 stands.
**Authorisation boundary:** local, non-destructive M0 and M1 work that needs no migration. Migrations A and B, the role data step, push, PR, merge and deploy each need their own explicit approval.
**Labels:** *verified* = read or run this session; *proposed* = awaiting approval.

## 1. Git and migration dependencies (verified 2026-11-03)

| Fact | Evidence |
|---|---|
| Phase 2 is **not merged**. `origin/feat/customer-communication-core` (9a72d19) is contained in no other remote branch; it is 14 commits ahead of and 5 behind `origin/work`. | `git branch -r --contains 9a72d19`; `git rev-list --left-right --count origin/work...HEAD` = `5 14` |
| The 5 commits on `work` touch CI, Dependabot and `qa/e2e/tests/support.spec.js` only. No migration, model, URL or `audit.py` change. | `git diff --name-only d04e3bd origin/work` |
| A trial merge of `work` into Phase 2 conflicts in `docs/CHANGELOG.md` only. | `git merge-tree --write-tree` |
| Highest migration anywhere on `origin` other than my branch is `0039`. `rag-db-improvements` (86 commits behind `work`, last migration `0034`) adds none. Open PRs #59 and #65 add none. My branch holds `0040` (outbox) and `0041` (support chat). | `git ls-tree` per branch; `gh pr list` |
| Local, unpushed work by the other developer is invisible to me. | by construction |

**Consequence.** Starting Phase 3 from a fresh `origin/work` would lose `api/support_chat/` and the outbox, so it is wrong. The plan sentence "Branch from a fresh `origin/work`" is replaced by:

1. **Phase 3 is stacked on Phase 2.** Work happens on a new local branch `feat/support-chat-phase3` cut from `9a72d19`. Phase 2's branch is not touched, rebased or force-pushed.
2. **Integration sequence (proposed, needs approval at each step):** (a) the Phase 2 PR to `work` merges first (the CHANGELOG conflict is mechanical: keep both lines, newest first); (b) `feat/support-chat-phase3` is then updated with `work` by a normal merge (never a rebase of a pushed branch) and opened as a second PR; (c) if the owner prefers one review, the Phase 3 branch may carry both, but then Phase 2's PR is closed, not merged separately.
3. **Migration numbers are not assumed.** `0042`/`0043` are only *expected*. Immediately before generating either migration: `git fetch`, `check_migrations.py origin/work`, `makemigrations --check`, and a written confirmation from the other developer that they hold no pending `0040`-`0043`. If a collision appears the later migration is renumbered before any merge; the dependency line, not the file name, is what ties them.
4. All Phase 3 tables are new tables with no foreign key into an existing table other than `PlatformAdmin` ids stored as plain integers, so `deploy.sh --rollback` against the previous code remains safe (old code ignores unknown tables).

## 2. Role-based access: rollout without silent over-grant (replaces spec 8.2)

**Principles.** The global administrator authentication is not changed. The new permissions govern only `/api/admin/support-chat/*` and the support inbox UI; no other admin endpoint reads them. A wrong role assignment can therefore block support work for a person but never lock anyone out of the admin console, deployments, data-quality tools or the loopback script token.

**Design change: no permission-granting data migration.** Migration B creates only the empty `SupportStaffRole(admin_id, role, granted_by_admin_id, at)` table (unique `(admin_id, role)`). Nothing is granted by a migration, so nothing can be over-granted by one. The revision-2 idea of granting `support_owner` to every active admin is **withdrawn**.

**Bootstrap and recovery.** `KG_SUPPORT_OWNERS` (comma-separated usernames, set by a person on the server) names the bootstrap owners. They hold `support_owner` regardless of the table, so the system can always be configured and an emergency exists even if the table is empty or mis-assigned. Each use of that path is audited by id. It is read at call time, never stored.

**Enforcement mode** (`KG_SUPPORT_RBAC`, default `off`):

| Mode | Behaviour | Purpose |
|---|---|---|
| `off` | today's behaviour: any signed-in admin *person* may use support endpoints (the loopback token still may not) | until the owner has chosen roles |
| `audit` | allowed as in `off`, but each request that *would have been denied* writes an audit row (admin id, permission, thread id; no content) | proves the mapping before it can hurt anyone |
| `enforce` | default deny, scoped by role and intent | steady state |

**Rollout steps (each a person's decision):**
1. *Identify.* A read-only command `support_roles report` lists every admin (username, active, last token use, phone-on-file yes/no, has-support-activity yes/no). No secrets. It needs no migration.
2. *Decide.* The owner writes the mapping admin to role (and names bootstrap owners). Nothing is applied yet.
3. *Create the table* (migration B, approved separately). Mode stays `off`.
4. *Assign.* `support_roles assign --admin X --role Y` is dry-run by default and needs `--apply`; every change is audited by id.
5. *Observe.* Set `audit`; read the would-be-denial report for an agreed period; fix mappings.
6. *Enforce.* Set `enforce`. Only an explicit person action does this; nothing automates it.

**Rollback and recovery.** Set `KG_SUPPORT_RBAC=off` (instant, no migration reversal, no data loss). A person locked out of support is restored by listing them in `KG_SUPPORT_OWNERS` or by a bootstrap owner assigning a role. Reversing migration B drops the empty-by-design table and is safe because no other table references it.

**Status:** M0/M1 use the existing flat admin model through one function, `permissions.can(admin, permission, thread=None)`, which today returns true for a signed-in admin person. The seam exists so migration B changes one function, not every view. Contact masking, scope and role-aware UI are **blocked** until migrations B and the mapping are approved (M2).

## 3. Event history and retention (replaces spec 6.2 and 12.3)

**Classification.** A `SupportThreadEvent` is **pseudonymous operational data, not anonymous data.** It holds no message text and no visitor contact or IP, but a thread id, an acting staff id and a timestamp can indirectly identify (the thread id links to the conversation while it exists; staff ids identify staff; rare timing patterns can single someone out). The design therefore minimises, restricts and bounds it instead of calling it non-personal.

**Minimised shape (proposed).** `id`, `thread_ref` (UUID, plain column, no FK), `kind` (closed enum), `at`, `actor_admin_id` (nullable int, no FK, only for staff-initiated kinds), `intent` (enum), `mode` (`live`/`async`, only where relevant), `closure` (small int, for rating and closure pairing), `dedupe_key` (nullable, unique). No free-form JSON column: a closed set of typed columns cannot be used to smuggle text, and a test enumerates the schema. Visitor-initiated events carry no actor.

**Integrity and consistency.** Written inside the same `transaction.atomic()` as the state change they describe (a rolled-back change leaves no event). Append-only at the application layer: the model refuses updates and deletes, the manager exposes `record()` only, and the retention command is the single deleter. `dedupe_key` (e.g. `closed:<thread>:<closure>`) makes retries and concurrent double-submits write one event. A reconciliation test proves every status transition made through the API has exactly one matching event.

**Access.** Never exposed to the public API. Thread timeline: staff with `support.read` for that intent. Aggregates: `support.metrics`. Raw `thread_ref` is not returned by metric or export endpoints. Event contents never go to application logs, `AuditLog` details beyond the existing id-only rows, or the notification outbox.

**Retention and deletion boundaries (design only; nothing approved, cleanup stays disabled).**
- *Detail stage* (proposed, a number for the owner to set): thread-level events are kept for a bounded period so lifecycle questions and disputes can be answered.
- *Rollup stage* (later, not built now): before the detail stage ends, a job converts events into **aggregate rows** (per day, intent, mode: counts and bucketed durations) that carry no thread ref and no actor. Historical dashboard figures after that point come from the aggregates, and an evidence export states which basis (events or aggregates) each period uses. This preserves reproducible headline metrics without indefinite person-linkable retention.
- *No indefinite default.* No retention period is chosen by this document. `purge_support_chat` stays report-only; `KG_SUPPORT_RETENTION_ENABLED` stays off; the report will list events as a separate line item so the owner sees both.
- *Conversation deletion* removes content, contact and outbox rows. Events for that thread remain until the detail stage ends unless an erasure applies.
- *Individual erasure.* An authorised, audited action deletes the thread, its outbox rows **and its events by `thread_ref`**. Only a counter of erasures (no thread ref, no date finer than a month) is kept. The cost is explicit: metrics derived from that thread change; exports record that erasures occurred.
- *Backups.* Deleted data persists in backups until backup expiry. Backup retention is a known open risk (workspace risk list); the privacy notice must say erasure does not instantly reach backups. Verifying backup expiry is an owner/ops input, not assumed.

**Status:** migration A is **blocked** pending approval. Until then M0/M1 record traceability in the existing `AuditLog` (ids only, written by `views_admin._audit`) and the visitor-visible system messages. No placeholder event function or temporary event model is added; Task 0.2 and the event timeline in the staff detail view are blocked, and the detail view builds its timeline from existing columns and `AuditLog` ids only.

## 4. Summary of what is and is not authorised now

| Item | State |
|---|---|
| Kill switch, staff list/detail, assign/priority/intent actions on existing columns, heartbeat fix, visitor widget, staff inbox tab, tests, docs, local commits on `feat/support-chat-phase3` | authorised, migration-free |
| `SupportThreadEvent`, `SupportStaffRole`, the `exclude` marker (needs a new column), contact masking by role, intent scopes | **blocked** until migrations A/B are approved |
| Role data migration | **withdrawn**; replaced by the audit-mode rollout above |
| Push, PR, merge, deploy, public activation, real SMS/email, retention cleanup | not authorised |
