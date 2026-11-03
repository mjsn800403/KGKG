# Phase 2 correction plan (before Phase 3)

**Status:** PROPOSAL. Nothing in this document has been applied. No code, migration, commit, push or deploy.
**Branch:** `feat/customer-communication-core` (Phase 1 pushed at `2f1033c`; Phase 2 = 7 local commits `f468f2c..6ce874e`, unpushed).
**Labels:** *verified* = observed this session by running code or reading the cited file; *documented* = stated in repo docs; *assumed/unverified* = not checked.

## 0. New findings from this investigation

| # | Sev. | Finding | Evidence |
|---|---|---|---|
| F11 | **Important (privacy)** | `AuditMiddleware` (`api/audit.py`) records the body of **every** mutating `/api/*` call except a skip list. The chat routes are not on it. The append-only, never-trimmed `AuditLog` therefore stores each visitor's message, phone, email, raw IP and user agent. This is a larger version of F1 than the `Event` preview. | *Verified by probe*: one `POST /api/chat/threads/` produced `AUDIT post /api/chat/threads/ 5.6.7.8 {"request": {"message": "please call me about pricing", "contact": {"phone": "09121112222", "email": "a@b.ir"}}}`. Docstring: "`AuditLog` rows are never trimmed". |
| F12 | Medium | `purge_chat` never deletes a promoted thread, but a promoted thread is a duplicate of data now held in the ticket, so it keeps visitor PII forever for no operational reason. | `purge_chat.py` filter `promoted_request__isnull=True` |
| F13 | Low | `source_page` and `referrer` are stored as sent; query strings can carry personal data. | `views_public.py` `create_view` |

Reassuring, *verified*: Sentry/GlitchTip is configured with `send_default_pii=False`, `max_request_body_size='never'` and a `scrub_event` hook (`settings.py:370-373`), so exceptions in chat views do not ship message bodies. `ActivityLog` is portal-user-only. The Django chat routes do **not** collide with the paid assistant at the proxy: nginx's `^~ /api/chat` (zone `kg_chat`) matches the Next.js origin path only; browsers reach Django through `/kg-api/` (zone `kg_api`).

## 1. Must-fix before Phase 3

All on the unpushed commits. Migration `0040` (Phase 1) is already on `origin` and stays untouched; `0041` is unpushed and is regenerated.

### C1. Privacy: where visitor data lives, and what stops it persisting (F1, F11, F12, F13)

Every store that can hold visitor data:

| Store | Today | Proposed |
|---|---|---|
| `ChatThread` / `ChatMessage` | content + contact, purge by idle age | purge by the retention policy in section 2 (R1) |
| `Event` (`chat.message`) | 80-char message preview | **ids and intent only**, never text or contact |
| `AuditLog` (via middleware) | full body, phone, email, IP, UA | add the support-chat prefixes to `audit._SKIP_PREFIXES`; write explicit `audit('support_chat.*', ...)` rows for **staff** actions with ids only, no body, no visitor IP |
| `NotificationOutbox` | recipient number/address, rendered body | delete `sent`/`dry_run`/`suppressed` rows after 30 days, `dead` after 90; blank `payload.body` on terminal status for visitor/customer-addressed rows |
| nginx / Umami logs | URL with thread UUID, never the token | unchanged; token travels in a header (*documented*, `kgkg.conf` logs paths) |
| Sentry/GlitchTip | bodies excluded | unchanged |
| Backups (`KGKG_backups`) | retention not checked | *unverified*; an open risk in CLAUDE.md (backup retention). Deletion is not instant in backups |
| Provider logs (Melipayamak, SMTP) | outside our control | note in the privacy text |

Components: `api/chat/views_public.py`, `api/chat/views_admin.py`, `api/audit.py` (one tuple, shared file, minimal edit), `api/management/commands/purge_chat.py`, new `purge_outbox` command in `api/notifications/`, `api/notifications/worker.py` (scrub on terminal status).
Also: strip the query string and fragment from `source_page`/`referrer`; delete a promoted thread 30 days after promotion (the ticket holds the record); add an admin "erase visitor data" action in Phase 5 for individual requests.
Risks: editing the shared `audit.py` skip list (low, one line, covered by a test); Phase 1 files change (additive).
Tests: after create, send, contact and reply there are **zero** `AuditLog` rows containing the message text, phone, email or visitor IP (negative test written first); `Event` payload has no `preview`/text keys; `purge_chat` removes promoted threads after 30 days; `purge_outbox` ages; outbox body scrubbed after `sent`.

