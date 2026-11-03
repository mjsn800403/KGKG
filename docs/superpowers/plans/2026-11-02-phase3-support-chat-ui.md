# Phase 3: Human Support Platform Implementation Plan (revision 3)

> **Revision 3 (2026-11-03):** M0 and M1 are authorised locally for migration-free tasks only. Task 0.2 (events) and the role parts of Task 2.1 are blocked pending migrations A/B; the role rollout, event design and branch strategy are in `specs/2026-11-03-phase3-architecture-reconciliation.md`. **M4 acceptance gate (G4)**: metric dictionary entries merged with each endpoint; every metric has calculation, source of truth, exclusions and a pinning test that recomputes it independently from fixtures; data-completeness indicators; `null`/empty states on an empty database; sales and technical never blended; evidence export is deterministic (same data, same bytes) and contains no contact, text or thread ref; metrics are computed only from real records, test/QA threads carry the exclusion marker and fixtures never appear outside tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. **Nothing in this plan is approved or started.** Execution needs the owner's explicit approval, and tasks marked **[needs approval]** need a separate yes first.

**Goal:** A visitor sends a message, staff receives it, a human answers, the visitor sees the reply, and the whole interaction is recorded and traceable; then grow that into a role-governed, measurable, monitored support operation.

**Architecture:** Hybrid (spec option C). New isolated frontend module for the anonymous widget; staff conversations as a tab inside the existing «میز پشتیبانی» reusing `TicketThread`; additive backend in `api/support_chat/`; an append-only event history for measurement; role permissions for support; notifications through the Phase 1 outbox. Visitors poll, staff and customers use the existing SSE. No new infrastructure, no AI.

**Tech Stack:** Next.js 16 / React 19, `node:test`, Playwright, Django 5.2, PostgreSQL 16 in CI.

**Spec:** `docs/superpowers/specs/2026-11-02-phase3-support-chat-ux-design.md` (read first; this plan argues from it). **Privacy draft:** `docs/superpowers/specs/2026-11-02-privacy-notice-draft.md`.

## Scope tiers (what is in which increment)

| Tier | Milestones |
|---|---|
| **Immediate (launch path)** | M0 foundations, M1 first functional milestone, M2 operations and access control, M3 notifications and monitoring, M6 hardening and gates |
| **Soon after** | M4 reporting, dictionary and evidence pack, M5 authenticated customer integration |
| **Later** | canned replies, merged ticket and chat list, per-agent read state, desktop notifications, audit-log viewer, configurable service targets, erasure tool (after retention approval) |
| **Future** | adoption of an anonymous thread at login, attachments, reply by email, staffing calendar |

Execution order is by dependency, not only priority: M0 first; M1 needs M0; M2 can start in parallel with M1 (different files) but must finish before launch; M3 before launch; M4 and M5 may follow launch preparation; M6 gates everything.

## Migrations (proposed, none created until approved)

| # | Table | Why | Notes |
|---|---|---|---|
| A | `SupportThreadEvent` | structured, append-only history for traceability and every time-based KPI; survives content purge | no FK to the thread (plain UUID), enums and ids only |
| B | `SupportStaffRole` (empty table, **no data migration**) | role-based access; default deny; bootstrap owners from `KG_SUPPORT_OWNERS`; `off`/`audit`/`enforce` rollout | pair unique; see reconciliation section 2 |

Both are new tables (no existing table altered), written with `db_default` on NOT NULL columns, passing `check_migrations`. Before generating either: fetch, re-check the graph (`origin/work` and all branches), and agree numbering with the other developer. Expected numbers `0042` and `0043` after `0041` lands.

## Global Constraints

