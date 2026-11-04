# 44 — Data lifecycle: collection, processing, storage, access, retention, deletion, backup

How each class of data enters the platform, where it lives, who can read it, how long it is kept and how it is removed — **as implemented**. Where no rule exists in code the document says so; it never invents a policy. Persian version: [fa/44-data-lifecycle.md](fa/44-data-lifecycle.md). Evidence tags: **[C]** code, **[P]** observed on production 2026-11-04 ([38](38-implementation-status-matrix.md)), **[U]** not verified, **[POLICY?]** a retention or deletion rule that the owner has not formally defined (see the questions in §44.9).

## 44.1 Summary

| Aspect | State |
|---|---|
| Collection | accounts are created by administrators or the company's root seat (no self-registration); usage, assistant questions, tickets and (when enabled) chat messages are collected as people use the product |
| Defined retention in code | session tokens, 90-day monitoring rollups, the live-event table (20,000 rows), support-chat threads (**proposed**, enforcement off), pre-deploy database dumps (3 kept) |
| No retention or deletion rule found in code | activity log, assistant chat logs, audit log, tickets and ticket messages, expired OTP challenges, notification outbox rows, feedback database, portal user accounts (except through administrator actions) |
| Right-to-erasure / export workflow | none implemented **[C]**; privacy notice for the chat is an unapproved draft (`/privacy`, hidden unless `KG_PRIVACY_DRAFT_PAGE=1`) |
| Backups | see §44.8: portal database dumped on every deploy and hourly; vehicle-content database **not** in any backup path visible from the host; company-server and hosting-provider backups not visible from the host |

## 44.2 Lifecycle by data class