### C2. Token- and thread-scoped rate limits (F2, F3)

Findings recap, *verified*: polls hit 429 at request 121 per IP per minute (about 6 pollers per IP at 3 s); 600 bad-token GETs and 200 contact PATCHes were never throttled.

Design (no new infrastructure; `ratelimit._allow(key, limit, window)` already accepts any string key, so `ratelimit.py` is not edited):

| Endpoint | Key | Limit | Store | Why |
|---|---|---|---|---|
| poll GET | thread id | 30 / min, burst 10 | in-process token bucket (per worker, so up to 3x effective) | a poll must stay cheap; the shared sqlite store does a write transaction per call |
| send POST | thread id | 20 / min and the existing 30 / hour | shared store | low rate, correctness matters |
| contact PATCH | thread id | 10 / min | shared store | was unlimited |
| csat POST | thread id | 5 / min | shared store | was unlimited |
| create POST | IP | **20 / 10 min** (was 5) + Turnstile; a global creation counter that raises a `SystemAlert` above an hourly threshold | shared store | 5 / 10 min would block six visitors starting a chat from one office NAT |
| invalid token | IP, **counted only on failure** | 30 failures / min then 429 | shared store | users with valid tokens are never counted, so a NAT neighbour cannot lock them out |
| status GET | IP | 60 / min stays | shared store | polled rarely |

Cheap early rejection: a malformed token (wrong length/charset) or malformed id returns 404 with **no database query**.
Volumetric abuse stays with nginx (`kg_api` 20 r/s per client, burst 100, *verified* in `kgkg-limits.conf`); adding a dedicated chat zone is an infrastructure change and is listed under decisions (not applied).
Dependencies: C1 not required. Risk: per-worker poll buckets are approximate by design; the 3x slack is acceptable because the goal is abuse containment, not billing.
Tests (written first): poll over limit on one thread returns 429 while a second thread from the **same IP** still polls; ten visitors on one IP all poll at 3 s for 60 s without a 429 (simulated clock); 31 bad tokens from one IP then 429, while a valid token from that IP still succeeds; contact and csat limits; garbage token makes zero queries (`assertNumQueries(0)`); create at 20 per 10 min per IP.

### C3. Rename the subsystem (F4)

Blast radius, *verified by repo search*: no existing Django route starts with `api/chat/` (the existing ones are `api/auth/chat-log/`, `chat-feedback`, `api/team/chat-logs/`, `api/admin/chat-logs/`); no `SupportThread`/`SupportMessage`/`support-chat` identifier exists anywhere; the existing `api/admin/support/metrics/` and `kind='support'` are distinct strings. The paid assistant's references (`kg_frontend/src/app/api/chat/route.js`, `AssistantChat.jsx`, `instrumentation.ts`, `ops/deploy/smoke.sh:59`, nginx `^~ /api/chat`, docs 18) are all on the Next.js side and are untouched by a rename. The new subsystem has **no frontend code yet**, so no frontend dependency exists to break. Everything to rename is in my own unpushed work: `api/chat/` (12 files), `urls.py`, `models.py` import line, migration `0041`, `docs/openapi.yaml` (10 refs), docs/05, qa/k6, tests.

Proposed names: package `api/support_chat/`; models `SupportThread`, `SupportMessage`, `SupportPresence` (not "Agent": it is staff availability); routes `/api/support-chat/...` and `/api/admin/support-chat/...`; OpenAPI tag `support-chat`; rate-limit names `support_chat_*`; env/SystemState keys `KG_SUPPORT_*`.
Why now: renaming after `0041` is pushed means a rename migration on a table that CI and staging have already created. Unpushed, it is delete-and-regenerate of one migration file.
Risks: regenerating `0041` (mitigated: unpushed, no data anywhere); a missed reference (mitigated by a route-guard test).
Tests: a guard test asserting no URL pattern in `api.urls` starts with `api/chat/`; the existing assistant routes still resolve (`api/auth/chat-log/`, `chat-feedback/`, `team/chat-logs/`, `admin/chat-logs/`); `test_openapi_routes` green; `ops/deploy/smoke.sh` unchanged.