- Human support only. No AI/LLM/RAG/external inference; no new third-party npm or pip package; a test scans backend and `support-chat/` imports for AI stacks.
- Persian RTL UI copy, English code and comments; all Persian copy is a proposal until approved.
- Keep Phase 2 invariants: token isolation, person-required staff endpoints, no message text, contact or visitor IP in `AuditLog`, `Event` or any new log, limits per thread, explicit reopen, ratings per closure, idempotent create.
- Do not touch: `api/rag/*`, `cardb*`, `parts*`, `frm.py`, `safepath.py`, `deploy.sh`, `ci.yml`, `requests_api.py`, `sla.py`; `api.jsx`, `globals.css`, `GuidanceProvider.jsx` only in M5.
- Retention stays report-only. `KG_NOTIFY_SMS`/`KG_NOTIFY_EMAIL` stay `off`; no real send; no credentials.
- The widget is never made public by deployment: it is gated by `KG_SUPPORT_CHAT_ENABLED` (default off) and a person flips it after G2.
- Never claim an unmeasured number; never create, seed or imply operational history; QA conversations are marked `excluded`.
- Frontend gates: `npx eslint src --max-warnings "$(cat ../ops/deploy/lint_max_warnings)"`, `npm test`, `npm run build` (Node 20).
- Branch `feat/support-chat-phase3` is stacked on the unmerged Phase 2 branch (reconciliation section 1); never rebase pushed branches; PR to `work` referencing an issue the owner approves; docs and one CHANGELOG line with each behaviour; `git add -f` for `*.md`; the metric dictionary entries ship with the endpoint that serves them.
- Windows: run local backend suites from Git Bash (existing `hostjobs.pid_alive` sends Ctrl-C from a console); do not fix it here.
- Isolated tooling: install Playwright Chromium into a directory outside the repo (`PLAYWRIGHT_BROWSERS_PATH`) when implementation is authorised.

## Review Focus (cases the tests below do not name but must cover)

- Turnstile blocked or failing: typed text kept, fallback contacts shown.
- Double-click and retry: no second message or thread.
- Thread gone (404), `localStorage` unavailable or full, token revoked.
- RTL: Latin names, digits, URLs and emoji inside Persian bubbles keep logical order.
- A role without `reveal_contact` must not recover contact from any response, event, export or error.
- An agent outside an intent scope must not see, count in metrics views, or be assigned that thread.
- Heartbeats must not extend an admin session.
- Kill switch off: no launcher, no polling, no widget network calls, and thread creation refused server-side.
- An empty database must produce `null`/empty states everywhere, never zeros that look like measurements.

---

## M0: Foundations (backend, additive)

**Value:** staff can see conversations at all; the widget can stay dark; every transition leaves a structured record. **Depends on:** Phase 2 (done).

### Task 0.1: Kill switch

**Files:** `support_chat/config.py`, `views_status.py`, `views_public.py`, tests. **Interface:** `config.enabled() -> bool` (`KG_SUPPORT_CHAT_ENABLED == "1"`). Status adds `enabled`; thread creation returns 404 when disabled.
- [ ] Tests first (default off, only `"1"` enables, create refused while off, existing threads still readable by their owners). Implement; commit.

### Task 0.2: Event history **[needs approval: migration A]**

**Files:** `support_chat/models.py` (new model), `events_log.py` (`record(kind, thread, actor=None, **data)`), tests. **Interface:** `record` writes inside the caller's transaction, rejects any `data` value that is not an enum-like string, int or bool (a guard test proves text and contact cannot be stored).
- [ ] Tests first: each lifecycle function and view writes the right kind (`created` with mode and intent, `closed`, `reopened`, `rated`, `assigned`, `fallback_to_async` via an endpoint the widget calls, `opened`), no text in `data`, survives thread deletion, indexes used.
- [ ] Wire into Phase 2 code paths; PostgreSQL concurrency tests extended (two closes write one event).

### Task 0.3: Staff list and detail with computed unread