| Data class | Collected / created | Processed | Stored | Read by | Updated | Retention / deletion (implemented) | In backup |
|---|---|---|---|---|---|---|---|
| **Vehicle manuals** (222 cars) | source ZIPs placed on the host; `scan_zips`, `parse_worker` | parse → `pgcar` adopt into a schema of `kgkg_vec`; the SQLite file is deleted after adoption [C][P] | PostgreSQL `kgkg_vec`, schema `car_<md5>`, registry `public.car_dbs` | users with a grant (`allowed_cars`, layer) via the API; media through `auth_request` | re-run of the pipeline re-ingests; pipeline stages are incremental | no deletion policy; `dataquality` fixes quarantine corrupt or duplicate vehicle files (moved aside, not erased) and delete their catalog rows, via an admin action [C] | **not visible** (§44.8) |
| **Parts catalogs** (15 parts-only cars) | `import_parts`, `partsingest`, crawlers (`partsouq_crawler`, `tis_crawler`) | build SQLite per car | `Database_warehouse/_parts/*.sqlite` | users with the `parts` layer | re-import | none defined | **not visible** |
| **RAG index and diagnostic sidecars** | derived by `build_rag` / `build_diag` | blob de-duplication, embeddings (bge-m3), graph | PostgreSQL `kgkg_vec` (pgvector, FTS) [P] and the SQLite index file (still present) | assistant retrieval (authorised by `allowed_cars`) | rebuilt by the pipeline | derived data; can be rebuilt only if sources exist ([23 §23.2](23-data-layer.md)) | **not visible** |
| **Accounts, companies, grants** | created by platform admin or by the root seat (`orgCreateUser`); invitation tokens | passwords hashed; phone numbers used for OTP | `kgkg` (`PortalUser`, `Company`, `CompanyCarAccess`, `UserCarAccess`, `OrgNode`) | admin; company managers within org reach | admin panel, org canvas, settings | no automatic deletion; seats can be removed (`DELETE /api/org/nodes/{id}/`); admin can delete purchase requests; no account-erasure routine | yes (portal dumps) |
| **Session tokens** | on login | SHA-256 of the key stored | `AuthToken`, `AdminAuthToken` | the backend only | sliding expiry | portal idle 14 d / absolute 90 d; admin idle 12 h / absolute 7 d; expired rows deleted by `rotate_tokens --prune` (timer, **[P]** enabled) | yes (but expired rows are pruned) |
| **OTP challenges** | on login/recovery | code stored as SHA-256 | `OtpChallenge`, `AdminOtpChallenge` | backend | one-shot (TTL 2 min, 5 attempts) | expiry enforced at verify time; **no job found that deletes old rows**; a new admin challenge deletes that admin's earlier ones [C] | yes |
| **Activity log** | `logActivity`, `ActivityBeacon` (action, car, category, URL) | category resolved server-side; rolled up for analytics and recommendations | `ActivityLog` (86,250 rows [P]) | admin analytics; company managers within reach; recommendations | append-only | **no retention or deletion found** **[POLICY?]** | yes |
| **Assistant questions and answers** | on every answered question (`/api/auth/chat-log/`, best effort) | stored with mode, grounded flag, sources | `ChatLog` (63 rows [P]); `feedback.db` (582 logged queries, 11 ratings [P]) | the user's managers within reach; admin | ratings/pins add rows | **no retention or deletion found** **[POLICY?]** | `ChatLog` yes; `feedback.db` **not visible** |
| **Audit log** | middleware on logins and changes (who, what, from where) | request bodies redacted (`audit.redact`) | `AuditLog` | admin audit screen | append-only | **no retention or deletion found** | yes |
| **Tickets** (`CompanyRequest`, `TicketMessage`) | customer files a request; staff replies | SLA state computed (`sla.py`); CSAT asked once after closure | `kgkg` (7 requests [P]) | the filing company; platform staff | thread grows; closed tickets reopen on reply | **no retention or deletion found** **[POLICY?]** | yes |
| **Knowledge base** | authored by staff | versioned articles, owners | `kgkg` (23 published [P]) | all portal users (published) | edit with history | none | yes |
| **Support chat** (disabled in production) | visitor messages, optional contact details, hashed user agent | token stored as SHA-256 only | `SupportThread`, `SupportMessage`, ratings (0 rows [P]) | staff (RBAC off/audit/enforce) | status changes | **proposed** periods: no-contact 30 d, contact 180 d, spam 7 d, promoted 30 d; `purge_support_chat` reports only, deletes only if `KG_SUPPORT_RETENTION_ENABLED=1` **and** `--apply`; backups are not touched [C] | yes |
| **Notification outbox** | on events when channel mode is on | rendered; `recipient_ref` holds phone/e-mail "only as long as the row lives" | `NotificationOutbox` (0 rows [P]) | worker | status transitions | **no row pruning found** | yes |
| **Monitoring data in the database** | alert sweep and traffic rollups | aggregated | `TrafficStat`, `VisitorSeen`, `SystemAlert` | admin dashboard | rolled | rows older than 90 days (closed alerts too) deleted by `check_alerts` (`--prune-days`, default 90) [C]; `Event` table trimmed to the newest 20,000 rows [C] | yes |
| **Telemetry outside the database** | Prometheus, Loki, GlitchTip, Umami | metrics, logs, errors, redacted page views | their own stores | operators | — | Prometheus 30 d, Loki 90 d [C: `ops/observability/`]; GlitchTip and Umami retention **[U]** | **[U]** |
| **Browser-held data** | the user's browser | — | `localStorage`/`sessionStorage` keys ([42 §42.4](42-frontend-architecture.md)) | the user | by the app | cleared by the user or logout (session token); support-chat unsent messages capped at 24 h | n/a |

## 44.3 Access control at each stage

Reads of vehicle content are gated by token → `UserCarAccess` → company ceiling → document layer ([43 §43.7](43-architecture-diagrams.md), [06](06-permissions-rbac.md)); retrieval applies the same grants (`allowed_cars`) before ranking; media goes through `auth_request`; admin surfaces require the admin token (12 h idle) and the audit trail records changes. Chat logs and analytics are scoped to the viewer's org-graph reach by the backend, not by the UI.

## 44.4 Update paths

Content changes only through the pipeline (re-ingest, incremental, resumable) — never by editing the live store by hand. Account and grant changes go through `apply_user_access` and the org-graph API; changes are written to the audit log. Derived data (RAG index, sidecars, terminology) is rebuilt, not edited.

