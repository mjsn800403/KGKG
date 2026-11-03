# Customer Communication: Phases 1 and 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the notification outbox (Phase 1) and the anonymous chat backend with presence (Phase 2), neither of which can send a real SMS or email until explicitly activated.

**Architecture:** Hybrid (spec option C). New isolated tables and modules under `api/notifications/` and `api/chat/`; existing ticket tables and `requests_api.py` are not modified. Visitors authenticate with a hashed bearer token and poll; staff and customers keep SSE. Every send path goes through a mode switch that defaults to `off`.

**Tech Stack:** Django 5.2 (`api` app), Python, PostgreSQL in CI / SQLite WAL locally, Django test runner, Melipayamak REST (existing `portal._post_sms`), Django `EmailMessage`.

**Spec:** `docs/superpowers/specs/2026-11-02-customer-communication-design.md` (sections 5 and 6). Phases 3 to 7 (widget, customer unification, admin inbox, wiring, activation) each get their own plan once the interfaces below exist, because their UI depends on the real API shapes.

## Global Constraints

- Migrations additive only: a new table is fine; any new NOT NULL column needs `db_default`. `python ../ops/deploy/check_migrations.py origin/work` must pass (run from `KG_backend/`).
- Branch from a fresh `origin/work` in a git worktree (the main checkout is on `fix/nightly-e2e-help-panel`). PR targets `work`; title/body reference an issue (`ops/governance/check_traceability.py`).
- Do not touch: `api/rag/*`, `cardb*.py`, `partsouq*.py`, `frm.py`, `parts.py`, `safepath.py`, `ops/deploy/deploy.sh`, `.github/workflows/ci.yml`, `requests_api.py`.
- New models live in `api/notifications/models.py` and `api/chat/models.py`, each imported by one appended line in `api/models.py`. One `include`-style line per module in `api/urls.py`.
- Modes: `KG_NOTIFY_SMS` and `KG_NOTIFY_EMAIL` take `off` (default), `dry_run`, `live`. Under `TESTING` a real provider is never used (same guard as `alert_rules.deliver`).
- SMS caps: `KG_NOTIFY_SMS_MAX_PER_HOUR` default `10`; visitor-addressed SMS at most 1 per thread per 6 h and 3 per phone per day. SMS bodies for Persian text end with `لغو11` and contain no links.
- Retry schedule minutes: `(1, 5, 15, 60, 240)`, then status `dead` and a `SystemAlert` with key `notify:dead`.
- Presence: live iff an `AgentPresence` has `manual_status='available'` and `last_heartbeat_at` within 60 s. Heartbeat client interval 25 s.
- Visitor body cap 2000 chars; 30 messages per thread per hour; token = 32 random bytes, stored as SHA-256 hex only; wrong token or wrong thread returns 404.
- Retention defaults: threads with no contact purged after 30 days idle; with contact after 12 months idle.
- UI copy Persian, code and comments English. Docs and one dated CHANGELOG line ship in the same commit as behaviour (`git add -f` for `*.md`).
- Nothing in this plan activates delivery. No credentials are read from or written to the repo.

## Review Focus

- A provider call that raises or hangs after a row is marked `sending`: the row must be reclaimed after 10 minutes, not stuck forever.
- Two workers (timer plus opportunistic thread) racing on the same due row: exactly one send.
- A visitor double-submitting (network retry): one stored message, via `client_id` idempotency.
- Messages that are only zero-width/whitespace characters, or mixed RTL/emoji at the length cap: rejected or stored intact, never a 500.
- Phone numbers typed with Persian/Arabic digits or separators: normalised before dedupe and cap accounting.
- Heartbeat from a deactivated admin, or a clock that went backwards: must not count as live.
- Mode switched `live` to `off` while rows are queued: nothing sends, rows stay queued (not lost, not marked sent).

---

## Phase 1: notification core

### Task 1: Outbox model and migration

**Files:**
- Create: `KG_backend/api/notifications/__init__.py`, `KG_backend/api/notifications/models.py`, `KG_backend/api/notifications/test_models.py`
- Modify: `KG_backend/api/models.py` (append one import line)
- Create: `KG_backend/api/migrations/0040_notification_outbox.py` (generated; renumber to follow the latest migration on `origin/work` at PR time)

