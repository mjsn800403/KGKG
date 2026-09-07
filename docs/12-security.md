# 12 — Security


> **2026-08-05:** secret/token rotation, edge rate limiting, the
> ModSecurity+CRS WAF and self-hosted error monitoring are documented
> in [18 — Security hardening](18-security-hardening.md). The known
> limitations below were re-assessed on that date.
## 12.1 Enforced guarantees (as of 2026-07-15)

1. **Content paywall is backend-enforced.** Every manual-content endpoint (car content,
   search, assist, diagnose, feedback) requires a live portal session and a per-car grant;
   the general assistant is scoped by a per-user car allow-list threaded through RAG
   retrieval and caches. `db_address` never leaves the server. (Closed 2026-07-09; the
   paywall had been frontend-only before that. Cross-car cache leak B-01 closed 2026-07-11.)
2. **Chat costs are gated.** `/api/chat` validates the session + AI eligibility
   (user flag ∧ company flag ∧ `manual` package) before any paid Metis call.
3. **Grant writes are clamped.** All grant mutations run through
   `apply_user_access`/`apply_managed_access`: company purchase is the ceiling, managers
   can only delegate what they hold, silent upgrades are refused (doc 06).
4. **No user enumeration on login** (timing-equalized dummy hash) and login/admin-login are
   rate limited per real client IP (`KG_TRUST_PROXY=1`; nginx sets `X-Real-IP`).
5. **Tokens:** opaque 256-bit random, DB-backed, revocable (logout deletes; deleting rows
   force-logs-out). Invite tokens are single-use, 7-day, sha256-hashed at rest, raw value
   shown exactly once.
6. **Secrets hygiene:** `DJANGO_SECRET_KEY` mandatory in prod (boot refuses without);
   Metis keys server-side only; `db.sqlite3` untracked from git (2026-07-10);
   admin default password (admin/admin) rotated 2026-07-08 and all old admin sessions
   invalidated.
7. **Request-body hardening:** JSON bodies that aren't objects are coerced to `{}`
   everywhere (no 500s from `"string"` payloads); admin company updates clamp field
   lengths (SQLite ignores VARCHAR limits).
8. **Privacy:** daily-unique visitor tracking stores salted, truncated, irreversible IP
   hashes only; activity logging is per authenticated seat (business requirement).

## 12.2 Known limitations / accepted risks (ranked)

| # | Risk | Notes / path |
|---|---|---|
| 1 | **HTTP only (no TLS).** All credentials and tokens cross the wire in cleartext. | Highest-value fix: put the IP (or a domain) behind TLS — certbot or a fronting CDN. Until then, treat all passwords as network-visible. |
| 2 | **No off-host backups.** Single disk holds the only copy of `db.sqlite3` + the 21 GB warehouse. | Nightly rsync/restic to object storage or a second host. |
| 3 | **Portal token readable by JS.** Token lives in localStorage + a JS-set (non-HttpOnly) cookie. XSS ⇒ token theft. Mitigation: React escaping; no third-party scripts; manual HTML content is served from our own parsed DBs. | Move to HttpOnly cookie sessions when auth is next touched. |
| 4 | **No password reset / self-service change** for portal users or the platform admin (re-rotate via ORM `set_password`). | Add flows; requires SMTP decision (see 6). |
| 5 | **No CSRF tokens on state-changing endpoints** — acceptable *only because* auth is header-Bearer for mutations; the cookie path is used by GET/SSR reads. Keep it that way: any cookie-authenticated mutation would need CSRF. |
| 6 | **No SMTP** — invite e-mail off (`KG_INVITE_EMAIL`); invite links are copy-pasted by managers (they see the raw link — acceptable, they created the account). |
| 7 | **Rate limiter is per-process** (×3 workers) and memory-based — a determined abuser gets ~3× the nominal budget; fine at current scale. |
| 8 | **Admin token in env** (`KG_ADMIN_TOKEN`) is long-lived — rotate occasionally; session tokens exist for humans. |
| 9 | **SQLite files world-readable on host** — anyone with shell access reads everything. Host access is the perimeter (root-only box). |

## 12.3 Security-relevant history (why things are the way they are)

- **2026-07-08:** PlatformAdmin was literally `admin/admin`, publicly reachable → rotated to
  a strong random password, all 13 admin session tokens deleted, verified old creds/tokens
  401. No self-service admin password endpoint exists (deliberate minimalism).
- **2026-07-09:** Content-authz gap found and closed (backend gates + SSR cookie
  forwarding + chat gating + per-IP rate limiting). Regression-tested
  (`ContentAccessGateTests`).
- **2026-07-10:** `db.sqlite3` removed from git tracking (live tokens/hashes were in
  history; old copies remain in git history — treat the repo as sensitive), monitoring/
  alerting added.
- **2026-07-11:** RAG allow-list threading (B-01), admin body clamps (B-02), manager grant
  no-silent-upgrade (B-03), JSON body hardening (G12) — all with regression tests.
- **2026-07-14:** assistant link integrity repaired fleet-wide (broken links had been
  routing users to 404/500s — availability, not confidentiality).

## 12.4 Reviewer checklist for new code

- Does any new endpoint serve manual-derived content? → it needs `_guard_car_content` (or
  equivalent) AND allow-list threading if results can span cars.
- Does it mutate state? → Bearer-token auth (not cookie), rate limit if unauthenticated
  surface, Persian validation errors, body via hardened parsers.
- Does it write grants/org structure? → only via the access.py writers + consistency pass.
- Does it log anything? → no secrets/PII beyond the established activity fields.
- Does it add a long-lived connection or background work? → document the envelope; make it
  survive restarts or fail visibly (events/alerts).