### C4. Product-critical data fields (F7), kept minimal

| Candidate | Decision | Reason |
|---|---|---|
| `staff_seen_at` on `SupportThread` (nullable) | **add** | the only way to show the visitor «خوانده شد» and the admin an unread dot; not derivable |
| `reopen_count` (default 0, `db_default 0`) | **add** | parity with tickets (`CompanyRequest.reopen_count`), needed to read reopen metrics honestly |
| `first_response_at` | **do not add yet** | derivable as the minimum `created_at` of the first non-internal staff `SupportMessage`; ticket denormalises it for list ordering, a lead inbox at this volume does not need to. Add only if the metrics query measures slow |
| `response_due_at` / per-thread SLA columns | **do not add** | no supported response commitment exists yet; the inbox "waiting" age is computed from `last_activity_at` and `status`. Reuse `sla.state()`/`due_dates()` (pure functions) when owner-set targets exist |
| staff display label field | **do not add** | the customer-facing label is the constant «پشتیبانی»; attribution stays in `author_admin` |
| `author_label` for the loopback token | **do not add** | replies and reopen require a signed-in staff person (like the presence endpoints); a script token cannot reply to a visitor |
| per-admin read state (`TicketRead` equivalent) | **defer** | `reads.py` is bound to `CompanyRequest`; one shared `staff_seen_at` serves a small team; revisit if several agents work in parallel |

Reuse (no duplication): `sla.py` pure helpers; `support_metrics.py` helpers (`_p90`, `_avg`, `_sla_block`) for a later lead-metrics endpoint; the existing `TicketThread.jsx` conversation component (props: `messages`, `onSend`, `allowInternal`, `placeholder`) for the admin thread and, with a visitor skin, the widget. Not reused: `TicketRead` and `requests_api` (ticket-specific by design).
Pre-sales vs technical: `intent` already partitions threads (`sales`, `demo`, `technical`, `other`). Reporting groups: pre-sales (`sales`+`demo`), visitor support (`technical`+`other`); authenticated tickets keep the existing `support_metrics` untouched, so sales and technical SLA figures never mix.

### C5. Concurrency and idempotency (section 2 of your brief)

Changes: `_send` becomes one transaction that locks the thread row (`select_for_update`, a no-op on SQLite where `IMMEDIATE` already serialises writers), then checks idempotency and the 30 / hour count, then inserts; the staff reply and reopen lock the same row, so status transitions are ordered rather than last-writer-wins. The unique partial index stays as the final backstop.
Known remaining gap: two concurrent `create` calls with the same `client_id` make two threads (no thread exists to dedupe against). Impact is cosmetic; the widget disables its send button while a create is in flight. Not fixed server-side.
Tests (`TransactionTestCase`, real threads, authoritative on PostgreSQL via CI; skipped on SQLite with `skipUnlessDBFeature('has_select_for_update')`): two simultaneous sends with one `client_id` produce one row and statuses 201/200; 40 simultaneous sends against a cap of 30 persist at most 30; simultaneous visitor send and staff reply end in a status matching the last committed message; two `process_due` workers send one outbox row once.

### C6. Explicit reopening, replacing silent reopen-on-reply

Behaviour:
- A closed thread rejects a visitor message **and** a staff public reply with `409 {"code": "closed"}`.
- Staff: `POST /api/admin/support-chat/threads/<id>/reopen/` `{reason?}`, person required. Sets status `open`, clears `closed_at`, `reopen_count += 1`, writes a visible system message «گفتگو دوباره باز شد» and a semantic `AuditLog` row (ids only).
- Visitor: `POST /api/support-chat/threads/<id>/reopen/` allowed within a window after closing (value needs approval; default proposal 14 days); same effects; after the window the widget starts a new thread and pre-fills the stored contact.
- CSAT: a rating survives a reopen (same rule as tickets: the score is kept and the next closure can be rated again, replacing it; the previous value is not lost from metrics because the metric reads the final score per thread). Needs approval.
Tests: reply to closed returns 409 and changes nothing; reopen by staff and by visitor write the system message and the audit row; visitor reopen after the window returns 409; `reopen_count` increments once per reopen; a rated thread keeps its score when reopened.

