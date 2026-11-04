# Support platform: readiness audit, gap register, checklist and launch plan

Date: 2026-11-03. Evidence labels: **confirmed** (checked this session against the repository,
GitHub or tests), **documented** (stated in docs only), **unverified** (not checked; needs a
person or a server read). Scope: the human support chat (`api/support_chat/`, `src/support-chat/`).
No AI is involved anywhere in it. Everything below is migration-independent; migrations A and B
(event history, exclusion flag, role table) wait for Ali's written confirmation and are not touched.

## 1. What exists, split by how far it is proven

| Capability | Implemented | Tested | Operational today |
|---|---|---|---|
| Visitor chat: create, send, poll, contact, reopen, rating | yes | unit + API + 17 Playwright scenarios | **no** (kill switch off) |
| Visitor token (SHA-256 at rest), Turnstile, idempotent create | yes | yes | no |
| Staff inbox, replies, close/reopen, assign, priority, intent | yes | yes | no (chat off; inbox reachable but empty) |
| SSE with shared stream, polling fallback, 12 h idle policy | yes | unit + E2E | yes for admin events |
| RBAC matrix, modes, fail-closed invalid mode, scoped events | yes | yes | **off** (default); roles come from env only |
| `support_roles report/check` | yes | yes | read-only, usable now |
| `support_roles grant/revoke` | branch `feat/support-roles-admin`, unmerged | against a fake store only | **no**, needs migration B |
| Event history, exclusion flag, KPI evidence pack | design only | none | no, needs migration A |
| Reply notifications (SMS/email) | outbox only | outbox tests | **no**, sending off |
| Unanswered-conversation monitor | `support_health` (this batch) | yes | usable read-only, not wired to alerts |
| Retention purge | `purge_support_chat` dry run | yes | no policy approved |

## 2. Verified findings, ranked

