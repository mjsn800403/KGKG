# Customer communication system: design

**Date:** 2026-11-02
**Status:** DRAFT for approval. No code, migration, infrastructure or messaging change has been made.
**Evidence labels:** *confirmed* = read in this repo today; *unverified* = not checked; *assumed* = my judgement.

## 1. Goal and what must hold

Turn landing-page visitors into conversations, and give existing customers one coherent way to get help, while staff learn of every message fast and nothing is lost.

Non-negotiables (from the product owner and CLAUDE.md):

* Hybrid: real-time when a staff member is genuinely available, asynchronous otherwise, **one** thread, no restart when the mode changes.
* Presence is computed from real signals. No "online" claim or promise of an instant reply without it.
* Additive migrations only. Nothing breaks on `deploy.sh --rollback`.
* No SMS/email is sent, and no credit spent, until explicitly authorised. Nothing assumed configured.
* Do not collide with the other developer's database/RAG work.

## 2. Findings about the current system (confirmed)

| Area | Finding |
|---|---|
| Landing page | No contact channel except footer phone/email, the "?" help panel (tours + KB) and `/purchase`. `PurchaseRequest` is a one-way form: no thread, no reply path, no notification. |
| Tickets | `CompanyRequest` + `TicketMessage` (SLA, CSAT, per-viewer read state `TicketRead`, topic, car, assignee, escalation, source). `company` is a **non-null FK**; visibility is `_visible_qs` by company. Good model, UI is a form plus accordion list. |
| Entry points | Three separate floating/hidden entries for a logged-in seat: help FAB (`GuidanceProvider`), `FeedbackWidget`, Requests page. |
| Real time | `Event` table + SSE (`events.stream_view`): one **held** connection per client, up to 300 s, tail every 1 s. |
| Server capacity | gunicorn `gthread`, `KG_WORKERS` default 3 x `KG_THREADS` default 8 = **24 request threads**. Each SSE stream occupies one for up to 5 minutes. |
| Notifications | SMS only: `portal._post_sms` (Melipayamak; Persian body needs the `لغو11` footer, no links; success = `Value > 1000`). `notify.py` logs to `NotificationLog`. `alert_rules.deliver` SMSes `KG_ALERT_PHONES` with cooldown and refuses to send under tests. **No `EMAIL_*` settings.** No retry, no outbox, no delivery receipt. Support events (new ticket, reply) emit SSE only; nobody is pushed anything. |
| Scheduler | `kgkg-alerts.timer` runs `check_alerts` every 5 min. No faster job exists. |
| Abuse controls | `rate_limited` decorator (per IP), Cloudflare Turnstile already verified server-side in `portal._verify_turnstile` for login/recover. |
| Staff | `PlatformAdmin` has `phone`, no email. |
| Open issues | #44 (desk should push: SLA breach page, reply notification, attachments), #24 (SMS path unverified end to end). Both overlap this work. |

### Design constraints these findings create

1. **Anonymous visitors must not hold SSE streams.** 24 threads total; a modest landing-page crowd would starve the API. This is the single most important technical constraint (see 5.3).
2. `CompanyRequest.company` non-null means anonymous rows cannot live in the ticket table without relaxing a core constraint.
3. There is no outbox: reliable delivery, retries and dedupe must be built, not configured.

## 3. Architecture alternatives

### Option A: extend `CompanyRequest` / `TicketMessage`

Make `company` and `created_by` nullable, add visitor fields (contact, token hash, intent), reuse every endpoint, SSE event and admin screen.

