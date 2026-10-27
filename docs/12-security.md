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
9. **Deploy privilege is scoped by key, on the server** (2026-10-27). Each deploy key is
   pinned to a forced command whose role decides which verbs exist: the CI key may `stage`
   and read `status`, and has no `deploy` verb at all. CI therefore cannot promote to
   production — not by policy, by construction — and a leaked CI secret buys a staging run.
   The matrix is tested (`ops/deploy/test_gate_roles.sh`). Promotion requires a person
   typing a confirmation into `kgkg-promote`; no timer, cron or workflow can reach it.
   The previous `deploy.yml` would have promoted on green CI, held back only by a GitHub
   environment setting; it was deleted.
10. **Staging holds no usable credentials** (2026-10-27). The database copy staging runs on
   is sanitized before it serves anything: session/OTP/invite tables emptied, password
   hashes replaced with an unusable sentinel, phone numbers and e-mails replaced, audit IPs
   masked to the /24. Previously a session token lifted from staging would have worked
   against production.
11. **Monitoring has its own credential.** `KG_METRICS_TOKEN` gates `/api/metrics/` and is
   separate from `KG_ADMIN_TOKEN`, so handing a scrape credential to Prometheus does not
   hand it the admin surface. The public path to the endpoint is denied at nginx regardless,
   and the scrape reaches it only over a loopback-plus-docker-bridge listener.
12. **Supply chain is gated in CI** (2026-10-27). shellcheck, hadolint, gitleaks, pip-audit,
   npm audit and a trivy scan of both production images, failing closed; exceptions need a
   stated blocker, a reachability argument and a review date (`ops/security/README.md`).
   The gates' first run found an unauthenticated-RCE advisory range covering the installed
   Next.js and a WeasyPrint arbitrary-code-execution issue on the PDF path; both are fixed.

## 12.2 Known limitations / accepted risks (ranked)

| # | Risk | Notes / path |
|---|---|---|
| ~~1~~ | ~~**HTTP only (no TLS)**~~ — **closed.** The site is served over TLS with Cloudflare origin certificates, and ufw admits 80/443 only from Cloudflare ranges, so the origin is not directly reachable. |
| **1** | **Backup retention on the far side is unconfirmed.** An hourly off-host snapshot does exist and restores correctly (doc 11 §11.6, verified 2026-10-27). What is not established from this host is whether the internal server keeps *versions*: if it mirrors, a corruption propagates within the hour and the monthly provider backup becomes the only older restore point. | Confirm retention on that server; a few daily plus a few weekly copies is enough. No new backup system is needed. |
| 2 | **Secrets are in no backup, by design.** `.env.prod` and the Cloudflare origin key are excluded from the snapshot. A bare-metal rebuild needs them from wherever they are kept. | Keep them in a password manager; without `DJANGO_SECRET_KEY` the restored database still works but every session is invalidated. |
| ~~3~~ | ~~**Portal token readable by JS.**~~ — **closed.** The session is a backend-set `HttpOnly; Secure; SameSite=Lax` cookie (`portal._set_portal_cookie`); the frontend no longer stores the token (`utils/api.jsx setPortalSession`). Covered by `api/test_qa_auth.py`. |
| ~~4~~ | ~~**No password reset**~~ — **closed.** SMS-verified recovery (`/api/auth/recover/start/`, `/reset/`), rate-limited; covered by `api/test_recover.py`. |
| 5 | **No CSRF tokens on state-changing endpoints.** Sessions are now cookies, so the original "Bearer-only mutations" argument no longer holds. What protects mutations today is `SameSite=Lax` (browsers do not send the cookie on cross-site POST/PUT/DELETE) plus JSON request bodies. | Add an `Origin`/`Sec-Fetch-Site` check on cookie-authenticated mutations as defence in depth; never add a state-changing GET. |
| 6 | **No SMTP** — invite e-mail off (`KG_INVITE_EMAIL`); invite links are copy-pasted by managers (they see the raw link — acceptable, they created the account). |
| ~~7~~ | ~~**Rate limiter is per-process**~~ — **closed.** Counters live in a SQLite store shared by all workers (`api/ratelimit.py`, `KG_RL_STORE`), falling back to in-process only if the store is unusable; covered by `api/test_qa_ratelimit.py`. |
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
