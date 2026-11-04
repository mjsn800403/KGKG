# 22 — Support chat (visitor widget and staff inbox)

Human live-chat for anonymous website visitors, answered by platform-admin staff. It is separate from
the AI assistant (`/api/chat/`, doc 08) and from the in-portal request desk (`requests_api.py`).
**Status:** code is on `work` and deployed, but the public widget is OFF in production unless a person sets
`KG_SUPPORT_CHAT_ENABLED=1`. [C `support_chat/config.py`] Whether it is set on the host is **[U]**
(not read; `.env.prod` is not inspected by documentation work). Design history and approvals:
`docs/superpowers/specs/2026-11-02-customer-communication-design.md`,
`2026-11-02-phase3-support-chat-ux-design.md`, `2026-11-03-phase3-*`, `2026-11-03-support-readiness-gap-register.md`.

## 22.1 Code map [C]

| Piece | Where |
|---|---|
| Models `SupportThread`, `SupportMessage`, `SupportRating`, `SupportPresence` | `KG_backend/api/support_chat/models.py` (migration `0041_support_chat_core`) |
| Visitor API (anonymous, bearer token) | `views_public.py`; routes in `support_chat/urls.py` under `/api/support-chat/` |
| Staff API (platform-admin session) | `views_admin.py`, `views_admin_inbox.py`, `views_status.py` under `/api/admin/support-chat/` |
| Token handling | `tokens.py`: 32 random bytes, URL-safe base64, 43 chars; only the SHA-256 is stored; a client-chosen token makes thread creation idempotent |
| Input rules | `limits.py` (body max 2000 chars; intents `sales`, `demo`, `technical`, `other`) |
| Rate limits | `throttle.py`, defaults in `config.py` (`KG_SC_<NAME>="N/seconds"`, `0/0` disables); per thread, not per IP, except creation and failed-token counters |
| Presence ("is anyone live") | `presence.py`: connected + declared available + active account; `KG_SUPPORT_PRESENCE_WINDOW_S` default 60 |
| Close/reopen | `lifecycle.py`; visitor may reopen for `KG_SUPPORT_REOPEN_DAYS` (default 14) |
| Contact masking | `mask.py`: staff see masked phone/e-mail unless they hold the reveal permission |
| Roles | `rbac.py` (five roles, modes `off` / `audit` / `enforce`), `management/commands/support_roles.py` |
| Queue health | `health.py`, `manage.py support_health` (read-only, not wired to alerts) |
| Retention | `manage.py purge_support_chat` is report-only unless `KG_SUPPORT_RETENTION_ENABLED=1` **and** `--apply` |
| Frontend | `kg_frontend/src/support-chat/` (widget client), staff inbox in the admin console |

## 22.2 Thread model [C]

`SupportThread.status`: `open`, `waiting_staff`, `waiting_customer`, `closed`, `spam`. Fields: `intent`,
`priority`, `assignee` (PlatformAdmin), `contact_name/phone/email` (optional, visitor-supplied),
`source_page`, `referrer`, `ua_hash` (hash, not the agent string), `token_hash`, `promoted_request`
(link to a `CompanyRequest` when a thread becomes a desk request), `staff_seen_at`, `closed_at`.
`SupportMessage.author_kind` (`visitor` / `admin` / `system`; staff are `admin` rows), `internal` (staff-only note), `client_id`
(visitor-side id for de-duplicating resends). Ratings (CSAT) are one row per rating event.

## 22.3 Security properties [C, tested in `support_chat/test_security_sweep.py`]

- Visitor routes answer identically for a real and an unknown thread (no existence oracle).
- Staff routes answer 401 without an admin session; the loopback `KG_ADMIN_TOKEN` is never a person and holds
  no support permission in any RBAC mode.
- Logs carry no message text, contact data or tokens.
- All support views are `@csrf_exempt` by design and listed in `api/csrf_registry.py` (doc 21): visitor routes
  authenticate by bearer token header, staff routes by admin header; `OriginGuardMiddleware` adds a
  cross-origin check for cookie-authenticated writes.
- Staging/QA copies of production data have support contact fields and message bodies masked, and the
  sanitizer fails the run if any masked value survives (`ops/deploy/sanitize_staging_db.py --strict-audit`,
  PR #85). Production had 0 support threads on 2026-11-04. [D Slack #kg-dev]

## 22.4 RBAC rollout (enforcement is OFF unless configured)

`KG_SUPPORT_RBAC`: unset/blank/`off` = every signed-in admin *person* may do everything; `audit` = same
access but would-be denials are written as id-only audit rows; `enforce` = default deny. An unrecognised value
**fails closed** (treated as `enforce`, logged, reported by `support_roles check`). `KG_SUPPORT_OWNERS`
(comma-separated usernames) are bootstrap owners. Roles come from the environment until the planned
`SupportStaffRole` table exists.

**Migrations 0042/0043 are not on `work`** (latest is `0041`, [C]). A design reserves `0042` (`SupportThreadEvent`
+ `SupportThread.excluded`) and `0043` (`SupportStaffRole`), pending the other maintainer's written confirmation
that the numbers are free. [D Slack #kg-dev 2026-11-03; answer **[U]**]. Verify with
`ops/deploy/check_migrations.py` and `git fetch` before generating either.

## 22.5 Operating it

- Runbook R10 in `20-runbooks.md`. Before enabling publicly: the `support-chat-e2e` CI job must be green
  (21 browser tests), the privacy notice (draft in `docs/superpowers/specs/2026-11-02-privacy-notice-draft.md`,
  unpublished) must be approved, and backup retention must be known (doc 27, R1/R5).
- Kill switch: `KG_SUPPORT_CHAT_ENABLED` gates only NEW visitor threads; existing threads and staff replies keep working.
- Live-update transport is SSE with polling fallback; the shared event stream and 45 s stall watchdog are in
  `kg_frontend/src/utils/eventStreamConnector.js` (doc 09).

## 22.6 Known gaps [U / D]

- No `SupportThreadEvent` timeline until migration `0042`; traceability uses `AuditLog` (ids only).
- Retention periods are not chosen; purge is disabled.
- Reply-target promise is unset by design (`KG_SUPPORT_REPLY_TARGET_MINUTES`).
- The customer-communication outbox (`api/notifications/`, `manage.py process_outbox`, migration `0040_notification_outbox`, unit `ops/outbox/kgkg-outbox.service`)
  is documented in [35-support-system.md](35-support-system.md) §35.9 (SMS/e-mail are off by default; providers in `notifications/providers.py`; SMTP via `EMAIL_*` and
  `KG_NOTIFY_FROM_EMAIL`, see also doc 24). This chapter is the code map; [35](35-support-system.md) is the deep reference.