* **For:** one table, one inbox, one thread component, one SLA/CSAT/unread implementation. Least new code.
* **Against (confirmed in code):**
  * Relaxing `NOT NULL` is safe for new code but **not for rollback**: `_request_dict`, metrics and admin views dereference `r.company`; old code reading an anonymous row raises. `deploy.sh --rollback` is a documented, used path, and `check_migrations.py` exists precisely to refuse this class of change.
  * Pre-sales leads would enter SLA, CSAT and `support_metrics`, diluting the numbers the desk was built to make honest.
  * Authorisation is company-scoped everywhere (`_visible_qs`, event audiences). An anonymous principal needs a second auth path threaded through a 950-line, heavily tested module the desk depends on. A mistake there exposes tickets, not just chats.
  * Edits land in `models.py`, `requests_api.py`, `urls.py`, `reads.py`, `support_metrics.py`: the files most likely to collide with parallel work.
  * SSE is the wrong transport for anonymous users (constraint 1) so a second transport is needed anyway.

### Option B: separate conversation subsystem (`VisitorConversation` / `VisitorMessage`)

* **For:** zero risk to tickets, rollback-safe (new tables only), anonymous data isolated, can have its own retention policy.
* **Against:** if the *whole* experience is separate, a logged-in customer has chats **and** tickets, and staff have two inboxes, two thread UIs, two notification paths and two unread systems. That is exactly the "two disconnected systems" the brief rejects, and it duplicates SLA, CSAT and read-state logic.

### Option C: hybrid (recommended)

Storage splits at the real security boundary; everything above storage is unified.

* **Authenticated customers keep `CompanyRequest`/`TicketMessage` as the system of record.** No change to these tables, no migration on them. The "chat" is a conversation-first front end over the existing ticket API (first message creates the ticket with an automatic subject).
* **Anonymous visitors get new, isolated tables** (`ChatThread`, `ChatMessage`), accessed only by a hashed bearer token.
* **One widget, one admin inbox, one notification service, one presence service** sit over both. The admin inbox is a *read-model* that merges the two streams; no data is unified, so no risky migration.
* **Continuity:** when a visitor signs in (or a staff member decides), the anonymous thread is *promoted*: a ticket is created and the messages are copied in order, so history survives and the visitor continues in the same window.

### Comparison

Scores 1 (poor) to 5 (strong); my judgement, justified by the findings above.

| Criterion | A: extend tickets | B: separate | C: hybrid |
|---|---|---|---|
| Product experience / completeness | 4 | 2 (split experience) | **5** |
| Compatibility with ticketing | 3 (touches core, rollback hazard) | 3 (parallel, duplicated) | **5** (core untouched, shared UI) |
| Data model / migrations | 2 (relax NOT NULL, new nullable columns on hot table) | 4 | **4** (new tables only) |
| Anonymous auth and security | 2 (second principal inside company-scoped code) | **5** | **5** |
| Real-time + presence | 3 (SSE unsuitable for anon) | 4 | **4** (poll for anon, SSE for known users) |
| Data consistency / history | 5 | 3 | 4 (promotion copies history) |
| Reuse of existing components | 5 | 2 | 4 |
| Admin workflow complexity | 4 | 2 | **4** (merged inbox read-model) |
| Metrics integrity | 2 (leads dilute SLA/CSAT) | 4 | **5** |
| Scalability / maintainability | 3 | 3 (duplication) | **4** |
| Effort / operational cost | **5** | 3 | 3 |
| Collision risk with parallel DB work | 2 | 4 | **4** |

**Recommendation: C.** Reasons, in priority order: (1) it keeps anonymous input structurally away from company-scoped ticket data; (2) it is rollback-safe; (3) it preserves SLA/CSAT meaning; (4) it still gives staff and customers a single experience. The cost over A is roughly one extra pair of tables and a promotion function; I judge that cheap against the risks A carries. A is only preferable if the team accepted breaking the rollback guarantee, which the ops rules rule out.

## 4. Product and UX specification

### 4.1 Principles

Open fast, ask little, never pretend. The visitor can type the first message before giving any details. Every state is stated in plain Persian. RTL first; Latin runs wrapped in `bdi`.

### 4.2 Landing page (anonymous)