| # | Finding | Evidence | Severity | Status |
|---|---|---|---|---|
| G1 | **Production runs a commit that is on no branch.** `3a65964` (Ali, one file `kg_frontend/src/app/api/chat/route.js`, parent `551f6f6` which is on `work`) is reachable only through the annotated tag `deploy-20261103-123544`. Against `origin/work` it is 1 ahead, 3 behind. Not lost (the tag keeps it, and the commit is fetchable from GitHub) but never reviewed or CI-tested as a PR, and the next promote from `work` would silently revert the fix. | confirmed: `git rev-list --left-right --count`, tag object, GitHub compare API | high (integrity, not availability) | open **Update 2026-11-03: resolved** by #72 (merge of `3a65964` into `work`); staging passes again. |
| G1a | Cause of G1 (**inferred**): `kgkg-promote` refuses a commit that is not an ancestor of `origin/work` (`ops/deploy/kgkg-promote:99`), but `deploy.sh` itself only requires a fast-forward of the live commit (`deploy.sh:350`) and writes the deploy tag (`:562`). Running `deploy.sh` directly skips the guard. How it was actually run is unverified (needs the server shell history or the CI/promote record). | confirmed (code) / unverified (what happened) | | open **Update:** the full analysis and a tested, unwired guard are in `2026-11-03-promote-drift-prevention.md`; enabling it needs separate approval. |
| G1b | Same class as issue #50 (five unpushed commits, rescued to #51), now a one-file fix. #50 stays open. | confirmed | | open |
| G2 | **No alert on unanswered visitors.** `monitoring.evaluate_alerts` has no support-chat rule. Once the chat is on, a visitor can wait unnoticed. | confirmed: grep, no match | high before launch | `support_health` added (read-only); wiring to alerts needs approval because it sends real alerts |
| G3 | **Half-typed text was lost on reload or when the panel closed** (draft only lived in component state). | confirmed: code read | medium (UX) | fixed in this batch **Update:** also fixed in batch 2: a message resent after an outage no longer leaves its text in the box. |
| G4 | Route-level authorization had no sweep test: a new staff route could ship without a guard. | confirmed: no such test | medium | fixed: `test_security_sweep.py` covers every URL pattern |
| G5 | No test asserted that application logs stay free of message text, contact details and tokens (audit rows were covered, logs were not). | confirmed | medium (privacy) | fixed: `LogPrivacy` test, includes a self-check that the collector can fail |
| G6 | CSRF concern. Support endpoints are `csrf_exempt` and authenticate with a header token (`X-Support-Chat-Token`, `Authorization: Bearer`), never a cookie, so a cross-site form cannot carry credentials. | confirmed: code + sweep test (requests without the header get 401/404, and no auth path reads a cookie) | **not a defect for these endpoints** | closed for support chat; the wider site was not audited |
| G7 | Enumeration: a real thread id and an unknown one get byte-identical answers without the right token. | confirmed: sweep test | n/a | passing |
| G8 | Rate limiting: nginx volumetric zones exist (`kg_api` 20 r/s, SSE `limit_conn 8`); Django per-thread/IP limits on top. Poll limiter is per gunicorn worker (up to 3x the configured value), by design and documented in code. | confirmed (config + code) | low | accepted; no load numbers yet (G10) |
| G9 | SSE through nginx: `/kg-api/api/events/stream/` has `proxy_buffering off`, `X-Accel-Buffering: no`, `proxy_read_timeout 3600s`. | confirmed: `ops/nginx/kgkg.conf` | low | OK on paper; **unverified end to end behind the real proxy** |
| G10 | No measured performance baseline or soak test of the stream/poll path. | confirmed: none exist | medium | next batch (isolated environment only) **Update (batch 2):** handler-level baseline added (`test_benchmark.py`, PostgreSQL in CI); a network-level soak is still not done. |
| G11 | Backup retention, secrets missing from backup, restore drill. Docs describe an hourly off-host backup verified 2026-10-27. Retention policy and restore of secrets are listed as open risks in the workspace notes. | documented | high (recovery) | **unverified**: needs a read-only server check and a restore drill |
| G12 | Missing staging secret turns the `stage` job red. CI has a "Check the staging credential" step. | documented + CI file | low | unverified whether it currently fails |
| G13 | `khadamat.pem` private key sits in `D:\programing`. | documented | high if the folder was ever shared | owner action: move, treat as exposed if shared |
| G14 | Role changes reach an open stream only at reconnect (up to 300 s). | confirmed (design) | low | accepted; documented |
| G15 | `TableStore` and the last-owner concurrency test cannot be exercised before migration B. | confirmed | blocker for RBAC enforcement | waits on Ali |

## 3. Roadmap

Batch 1 (done in this change, migration-independent): G3, G4, G5, and the monitor half of G2.
Batch 2 (needs no approval beyond a branch): SSE reconnection/offline Playwright scenarios
(S-series gaps), mobile and RTL accessibility pass, empty/error/offline states, a measured
baseline for create/poll/SSE in an isolated stack.
Batch 3 (needs your decision): wire `support_health` into the alert sweep (G2); resolve G1 by opening
a PR from the deploy tag; backup and restore drill on a scratch host (G11).
Blocked on Ali: migrations A and B, `grant`/`revoke`, RBAC enforcement, event history, KPI pack.

## 4. Production readiness checklist (objective pass/fail)

Pass means evidence exists and is linked. Today: nothing below the "Security" and "Reliability"
code rows has been run against production.