### C7. Truthful availability and response time

- Remove `expected_reply_minutes` (currently 480, derived from the normal-ticket SLA) from `GET /api/support-chat/status/`. Return `{mode, reply_target_minutes}` where the second field is `null` unless the owner sets `KG_SUPPORT_REPLY_TARGET_MINUTES` (or the SystemState equivalent); the default is unset, so **no time is shown or promised**.
- Customer-facing copy (for approval): live «پشتیبانی آنلاین است»; async «پیام شما ذخیره شد و در اولین فرصت پاسخ می‌دهیم». Operational SLA stays internal and is never serialised to visitors.
- Presence window: keep the 25 s heartbeat but widen `LIVE_WINDOW` to 90 s and send the heartbeat from a Web Worker in Phase 5, because browsers throttle timers in hidden tabs (*documented browser behaviour; not measured in this app*). A false "async" is the safe failure; a false "live" is not possible without a fresh heartbeat.
Tests: status returns `reply_target_minutes: null` by default and the number when configured; the status payload never contains the SLA minutes; presence stays live at 80 s and drops at 91 s.

## 2. Decisions that need your approval

| # | Decision | Recommendation | Alternatives |
|---|---|---|---|
| A1 | **Retention periods** (not applied; nothing is deleted until approved) | **R1** below | the original 30 / 365 |
| A2 | Visitor reopen window | 14 days after closing | 7 or 30 days; or no self-reopen |
| A3 | CSAT after reopen | keep score, allow re-rating at next closure | lock the score; or clear it on reopen |
| A4 | Rename to `support-chat` / `Support*` now | yes (C3) | keep `chat` names, accept the confusion |
| A5 | Poll limits (30 / min per thread; create 20 / 10 min per IP) | as in C2 | stricter, accepting NAT false positives |
| A6 | Dedicated nginx zone for `/kg-api/api/support-chat/` | defer; `kg_api` already limits at 20 r/s per client | add a zone (infrastructure change, not applied) |
| A7 | Customer copy and the unset-by-default reply target | as in C7; you set a number only when staffing supports it | show a worded range |
| A8 | Staff reply and reopen need a signed-in person | yes | allow the script token |
| A9 | Pre-sales vs technical reporting groups | as in C4 | different grouping |

### R1: proposed retention (for approval; **not** implemented)

Reasoning: store personal data only while a follow-up is plausible; keep conversation text no longer than its context is useful; anonymous threads with no way to reach the visitor have no follow-up value; unverified phone numbers typed by strangers are a liability, so 365 days is hard to justify. A legal-entity purchase cycle can run for weeks, so contact threads need months, not days. This is an engineering recommendation, not legal advice; the policy text is yours.

| Data | Recommendation | Rationale |
|---|---|---|
| Thread, no contact | delete 30 days after last activity | cannot be followed up; covers a return visit |
| Thread with contact | delete 180 days after last activity | two sales quarters; shorter than the original 365 |
| Thread marked spam | delete 7 days after being marked | no value |
| Promoted thread | delete 30 days after promotion | the ticket holds the record |
| `Event` | never contains message text or contact | already bounded to the newest 20,000 rows |
| `AuditLog` | staff actions only, ids only, no visitor body or IP | its rows are never trimmed |
| `NotificationOutbox` | 30 days (`sent`, `dry_run`, `suppressed`); 90 days (`dead`); body blanked on terminal status | enough for delivery investigations |
| Individual erasure | admin action in Phase 5 deletes a thread and its outbox rows on request | |
| Backups | cannot honour deletion until backup retention is defined (open risk; *unverified*) | |

## 3. Verification required before pushing Phase 2

Each item is a gate; I will report it as verified only after running it and quoting the output.

