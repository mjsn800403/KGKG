# 26 — Authentication and sessions as built

Complements `06-permissions-rbac.md` (who may do what) and `12-security.md` (guarantees and hardening history).
This document records **behaviour that is in code but was written down nowhere**, with the file that proves it.
Everything here is **[C]** at `origin/work` `8a380f6` unless tagged.

## 26.1 Session tokens

| | Portal (`AuthToken`) | Platform admin (`AdminAuthToken`) |
|---|---|---|
| Base class | `SessionTokenBase` (`api/models.py`) | same |
| Idle TTL | 14 days | **12 hours** |
| Absolute TTL | 90 days | **7 days** |
| Override | `KG_TOKEN_IDLE_DAYS`, `KG_TOKEN_MAX_DAYS` (`SessionTokenBase._ttls`), no deploy needed | `KG_ADMIN_TOKEN_IDLE_DAYS`, `KG_ADMIN_TOKEN_MAX_DAYS` |
| Stored as | SHA-256 of the key; the raw key is returned once | same |
| Sliding | each use moves `expires_at` to `min(last_used + idle, created + absolute)` | same; `touch=False` is used for background pings (`X-Kg-Background: 1`) so an open console does not keep itself signed in |

Portal sessions travel as an `HttpOnly; Secure; SameSite=Lax` cookie set by the backend (`portal._set_portal_cookie`)
or as `Authorization: Bearer`.

## 26.2 Login flow (portal)

1. `/api/auth/login/`: username or e-mail + password, plus a Cloudflare Turnstile token verified server-side
   (`portal._verify_turnstile`; `TURNSTILE_SECRET`, optional `TURNSTILE_HOSTNAMES`; the action must match).
   Verification calls `challenges.cloudflare.com`; on 2026-11-03 a missing IPv6 route made this call take about
   40 s until the backend image preferred IPv4 (`ops/docker/backend.Dockerfile`). [D Slack #kg-dev]
2. If the account has a phone on file and `otp_enabled`, an SMS code is required (`OtpChallenge`: TTL 2 minutes,
   resend unlocks at the same moment, at most 5 attempts; per-day caps `KG_OTP_MAX_SENDS_PER_DAY`,
   `KG_OTP_MAX_FAILS_PER_DAY`). An account without a phone logs in with password and Turnstile only.
   Admins have the same flow (`AdminOtpChallenge`, `/api/admin/verify-otp/`).
3. `portal._issue_session` sets `last_login_at`, creates the token, **deletes every other token of the user**,
   writes the `login` activity row and emits a live event.
4. `notify.check_login_device` runs a rotating `kg_dev` cookie: a retired (copied) device ID texts the owner and
   signs out all other sessions; an unknown device texts the owner (unless it is the account's first).

## 26.3 One active session per account

A new login signs every other browser out. Introduced by `7200db7` (2026-10-21, "content protection ... one session
per account"), part of the anti-scraping bundle with `contentguard.py` and `shield.py`; it was pushed without an
issue reference. Kill switch: `KG_SINGLE_SESSION=0`; on by default. Tests: `SingleSessionTests` in
`test_contentguard.py` and `test_qa_auth.py`. [C, git history]

## 26.4 Admin gate

`admin_auth.require_admin_token` accepts (a) a platform-admin session token, or (b) the static `KG_ADMIN_TOKEN`
**only for a direct loopback call without proxy headers** (`_from_server_itself`), so scripts and cron on the host work and
the internet cannot use a static, 2FA-free secret. The loopback token is never a "person" for the support-chat RBAC.
`vncauth.py` gates the browser screen used for the TIS crawler (`/kg-vnc/`) with a signed, 2-hour, path-scoped
cookie checked by nginx `auth_request`.

## 26.5 Content protection (not authentication, but sessions are its key)

`shield.py` (`KG_SHIELD=1` + `KG_SHIELD_SECRET`) encrypts document payloads with per-session, per-epoch keys and requires
signed single-use requests; the Next.js server derives the same keys (`utils/shieldServer.js`). `contentguard.py`
raises page/media thresholds (`KG_CG_PAGE_WARN/BLOCK`, `KG_CG_MEDIA_WARN/BLOCK`). Whether shield is enabled in
production is **[U]** (environment not read).

## 26.6 Known gaps

- No password change/reset route exists in `api/urls.py` for portal users or admins [C: no `password` route]. Doc 12 lists it.
- No CSRF tokens; mitigations are `SameSite=Lax` and `OriginGuardMiddleware` (`KG_ORIGIN_GUARD=0` disables). Doc 21.
- `KG_TRUST_XFF` controls whether `X-Forwarded-For` is trusted for client IPs; correct only behind the Cloudflare/nginx chain [C `ratelimit.py`; production value **U**].