**Files:** `views_admin_inbox.py`, `test_inbox_api.py`, `urls.py`, OpenAPI and docs. **Produces:** `GET /api/admin/support-chat/threads/` (filters: status, intent group, intent, assignee me/none/id, priority, unread, `q` over contact fields and id prefix, cursor, counts) and `GET .../threads/<id>/` (all messages including internal, event timeline, ratings history, `staff_seen_at`). Contact is returned masked until M2 adds permissions; for M0 the endpoints require a signed-in person.
- [ ] Tests first: 401/403, filters, counts, unread rule (newest visitor message later than `staff_seen_at`), paging stability on PostgreSQL, query count bound, internal notes only for staff.

### Task 0.4: Actions and staff events

**Files:** `views_admin.py`, tests. **Produces:** `assign`, `priority`, `intent`, `spam`, `exclude` (marks QA/test threads out of metrics; reversible via `restore`), each person-required, audited by id only, writing events, emitting `support_chat.updated {thread_id}` to the admin audience; replies, close and reopen also emit it.
- [ ] Tests: validation, audit has no content, events carry ids only, concurrent assign and close serialise (PostgreSQL).

### Task 0.5: Heartbeat fix

**Files:** `admin_auth.py` (small additive `require_admin_session_no_touch`), `views_status.py`, tests. **Behaviour:** heartbeat resolves the session read-only and never slides `expires_at`; accepts `{active: bool}`.
- [ ] Test first: repeated heartbeats leave `expires_at` and `last_used_at` unchanged; an expired token is refused; all other admin endpoints still touch as before.

**Acceptance M0:** new tests pass locally and in PostgreSQL CI; OpenAPI sync green; no existing table altered; privacy tests extended to new paths; kill switch verified off by default.

---

## M1: First functional milestone, visitor to human to visitor

**Value:** the complete journey in spec section 4 works end to end and is recorded. **Depends on:** M0. **Reuse:** `TicketThread`, `useEventStream`, tokens and icons, `lib/support.js` helpers.

### Task 1.1: Pure widget modules (tests first)
**Files:** `kg_frontend/src/support-chat/{copy.fa.js,token.js,storage.js,client.js,state.js,schedule.js}` + `__tests__/`.
**Interfaces:** `makeToken(rand)` (43 chars `[A-Za-z0-9_-]`); `createStore(backing)` (memory fallback, bounded queue of 20 with 24 h expiry, queue in `sessionStorage`, token in `localStorage`, `onChange`); `createClient({fetch, base})` returning `{ok,data}` or typed errors (`rate_limited` with `retryAfter`, `closed`, `not_found`, `invalid`, `network`, `server`); `reduce(state, event)`; `nextPollDelay({...}) -> ms|null` per spec 6.4.
- [ ] Failing tests first for each; implement; `npm test` green.

### Task 1.2: Turnstile loader
**Files:** `turnstile.js` + test. **Interface:** `createTurnstile({sitekey, doc}) -> {prepare, execute, reset, dispose}`; `action:'support_chat'`, `appearance:'interaction-only'`, `execution:'execute'`; sitekey from `NEXT_PUBLIC_TURNSTILE_SITEKEY` defaulting to the login key; rejects `{kind:'blocked'|'timeout'|'failed'}`.
- [ ] Tests with a fake `window.turnstile`; dispose guard matches the login page's.

### Task 1.3: Widget UI
**Files:** `SupportChat.jsx`, `ChatPanel`, `MessageList`, `Composer`, `ContactCard`, `Availability`, `StartersGrid`, `ClosedBar`, `useSupportChat.js`, `support-chat.css`; one-line mount in `layout.tsx`.
**Behaviour:** spec section 3 exactly (honesty rules, per-intent status, 90 s fallback calling the event endpoint, contact card after first send, delivery states, offline queue, retry, 429 countdown, closed bar, rating, "delete from this browser", privacy link).
- [ ] Lint and build within ratchet; with `enabled:false` zero widget requests.