1. New tests for C1 to C7 written first and watched failing, then passing. Target: all `api.support_chat` and `api.notifications` tests pass locally on SQLite.
2. Full backend suite on SQLite: the report states the count and **lists the 17 baseline failures by name** (10 failures, 7 errors, 2 skipped, 1 expected failure on the pre-change baseline) and diffs against them. They stay visible as failures, not as passes.
3. PostgreSQL: push needs your approval; CI then runs the whole suite and `migrate` on PostgreSQL 16, including the new `TransactionTestCase` concurrency tests. No PostgreSQL is available locally, so until CI runs, PostgreSQL compatibility is **unverified**.
4. Migration graph: re-fetch immediately before regenerating `0041` and again before any PR; `check_migrations.py origin/work` and `makemigrations --check`. Today *verified*: `origin/work` and every remote branch have no migration beyond `0039` except mine; local-only work by the other developer is invisible to me. I will ask them to confirm no pending `0040`/`0041`/`0042`.
5. Rollback rehearsal: `check_migrations` plus a documented `deploy.sh --rollback` run on staging, which needs your authorisation (not performed).
6. OpenAPI and routing: `test_openapi_routes` green; guard test that no route starts with `api/chat/`; assistant routes still resolve.
7. Assistant compatibility: `smoke.sh` assertion for `/api/chat` untouched; the Next.js route and nginx rules unchanged.
8. Performance: **no target is claimed** until `qa/k6/chat_poll.js` is run against staging with limits relaxed for the run (k6 is not installed here). Only the arithmetic of limits is stated, labelled as such.
9. Security tests: the C1 AuditLog/Event negative tests, the C2 negative paths, token-format early rejection with zero queries.

## 4. Safe to defer

Per-admin read state; `first_response_at` column; per-thread SLA columns; dedicated nginx zone; WebSockets or any new infrastructure (SSE vs polling below); server-side dedupe of duplicate `create`; verified visitor phone; cross-device recovery; delivery receipts and bounce handling; outbox kick wiring (Phase 6); the Web Worker heartbeat (built with the admin inbox in Phase 5).

### Messaging: polling vs the existing SSE

| | Polling (chosen for visitors) | SSE (existing) |
|---|---|---|
| Cost per visitor | short requests; a visitor holds no thread between polls | holds **one of 24 request threads** for up to 300 s and queries the database every second (*verified*, `events.py`) |
| Visitor scale | grows with request rate | capped by 24 threads shared with the whole API |
| Latency when live | about the poll interval (3 s proposed) | about 1 s |
| Fit | anonymous visitors, unknown count | signed-in customers and staff, bounded by seats; nginx `limit_conn kg_sse 8` per client |
| Maintainability | stateless, simple retry | already built and tested |

Recommendation: keep polling for anonymous visitors, adaptive (3 s only while live and active, 15-30 s otherwise, stopped when the tab is hidden), and reuse SSE for staff and signed-in customers, exactly as designed. No new infrastructure. Whether polling meets the "responsive when live" goal is **unmeasured**; it is measured with k6 on staging before any claim.

## 5. GitHub and development record

Performed and verified through `gh` and `git`:
- Issue **#61** "Customer communication Phase 1: notification outbox (SMS/email, off by default)" created 2026-11-02 11:41 UTC by account `mjsn800403` under decision D11. State open; 0 comments, 0 labels, 0 assignees. No other issue was created, edited or commented on.
- Branch **`feat/customer-communication-core`** pushed once (2026-11-02, 18:14 +03:30 local), carrying the 5 Phase 1 commits (head `2f1033c`). That push triggered CI run 41464774217 (success, including PostgreSQL 16).
- **No pull request** exists for the branch (checked); nothing merged; nothing deployed; the production server was not touched.
- Local only, unpushed: 7 Phase 2 commits `f468f2c..6ce874e`.
- Outside GitHub: the worktree `D:\programing\KGKG-wt-chat`; Python 3.12.10 (winget, user scope) and Node 20.20.2 (portable, `D:\programing\tools`) installed locally with your approval; two untracked files (this spec and the first plan) sit in the main checkout `D:\programing\KGKG` because I created them there before making the worktree (copies are committed on the branch). I have not removed them.

## 6. Proposed order after authorisation

1. C3 rename (mechanical, first so later work is not renamed twice). 2. C1 privacy. 3. C4 fields and the regenerated `0041`. 4. C2 limits. 5. C5 concurrency. 6. C6 reopen. 7. C7 status/presence. 8. Docs, OpenAPI, CHANGELOG. 9. Local gates, then ask to push for PostgreSQL CI.