## 44.5 Archiving

No archival tier exists: nothing is moved to cold storage. Older pre-deploy SQLite copies and ad-hoc archives under `/root` (observed [P]) are manual leftovers, not a designed archive.

## 44.6 Deletion paths that exist

Session expiry pruning; monitoring and event trimming; org seat deletion; administrator deletion of purchase requests and company roles; `dataquality` fixes that quarantine corrupt/duplicate vehicle files and delete their catalog rows; the guarded `purge_support_chat`. There is **no** user-initiated deletion, account erasure, data export or per-company offboarding routine in code **[C]**.

## 44.7 Personal and sensitive data inventory

Phone numbers and e-mail addresses (accounts, optional chat contact), names, usernames, password hashes, hashed session tokens, IP addresses and hashed user agents (audit/chat), assistant questions (free text, may include vehicle details), tickets (free text). Credentials sent by SMS on account creation are not stored by the application after sending, except as hashed passwords **[C: `orgCreateUser`]**; SMS provider retention is outside this system **[U]**.

## 44.8 Backup and recovery — evidence-based status (read-only checks 2026-11-04)

The owner reports two further arrangements: **the hosting provider's backups** and **the company's internal server-backup infrastructure**. Three levels are kept apart: *an arrangement exists*, *coverage is verified*, *recovery is verified*.

| Mechanism | Arrangement exists? | Coverage verified? | Recovery verified? |
|---|---|---|---|
| Pre-deploy `pg_dump` into `/opt/KGKG_release/db-backups/` (newest 3 kept, `deploy.sh:464`) | **Yes [P]** — newest 2026-11-04 | `kgkg` only; ≈ 25 MB; 116 tables | readable with `pg_restore --list` (545 entries); no restore performed |
| Hourly snapshot `/root/backup_snapshot/` (script `/root/kgkg_snapshot.py`; scheduled from the company server) | **Yes [P]**: stamp and `portal.dump` refreshed on 2026-11-04 | includes `kgkg` dump, old `db.sqlite3`, nginx configs, code mirror, eval data; **excludes** `kgkg_vec`, `_parts`, `_rag`, `/var/lib/postgresql`, env files (from script text and directory tree) | dump readable; `verify_restore.py` (restore into a throw-away database and compare counts) exists; **no run log found** |
| Company internal server backup | **Owner-stated; indirectly evidenced** (the snapshot stamp is refreshed hourly and the watchdog describes the company server pulling it) | **Not visible from the host**: what the company server keeps, for how long, and whether it copies anything else | **Not visible** |
| Hosting-provider backup | **Owner-stated; the repository documents a monthly full server backup on the 5th** ([11](11-operations-deployment.md)) | **Not visible from the host** (VM is QEMU/KVM with the guest agent running; this proves nothing about snapshots) | **Not visible** |
| PostgreSQL WAL archiving / replica / base backup | No (`archive_mode=off`, no replication, no slots) [P] | n/a | n/a |

What can be said safely: *the portal database is backed up locally on every deploy and hourly, and an off-host copy of the hourly snapshot is very probably taken by the company server; whether the 58 GB vehicle-content database and the parts catalogs are covered by the company-server or provider backups has not been verified, and no restore has been demonstrated.* What must not be said: that all databases are backed up, that backups are restorable, or that no backups exist. To close the gap: inspect the company backup server's job definitions and the provider panel (read-only), then run `verify_restore.py` in a maintenance window and record the result — see [47](47-engineering-followups.md).

## 44.9 Policies not yet defined (decisions needed from the owner)

Retention of activity logs, assistant questions, audit rows, tickets and outbox rows; whether support-chat retention (30/180/7/30 days) is approved and enabled; account offboarding and erasure on request; export of a company's data; backup scope and off-host retention for `kgkg_vec` and `_parts`; retention of GlitchTip and Umami data. Until decided, official reports should state "no retention period is defined for X" rather than a number.