### Task 1.4: Staff workspace tab (core)
**Files:** `src/support-chat/admin/{SupportChatInbox,ChatThreadList,ChatThreadPane,ChatContextPane,AvailabilityControl}.jsx`, `utils/supportChatApi.js`, additive system-line branch in `TicketThread.jsx`, tab mount in `admin/page.jsx` at `company-requests`.
**Behaviour:** list with status tabs and unread, thread pane via adapter, reply and internal note, assign to me, close and reopen, mark seen once per open, event timeline, availability declare, combined unread in tab title; SSE refresh.
- [ ] Adapter and list logic unit-tested first; the ticket desk's existing tests stay green.

### Task 1.5: Journey proof
**Files:** `qa/e2e/tests/support-chat.spec.js` (S1-S5, S8-S10), isolated Chromium install, local stack (`runserver` DEBUG + `next build/start`, Cloudflare test sitekey).
- [ ] Two browser contexts (visitor, staff); assertions on the DB records of spec section 4 (thread, messages, events, audit rows without text).

**Acceptance M1 (gate G1):** E2E green locally and on the QA stack (kill switch on there only); every step leaves its record; CI green on PostgreSQL; unit tests, lint and build within ratchet; no staff name, avatar, typing indicator or time promise anywhere; Turnstile failure never loses typed text.

---

## M2: Operations and access control

**Value:** a governed support operation: least privilege, honest presence, ownership discipline. **Depends on:** M0 (M1 for the UI parts). Must finish before launch.

### Task 2.1: Roles and permissions **[needs approval: migration B]**
**Files:** `support_chat/models.py` (`SupportStaffRole`), `perms.py` (`has_perm(admin, perm, intent=None)`, `require_support_permission(perm)`), management command `set_support_roles`, data migration, tests.
**Behaviour:** spec section 8: default deny, five roles, intent scopes, owner grandfathering of active admins, role changes audited by id, loopback token has nothing.
- [ ] Tests first: a role-by-endpoint matrix covering every support endpoint (agent, sales, lead, auditor, owner, no role, loopback); scope enforced in the queryset (an out-of-scope id is 404, not 403, and absent from counts); masked contact cannot be recovered from any field, event, export or error; contact reveal audited once per admin and thread per day.

### Task 2.2: Role-aware UI and role admin panel
**Files:** staff components (controls absent when not permitted), `SupportRoles.jsx` (owner-only) in the support section.
- [ ] Component logic tests for visibility rules; E2E S17.

### Task 2.3: Presence reliability
**Files:** `support_chat/presence.py` (eligibility with permission, scope, activity, optional capacity), `public/support-presence-worker.js`, `AvailabilityControl.jsx`, tests.
**Behaviour:** spec section 9: eligible only if active, permitted, connected, declared, practically present; per-intent `current_mode(intent)`; auto-away after `KG_SUPPORT_AUTO_AWAY_MIN` (default 10); one leader tab (BroadcastChannel); worker timer with main-thread fallback; `pagehide` offline with keepalive; reconnect banner.
- [ ] Unit tests with fake clocks (stale, away, scope, capacity, permission loss); Playwright experiment measuring ping cadence in a background tab with and without the worker; tab-close-to-async time; results recorded in the PR as measured (keep the worker only if it measurably helps).

### Task 2.4: One SSE stream per admin tab
- [ ] Count open streams first and record it; add a provider shared by the admin page and the inbox; assert the new count in E2E; no event semantics change.

### Task 2.5: Ownership and priority discipline
- [ ] Unassigned queue view, claim, reassign with events, default priority rules (deterministic by intent, editable), tests for every transition and its event.

**Acceptance M2:** role matrix green on SQLite and PostgreSQL; S17 passes; heartbeat experiments reported with numbers; an agent outside scope cannot learn that a thread exists.

---

## M3: Notifications and operational monitoring

**Value:** staff learn about conversations promptly; unanswered and aging work is visible; failures are never silent. **Depends on:** M0 events, Phase 1 outbox. Must finish before launch. Nothing is sent: `off` and `dry_run` only.