**Launcher.** Floating button at the bottom, on the same side as today's help FAB, which is folded into this widget as a tab so the two never overlap. Label "گفتگو با ما". After 20 s on the page, once per session, a small teaser bubble appears (dismissable, never again after dismissal). Real `<button>`, `aria-expanded`, `aria-controls`, 44 px target, visible focus, `prefers-reduced-motion` respected.

**Panel.** Desktop: 380x600 anchored card. Mobile (<640 px): full-height sheet using `100dvh` and safe-area insets, the input stays above the keyboard (visualViewport). Focus moves into the dialog and returns to the launcher on close; `role="dialog"`, Esc closes; the message list is `aria-live="polite"`.

**Header status (the honesty rule).** Computed server-side, three states only:

* Live: "تیم پشتیبانی آنلاین است. معمولاً در چند دقیقه پاسخ می‌دهیم." Shown only if at least one agent has set themselves available **and** their heartbeat is under 60 s old.
* Async: "الان کسی پشت میز نیست. پیام شما ذخیره می‌شود و پاسخ را از طریق پیامک یا ایمیل یا همین‌جا دریافت می‌کنید. زمان معمول پاسخ: {X}." X comes from `sla.POLICY` / working-hours config, never hard-coded.
* Degraded: status service unreachable. Treated as Async; never as Live.

No typing indicator, no avatar, no "agent is typing", no agent name until a real agent has actually replied in this thread.

**First contact.** Greeting plus four intent chips, one tap:

| Chip | Persian | What it changes |
|---|---|---|
| Sales/pricing | «قیمت و خرید اشتراک» | shows plan/price KB cards + `/purchase` link; asks nothing else |
| Demo | «درخواست دمو» | asks company name + phone (the only required fields for this intent) |
| Technical | «پرسش یا مشکل فنی» | KB suggestions as they type; "already a customer? sign in for faster help" |
| Other | «سایر» | free text |

Intent is a label on the thread (`sales | demo | technical | other`) used for routing and priority. It never blocks sending: typing without choosing a chip is allowed (`other`).

**Composer and sending.** Enter sends, Shift+Enter newline, 2000-char cap with counter near the limit. The message is stored on send (optimistic bubble with states: sending, "ارسال شد" (saved on our server), "خوانده شد" (staff opened it)). Failed sends stay in the list with retry; the draft survives reload (`sessionStorage`).

**Contact capture.** After the first message, an inline card (not a modal): "برای پاسخ‌گویی وقتی آنلاین نیستید، یکی را بنویسید: موبایل یا ایمیل". Name optional. At least one contact method is requested, but the message is already saved; skipping shows a clear note that replies will only appear in this window on this browser. Phone is normalised with the existing `normalize_phone`. Short privacy line: what we do with the contact, link to the policy page (*decision D9*).

**Confirmation.** After send: "پیام شما دریافت شد ✓" plus the honest expectation line for the current mode. Never a fake auto-"agent" message. An optional automated reply (KB article match) is labelled «پیشنهاد خودکار».

**Return visits.** Token in `localStorage` restores the thread and its replies; a badge on the launcher shows unread staff replies. Recovery on another device is out of scope for v1 (SMS cannot carry links); the thread continues if the visitor signs in (see 4.3).

**Empty/edge states:** offline network banner with queued sends; rate-limited message; closed thread ("این گفتگو بسته شد. پیام جدید یک گفتگوی تازه باز می‌کند" and CSAT 1 to 5 once).

### 4.3 Authenticated customers (all panels)

One launcher replaces the help FAB and the feedback FAB. Tabs: «گفتگو» (default), «راهنما» (existing HelpCenter content and tours), «بازخورد» (existing feedback). Because the widget lives in `GuidanceProvider`'s mount point it already exists on every panel.

