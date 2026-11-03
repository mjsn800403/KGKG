# Phase 3: a product-grade human support platform (final design)

**Date:** 2026-11-02 (revision 2, after the owner's strategic direction). **Revision 3 (2026-11-03):** the owner approved the direction conditionally; sections 6.2, 8.2 and 12.3 are superseded by `2026-11-03-phase3-architecture-reconciliation.md` (no role-granting data migration; events are pseudonymous, minimised, retention-bounded; Phase 3 is stacked on the unmerged Phase 2 branch).
**Status:** DRAFT for approval. Nothing here is implemented. No code, migration, commit, push, deploy or message has been made for Phase 3.
**Builds on:** `2026-11-02-customer-communication-design.md` (architecture C) and the verified Phase 2 backend (`api/support_chat/`, CI run 41490509088 green on PostgreSQL).
**Hard constraint:** every support reply is written by a human. No AI, LLM, RAG or external inference anywhere in this system. Rule-based routing, scheduling and notification triggers are fine.
**Companion files:** `plans/2026-11-02-phase3-support-chat-ui.md` (implementation plan), `2026-11-02-privacy-notice-draft.md` (proposed wording and page structure, not legal advice).
**Labels:** *verified* = read in this repo or run this session; *assumed* = my judgement; *unverified* = not checked; *proposed* = a value or text awaiting your decision or a measurement.

## 0. Strategic objective and scope

The 2026 evaluation criticised the maturity of customer support (`audit-evidence/16-improvement-programme/ROOT_CAUSE_ANALYSIS.md`, Finding 4: no ownership, no clock, no satisfaction measurement, no reopen, no escalation, nothing that tells anyone). The desk shipped in October answers that for authenticated tickets. This phase extends the same standard to **visitors and sales enquiries** and adds the missing operational layer: roles, structured history, defined metrics, monitoring and an evidence trail.

The aim is a platform whose claims can be checked: every number comes from a recorded event, every definition is written down and pinned by a test, no history is fabricated. Complexity is accepted where it produces working functionality, but each item below is justified by a concrete workflow or a defined metric.

### 0.1 Scope tiers

| Tier | Contents |
|---|---|
| **Immediate** (Milestones M0-M3, the launch path) | kill switch; structured thread event history; staff inbox with assignment, notes, priority, status, explicit close and reopen; role-based access with contact masking; honest presence with reliable heartbeat; visitor widget (live and asynchronous, persistence, retry, Turnstile, RTL, mobile, accessibility); notification triggers, outbox monitoring and aging alerts (delivery stays off until authorised); privacy page and in-widget notice; E2E and security gates |
| **Soon after** (M4-M5) | support operations dashboard and metric dictionary with an evidence-pack export; authenticated customer integration and one launcher for help, chat and feedback |
| **Later** | canned replies written and owned by staff; merged ticket and chat list; per-agent read state; browser desktop notifications; audit-log viewer for support actions; configurable service targets once the owner defines them; individual data-erasure tool once retention is approved |
| **Future** | adoption of an anonymous thread at login (deferred by decision); optional attachments; reply by email; staffing calendar |

### 0.2 Decisions incorporated from the owner

Inbox as a tab in «میز پشتیبانی»; reuse the existing Turnstile sitekey after checking compatibility; launcher on landing, purchase and portal, with login and recover evaluated against UX conflicts (3.1); fallback to asynchronous mode after a configurable 90 s unanswered (never a response-time promise); staff label «پشتیبانی»; system label «سامانه»; role-based staff permissions; genuine KPIs; privacy wording prepared for review; SMS and email activation and public activation each need separate approval; adoption at login deferred.

## 1. Verified facts that shape the design

| Fact | Evidence |
|---|---|
| The landing page has **no floating support presence**; the help button is hidden there. | `landing.css:690` |
| A signed-in seat sees three overlapping entry points (help FAB, feedback launcher, Requests page). | `globals.css:1539,2462`, `GuidanceProvider.jsx:211-243` |
| The KB endpoints need a portal login; an anonymous visitor has no article search. | `knowledge.py` |
| Customer tickets are conversation-oriented, with unread state and CSAT, and show SLA state and a due time to the customer. | `RequestsView.jsx:360-374` |
| The admin desk is a section of a 3568-line `admin/page.jsx`; `RequestsInbox` and `TicketThread` are reusable. | `admin/page.jsx:207-238,423` |
| **Platform admins have no roles.** `PlatformAdmin` is a flat superuser (username, phone, active); the loopback token and any active admin can read every conversation and contact. | `models.py` (`PlatformAdmin`), `docs/06-permissions-rbac.md` §6.7 |
| There is no UI or command that creates platform admins (only a QA seed); they are created out of band. | repo search |
| An admin session has a **12 h idle** and **7 day absolute** limit, but every authenticated call slides the idle window (`touch`). The Phase 2 heartbeat uses that gate, so a console pinging every 20 s would keep a session alive for the full 7 days. Not yet reachable (no heartbeat UI), but it must be fixed before one exists. | `models.py` (`AdminAuthToken`, `SessionTokenBase`), `admin_auth.py` (`_admin_session`), `views_status.py` |
| The project has a **metric dictionary convention**: one entry per metric with calculation, source column, reproduce-by-hand and a pinning test; "an average of nothing is null"; backlog is current state; calendar time; "a metric not defined here does not exist". | `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md` |
| Existing ticket metrics already report measured versus unmeasured counts, p90, CSAT and backlog; their helpers are importable. | `support_metrics.py` |
| `AuditLog` and `Event` keep no foreign keys so history outlives deleted rows; neither is trimmed by the app. | `models.py` |
| Production's login page loads Cloudflare's script under the real CSP and exposes `turnstile.render/execute/reset/remove` (checked by loading the public page read-only). The widget's dashboard mode and hostname list are **not visible** from the page. | browser check 2026-11-02 |
| Backend capacity: 3 workers x 8 threads = 24 request threads; each SSE stream holds one for up to 5 minutes. An admin tab can hold two streams today. | `backend.Dockerfile:46`, `events.py`, `RequestsInbox.jsx:118`, `admin/page.jsx:38` |
| CSP: scripts `'self'` plus nonce plus Cloudflare, no `worker-src` (so same-origin worker files work, blob workers do not). | `proxy.ts:27-34` |
| Frontend tests are `node:test` over pure modules; E2E is Playwright on the QA stack with a Pixel 7 project for the public spec only. | `package.json`, `qa/e2e/playwright.config.js` |
| No privacy or terms page exists. | search |

## 2. Product principles

1. Honest always: "online" only when a person is eligible; no typing indicator, avatar, staff name or time promise unless the owner sets one.
2. One question before any form; contact details only after the first message is stored.
3. One thread, two modes; nothing is lost when the mode changes.
4. Customer simplicity over backend sophistication: the visitor sees a chat, never a ticket.
5. **Evidence by construction:** operational facts are recorded as they happen (section 6.2), metrics are defined before they are shown (section 10), tests and QA conversations are excluded by an explicit marker, never deleted or invented.
6. Least privilege for staff; contact details masked unless the role needs them.
7. Reuse before building; build only what the workflow needs.

## 3. Landing widget: UX specification

The mockup shown with the earlier draft remains the reference for the three states (welcome while nobody is available, live conversation, closed with rating).

### 3.1 Launcher and placement

* A real `<button>` at the bottom inline-end corner (physical left, matching today's help button), 56 px, chat icon, accent colour, `aria-expanded`/`aria-controls`, visible focus, 44 px minimum target; label «گفتگو با ما» shown for 6 s then collapsed to the icon.
* A dismissible teaser once per session after 20 s on the landing page, never after dismissal or once a thread exists; reduced-motion removes all motion.
* **Where:** landing `/`, `/purchase`, signed-in portal pages (Increment M5) by decision. `/login` and `/recover` are **evaluated, not assumed**: they are the moment a locked-out customer most needs a human, but the page already hosts a Turnstile widget, an OTP flow and (on login) suppresses guidance for cleanliness. Rule: include them only if E2E at 375 px and 1280 px shows no overlap with the form, OTP inputs or footer, no focus conflict with the login Turnstile (two widgets can coexist; the chat's is lazy), and the launcher starts collapsed without teaser there; otherwise keep them off and offer a footer link «گفتگو با پشتیبانی» that opens the panel. `/admin/*` and `/invite/*` are excluded. On `/purchase` the launcher sits above the help FAB until M5 merges them.

### 3.2 Panel

Desktop: 380 x 560 non-modal card, `role="dialog"`, Esc closes and returns focus. Phones (< 640 px): full-height sheet (`100dvh`), modal, safe-area aware, composer above the keyboard via `visualViewport`. Header: brand mark, «گفتگو با پشتیبانی», availability line, close, overflow menu («گفتگوی جدید»، «راهنما»، «حریم خصوصی»، «حذف این گفتگو از این مرورگر»). Existing tokens, both themes, logical CSS properties, Persian digits.

### 3.3 Availability and the 90-second fallback

The server decides `live` or `async` (status fetched on open and every 30 s while open). A visitor may pick a starter first; the status can be asked **per intent** (`?intent=sales|demo|technical|other`) so «قیمت و خرید» can be live while «مشکل فنی» is not, because eligibility is scoped by role (section 8).

| Situation | Header | Notes |
|---|---|---|
| `live` for this intent | «پشتیبانی آنلاین است» | no time promise |
| `async` | «الان کسی پشت میز نیست» + «پیام شما ذخیره می‌شود و در اولین فرصت پاسخ می‌دهیم» | |
| status unreachable | «وضعیت پشتیبانی نامشخص است» | treated as `async` |
| `live` but the first message is unanswered for **N seconds** (default 90, `KG_SUPPORT_LIVE_FALLBACK_S`) | line switches to the `async` text; system line «هنوز کسی پاسخ نداده؛ پیام شما ذخیره شد»; contact card expands | the switch states a fact about this thread, never a guarantee; the fallback event is recorded (6.2) so unanswered-while-live is measurable |
| `reply_target_minutes` configured by the owner | adds «معمولاً ظرف N دقیقه» | only when set |

Never shown: typing indicators, staff names or photos, person-like avatars, invented reply times. Staff replies read «پشتیبانی»; system lines read «سامانه» (centred, muted, never styled as a person).

### 3.4 First contact

Greeting «سلام، چه کمکی از ما برمی‌آید؟» and four starters («قیمت و خرید اشتراک»=sales, «درخواست دمو»=demo, «پرسش یا مشکل فنی»=technical, «سایر»=other). A starter sets the intent and a helpful placeholder; no form opens. Sales shows two static links (plans, pricing) because no anonymous KB exists. Enter sends, Shift+Enter newline, 2000 characters with a counter from 1800. The **contact card** appears after the first message is stored (expanded when `async`, one line when `live`; demo asks name and phone), skippable, with a privacy notice (3.9). Deterministic rules route by intent; there is no classifier.

### 3.5 Conversation

Bubbles: visitor (accent tint), staff «پشتیبانی» (surface, brand mark), system «سامانه» (centred chip). Day separators via `groupByDay`, `fa-IR` times, Latin runs in `bdi`. Delivery states: «در حال ارسال» → «ارسال شد» (stored) → «خوانده شد» (`staff_seen_at` at or after the message) or «ارسال نشد، تلاش دوباره» (the retry reuses the same `client_id`). Stick-to-bottom with a «پیام جدید» pill; `aria-live="polite"` for staff replies only.

### 3.6 Turnstile

Script loaded when the panel first opens (not on page load); `action: 'support_chat'`, `appearance: 'interaction-only'`, executed on the first send; an inline «تأیید امنیتی» box appears only if Cloudflare needs interaction; the token is single-use (creation only; later sends use the thread token); on expiry or failure re-execute and keep the typed text; if the script is blocked show «تأیید امنیتی بارگذاری نشد» with retry and the footer phone and email. **Sitekey compatibility:** reuse the login sitekey. *Verified:* the script and API load under production's CSP, same host as the login page. *Unverified:* the widget's Cloudflare dashboard mode and hostname list; confirm in staging by rendering with the new action and watching the server's verdict (a mismatch is logged by `_verify_turnstile`). If it fails there, a dedicated widget is the fallback (needs Cloudflare access, your call).

### 3.7 Persistence and recovery

First send generates a 32-byte token in the browser (43 base64url characters), stored with the thread id in `localStorage` (`kg_sc_v1`) and sent on create so a retry is idempotent. Unsent messages are queued with their `client_id`. On first panel open and on `visibilitychange` (when a reply is awaited) one request restores history and the unread badge. Tabs share state through the `storage` event. A 404 means the thread is gone: clear storage and show a fresh welcome, no error screen. A closed thread offers «ادامهٔ گفتگو» while `can_reopen` (14 days, `KG_SUPPORT_REOPEN_DAYS`) else «گفتگوی جدید» with contact prefilled; the rating prompt (five faces) shows once per closure.

### 3.8 States, accessibility, mobile

| State | Behaviour |
|---|---|
| Loading | skeleton bubbles, composer usable |
| Offline | bar «اتصال برقرار نیست. پیام‌ها پس از اتصال ارسال می‌شوند»; text queues |
| Failure (5xx/network) | automatic backoff, then bubble state «ارسال نشد» + retry |
| Rate limited (429) | «کمی صبر کنید» with the `Retry-After` countdown |
| Closed (409) | closed bar |
| Validation (400) | server's Persian message beside the field |
| Kill switch off | launcher not rendered; no requests |

A labelled dialog, a `log` region for messages, named icon buttons, full keyboard path (focus trap only on the phone sheet), contrast from the existing themes (axe in both), no clipped text at 200% zoom, 44 px targets, reduced motion honoured.

### 3.9 Privacy information in the product

A two-line notice under the contact card and in the overflow menu linking to a public page `/privacy` (structure and proposed Persian wording in `2026-11-02-privacy-notice-draft.md`, for your and legal review; it is **not** presented as an approved policy). The notice states what is kept, who can see it, and how to remove the browser copy.

## 4. The complete visitor-to-human workflow, with its record

| # | What happens | Recorded as (source of truth) |
|---|---|---|
| 1 | Visitor opens the panel; status fetched | nothing stored |
| 2 | Visitor sends the first message; Turnstile passes | `SupportThread` + `SupportMessage`; event `created {mode, intent, page}`; admin SSE `support_chat.message` (ids only) |
| 3 | Mode is `live` and no one answers for N s | event `fallback_to_async` |
| 4 | Staff row turns bold; the inbox shows count and tab title | computed unread (last visitor message newer than `staff_seen_at`) |
| 5 | Agent opens the thread | `staff_seen_at`; event `opened` (first per agent per thread) |
| 6 | Agent takes it | event `assigned {to}`; audit row by id |
| 7 | Agent replies (and may add internal notes) | `SupportMessage` (public or internal); audit row by id, never the text; first public reply defines first human response time |
| 8 | Visitor sees the reply and the «خوانده شد» tick on the next poll | none beyond the above |
| 9 | Agent closes explicitly | event `closed`, system line, audit row |
| 10 | Visitor rates (once per closure) or continues within 14 days | `SupportRating` (+ event `rated {score}`), event `reopened {by}` |
| 11 | Staff alerted when unanswered or aging | outbox rows (accepted or failed, never the text) |

Every step is attributable (actor id), timestamped, free of message text in logs, and reconstructable by hand from the tables named, which is what the KPI definitions in section 10 rely on.

## 5. UI architecture

### 5.1 Visitor widget (`kg_frontend/src/support-chat/`)

Pure modules with `node:test` tests: `copy.fa.js`, `storage.js`, `token.js`, `client.js`, `state.js` (reducer), `schedule.js` (poll intervals), `turnstile.js`. Presentation: `SupportChat.jsx` (mount, kill switch, route rules), `ChatPanel`, `MessageList`, `Composer`, `ContactCard`, `Availability`, `StartersGrid`, `ClosedBar`, hook `useSupportChat.js`, styles `support-chat.css` (`.sc-*`, tokens only). Mounted by one line in `layout.tsx`. A separate `utils/supportChatApi.js` avoids editing the shared `api.jsx`.

### 5.2 Staff workspace (inside «میز پشتیبانی»)

A tab «گفتگوی بازدیدکنندگان» beside the tickets tab, sharing one header (availability control, combined unread, notification health). Three panes on desktop (list, thread, context), stacked on phones. List: status tabs (new, waiting for us, waiting for visitor, closed), filters (intent group, assignee: me/unassigned/all, priority, unread, search by contact or id), per-row intent chip, age, owner, unread. Thread pane: reuse `TicketThread` (adapter; one additive system-line branch), internal-note toggle, actions gated by role. Context pane: contact (masked unless permitted), page, referrer host, intent, mode at start, ratings history, reopen count, event timeline (the structured history). Role-aware: controls the viewer may not use are absent, not disabled.

### 5.3 Reuse and non-reuse

Reused: `TicketThread`, `DeskFilters` patterns, `useEventStream`, `lib/support.js` helpers, `friendlyError`, `Icon`, theme tokens, `HelpCenter`, `CsatPrompt` pattern. Not reused: `KbSuggestions` (portal-only API), the ticket create form (ticket-shaped), `RequestsView` for anonymous visitors.

## 6. Technical integration with the Phase 2 backend

### 6.1 Visitor calls (exist)

`GET status` (optionally `?intent=`), `POST threads`, `GET/POST messages`, `PATCH contact`, `POST reopen`, `POST csat`, header `X-Support-Chat-Token`; 404 = gone, 409 = closed, 429 honours `Retry-After`.

### 6.2 Structured thread history: `SupportThreadEvent` (proposed new table, needs approval)

> **Revision 3:** the shape below is superseded by reconciliation section 3: typed columns instead of a JSON `data` field, events classed as pseudonymous (not anonymous), a bounded detail stage then aggregate rollups, and thread-level erasure. The rationale in the next paragraph still holds.

Today state transitions live only as free-text system messages and `closed_at`/`reopen_count` that are overwritten. Metrics such as resolution time per closure, time to assign, live-versus-async response and CSAT history cannot be computed reliably from that, and parsing message text would be brittle.

Proposal: an **append-only** table `SupportThreadEvent(id, thread_id UUID (plain column, no FK), kind, at, actor_admin_id nullable int, data JSON)`; kinds: `created`, `fallback_to_async`, `opened`, `assigned`, `unassigned`, `priority_changed`, `intent_changed`, `closed`, `reopened`, `rated`, `spam_marked`, `excluded` (QA/test marker), `restored`. `data` carries only enums and ids (mode, intent, from/to, score, who), **never text or contact**. No foreign key on purpose (same rule as `AuditLog`): when a conversation is purged under an approved retention policy its content disappears but the non-personal operational facts survive, so evaluation figures stay reproducible. Written in the same transaction as the change; indexed on `(kind, at)` and `(thread_id, at)`.

Options considered: (a) derive from `AuditLog` (no migration, but it mixes concerns, `target_id` is an unindexed string, visitor-side facts like mode and rating are not there, and its retention is a separate policy); (b) status quo (not good enough for the KPIs required); (c) the table above (recommended). Cost: one additive migration, written code in the existing transaction boundaries, no change to existing tables.

### 6.3 Other backend additions (additive code; see the plan for tests)

| Need | Detail |
|---|---|
| Kill switch | `enabled` in the status payload from `KG_SUPPORT_CHAT_ENABLED` (default off); widget renders nothing unless true; also checked server-side on thread creation |
| Per-intent availability | status accepts `intent`; eligibility respects role scope (section 8) |
| Staff list and detail | filters, counts, computed unread, cursor paging; masked contact per permission; internal notes only for staff |
| Actions | assign, priority, intent, spam, exclude-from-metrics, all permission-gated, audited by id |
| Staff events | `support_chat.updated {thread_id}` to the admin audience on every change so several agents stay in sync |
| Heartbeat | resolves the session **without extending it** (new non-touching gate), carries `active` (recent human activity) |
| Metrics endpoint | `GET /api/admin/support-chat/metrics/?days=` per section 10, permission `support.metrics` |
| Notification health | counts by status and event, no recipients |
| Aging alerts | rules in `alert_rules` raising a `SystemAlert` (dashboard and email, not SMS) |

### 6.4 Real-time model

Visitors poll (reason verified: 24 request threads, an SSE stream holds one). Proposed schedule, unmeasured: panel open and live 3 s (+-20% jitter); open and async 10 s for 2 minutes after the last send then 20 s; panel closed with a reply owed 60 s; closed with nothing pending none (check on load and `visibilitychange`); hidden tab none; errors back off to 60 s; 429 honours `Retry-After`. Staff and signed-in customers use SSE. A visitor at 3 s makes 20 requests a minute, under the 30 a minute per-thread limit. Capacity is arithmetic only until k6 measures it.

## 7. Support management capabilities

| Capability | How it is provided | Source of truth |
|---|---|---|
| Pre-sales versus technical separation | `intent` groups (`sales`+`demo` = pre-sales; `technical`+`other` = visitor support), role scopes, separate metric groups; authenticated tickets keep `support_metrics` | `SupportThread.intent`, `intent_changed` events |
| Ownership and assignment | assign to me, assign to another, unassign; unowned queue visible; history kept | `SupportThread.assignee`, `assigned` events |
| Categorisation and priority | intent plus priority (low, normal, high) set by staff rules; deterministic default priority by intent (demo normal, technical normal, sales normal; changeable) | thread fields, events |
| Traceable status transitions | open, waiting for staff, waiting for visitor, closed, spam; explicit close and reopen with system lines | status, events, audit |
| Internal notes | staff-only messages, never serialised to visitors | `SupportMessage.internal` |
| Unread and unresolved visibility | computed unread; backlog and waiting-for-us counts; tab and title counters | messages, `staff_seen_at` |
| Response-time measurement | from real timestamps (section 10) | messages, events |
| Aging and overdue monitoring | age of waiting-for-staff threads in display buckets; "overdue" only when the owner configures a threshold; alert rule | messages, config |
| Satisfaction history | rating per closure, retained; trend | `SupportRating`, `rated` events |
| Notification delivery status | outbox counts, dead-letter alert, health panel | `NotificationOutbox` |
| Secure, auditable actions | role checks, person-required, id-only audit rows, contact reveal audit | `AuditLog` |
| Integration with tickets | shared desk shell, shared `TicketThread`, shared metric helpers and dictionary; a visitor conversation is **not** copied into tickets (adoption deferred) so there is no duplication | existing desk |

## 8. Role-based access (proposed)

### 8.1 Why and how it fits

Verified gap: every platform admin is a superuser (section 1). Proposal that keeps the existing authentication (username, password, SMS second factor, `AdminAuthToken`) unchanged and adds **permissions for support only**:

| Permission | Allows |
|---|---|
| `support.read` | list and open conversations in scope (contact masked) |
| `support.reveal_contact` | see full phone and email (audited once per admin and thread per day, ids only) |
| `support.reply` | public replies, internal notes, mark seen, declare availability (eligibility needs it) |
| `support.manage` | assign others, close, reopen, priority, intent, spam, exclude-from-metrics |
| `support.metrics` | metrics endpoint and dashboard (aggregates, no personal data) |
| `support.notify_health` | delivery health and aging views |
| `support.roles` | grant and revoke support roles (owner only), erase on request later |

Roles (names proposed; Persian labels for the UI):

| Role | Permissions | Scope |
|---|---|---|
| `support_agent` «پشتیبان فنی» | read, reveal_contact, reply | intents `technical`, `other`; unassigned plus own threads |
| `sales_agent` «کارشناس فروش» | read, reveal_contact, reply | intents `sales`, `demo`; unassigned plus own |
| `support_lead` «مسئول پشتیبانی» | all of the above, manage, metrics, notify_health | all intents, all threads |
| `support_auditor` «ناظر» | read (masked), metrics, notify_health | read-only, no reply, no contact |
| `support_owner` «مالک پشتیبانی» | everything including roles | all |

### 8.2 Rollout without breaking anyone

Storage: a small additive table `SupportStaffRole(admin FK, role, granted_by_admin_id, at)` with a unique pair (a **second proposed migration**, needs approval). Default deny: an admin with no role gets 403 on every support endpoint. **SUPERSEDED (revision 3): no data migration grants any role; rollout is bootstrap owners from `KG_SUPPORT_OWNERS` plus `off` / `audit` / `enforce` modes, see the reconciliation file section 2.** The loopback token is never a person and gets nothing. Assigning roles: a management command first, then a small owner-only panel «نقش‌های پشتیبانی» in the support section. Role changes are audited by id. Eligibility for live mode requires `support.reply` plus a role whose scope covers the intent.

### 8.3 Enforcement

One decorator `require_support_permission(perm)` over the existing `require_admin_token` + person check; list and detail serializers mask contact unless `reveal_contact`; thread visibility filters apply in the query (not only in the UI); each rule has a test per role (a role-by-endpoint matrix), including that a masked role cannot recover contact through any response field, event or export.

## 9. Presence and live communication

Eligibility is no longer "browser session exists". An agent is **eligible** only when all hold: active account, holds `support.reply` with a scope covering the intent, **connected** (heartbeat fresh), **declared** available, **practically present** (recent human activity), and, if the owner sets `KG_SUPPORT_MAX_ACTIVE_PER_AGENT`, under that many active assigned threads.

Reliability measures:

* **Heartbeat does not extend the login.** A non-touching gate (the existing audit module already resolves sessions read-only); the 12 h idle limit remains meaningful.
* **Activity-aware:** the console reports `active` from real input events; after 10 minutes without activity (`KG_SUPPORT_AUTO_AWAY_MIN`, default 10, proposed) the console stops declaring availability (auto-away, visible to the agent with a one-click return) and, once the heartbeat stops, the server drops the agent from `live` within the window. A console left open overnight therefore stops counting.
* **Web Worker timer** for the 20 s ping so background-tab throttling does not stall it; **one leader tab per browser** (BroadcastChannel) so several tabs do not multiply pings; `pagehide` sends `offline` with `keepalive`; a console that cannot reach the server shows «اتصال شما قطع شده است؛ تا N ثانیه دیگر آفلاین می‌شوید».
* Window stays 60 s (configurable). A shorter window is more accurate and more flappy; a longer one risks false "live" after a crash. With a worker, 60 s tolerates three missed pings.
* **Demonstrable reliability evidence (to be produced, not assumed):** a Playwright experiment that runs the console in a background tab and records ping cadence with and without the worker; a test that closes the tab and measures time to `async`; an auto-away test with a fake clock; a measurement of how many SSE streams an admin tab holds before and after the single-stream provider. Results are reported as measured, and the worker is kept only if it measurably helps.

Live-to-async switching is per thread (3.3). The fallback never states a guarantee. If staffing is not established, the product defaults to async copy, which is always truthful.

## 10. Reporting, KPIs and the evidence trail

### 10.1 Rules (inherited from `METRIC_DEFINITIONS.md`)

An average of nothing is `null`, not 0; windows are closed-open on `created_at` with `days` clamped 1 to 365; backlog is current state; calendar time, not business hours; each metric names its test; a metric that is not defined does not exist. Additions: every rate shows its numerator, denominator and an `unmeasured` count; spam and **excluded** (QA/test) threads are never counted, and the exclusion count is shown so nothing is hidden; no target appears unless the owner configures one, and then it is labelled as the owner's; the dashboard has a visible «تعریف شاخص‌ها» panel generated from the same dictionary text.

### 10.2 Metric dictionary (entries to be added to `METRIC_DEFINITIONS.md` under "Visitor support chat")

| ID | Metric | Definition and calculation | Source | Exclusions and limits |
|---|---|---|---|---|
| V1 | Conversations created | count of threads with `created` event in window, by intent group (pre-sales, visitor support) and by intent | `SupportThreadEvent(created)` | excludes spam and excluded; counts conversations, not messages |
| V2 | Current backlog | threads now in open, waiting_staff or waiting_customer, split "waiting for us" versus "waiting for visitor" | `SupportThread.status` | state now, not windowed |
| V3 | First human response time | per thread: earliest public staff message time minus the `created` time; reported as average, median and p90, with `measured` and `unmeasured` (no human reply yet) | messages (author admin, not internal), `created` event | system lines and internal notes never count; calendar time; right-censored threads are `unmeasured`, never zero |
| V4 | First response by mode | V3 split by `created.data.mode` (live or async) | events | shows whether a person was genuinely eligible at the moment of contact |
| V5 | Live unanswered | threads that started `live` and had a `fallback_to_async` event, as a share of threads started `live` | events | measures honesty of availability, not staff speed |
| V6 | Resolution time per closure | `closed.at` minus the later of `created.at` and the previous `reopened.at`; average, p90, `measured` and still open | events | a late close inflates it; the closure is not the visitor's agreement |
| V7 | Reopen rate | `reopened` events divided by `closed` events in window, split visitor versus staff | events | both counts shown |
| V8 | Customer satisfaction | per closure rating 1-5: average, distribution, response rate (ratings divided by closures), weekly trend; history retained | `SupportRating`, `rated` events | `null` with no ratings; small-n warning shown |
| V9 | Assignment | current unassigned count (open threads, no owner); time to assign (created to first `assigned`) with measured and unmeasured | events, thread | shows ownership practice |
| V10 | Aging | for waiting-for-staff threads, age of the oldest unanswered visitor message in display buckets (default under 1 h, 1-4 h, 4-24 h, over 24 h); **overdue** only if the owner sets `KG_SUPPORT_OVERDUE_MINUTES` | messages, config | buckets are display, not commitments |
| V11 | Workload | open threads per assignee now; public replies per agent in window | thread, messages | visible only with `support.metrics`; about staff, so shown to leads and owner, not agents |
| V12 | Notification delivery | outbox rows by channel and event: accepted, retrying, dead, suppressed, dry-run; queue latency p90 (`sent_at` minus `created_at`); excludes recipients | `NotificationOutbox` | "accepted" means the provider accepted it, not that it was received; dry-run and suppressed are shown as not sent |
| V13 | Channel mix | visitor chats versus tickets by source, with the existing `support_metrics` | both | shown side by side, never summed into one SLA |

Ticket SLA metrics are untouched and are never blended with pre-sales figures.

### 10.3 Support operations dashboard

A «گفتگوی بازدیدکنندگان» section in the existing «شاخص‌های پشتیبانی» panel (not a new app): backlog and aging, first-response and resolution distributions by intent group, reopen, CSAT with trend, assignment and workload (leads), notification health, a data-completeness strip (measured versus unmeasured, excluded count, date range), and the metric dictionary. Charts are only drawn from the endpoint; there is no sample or placeholder data in the product. An empty system shows empty states, not demonstration figures.

### 10.4 Evidence pack (for future evaluations)

A management command and an owner-only button that write a dated snapshot: the metric values for a chosen window with numerators and denominators, the dictionary text as of that commit, the git SHA, generation time and the data-completeness strip, plus counts of events by kind and role-change audit rows (ids only). It contains no personal data, is reproducible from the database by hand using the definitions, and states plainly when the system has little or no history. It does not generate, seed or imply activity. QA and demonstration conversations made on staging are marked `excluded` and are listed as such.

## 11. Notifications and operational monitoring

Rule-based triggers over the Phase 1 outbox. Nothing is active; `KG_NOTIFY_SMS`/`KG_NOTIFY_EMAIL` stay `off`.

| Trigger | Recipient | Channel | Rule |
|---|---|---|---|
| First message, intent sales or demo | staff recipients | SMS and email | one per thread; SMS delayed 5 minutes and cancelled by a guard if a staff reply exists |
| First message, technical or other | staff recipients | email | one per thread |
| Later visitor messages | staff recipients | email digest per thread per 10 min | coalesced; SMS only after 15 min unanswered with no eligible agent |
| Visitor reopens | staff recipients | email | one per reopen |
| Aging (unanswered beyond the owner's configured threshold, if set) | role `support_lead` | email | one per thread per day |
| Staff reply | visitor, if contact exists | content-less nudge | delayed 3 min, at most 1 per thread per 6 h, 3 per phone per day |
| Delivery failure | leads | dashboard alert plus health panel | existing `notify:dead` |

**Resilience:** the product never depends on a notification channel. A message is stored before any alert is queued, outbox failure never fails the visitor's request, the inbox and SSE work with channels off or failing, and a dead-letter alert surfaces failures. A send-time **guard** hook (new, small, in the worker) drops delayed alerts that are no longer needed.

**Monitoring added:** aging alert rule (a `SystemAlert`, dashboard and email), unanswered-live count, outbox health, and the heartbeat/eligible-agent count (an alert when the kill switch is on and no eligible agent exists for longer than the owner chooses, to catch an abandoned inbox).

**Activation inputs (none assumed):** staff recipients (numbers, emails), SMS budget and whether support alerts share the OTP credit pool, SMTP provider and domain (SPF, DKIM, DMARC), approved templates (`check_sms_body`), caps, quiet hours, a person installing the outbox timer, then `dry_run` review and one authorised live test per channel.

## 12. Security, privacy and data governance

### 12.1 Browser storage review

| Item | Exposure | Assessment and mitigation |
|---|---|---|
| Thread token in `localStorage` | any script running on our origin can read it (XSS, or a compromised first-party script such as analytics); other sites cannot | scope is one visitor's own thread; the CSP uses nonces and `'self'`, React escapes message text, rendered KB/manual HTML is sanitised; **mitigations:** token is revocable (a "delete from this browser" action calls a revoke, proposed), messages render as text only with no auto-linking, no token in URLs or logs; **rejected alternatives:** HttpOnly cookie (needs CSRF design and a backend change, and this project has no CSRF tokens), `sessionStorage` (loses history on tab close, defeating persistence) |
| Unsent queue | sensitive text could sit in storage | queue is bounded (20 messages, 24 h expiry), cleared on acknowledgement, cleared by "delete from this browser", never holds contact fields beyond what the visitor typed in the draft; **proposed:** the queue lives in `sessionStorage` while the token stays in `localStorage` |
| Shared computers | the next user could open the thread | the notice offers «حذف این گفتگو از این مرورگر»; no sensitive data is shown before the visitor interacts |
| Private mode or full storage | cannot persist | memory fallback with a visible note |

### 12.2 Other controls

Visitor token isolation, staff role checks in the query, contact masking, id-only audit and events (verified in Phase 2 and extended by tests), safe rendering, limits per thread, idempotent create, explicit reopen, ratings per closure. New privacy-sensitive paths each get a test that no message text, contact or visitor IP appears in `AuditLog`, `Event` or any new log.

### 12.3 Retention and erasure

Cleanup stays **disabled** (`purge_support_chat` reports only). With section 6.2 as revised, an approved purge would delete content and contact and leave only pseudonymous events for a bounded detail stage, then aggregates (reconciliation section 3); nothing is retained indefinitely by default. Individual erasure on request is a later tool (an authorised, audited admin action deleting the thread and its outbox rows, recording an `erased` event with no content); backups keep deleted data until their own retention expires, which remains unverified.

### 12.4 Public pages

`/privacy` (static, linked from the widget, the landing footer and the contact card). Proposed wording and structure: see the companion draft; the owner and legal review must supply the retention periods, legal entity details and processor names.

## 13. Verification strategy and acceptance gates

### 13.1 Layers

| Layer | Content | Where |
|---|---|---|
| Frontend unit | token, storage, reducer, poll schedule, client, Turnstile loader, copy, adapters, presence timing (fake clocks) | local (`node:test`) |
| Backend unit and API | every new endpoint: authorisation matrix per role, filters, unread, masking, events written, audit has no content, OpenAPI sync | local, PostgreSQL in CI |
| Concurrency | assign, close, reopen, reply, rating races with real threads | PostgreSQL in CI |
| Data and metrics | each metric V1-V13 has a test with a hand-computable fixture, including the empty case returning `null` | local, CI |
| E2E | Playwright journeys S1-S18 below, desktop Chrome, Pixel 7, Firefox for the widget spec | local after an isolated Chromium install (approved), QA stack |
| Accessibility and RTL | axe in both themes on every state; keyboard-only; 200% zoom; mixed Latin, digits, emoji | E2E |
| Security regression | token isolation, role matrix, masking leaks, privacy of logs, rate limits, XSS-as-text, heartbeat does not extend sessions | backend and E2E |
| Notification | Fake provider and dry-run: triggers, delayed SMS cancelled by a reply, coalescing, caps, no text in payloads, channels failing leaves chat working | local |
| Performance | k6 for visitor polling, staff list, SSE stream count, presence under a throttled tab | staging, later gate |
| Operational | alert rules fire on an aged fixture, health panel reflects failures, kill switch off means zero widget requests | local, staging |

### 13.2 E2E scenarios (L = local, S = staging/QA, N = separate approval)

S1 visitor sends an enquiry (L,S) · S2 Turnstile completes (test key locally, real key on staging) (L,S) · S3 available agent assigns and replies, visitor sees reply and read tick (L,S) · S4 no agent: async copy, contact card, later return sees reply (L,S) · S5 refresh and reopen the tab restores history (L,S) · S6 thread gone (404) restarts cleanly (L) · S7 authenticated customer uses support (L,S, M5) · S8 staff unread, filters, assignment, priority, close, reopen, 14-day window (L,S) · S9 mobile and RTL (L,S) · S10 network drop and retry without duplicates (L) · S11 Turnstile blocked fallback (L) · S12 limits: second visitor on the same IP unaffected (L) · S13 privacy and authorisation regressions across roles (L, CI) · S14 notification behaviour with safe providers (L) · S15 real SMS and email (N) · S16 load and presence under throttling (S, later) · S17 role matrix end to end: agent cannot see another scope, auditor cannot reply or see contact, lead sees metrics (L,S) · S18 evidence pack from a fixture database matches hand calculation (L).

Local runs never count as PostgreSQL or production evidence; CI and staging results are reported separately, listing failures and skips.

### 13.3 Operational acceptance gates

* **G1 first functional milestone (end of M1):** the visitor-to-human journey in section 4 works locally and on the QA stack with the kill switch on there; every step leaves its record; E2E S1-S5, S8-S10 green; CI green on PostgreSQL. The kill switch is still off in production.
* **G2 launch readiness (before any public activation):** M0-M3 complete; role matrix tests and masking green; presence experiments measured and reported; privacy page published and approved; staffing and hours confirmed; notification `dry_run` reviewed and one authorised live test per channel; aging alert and health panel verified; k6 measured and accepted; copy approved; at least one person owns the inbox; the kill switch flipped by a person after explicit approval. Production promotion stays a person running `kgkg-promote`.
* **G3 evaluation readiness:** dashboard and evidence pack work on real recorded data; metric dictionary updated and pinned by tests; an empty or short history is stated as such.

## 14. Decisions and approvals needed

Needs your explicit approval (none assumed):

1. **Two additive migrations:** `SupportThreadEvent` (6.2) and `SupportStaffRole` with the grandfathering data migration (8.2). Both new tables, no existing table altered; revisit numbering with the other developer before generating.
2. **Role model:** the five roles, scopes and the default-deny plus owner grandfathering; Persian labels.
3. **Heartbeat change:** new non-touching gate and activity-aware auto-away (default 10 min).
4. **Privacy page:** review of the draft wording and who supplies legal entity, retention, processors.
5. **Metrics:** the dictionary V1-V13 and the exclusion marker for QA conversations; whether to set any owner threshold (overdue minutes, aging alert) now or leave unset.
6. **Login and recover:** include only if the UX criteria in 3.1 are met in E2E.
7. **Operational inputs before activation:** staff identities, working hours, notification recipients, SMS budget and credit-pool sharing, email provider and domain.
8. **Playwright Chromium:** approved; I will install it in an isolated tool directory outside the repo when implementation is authorised, not before.
9. Public activation of the widget, real SMS or email, retention cleanup: each separate.

## 15. Risks and limitations

| Risk | Status |
|---|---|
| Widget live without a staffed, notified inbox | kill switch plus G2; **assumed** sufficient |
| Heartbeat extends admin sessions | **verified in code**; fixed in M2 before any heartbeat UI |
| Visitor polling load on 24 request threads | arithmetic only; **unmeasured**; k6 gate |
| Worker keeps presence accurate in background tabs | **unverified**; experiment in M2, kept only if it measurably helps |
| Admin SSE stream count | **unverified**; measured, then reduced |
| Turnstile widget mode and hostname list | **unverified**; staging check; script and CSP compatibility verified |
| Ad blockers and privacy modes | designed fallbacks; real-world rate **unknown** |
| iOS keyboard and `visualViewport` | **untested** |
| Metrics need history that does not exist yet | the dashboard shows empty states; nothing is simulated |
| KPI figures for individuals (workload) | restricted to leads and owner |
| Token in `localStorage` | residual XSS exposure limited to one thread; mitigations in 12.1 |
| Existing ticket UI shows SLA state and a due time to customers | observed, **not changed**; separate product decision |
| The admin page is a merge-conflict magnet | few-line touches |
| Windows `pid_alive` truncating local test runs | pre-existing, out of scope; run suites from Git Bash |