### Task 3.1: Worker guard hook
**Files:** `notifications/worker.py`, `guards.py`, tests. **Interface:** `register_guard(event_type, fn(row) -> bool)`; a row whose guard is False at send time becomes `suppressed` (reason `guard`) and is not counted toward the cap.
- [ ] Tests first.

### Task 3.2: Triggers and templates
**Files:** `support_chat/notify.py`, call sites, tests. **Behaviour:** the table in spec section 11 (first-message SMS and email with a delayed, guard-cancelled SMS, email digests via window keys, reopen email, aging email to leads, content-less visitor nudges with the per-thread and per-phone limits); recipients from configuration (`KG_SUPPORT_NOTIFY_PHONES`, `KG_SUPPORT_NOTIFY_EMAILS`); every SMS body passes `check_sms_body`; payloads contain no message text.
- [ ] Tests with the Fake provider: dedupe, coalescing, guard cancellation, caps, scrubbing, channel failure leaves the chat fully working, mode `off` yields only `suppressed`.

### Task 3.3: Monitoring and health
**Files:** `alert_rules` additions (aging, unanswered-live, abandoned inbox: kill switch on with no eligible agent beyond the owner-set time), `GET /api/admin/support-chat/notifications/health/` (counts only, no recipients), header panel.
- [ ] Tests: rules fire on aged and empty fixtures and stay quiet otherwise; thresholds come only from configuration and are unset by default.

### Task 3.4: Operations pack (docs)
- [ ] Activation checklist, timer installation by a person, `dry_run` review procedure, one authorised live test per channel, kill-switch and rollback runbook, on-call guidance for aging alerts.

**Acceptance M3:** S14 passes locally; nothing sends in any default configuration; `dry_run` on staging yields reviewable rows; the owner has the exact input list.

---

## M4: Reporting, metric dictionary and evidence pack (soon after launch path)

**Value:** defensible, reproducible support figures and a way to show them. **Depends on:** M0 events and ratings.

### Task 4.1: Metric dictionary
**Files:** `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md` (new section "Visitor support chat", entries V1-V13 exactly as in spec 10.2, each naming calculation, source, hand reproduction and pinning test).
- [ ] Written with the tests that pin it, in the same change as the endpoint.

### Task 4.2: Metrics endpoint
**Files:** `support_chat/metrics.py`, `test_metrics.py`. **Produces:** `GET /api/admin/support-chat/metrics/?days=` (permission `support.metrics`), reusing `support_metrics` helpers; every rate returns numerator, denominator and `unmeasured`; empty input returns `null`.
- [ ] Tests first per metric with a hand-computable fixture: empty, one thread, censored thread, reopen chain, rating per closure, excluded and spam threads, intent-group split, live versus async, closures across a window edge, PostgreSQL ordering.

### Task 4.3: Dashboard
**Files:** panel inside «شاخص‌های پشتیبانی» (`SupportChatMetricsPanel.jsx`), definitions drawer from the same text, data-completeness strip, empty states, workload visible only to leads and owner.
- [ ] Logic tests for formatting and empty states; axe; no sample data anywhere (a test asserts the component renders only endpoint data).

### Task 4.4: Evidence pack
**Files:** `management/commands/support_evidence_pack.py`, owner-only trigger. **Output:** dated JSON and markdown with values, numerators, denominators, dictionary text at that commit, git SHA, completeness strip, event counts by kind, role-change audit counts (ids only); states plainly when history is short or empty.
- [ ] Test S18: a fixture database reproduces hand-calculated values; the pack contains no personal data (scanned); running it on an empty database yields an honest empty report.

**Acceptance M4 (gate G3):** every displayed metric has a dictionary entry and a passing test; the pack is reproducible by hand from the tables named; no placeholder data exists in code or UI.

---