**Interfaces:**
- Produces: `NotificationOutbox` with fields `event_type`, `channel` ('sms'|'email'), `recipient_kind` ('staff'|'visitor'|'customer'), `recipient_ref` (str, the phone or address), `dedupe_key` (str, null, unique), `payload` (JSON), `status` ('queued'|'sending'|'sent'|'failed'|'dead'|'suppressed'|'dry_run', default 'queued', indexed), `attempts` (default 0), `next_attempt_at` (indexed), `claimed_at` (null), `provider_ref`, `last_error`, `created_at`, `sent_at`. Index `(status, next_attempt_at)`.

- [ ] **Step 1: Write failing tests** in `test_models.py`: `test_defaults_are_queued_with_zero_attempts`; `test_dedupe_key_is_unique` (second create with same key raises `IntegrityError`); `test_two_rows_with_null_dedupe_key_allowed`.
- [ ] **Step 2: Run** `python manage.py test api.notifications.test_models` from `KG_backend/`. Expected: ImportError/FAIL.
- [ ] **Step 3: Implement** the model with `db_default` on every NOT NULL non-FK field; `makemigrations api -n notification_outbox`.
- [ ] **Step 4: Run** the tests (PASS) and `python ../ops/deploy/check_migrations.py origin/work` (exit 0).
- [ ] **Step 5: Commit** `feat(notify): outbox table (refs #<issue>)`.

### Task 2: Mode switch and provider interface

**Files:**
- Create: `api/notifications/config.py`, `api/notifications/providers.py`, `api/notifications/test_providers.py`

**Interfaces:**
- Produces: `config.mode(channel: str) -> Literal['off','dry_run','live']` (reads `KG_NOTIFY_SMS` / `KG_NOTIFY_EMAIL`, anything unknown or unset returns `'off'`); `providers.SendResult(accepted: bool, provider_ref: str, error: str)`; `providers.get_provider(channel) -> Provider` with `send(to: str, subject: str, body: str) -> SendResult`; classes `MelipayamakSMS` (wraps `portal._post_sms`; `accepted` mirrors its bool, `provider_ref` its Value), `SMTPEmail`, `FakeProvider` (records calls in `FakeProvider.sent`, can be told to fail), `DryRunProvider` (never touches the network, returns accepted with `provider_ref='dry'`).

- [ ] **Step 1: Failing tests:** `test_unset_and_garbage_mode_is_off`; `test_get_provider_is_fake_under_tests_even_when_live` (set env to `live`, assert `FakeProvider`); `test_melipayamak_wrapper_passes_text_unchanged` (patch `api.portal._post_sms` returning `(True,'12345678901')`); `test_smtp_not_configured_returns_error_result` (no `EMAIL_HOST` gives `accepted False`, never raises); `test_sms_body_validator_rejects_link_and_missing_footer` for helper `providers.check_sms_body(text) -> str|None` (error message or None).
- [ ] **Step 2: Run** `python manage.py test api.notifications.test_providers`; expect FAIL.
- [ ] **Step 3: Implement** as specified. `get_provider` returns Fake whenever `monitoring.TESTING`; otherwise by mode. `SMTPEmail` uses `django.core.mail.EmailMessage` with `fail_silently=False` inside try/except.
- [ ] **Step 4: Run tests;** expect PASS.
- [ ] **Step 5: Commit** `feat(notify): modes and provider interface`.

### Task 3: Enqueue with dedupe and suppression

**Files:**
- Create: `api/notifications/service.py`, `api/notifications/test_service.py`

**Interfaces:**
- Consumes: Task 1 model, Task 2 `config.mode`.
- Produces: `service.enqueue(*, event_type: str, channel: str, recipient_kind: str, recipient_ref: str, subject: str, body: str, dedupe_key: str|None = None) -> NotificationOutbox|None`. Behaviour: phone refs go through `models.normalize_phone` first; returns `None` (no row) if `dedupe_key` already exists; when `config.mode(channel) == 'off'` the row is created with status `suppressed`; otherwise `queued` with `next_attempt_at=now`. Helper `service.window_key(prefix: str, minutes: int, now=None) -> str` (bucketed key such as `thread:7:new:2026-11-02T10:0`).