| Area | Criterion | Today |
|---|---|---|
| Security | Every staff route returns 401 without a staff session (sweep test green) | pass |
| Security | Visitor routes give identical answers for real and unknown threads (sweep test green) | pass |
| Security | Logs contain no message text, contact details or tokens (test green) | pass |
| Security | Turnstile keys set in production, action `support_chat` | unverified |
| Security | No private key in the shared working folder | **fail** (G13) |
| Security | `support_roles check --for-enforce` exits 0 and at least two owners exist, before enforcement | not run (needs migration B) |
| Reliability | Production commit is an ancestor of `origin/work` | pass at 2026-11-03 (#72); can recur until the guard is enabled |
| Reliability | SSE survives drop, stall, expiry and reconnect | pass: 11 connector unit tests (mid-stream drop with cursor resume, 45 s stall, heartbeats, backoff, 401, 503, online) and E2E F5-F7 |
| Reliability | Restore drill completed from the off-host backup, including secrets | unverified |
| Performance | Baseline p95 for create, poll, send, staff list, thread detail and `support_health` on PostgreSQL | handler-level baseline in section 4.1; no network soak yet |
| Operations | Unanswered-visitor monitor wired to an alert and tested | **fail** (command exists, one query, not wired: needs your approval) |
| Operations | Runbook exists and was rehearsed on staging | written (R10), not rehearsed |
| Privacy | Privacy notice reviewed and published; retention policy approved. **Launch blocker:** the notice must name everything the widget keeps in the visitor's browser, including the **half-typed draft** (sessionStorage `kg_sc_d_v1`, this tab only, up to 2000 characters, expires after 24 h, removed when the box is emptied or by "delete conversation"), the unsent-message queue (`kg_sc_q_v1`) and the thread id and token (`kg_sc_v1`, localStorage). The draft page does not mention the draft yet | **fail** (draft only, not approved, not updated for the draft) |
| Staffing | Named staff on shift, hours, off-hours message, escalation path | not defined (owner decision) |
| Infrastructure | Kill switch off by default and flips only by a person | pass (documented, tested) |

### 4.1 Measured baselines (batch 2)

Handler-level latency through Django (URL routing, middleware, view, database), with the test client:
no network, TLS or proxy, so it is a baseline for regressions and for finding slow queries, **not a
capacity claim**. Isolated PostgreSQL service in CI (`test_benchmark.py`, 500 live threads with 3 messages
each, 60 samples, rate limits off); the run's log carries the `BENCH` lines.

| Endpoint | p50 ms | p95 ms | Queries |
|---|---|---|---|
| visitor create | 6.1 | 8.2 | 7 |
| visitor poll | 4.7 | 5.5 | 3 |
| visitor send | 8.4 | 9.5 | 10 |
| **staff list (500 live)** | **22.6** (was **192.4**) | 24.8 (was 208.5) | 4 |
| staff thread detail | 10.1 | 12.5 | 4 |
| `support_health` report | 16.6 | 19.8 | **1** (was 501 at 500 waiting) |
| `support_health`, 2000 waiting | 55 | n/a | 1 |

* **Bottleneck found and fixed:** the staff list was 192 ms for four queries on PostgreSQL (11 ms on SQLite, which hid it).
  The cause was the join plus aggregate behind `message_count`: PostgreSQL computed five correlated subqueries for every
  thread before sorting. A correlated count removes the join, so it sorts on the indexed `last_activity_at` and reads
  the subqueries for the page only. Remaining cost is the counts query (about 10 ms) and the 30-row page (about 8 ms).
* **`support_health`:** one query, no 500-thread cap (`SCAN_LIMIT` is now a 20000-row safety valve); `waiting` and the
  per-intent counts are exact. Cost grows with the number of waiting threads (about 55 ms at 2000), so run it on a timer
  of a minute or more, not per request. It still does not alert.
* **Not measured:** concurrency (many simultaneous polls and open SSE streams), real network latency, Nginx and
  gunicorn behaviour, and a long soak. A load test of those needs a deployed isolated stack and is the next performance step.

## 5. Launch plan

1. **Staging validation.** All "Security" and "Reliability" rows green; Playwright suite plus the
   new reconnect scenarios; load baseline; rehearse R10 (kill switch, rollback).
2. **Internal pilot.** Chat on for staff-only traffic (internal visitors), RBAC still `off` or `audit`,
   `support_health --fail-on warn` checked by hand; one week; review every thread.
3. **Limited public rollout.** Kill switch on for a small share (needs a rollout mechanism, not built;
   today it is all or nothing, so use the pilot period and business hours instead), reply notifications still off.
4. **Go / no-go.** Go only if: G1 and G2 closed, restore drill passed, staffing defined, privacy notice
   approved, two owners present, no open high finding. **Rollback conditions:** unanswered critical
   wait, any privacy incident, SSE error rate above the alert rule, abuse that the limits do not contain;
   rollback is unsetting `KG_SUPPORT_CHAT_ENABLED` (R10). Production promotion stays a person's `kgkg-promote`.