## M5: Authenticated customer integration and launcher consolidation

**Value:** one coherent support experience in every panel. **Depends on:** M1-M3. **Touches shared files:** `GuidanceProvider.jsx`, `globals.css`, `api.jsx` (additive), `guidance/content.js`.

- [ ] Task 5.1: one launcher hub with tabs «گفتگو», «راهنما» (existing `HelpCenter`), «بازخورد» (existing feedback content); the `.guide-fab` tour selector stays working or its tour step and test change in the same commit.
- [ ] Task 5.2: «گفتگو» for signed-in seats over the existing ticket API (first message creates the ticket: subject from the first line, topic starters mapped to existing topics, page and vehicle context; list, unread, existing CSAT); labels keep «گفتگو» (sales chat) distinct from «درخواست پشتیبانی» (ticket).
- [ ] Task 5.3: regression: desk tests, onboarding tests, tour tests, `support.spec.js`.

**Acceptance M5:** S7 passes; no signed-in page shows overlapping floating elements; tours work; tickets and visitor chats cannot read each other's data. Adoption of an anonymous thread at login stays deferred.

---

## M6: Hardening and launch gates

- [ ] Task 6.1: security regression pack: wrong and foreign tokens, internal note leakage through every visitor response, role matrix across all paths, masking leaks, no content in `AuditLog`/`Event`, heartbeat does not extend sessions, rate limits with two visitors on one IP, XSS-as-text, token revoke.
- [ ] Task 6.2: accessibility and RTL sweep: axe on every state in both themes, keyboard-only journeys, 200% zoom, mixed-direction text, Pixel 7 and Firefox projects for the widget spec (small `playwright.config.js` edit).
- [ ] Task 6.3: login and recover decision: run the 3.1 criteria at 375 and 1280 px; enable only if all pass.
- [ ] Task 6.4: privacy page `/privacy` built from the approved text; in-widget notice and links; revoke action.
- [ ] Task 6.5: performance gate: extend `qa/k6/support_chat_poll.js` with the staff list and SSE count; run on staging only; thresholds set from the first measured run and ratified by the owner. **Not run or claimed in this plan.**
- [ ] Task 6.6: staging soak with a real agent session and `dry_run` notifications; then the launch checklist.

### Launch gate G2 (not part of any increment's code)

M0-M3 merged and green on PostgreSQL CI; role matrix and masking green; presence measurements reported; privacy page approved and published; staffing, hours and inbox owner confirmed; copy approved; `dry_run` reviewed and one authorised live test per channel; aging alert and health panel verified; k6 measured and accepted; the kill switch flipped by a person after explicit approval. Production promotion stays a person running `kgkg-promote`.

## Approvals and external inputs checklist

Approvals: migrations A and B (and numbering with the other developer); the role model; heartbeat and auto-away change; privacy wording and its legal review; metric dictionary and any thresholds; login and recover outcome; public activation; real SMS and email; retention. Inputs before activation: staff identities and roles, working hours, notification recipients, SMS budget and credit sharing, email provider and domain with SPF, DKIM and DMARC, approved templates, who owns the inbox.

## Self-review

- Coverage against the brief: widget (M1, M6), staff workspace and ownership (M1, M2), RBAC (M2), hybrid presence (M2), notifications and monitoring (M3), KPI framework, dictionary and evidence pack (M4), authenticated integration (M5), privacy and storage review (spec 12, M6), verification and gates (spec 13, G1-G3).
- Order deviation, justified: foundations (M0) first because staff cannot see conversations today; notifications and RBAC before launch although they are not "visible" features.
- Types: `has_perm`, `require_support_permission`, `record`, `register_guard`, `nextPollDelay`, `reduce`, `createClient`, `createStore` are defined once and referenced consistently.
- M4-M6 steps are expanded to bite-sized form just before execution, because their details depend on M1-M2 outcomes; the acceptance criteria above are the fixed contract.