- [ ] **Step 1: Failing tests:** `test_enqueue_off_mode_creates_suppressed_row`; `test_enqueue_dry_run_creates_queued_row`; `test_duplicate_dedupe_key_returns_none_and_creates_no_second_row`; `test_persian_digit_phone_is_normalised`; `test_window_key_same_inside_window_differs_across_windows`.
- [ ] **Step 2: Run;** expect FAIL.
- [ ] **Step 3: Implement.** Catch `IntegrityError` for the dedupe race and return `None`.
- [ ] **Step 4: Run;** expect PASS.
- [ ] **Step 5: Commit** `feat(notify): enqueue with dedupe`.

### Task 4: Worker: claim, send, retry, dead-letter, caps

**Files:**
- Create: `api/notifications/worker.py`, `api/notifications/test_worker.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces: `worker.process_due(now=None, limit: int = 50) -> dict` with integer counts `sent, retried, dead, deferred, skipped`. `worker.BACKOFF_MINUTES = (1, 5, 15, 60, 240)`. `worker.STUCK_AFTER = timedelta(minutes=10)`.

Behaviour to implement: claim due `queued`/`failed` rows plus `sending` rows with `claimed_at` older than `STUCK_AFTER` using an atomic conditional update (`filter(pk=..., status__in=...).update(status='sending', claimed_at=now)`; only the caller whose update count is 1 sends). If the channel mode is `off`, leave the row untouched (counted `skipped`). In `dry_run` use `DryRunProvider` and finish as `dry_run`. SMS rows over `KG_NOTIFY_SMS_MAX_PER_HOUR` (counted from `sent` rows in the last hour) are deferred: `next_attempt_at += 10 min`, status back to `queued`, never dropped. On failure: `attempts += 1`; if `attempts` reaches `len(BACKOFF_MINUTES)` set `dead` and open `SystemAlert` key `notify:dead` through the existing alert-row helper; else `failed` with `next_attempt_at = now + BACKOFF_MINUTES[attempts-1]`. A provider exception counts as a failure with `last_error` set.

- [ ] **Step 1: Failing tests:** `test_success_marks_sent_with_provider_ref`; `test_failure_schedules_backoff_1_then_5_minutes`; `test_fifth_failure_marks_dead_and_opens_systemalert`; `test_provider_exception_is_a_failure_not_a_crash`; `test_stuck_sending_row_is_reclaimed_after_10_minutes`; `test_second_claim_on_same_row_does_not_send_twice` (call the claim helper twice, assert one provider call); `test_off_mode_leaves_queued_rows_untouched`; `test_dry_run_never_calls_real_provider_and_ends_dry_run`; `test_sms_hourly_cap_defers_without_dropping`; `test_mode_switched_live_to_off_midway_keeps_remaining_rows_queued`.
- [ ] **Step 2: Run** `python manage.py test api.notifications.test_worker`; expect FAIL.
- [ ] **Step 3: Implement** `process_due` as described, with providers injected for tests via `providers.get_provider`.
- [ ] **Step 4: Run;** expect PASS, then the whole `api.notifications` suite.
- [ ] **Step 5: Commit** `feat(notify): outbox worker with retry, caps and dead-letter`.

### Task 5: Command, opportunistic kick, timer unit file, docs

**Files:**
- Create: `api/management/commands/process_outbox.py`, `api/notifications/kick.py`, `ops/outbox/kgkg-outbox.service`, `ops/outbox/kgkg-outbox.timer`, `api/notifications/test_command.py`
- Modify: `docs/04-backend-reference.md`, `docs/11-operations-deployment.md`, `docs/CHANGELOG.md`, `docs/OWNERS.toml` (review date if the freshness gate requires it)

**Interfaces:**
- Produces: `manage.py process_outbox [--limit N]` printing the `process_due` counts; `kick.kick()` starts at most one short-lived daemon thread (module-level lock) that calls `process_due`, no-op when both modes are `off` and under `TESTING`.

- [ ] **Step 1: Failing tests:** `test_command_prints_counts_and_exit_zero`; `test_kick_is_noop_in_off_mode` (no thread started); `test_kick_does_not_start_second_thread_while_one_runs`.
- [ ] **Step 2: Run;** expect FAIL.
- [ ] **Step 3: Implement.** Unit files mirror `ops/qa/kgkg-qa-nightly.*`, `OnCalendar=minutely`. They are **not installed**; the docs list the install steps as a manual, person-run action (decision D6 approved in principle, installation still a person's step).
- [ ] **Step 4: Run** `python manage.py test api.notifications` and `ops/deploy/gate.sh` where possible; expect PASS. Run `python ../ops/governance/check_traceability.py` equivalent as the repo documents.
- [ ] **Step 5: Commit** `feat(notify): process_outbox command, kick, timer unit (not installed)`.

---

## Phase 2: chat core backend

### Task 6: Chat models and migration

**Files:**
- Create: `api/chat/__init__.py`, `api/chat/models.py`, `api/chat/test_models.py`, migration `0041_chat_core.py` (renumber at PR time)
- Modify: `api/models.py` (one appended import)

**Interfaces:**
- Produces: `ChatThread` (`token_hash` unique char(64), `intent` in sales/demo/technical/other default other, `status` in open/waiting_staff/waiting_customer/closed/spam default open, `contact_name`, `contact_phone`, `contact_email`, `source_page`, `referrer`, `ua_hash`, `assignee` FK `PlatformAdmin` null SET_NULL, `priority` default normal, `last_activity_at` indexed, `created_at`, `closed_at` null, `promoted_request` FK `CompanyRequest` null SET_NULL, `csat_score` null, `csat_at` null). `ChatMessage` (`thread` FK CASCADE, `author_kind` visitor/admin/system, `author_admin` FK null, `body`, `internal` bool default False, `client_id` char(40) blank default '', `created_at`; unique `(thread, client_id)` where `client_id != ''`; index `(thread, id)`). `AgentPresence` (`admin` OneToOne `PlatformAdmin`, `manual_status` available/away/offline default offline, `last_heartbeat_at` null). All NOT NULL fields carry `db_default`.

- [ ] **Step 1: Failing tests:** `test_thread_defaults`; `test_client_id_unique_per_thread_but_blank_repeats_allowed`; `test_deleting_promoted_request_does_not_delete_thread`.
- [ ] **Step 2: Run** `python manage.py test api.chat.test_models`; expect FAIL.
- [ ] **Step 3: Implement + `makemigrations`.**
- [ ] **Step 4: Run tests and `check_migrations.py origin/work`;** expect PASS / exit 0.
- [ ] **Step 5: Commit** `feat(chat): thread, message and presence tables`.

### Task 7: Token helpers

**Files:** Create `api/chat/tokens.py`, `api/chat/test_tokens.py`.

**Interfaces:** `new_token() -> tuple[str, str]` (raw urlsafe 32 bytes, sha256 hex); `authorise(thread_id: str, raw: str|None) -> ChatThread|None` using `hmac.compare_digest`; returns `None` for missing/empty/wrong token, unknown thread, or malformed id.

- [ ] **Step 1: Failing tests:** `test_new_token_hash_matches_sha256_and_is_unique`; `test_authorise_accepts_correct_pair`; `test_authorise_rejects_wrong_token_other_thread_empty_and_malformed_id`.
- [ ] **Step 2: Run;** FAIL. **Step 3: Implement.** **Step 4: Run;** PASS. **Step 5: Commit** `feat(chat): visitor token helpers`.

### Task 8: Presence and public status

**Files:** Create `api/chat/presence.py`, `api/chat/test_presence.py`, `api/chat/views_status.py`; modify `api/urls.py`.

**Interfaces:** `presence.heartbeat(admin) -> None`; `presence.set_status(admin, status: str) -> None`; `presence.current_mode(now=None) -> Literal['live','async']`. Endpoints: `GET /api/chat/status/` (public, `rate_limited('chat_status', 60, 60)`, returns `{mode, expected_reply_minutes}`, `expected_reply_minutes` from `sla.targets('normal')[0]`, cached 5 s), `POST /api/admin/chat/presence/heartbeat/`, `PUT /api/admin/chat/presence/` body `{status}` (both `require_admin_token`).

- [ ] **Step 1: Failing tests:** `test_live_requires_available_and_fresh_heartbeat`; `test_heartbeat_older_than_60s_is_async`; `test_away_with_fresh_heartbeat_is_async`; `test_inactive_admin_never_counts`; `test_future_dated_heartbeat_does_not_count_as_live`; `test_status_endpoint_shape_and_no_names_leaked`; `test_status_endpoint_requires_no_auth_and_heartbeat_requires_admin`.
- [ ] **Step 2: Run;** FAIL. **Step 3: Implement.** **Step 4: Run;** PASS. **Step 5: Commit** `feat(chat): agent presence and public status`.

### Task 9: Anonymous thread API

**Files:** Create `api/chat/views_public.py`, `api/chat/limits.py`, `api/chat/serializers.py`, `api/chat/test_public_api.py`; modify `api/urls.py`.

**Interfaces:**
- Consumes: Tasks 6 to 8, `portal._verify_turnstile(request, token, expected_action='chat')`, `rate_limited`, `events.emit`.
- Produces endpoints (all `csrf_exempt`, header `X-Chat-Token`, JSON):
  - `POST /api/chat/threads/` body `{message, intent?, client_id, turnstile_token?, website?}` returns `{thread_id, token, message, mode}` (token shown exactly once). `website` is the honeypot: non-empty returns 200 with a fake id and stores nothing.
  - `GET /api/chat/threads/<id>/messages/?after=<msg_id>` returns `{messages:[{id, author_kind, body, created_at}], status, mode}`; internal notes never included.
  - `POST /api/chat/threads/<id>/messages/` body `{message, client_id}` returns the stored message (same `client_id` returns the existing one, 200).
  - `PATCH /api/chat/threads/<id>/contact/` body `{name?, phone?, email?}`.
  - `POST /api/chat/threads/<id>/csat/` body `{score: 1..5}` only after `closed`.
- Admin event: each visitor message calls `events.emit('chat.message', {thread_id, intent, preview}, audience='admin')`.

- [ ] **Step 1: Failing tests:** `test_create_returns_token_once_and_stores_only_hash`; `test_wrong_token_and_other_threads_token_both_404`; `test_poll_returns_only_after_cursor_and_hides_internal_notes`; `test_double_submit_same_client_id_stores_one_message`; `test_body_over_2000_chars_rejected_400`; `test_whitespace_and_zero_width_only_body_rejected_400`; `test_rtl_emoji_body_at_cap_roundtrips_intact`; `test_31st_message_in_an_hour_rate_limited_429`; `test_honeypot_filled_stores_nothing`; `test_turnstile_enforced_on_create_when_secret_set` (patch `_verify_turnstile`); `test_persian_digit_phone_normalised_on_contact_patch`; `test_invalid_email_and_short_phone_rejected`; `test_csat_rejected_while_open`; `test_visitor_message_emits_admin_event_without_contact_details`.
- [ ] **Step 2: Run** `python manage.py test api.chat.test_public_api`; FAIL.
- [ ] **Step 3: Implement.** Strip zero-width/BiDi control characters when checking emptiness but store the original text. Update `last_activity_at` and status `waiting_staff` on each visitor message.
- [ ] **Step 4: Run;** PASS. **Step 5: Commit** `feat(chat): anonymous thread API`.

### Task 10: Minimal staff reply path

**Files:** Create `api/chat/views_admin.py`, `api/chat/test_admin_api.py`; modify `api/urls.py`.

**Interfaces:** `POST /api/admin/chat/threads/<id>/reply/` body `{message, internal?: bool}` (`require_admin_token`); public reply sets status `waiting_customer`, stores `author_admin`, emits nothing to visitors beyond being pollable. Internal note sets `internal=True` and never changes status. Full inbox endpoints are Phase 5.

- [ ] **Step 1: Failing tests:** `test_public_reply_appears_in_visitor_poll`; `test_internal_note_never_appears_in_visitor_poll`; `test_reply_requires_admin_token`; `test_reply_to_unknown_thread_404`.
- [ ] **Step 2: Run;** FAIL. **Step 3: Implement.** **Step 4: Run;** PASS. **Step 5: Commit** `feat(chat): staff reply and internal notes`.

### Task 11: Retention command

**Files:** Create `api/management/commands/purge_chat.py`, `api/chat/test_purge.py`.

**Interfaces:** `manage.py purge_chat [--dry-run]` deletes threads idle over 30 days with no contact, idle over 365 days with contact; never deletes a thread with `promoted_request`; prints counts.

- [ ] **Step 1: Failing tests:** `test_purges_idle_anonymous_but_not_recent`; `test_contact_threads_kept_until_12_months`; `test_promoted_threads_never_purged`; `test_dry_run_deletes_nothing`.
- [ ] **Step 2: Run;** FAIL. **Step 3: Implement.** **Step 4: Run;** PASS. **Step 5: Commit** `feat(chat): retention purge`.

### Task 12: Poll load check, authz regression, docs

**Files:** Create `qa/k6/chat_poll.js`; modify `docs/04-backend-reference.md`, `docs/CHANGELOG.md`, `docs/OWNERS.toml` if needed.

- [ ] **Step 1:** Write the k6 script: 100 virtual users, each creates a thread then polls its messages every 3 s for 60 s; thresholds `http_req_failed < 1%`, `p95 < 300ms`.
- [ ] **Step 2:** Run it against a local stack (`python manage.py runserver` on both SQLite and PostgreSQL if available) and save the output under `audit-evidence/` per repo convention. Expected: thresholds met. If not, stop and report; do not tune around it.
- [ ] **Step 3:** Run the whole backend suite `python manage.py test --noinput --shuffle` and confirm the existing desk tests (`api.test_helpdesk`, `api.test_helpdesk_desk`, `api.test_events`) are unchanged and green.
- [ ] **Step 4:** Document endpoints, env vars (`KG_NOTIFY_SMS`, `KG_NOTIFY_EMAIL`, `KG_NOTIFY_SMS_MAX_PER_HOUR`), modes and the retention policy; add one dated CHANGELOG line.
- [ ] **Step 5: Commit** and open the PR to `work` (only after the user's go-ahead to push).

---

## Phases 3 to 7 (separate plans, written when Phase 2 lands)

| Phase | Needs from this plan |
|---|---|
| 3 landing widget | Task 8 status, Task 9 endpoints and response shapes |
| 4 customer unification and promotion | Task 6 `promoted_request`, existing ticket API |
| 5 admin inbox | Tasks 6, 8, 10 plus merged list endpoint |
| 6 notification wiring and preferences | Phase 1 `service.enqueue`, trigger matrix in spec 6.3 |
| 7 activation | Phase 1 modes; every live step needs the user's explicit authorisation |

## Self-review (against the spec)

- Spec 5.2 tables: Task 6. 5.3 transport: Tasks 9 and 12 (polling, load check). 5.4 presence: Task 8. 5.5 security: Tasks 7 and 9 (hash, 404, Turnstile, honeypot, caps, retention in 11). 5.6 promotion: field in Task 6, behaviour deferred to Phase 4 (stated). 6.2 outbox, retry, dead-letter: Tasks 1 and 4. 6.4 modes/caps/dedupe: Tasks 2 to 4. Visitor-SMS per-phone and per-thread limits are policy in wiring (Phase 6) and are listed in Global Constraints so Phase 6 enforces them; the worker enforces only the global hourly cap.
- **Deviation from the spec, stated:** over-cap SMS are deferred, not downgraded to email, because recipient email addresses exist only after Phase 6 wiring. They are never dropped.
- Types checked across tasks: `enqueue` returns `NotificationOutbox|None`; `process_due` returns counts dict; `authorise` returns `ChatThread|None`; `current_mode` returns 'live'|'async', used by Tasks 8 and 9.
- Proportion: code appears only as signatures, test names and exact values.