* **«گفتگو» tab:** list of my conversations (managers: company's, per existing visibility rules) with status chip (در انتظار / در حال بررسی / پاسخ داده شد / بسته), unread dot from `TicketRead`, SLA line using the existing `_sla_dict`. "گفتگوی جدید": topic chips mapped to `TOPIC_CHOICES` (missing document, content wrong, access, assistant wrong, error/slow, billing, other), the page/vehicle is attached automatically as `car`/context, KB deflection while typing (existing `/api/kb/`), then free text. The first message creates a `CompanyRequest(kind=support)` with auto subject. Restricted kinds (seats, vehicle access, AI, documents) keep their form on the Requests page; the chat links to it when it detects that intent.
* Transport: existing SSE, already authenticated and bounded by seats.
* After closure: existing CSAT prompt. Reopen-on-message behaviour unchanged.
* Anonymous thread adoption: if a `localStorage` chat token exists at login, offer "این گفتگو را به حساب من اضافه کن". Promotion is idempotent.

### 4.4 Admin: unified inbox

Single page "صندوق گفتگو" in `SupportAdmin`:

* **Top bar:** availability switch (Available / Away / Offline) showing the *computed* state beside the manual one, counts: live now, waiting on us, unassigned, SLA at risk.
* **List (left):** merged stream of tickets and visitor threads, badge for type (مشتری / بازدیدکننده) and intent (فروش / دمو / فنی), filters: mine, unassigned, waiting on us, live now, sales leads, closed; sorted by last activity; unread bold; the existing cursor pagination is reused per source and merged.
* **Thread (centre):** the existing `TicketThread` component, extended with visitor styling, internal notes, quick actions, canned replies, KB insert.
* **Context (right):** visitor: contact, source page, referrer, intent, prior threads from same contact; customer: company, plan, seats, vehicles, SLA clocks, previous tickets. Actions: assign (self/other admin), priority, status, convert lead to customer ticket, link to a `PurchaseRequest`, mark spam.
* Browser tab title and optional sound on new live messages. No new infrastructure.

## 5. Technical design: hybrid live/async, presence, persistence

### 5.1 One thread, mode is a property of the moment

A thread is a list of messages. "Live" and "async" are not thread types. They differ only in (a) what the status line says, (b) how often clients refresh, (c) notification urgency. Therefore nothing is lost or restarted at a switch. If a visitor writes during Live mode and nobody replies in 90 s (configurable), the UI changes the banner to the Async text and the contact card is raised; the thread is untouched.

### 5.2 Data model (all new tables, additive)

```
ChatThread        id (uuid), token_hash (sha256, unique), intent, status (open|waiting_staff|waiting_customer|closed|spam),
                  contact_name, contact_phone, contact_email, source_page, referrer, user_agent_hash,
                  assignee -> PlatformAdmin (null), priority, last_activity_at (indexed), created_at, closed_at,
                  promoted_request -> CompanyRequest (null, SET_NULL), csat_score/csat_at
ChatMessage       id, thread -> ChatThread, author_kind (visitor|admin|system), author_admin -> PlatformAdmin (null),
                  body, internal (bool), created_at, delivery (stored|read)   index (thread, id)
AgentPresence     admin (unique) -> PlatformAdmin, manual_status (available|away|offline), last_heartbeat_at
NotificationOutbox, NotificationPreference   (see section 6)
```

No FK from or column on existing tables. Authenticated conversations use the existing tables unchanged. `ChatThread.promoted_request` is the only link and points outward.

### 5.3 Transport (decision driven by the 24-thread budget)

| Client | Transport | Why |
|---|---|---|
| Anonymous visitor | **Adaptive short polling** `GET /api/chat/threads/<id>/messages?after=<msg_id>` | no held connection; cost is one indexed query per tick. Interval 3 s while Live and the tab is visible, 10 s idle, 30 s after 5 min, paused when the tab is hidden or the panel closed, jittered. Estimated worst case: 100 simultaneously open panels at 3 s = ~33 req/s of trivial queries. |
| Authenticated customer | existing SSE | already bounded by seats; no change |
| Agent | existing SSE for new-thread/new-message events + heartbeat POST | already how the admin dashboard works |

Rejected for v1: WebSockets/ASGI (new infrastructure; ADR rule "no new infrastructure without a measured need"). Trigger to revisit: sustained poll rate or SSE count above an agreed threshold, measurable through the existing metrics. If production uses SQLite rather than PostgreSQL (*unverified: `KG_DB_ENGINE` on the server not checked*), polling reads are WAL-safe and writes are single small inserts; acceptable, to be load-tested in phase 2.

### 5.4 Presence

* Agent console sends `POST /api/admin/presence/heartbeat` every 25 s while the page is visible and the manual status is Available.
* Computed state: `live` iff at least one `AgentPresence` has `manual_status=available` and `last_heartbeat_at > now-60s`, optionally within configured working hours. Otherwise `async`.
* Public `GET /api/chat/status` returns `{mode, expected_reply_minutes}`, cached 5 s server-side, rate limited. It never reveals names, counts or whereabouts.
* An agent who closes the tab becomes non-available within 60 s with no cleanup job.

### 5.5 Anonymous identity and security

* Thread creation returns `{thread_id, token}`; the token is 32 random bytes, stored only as a SHA-256 hash. Client keeps it in `localStorage` and sends `X-Chat-Token`. Bearer header (not cookie) means **no CSRF surface**, relevant because the project has no CSRF tokens (open risk in CLAUDE.md).
* Every anonymous endpoint authorises by `(thread_id, token_hash)`; a wrong token returns 404, not 403 (no existence oracle). No endpoint lists threads; internal notes are never serialised.
* Creation requires Turnstile when `TURNSTILE_SECRET` is set (reuse `_verify_turnstile` with a new action name), plus: per-IP rate limit via `rate_limited`, a honeypot field, per-thread cap (e.g. 30 messages/hour), 2000-char body cap, thread-creation cap per IP/day. Text is stored and rendered as plain text only (React escaping; no HTML, no markdown links auto-fetched).
* PII: IP is not stored raw (HMAC with server secret if needed for abuse correlation); user agent stored hashed. Retention job: purge threads with no contact after 30 days, with contact after a period fixed by decision D9.
* XSS note: a stolen token only exposes that visitor's own thread.

### 5.6 Lead promotion

`promote(thread, portal_user)`: in one transaction, create `CompanyRequest(kind=support, source='portal', subject=first line)`, copy messages in order as `TicketMessage` (visitor lines attributed to the user, staff lines to their admin), set `promoted_request`, mark thread closed with a pointer. Idempotent via `promoted_request`. Triggered by the user opting in at login, or by an admin.

### 5.7 API surface (new, namespaced `api/chat/`)

Public: `GET status`, `POST threads` (create + first message), `GET/POST threads/<id>/messages`, `PATCH threads/<id>/contact`, `POST threads/<id>/csat`.
Authenticated customer: no new endpoints beyond `POST company/requests/` + promotion (`POST api/chat/threads/<id>/promote`).
Admin: `GET inbox`, `GET/POST inbox/threads/<id>`, `PATCH` assign/status/priority, `POST presence/heartbeat`, `PUT presence/status`.

## 6. Notification architecture (SMS + email)

### 6.1 Principles

Durable first, send second. Nothing is sent by request code; request code writes an outbox row in the same transaction as the message, so a crash cannot lose a notification and a notification cannot exist for a rolled-back message.

### 6.2 `NotificationOutbox`

```
id, event_type, channel (sms|email), recipient_kind (staff|visitor|customer), recipient_ref,
dedupe_key (unique per window), payload (template + params, no secrets), status
(queued|sending|sent|failed|dead|suppressed|dry_run), attempts, next_attempt_at,
provider_ref, last_error, created_at, sent_at
```

* **Worker:** `manage.py process_outbox`. Claims due rows atomically, sends through a provider interface, updates status. Triggered (a) opportunistically by a short background thread after commit (same pattern as the metrics flusher in `monitoring.py`) for sub-minute latency, and (b) by a `kgkg-outbox.timer` every minute as the guaranteed path. The timer is a new ops unit that a person installs on the server (*approval needed, D6*).
* **Retry:** 1, 5, 15, 60, 240 min then `dead`. A `dead` row raises a `SystemAlert` through the existing alert path (also useful for issue #24).
* **Provider interface:** `send(channel, to, rendered) -> (accepted, provider_ref, error)`. Implementations: `MelipayamakSMS` (wraps existing `_post_sms`, one place for the `لغو11`/no-link rules), `SMTPEmail` (Django `EmailMessage`), `Fake` (tests) and `DryRun` (render and log only).
* **Delivery tracking, honestly:** `sent` means *accepted by the provider* (SMS `Value > 1000`; SMTP 250). True handset delivery and email bounces are not observed today. Melipayamak may expose delivery receipts (*unverified: API not checked*); email bounce handling needs a mailbox or provider webhook. Both are listed as later work and stated in the UI as "accepted", never "delivered".

### 6.3 Events and policy

| Event | Staff | Visitor/customer | Channel policy |
|---|---|---|---|
| New visitor thread, intent sales/demo | SMS to on-call + email | none | SMS (high value lead) |
| New visitor thread, technical/other | email | none | email only |
| New customer ticket | email; SMS only if priority high or topic access/error | none | |
| Customer/visitor message on open thread | in-app/SSE; email digest if unattended 10 min; SMS only if Live-mode thread unanswered 5 min | none | coalesced |
| Staff public reply | none | visitor: SMS or email nudge if they are not in the widget; customer: per their preference | content-less SMS (no body leak, no cost spike, obeys no-link rule) |
| SLA breach / escalation (epic #44) | SMS | none | via existing alert rule |
| Provider failure / dead rows | SMS+SystemAlert | none | |

### 6.4 Safeguards

* **Dedupe and coalescing:** key `thread:{id}:{event}:{window}`; a burst of messages produces one alert per window (default 10 min), later ones append to the next digest.
* **Cost control:** global cap `KG_NOTIFY_SMS_MAX_PER_HOUR` and per-recipient daily cap; above the cap SMS degrade to email, never silently drop. A visitor-addressed SMS is sent at most once per thread per 6 h and at most 3 per phone per day, because a visitor can type someone else's number (harassment and spend vector). Visitor phone numbers are not verified in v1 (verification would itself cost an SMS); hence content-less nudges only.
* **Quiet hours:** per staff preference; SMS held until morning unless priority high.
* **Preferences:** `NotificationPreference` per staff admin (events x channel, quiet hours, digest) and per customer (reply channel: sms/email/none; extends the existing `notify_*` flags on `PortalUser` without touching them).
* **Kill switch and modes:** `KG_NOTIFY_SMS` and `KG_NOTIFY_EMAIL` each `off` (default) / `dry_run` / `live`. In `off`, rows are recorded as `suppressed`; in `dry_run`, rendered and logged with the cost it *would* have incurred; only `live` contacts a provider. Tests force `Fake` like `alert_rules.deliver`'s TESTING guard. Deploying the code therefore cannot send or spend anything.
* **Staff recipients:** `PlatformAdmin.phone` exists; email does not. Options in D5.
* **Email specifics (for when configured):** `EMAIL_HOST/PORT/USER/PASSWORD/USE_TLS`, `DEFAULT_FROM_EMAIL` on a domain with SPF + DKIM + DMARC; plain-text + simple RTL HTML; no message body or personal data in subjects; a footer explaining why they got it and how to opt out for customer-facing mail.

### 6.5 Activation checklist (nothing below is done or assumed)

1. Decide recipients: staff phone numbers/emails for new-lead and urgent alerts (D4, D5).
2. SMS: confirm Melipayamak credit, line and whether alert/support SMS may share the existing credentials `SMS_USERNAME/SMS_API_KEY/SMS_FROM` (already used for OTP and alerts, so sharing also shares the credit pool: D3).
3. Email: choose provider, supply SMTP credentials as server secrets, publish SPF/DKIM/DMARC (D5).
4. Set caps (D3), quiet hours, templates approved by you (Persian copy; the operator rejects some bodies, so the 'dry run' and a single approved test send per template are required).
5. Install the outbox timer on the server (D6).
6. Staged enablement: `dry_run` on staging, review the log, then one explicitly authorised live test per channel, then production.

## 7. Coordination with the other developer

*Confirmed:* open PRs touch `.github/workflows/ci.yml`, `ops/deploy/*` (#40), docs (#41), and parts/RAG/safepath files (#59). Recent commits by the other maintainer touch `cardb.py` and `rag/*`; none touch `models.py` or `migrations/` since `0039` (`mjsalimin`'s desk work). The last migration is `0039_helpdesk_topic_car_read`. *Unverified:* anything uncommitted or on a branch not on GitHub; I cannot see it.

Collision map and rules:

| Shared surface | Plan |
|---|---|
| `models.py` | new models live in new `api/chat/models.py`, imported by one line appended to `models.py` |
| `migrations/` | one new additive migration per phase, numbered at PR time after rebasing on `origin/work`; always depends on the then-latest migration; `check_migrations.py` must pass. **If the other developer has a pending migration, we agree the order before either merges.** |
| `urls.py` | single `include` line |
| `rag/*`, `cardb*`, `partsouq*`, `frm.py`, `parts.py`, `safepath.py` | not touched |
| `deploy.sh`, `ci.yml` | not touched; the new timer unit is a new file |
| `requests_api.py` | not modified; promotion goes through the public model API |
| frontend | new `components/chat/*`; small edits to `GuidanceProvider.jsx` and `SupportAdmin.jsx` only |

Process: branch from a fresh `origin/work` in a git worktree (the current checkout is on an unrelated branch with a PR open), never touch the shared server tree, and ask the other developer for their branch name and pending migration before phase 2.

## 8. Implementation plan (phased; nothing starts until approved)

Each phase ends with passing tests, a docs + CHANGELOG line, and its own PR to `work` referencing an issue (issues to be created on approval).

| Phase | Deliverable | Depends on | Tests / verification |
|---|---|---|---|
| 0 | Approvals D1..D12; issue(s) filed; other developer's pending migrations confirmed; production DB engine confirmed | you | n/a |
| 1 | **Notification core:** outbox, worker, providers (Fake/DryRun/Melipayamak wrapper/SMTP), modes, caps, dedupe, dead-letter alert; no triggers wired | 0 | unit tests for retry/backoff, dedupe, caps, modes-off sends nothing, failing provider, crash between commit and send; `check_migrations`; coverage floor |
| 2 | **Chat core backend:** `ChatThread/Message`, token auth, create/post/poll, status, presence, Turnstile + limits, retention job | 1 | authz matrix (wrong token, other thread, internal note leak), abuse limits, poll load test (k6) at target concurrency, SQLite and PostgreSQL |
| 3 | **Landing widget:** launcher, panel, intents, contact capture, honest status, polling, a11y and RTL | 2 | component tests, Playwright (desktop + 375 px), axe, keyboard-only path, offline/failed-send cases, screenshots reviewed |
| 4 | **Customer unification:** widget over tickets, single launcher, KB deflection, promotion of anonymous thread, feedback/help tabs | 2,3 | existing desk tests unchanged and green, new e2e for create/reply/unread/CSAT, promotion idempotency |
| 5 | **Admin inbox:** merged list, thread, context, assign/status/priority, availability toggle, canned replies | 2,4 | e2e agent flow incl. live to async switch, SLA display, merged pagination correctness |
| 6 | **Wiring and preferences:** events to outbox, reply nudges, SLA-breach rule (epic #44), preference UI, admin delivery-health panel | 1,2,5 | trigger matrix tests, coalescing under burst, cost-cap behaviour, staging in `dry_run` with reviewed log |
| 7 | **Activation + hardening:** authorised live test sends per channel, ZAP pass on new routes, k6 in CI, runbook, docs | 6, your approvals | evidence captured (closes #24 partly); rollback rehearsal with `deploy.sh --rollback` on staging |

Parallelism: 1 and the design of 3 can run alongside each other; 4 and 5 can run in parallel after 2. Production promotion remains yours (`kgkg-promote <sha>`).

Risks and mitigations: SSE/poll capacity (polling + load test + metric alarm); SMS cost abuse (caps, content-less visitor nudges, Turnstile); spam in the inbox (Turnstile, honeypot, mark-spam); staff never set availability (default Async copy is honest, never claims Live); migration collision (section 7); provider reject (dry-run + approved templates).

## 9. Decisions and approvals needed from you

| # | Decision | My recommendation |
|---|---|---|
| D1 | Architecture | Option C (hybrid) |
| D2 | Visitor transport | polling for anonymous, SSE for known users; no WebSockets in v1 |
| D3 | SMS budget: monthly cap, per-hour cap, sharing the OTP/alert credit pool | separate hourly cap (default 10/h) and daily per-recipient cap; ideally a separate sender line or credit |
| D4 | Who receives staff SMS (numbers) and who is "on call" for sales vs support | you supply numbers; sales leads and urgent tickets only |
| D5 | Email: provider and sender domain; staff emails (add `PlatformAdmin.email` column, or a standalone recipients table) | recipients table (no change to the auth model); provider your choice, must support SPF/DKIM |
| D6 | Permission to add a `kgkg-outbox.timer` unit on the server (a person installs it) | yes, 1-minute interval |
| D7 | Working hours and expected-reply copy (X in the Async text) | derive from `sla.POLICY` until you set hours |
| D8 | Anonymous reply channel: content-less nudge only vs full text in SMS | nudge only (cost + wrong-number risk) |
| D9 | Privacy: retention period for visitor contacts and thread text; privacy page link | 30 d without contact, 12 months with contact, then purge; needs your policy wording |
| D10 | Replace the help FAB and feedback FAB with one launcher with tabs | yes |
| D11 | Creating GitHub issues for traceability (new issues, not editing existing ones) | yes, one per phase |
| D12 | Other developer: branch name, pending migrations, files to avoid | you or they confirm before phase 2 |
| D13 | Is production on PostgreSQL or SQLite? (affects load-test target; I did not touch the server) | you confirm, or approve me checking read-only over SSH |

## 10. Out of scope for v1 (stated so they are decisions, not omissions)

Attachments (epic #44 item, separate), WhatsApp/Telegram channels, chatbot answers beyond labelled KB suggestions, verified visitor phone/email, cross-device visitor recovery, handset-level SMS delivery receipts, email bounce processing.

## 11. Decision log (2026-11-02)

The product owner replied "Approve defaults".

| # | Status |
|---|---|
| D1, D2, D6, D7, D8, D9, D10, D11 | Approved at the recommended default. D6: the timer is written but a person installs it. D11: issues may be created, one per phase. |
| D3 | Approved at the default caps (10 SMS/hour, per-recipient daily cap). The budget and whether to share the OTP/alert credit pool are still open. |
| D4, D5 | **Still needed:** staff phone numbers, email provider and sender domain. Not defaultable. Phase 1 to 2 do not need them (all delivery stays `off`). |
| D12, D13 | **Still needed:** the other developer's branch and pending migrations; production DB engine. |

Implementation has NOT started. Plan: `docs/superpowers/plans/2026-11-02-customer-communication-phases-1-2.md`.
