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
   masked to the /24, support-chat contact details and message bodies replaced (#79).
   Unhandled identifying columns fail the staging and QA builds (`--strict-audit`).
   Previously a session token lifted from staging would have worked against production.
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
| 5 | **No CSRF tokens on state-changing endpoints.** Sessions are now cookies, so the original "Bearer-only mutations" argument no longer holds. What protects mutations today is `SameSite=Lax` (browsers do not send the cookie on cross-site POST/PUT/DELETE) plus JSON request bodies, plus (added since this table was written) `OriginGuardMiddleware`, which refuses cookie-authenticated unsafe requests whose `Origin`/`Referer` is not ours (`KG_ORIGIN_GUARD=0` turns it off). | Never add a state-changing GET; see [21](21-csrf-exempt-views.md). |
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
- Does it mutate state? → authenticated session (Bearer header or the `HttpOnly; SameSite=Lax` cookie; cookie-authenticated writes also pass `OriginGuardMiddleware`), rate limit if
  unauthenticated surface, Persian validation errors, body via hardened parsers.
- Does it write grants/org structure? → only via the access.py writers and the org-graph API (`api/org/*`).
- Does it log anything? → no secrets/PII beyond the established activity fields.
- Does it add a long-lived connection or background work? → document the envelope; make it
  survive restarts or fail visibly (events/alerts).

## Addendum (2026-11-04): behaviour documented elsewhere

Session lifetimes, the single-active-session rule (`KG_SINGLE_SESSION`), the OTP flow, device-copy detection, the admin loopback
token rule and content-protection modules are described, with their source files, in [26 — Authentication and sessions](26-auth-and-sessions.md).
The open-risk register (backups of `kgkg_vec`, staging sharing production car data, reconstructed activity rows, missing password reset) is
[27](27-open-risks-and-decisions.md).

## CodeQL triage (KGTEC-14, 2026-11-04)

45 alerts were open, all reported against `main` (`95c45b6`). On `work` 31 of
them no longer occur (fixed earlier: `safe_join` on every user-influenced path,
the year/parts suffix regexes without leading/trailing `\s*`, the Metis path
and client-id checks in `kg_frontend/src/lib/safeUrl.js`); they close when
`work` is promoted to `main`. The 14 still found on `work`:

| Alert | Where | Verdict |
|---|---|---|
| #50 py/stack-trace-exposure | `parts.py` corrupt catalog (503) | **Fixed**: the sqlite message is logged, not returned. |
| #40 py/stack-trace-exposure | `adminops.py` `scan_zips` | **Fixed**: logged; the admin gets a fixed message. |
| #34-39, #41, #42 py/stack-trace-exposure | `adminops.py` pipeline / crawler / data-quality / alerts | **Fixed (see below)**. An independent re-audit found these were not all fixed text: raw `OSError`/sqlite/driver messages, `str(e)` of a database error and a stored full traceback reached admin responses. Admin-only, so low severity, but real. |
| #44 py/stack-trace-exposure | `portal.py` `admin_user_access_view` | **Fixed (see below)**. `Car.objects.filter(id='abc')` raises a `ValueError` that echoes the value, and the view returned `str(e)`. |
| #45 py/cookie-injection | `portal.py` `_set_portal_cookie` | False positive, to be dismissed by the owner. Both call sites pass a token that was minted by `AuthToken.issue` (`secrets.token_urlsafe(48)`) or, in `me_view`, a bearer that `portal_user()` has just resolved by hash. Cookie is HttpOnly, Secure, SameSite=Lax, path `/`, no Domain, max-age at most the token TTL. |
| #1 js/stored-xss | car page EWD `<iframe src>` | **Unresolved**. The flagged flow cannot change scheme, host or path (fixed `/kg-api/media/` prefix, `encodeURIComponent(model)`, `^[A-Z0-9]+$` directory), and the fragment comes from our own mirrored `termdata.xml`. The open question is the mirrored `viewer.html`, which is not in this repository: how it reads `location.hash`, and that it runs same-origin without `sandbox` or a CSP (the nginx `/kg-api/media/` block defines its own `add_header`, so the server-level CSP is not inherited). Needs a read-only look at the mirrored files and the live headers. |
| #2 js/xss-through-dom | `AssistantChat.jsx` link | False positive, to be dismissed by the owner. `fixHref` runs first, then only `isInternalHref()` paths (leading `/`, not `//` or `/\`, no control characters) become `next/link` links; everything else is a React text node. No `dangerouslySetInnerHTML` in the component. |

Status words in this table: **Fixed** means the code no longer returns the text and a regression test pins it; the GitHub alert closes by itself
when the fix reaches `main` and CodeQL rescans. **Unresolved** stays open. Nothing in this table has been dismissed in GitHub; dismissal of
#2 and #45 needs the owner's decision.

### What the fix does (KGTEC-14, second pass)

- **New errors.** The crawler/Chrome/build/ingest/audit/monitoring code logs the exception (logger `kgkg.*`, with traceback) and returns or stores
  only the exception class (`OSError`) or a fixed Persian sentence ending in "جزئیات در لاگ سرور". Our own `BuildError` validation messages are
  still shown. `DataQualityRun.error` no longer stores a traceback.
- **Stored errors.** Rows written before the fix still hold raw text. They are not rewritten. `safepath.public_error()` / `scrub_errors()` reduce
  every `error` / `db_error` value (and the detail of a `*_failed` data-quality action) on the way out of the data-quality, system, pipeline and
  `job_dict` (also used by the event stream) responses: a short plain phrase passes, anything with a path, URL, quote or traceback becomes its
  exception class name(s), or `error`.
- **Admin access view.** `apply_user_access` validates the shape of every entry before touching the database (`car_id` an integer or digit
  string, `documents` a list of strings) and the view answers `invalid accesses payload` for any `ValueError`.
- **Not changed.** `ProcessingJob.log_tail` is the worker's own log and is still returned to admins as is; it can contain exception text.
  `hostjobs` results returned by `tis_start_chrome` are host-helper text, not reviewed here. `apply_managed_access` (company-manager API) was
  not touched.
