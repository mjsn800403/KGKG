# 18 — Security hardening: secrets, rate limiting, WAF, error monitoring

Built 2026-08-05. Covers three gaps: secrets that had never been rotated and
sat world-readable, no edge rate limiting, and no WAF or error monitoring.

Related: [05-api-reference](05-api-reference.md), [12-security](12-security.md) (auth endpoints),
[11-operations-deployment](11-operations-deployment.md) (systemd units, timers).

---

## 1. Key management and token rotation

### Secrets at rest

`.env.prod`, `.env.production`, `db.sqlite3` and every backup copy of them are
now mode **0600, root-only**. They were 0644 — readable by any local account on
a box that has several — and each contained the Django secret key, the admin
token, and the paid Metis API key.

Also locked down: 17 stray copies under `/root` (old deploy backups, the
`/root/kgtest` staging tree) and 7 `db.sqlite3.bak*` files in `KG_backend/`,
each of which held live plaintext session tokens and password hashes.

### Session tokens are hashed and expiring

`AuthToken` and `AdminAuthToken` used to store the bearer value **in plaintext**
and **never expire**. A copy of `db.sqlite3` — which lived in git history for a
while — was therefore a set of permanent, ready-to-use sessions.

Now (migration `0017_hash_session_tokens`, model base `SessionTokenBase`):

| | portal user | platform admin |
|---|---|---|
| stored | `sha256(raw)` in `key_hash` | same |
| idle timeout | 14 days | 12 hours |
| absolute cap | 90 days | 7 days |

* `issue(owner)` returns the instance with the raw value attached as `.key`, an
  **in-memory attribute only** — `key` is no longer a model field, so every
  existing call site (`token.key` right after issue) keeps working while the
  database never sees the secret.
* `resolve(raw)` enforces expiry inside the query, so a stale row can never be
  resolved.
* `touch()` slides the idle window forward, clamped to the absolute ceiling,
  and writes at most once per 5 minutes per token (`TOUCH_INTERVAL`) — it runs
  on every authenticated request.
* TTLs are env-overridable: `KG_TOKEN_IDLE_DAYS`, `KG_TOKEN_MAX_DAYS`,
  `KG_ADMIN_TOKEN_IDLE_DAYS`, `KG_ADMIN_TOKEN_MAX_DAYS`.

The migration **deletes** the 89 pre-existing plaintext rows rather than
re-hashing them: re-hashing would keep already-leaked bearer values working,
which is the exact problem it exists to end. Everyone signed in once more.

### Rotation tooling

```bash
# Report ages and fingerprints — never prints a secret value.
manage.py rotate_secrets --status

# Rotate. The outgoing Django key is pushed onto DJANGO_SECRET_KEY_FALLBACKS so
# signatures already in flight keep verifying for one window.
manage.py rotate_secrets --what django-key
manage.py rotate_secrets --what admin-token --print-new
manage.py rotate_secrets --what all --prune-fallbacks 1
systemctl restart kgkg-backend        # nothing is live until this runs
```

The env file is rewritten **atomically** (temp file + `os.replace`) at mode
0600, preserving comments and unrelated keys, with a timestamped backup.

```bash
manage.py rotate_tokens                     # report
manage.py rotate_tokens --prune             # delete expired (daily timer)
manage.py rotate_tokens --revoke-user NAME  # incident response
manage.py rotate_tokens --revoke-admin
manage.py rotate_tokens --revoke-all --yes
```

`kgkg-token-prune.timer` runs the prune daily.

**Both production secrets were rotated on 2026-08-05** and the old admin token
verified rejected (401) while the new one works (200).

### Settings

`SECRET_KEY_FALLBACKS` is read from `DJANGO_SECRET_KEY_FALLBACKS`. Security
headers that work over plain HTTP are on (`SECURE_CONTENT_TYPE_NOSNIFF`,
`X_FRAME_OPTIONS=DENY`, `SECURE_REFERRER_POLICY`, `SESSION_COOKIE_HTTPONLY`).
The TLS-dependent group (`SECURE_SSL_REDIRECT`, secure cookies, HSTS) is gated
behind `DJANGO_SECURE_SSL=1` and **off**, because this deployment serves port 80
only — turning them on without a certificate would redirect-loop the site.

---

## 2. Rate limiting (nginx)

`/etc/nginx/conf.d/kgkg-limits.conf` defines the zones; the site config applies
them per location.

| zone | rate | burst | applies to |
|---|---|---|---|
| `kg_static` | 100 r/s | 300 | `/kg-api/media/`, `/_next/static/` |
| `kg_general` | 30 r/s | 120 | everything else on the frontend |
| `kg_api` | 20 r/s | 100 | `/kg-api/` |
| `kg_auth` | 30 r/min | 10 | login endpoints, `/kg-api/api/invite/` |
| `kg_chat` | 60 r/min | 15 | `/api/chat` (billed per call at Metis) |
| `kg_admin` | 60 r/min | 40 | `/kg-api/api/admin/` |
| `kg_conn` | 60 concurrent | — | per IP |
| `kg_sse` | 8 concurrent | — | the SSE stream only |

Rejections return **429** and are logged at `warn`, which the fail2ban jail
reads.

**Two things that are load-bearing and easy to break:**

1. **The loopback exemption.** `NEXT_PUBLIC_API_BASE` is the *public* URL, so
   every server-side render comes back to nginx from this machine's own
   address. The `geo`/`map` pair at the top of the limits file gives 127.0.0.1,
   ::1 and 103.75.197.155 an empty limit key, which disables the limit. Without
   it, all SSR traffic shares one bucket and the whole site throttles at once.
2. **`proxy_pass` is per-location, not in the shared snippet.** nginx rewrites
   the URI by replacing the matched part of the location with the proxy_pass
   path, so one shared value would mean different things in `location /kg-api/`
   than in `location = /kg-api/api/auth/login/` (the latter would rewrite the
   whole URI to `/`). `snippets/kgkg-backend-proxy.conf` carries **headers
   only**; each location states its own target.

The in-process limiter (`api/ratelimit.py`) stays — it keeps the per-endpoint
semantics. nginx is the volumetric guard that also counts once instead of once
per gunicorn worker.

---

## 3. WAF — ModSecurity 3 + OWASP CRS 3.3.5

`modsecurity on` site-wide, `off` in the two static locations. Rules load from
`/etc/nginx/modsecurity/main.conf`:

```
modsecurity-base.conf   # engine settings (tailored from the shipped file)
crs-setup.conf          # stock
kgkg-before-crs.conf    # paranoia level
<CRS rules>             # 926 rules
kgkg-after-crs.conf     # our exclusions, by rule id
```

Base config changes from the shipped default: `SecRuleEngine On`,
`SecStatusEngine Off` (no phoning home), `SecResponseBodyAccess Off` (manual
pages are served as JSON, which isn't scanned anyway, and this box also runs
bge-m3), audit parts `ABIJDFHZ`, temp/data dirs moved out of `/tmp`.

### Paranoia level 1, deliberately

Normal traffic here is Persian free text and manual paths full of `&`, `/`,
`:`, parentheses and U+2044 — exactly the shapes PL2+ starts calling
suspicious. PL1 catches real injection with a false-positive rate that can
actually run in blocking mode.

### Exclusions, and why each exists

* **920271** (non-printable characters) — removed. Persian query terms and the
  U+2044 fraction slash the parser uses to encode `/` inside section titles are
  all "non-printable" by this rule's definition. The null-byte/control checks
  in 920270 stay on.
* **920350** (numeric IP in Host header) — removed. It fired on **112 of 112**
  legitimate requests during the detection run, because the site is published
  as `http://103.75.197.155/` with no DNS name. At WARNING (3) against a
  threshold of 5 it blocks nothing alone, but it left every ordinary page view
  at 3/5, so any single additional borderline rule would 403 a real user.
  **Re-enable this when the site gets a domain name.**
* **10100/10101/10102** — SQLi/XSS scoring removed from the *named free-text
  arguments only* on search/assist/diagnose, `/api/chat`, and manual `seg`
  paths. A mechanic legitimately types `P0171 or P0174 - select which sensor`.
  These endpoints are login-gated and rate-limited, and the RAG layer uses
  bound parameters. Every other argument on the same request is still
  inspected.
* **10103** — request-body inspection off for admin pipeline/ingest uploads
  (multi-hundred-MB manual ZIPs), which sit behind the most privileged gate on
  the box.

### Procedure used

Deployed in `DetectionOnly`, drove the full site plus attack payloads, read the
audit log, wrote the exclusions above, confirmed **no legitimate request
exceeded the anomaly threshold**, then switched to `On` and re-verified.

Repeat that procedure after any CRS upgrade:

```bash
sed -i 's/^SecRuleEngine .*/SecRuleEngine DetectionOnly/' \
    /etc/nginx/modsecurity/modsecurity-base.conf
nginx -t && systemctl reload nginx && : > /var/log/nginx/modsec_audit.log
# ...drive real traffic, then:
grep -o '\[id "[0-9]*"\].*\[msg "[^"]*"\]' /var/log/nginx/modsec_audit.log \
  | sed -E 's/\[id "([0-9]+)"\].*\[msg "([^"]*)"\].*/\1 \2/' | sort | uniq -c | sort -rn
```

### fail2ban

| jail | reads | trips at | ban |
|---|---|---|---|
| `sshd` | journal | 5 | 2 h |
| `nginx-limit-req` | nginx error.log | 30 / 5 min | 1 h |
| `kgkg-modsecurity` | nginx error.log | 8 / 10 min | 6 h |
| `kgkg-auth` | nginx access.log | 25 × 401 / 30 min | 4 h |

Bans escalate (`bantime.increment`, max 1 week). **`ignoreip` includes
127.0.0.1, ::1 and 103.75.197.155 — the self-entry is mandatory**, since the
Next server calls back into nginx. It also lists **the admin workstation's
IP, which is deliberately not written down here**: this repository is public,
and an address that `ignoreip` exempts from fail2ban is of use only to someone
trying not to be banned. The live value is in
`/etc/fail2ban/jail.local` on the host; review that entry if the office IP
changes.

---

## 4. Error monitoring — self-hosted GlitchTip

`/opt/glitchtip` (docker compose, unit `glitchtip.service`, enabled at boot).
Postgres + Redis + web + worker. Speaks the Sentry wire protocol, so standard
`sentry-sdk` clients work — but nothing leaves the machine, which matters
because error payloads here can carry Persian customer manual content.

**Bound to 127.0.0.1:8010 only.** It is deliberately *not* published through
nginx: this box has no TLS, and putting an error dashboard's login form on
plaintext HTTP would undercut the rest of this work. Reach it over an SSH
tunnel:

```bash
ssh -L 8010:127.0.0.1:8010 root@103.75.197.155
# then open http://127.0.0.1:8010/ and sign in with the GlitchTip admin
# account. Neither the account nor the file holding its password is named
# here, for the same reason as the fail2ban entry above; both are on the host.
```

Publish it properly once 443 exists.

Projects: `kgkg-backend` (id 1), `kgkg-frontend` (id 2). DSNs are in the
respective `.env` files. Retention 30 days; container logs capped at 20 MB × 3.

### Two compatibility traps, both silent

1. **The Python SDK must be pinned to gzip.** sentry-sdk 2.x auto-selects
   Brotli whenever the `brotli` module is importable (it is here,
   transitively), and GlitchTip 4.1.3 cannot decompress it — it answers
   `400 {"detail": "Cannot parse request body"}`, which the SDK logs at DEBUG
   and drops. The app looks instrumented and not one error arrives. Fixed with
   `_experiments={'transport_compression_algo': 'gzip'}` (it is *not* a
   top-level option).
2. **The JS SDK rejects GlitchTip's own DSN format.** Its `DSN_REGEX` matches
   the public key with `\w+`, which excludes the hyphens in GlitchTip's UUID
   keys. GlitchTip resolves the dashless 32-hex form to the same UUID, so the
   frontend DSN uses that.

### What reports

* **Django** — `DjangoIntegration` (unhandled request exceptions) plus
  `LoggingIntegration` at `event_level=ERROR`.
* **Next.js** — `@sentry/node` via `src/instrumentation.ts` (`register()` +
  `onRequestError`). Covers server components, route handlers and `/api/chat`.
  `@sentry/nextjs` was avoided on purpose: it works through a build plugin
  whose Next 16 support is still settling, and the stable instrumentation hook
  needs no plugin. **Browser-side JS is not instrumented** — that needs a
  tunnel route because GlitchTip is loopback-only.

`send_default_pii=False` everywhere, plus a `before_send` scrub on both sides.

> The scrub is **surgical, not a blanket walk of the event**. An earlier
> version ran a recursive scrub over the whole event dict; Sentry events nest
> deeper than the recursion cap, so stack frames came out as the literal string
> `'<max-depth>'` and GlitchTip rejected every event with a 400. Touch only
> message/exception-value/extra/tags/request fields.

### Structured logs

`KG_backend/jsonlog.py` — one JSON object per line, UTC timestamps.

* `/var/log/kgkg/app.jsonl` — everything at `KG_LOG_LEVEL` (default INFO)
* `/var/log/kgkg/error.jsonl` — WARNING and above

Both rotate daily, kept 30 days (`/etc/logrotate.d/kgkg`), written with
`WatchedFileHandler` so rotation needs no restart. Credential-shaped keys and
inline `token=`/`Bearer` values are redacted before anything is written.
`QuietInTests` suppresses output under the test runner, which deliberately
exercises 4xx/5xx paths.

```bash
jq -c 'select(.level=="ERROR")' /var/log/kgkg/error.jsonl | tail -20
```

---

## 5. Verification (2026-08-05)

* Backend suite: **305 tests, all passing** (265 pre-existing + 40 new in
  `api/test_security.py`).
* External probe from a non-exempt IP: **44/44** — security headers, auth,
  content gating, six Persian/RTL false-positive probes, ten attack payloads
  blocked (403), four scanner UAs blocked, rate limiting, SSE, admin gate.
* Whole-site sweep: **39/39** — every frontend route, backend API surface,
  catalog, manual drill-down, search/assist/diagnose in Persian and English,
  SSE, media assets, logout revocation.
* Media images serve (200, `image/png`); admin session tokens authenticate
  through nginx + WAF + rate limiting on all three admin endpoints.

### Known issues found, not fixed

* **`/admin/<anything>` returns 500.** Pre-existing (present in access logs
  hours before this work). The `[brand]/[year]` catch-all swallows unknown
  two-segment paths — `/admin/config` becomes brand=`admin`, year=`config` —
  and `JSON.parse` then chokes on an HTML error response. There is **no
  `not-found.tsx` or `error.tsx` boundary** anywhere in `src/app`. Not an
  information leak (the body is Next's standard production error page, no
  stack, no paths), but it should return 404. GlitchTip now captures it as
  `SyntaxError: Unexpected token '<'`.
* **Orphaned staging process.** PID 467246, a manually-started `next-server`
  from an SSH session 18 days ago, listening on `*:3123` with a copy of the
  Metis API key in its environment. Not reachable externally (ufw allows only
  22/80/443/3389) and not production, but it should be killed.
* **No TLS.** The single largest remaining exposure: admin credentials, session
  tokens and all paid content cross the wire in cleartext. Everything above is
  written to flip on cleanly when 443 exists — `DJANGO_SECURE_SSL=1`, re-enable
  CRS 920350, publish GlitchTip.

## 6. Rollback

Backups from this work: `/root/sec_hardening_bak_1785964985/` (backend sources,
whole `/etc/nginx`, both env files, `db.sqlite3`, and `.next.bak`), plus
`/root/db_premigrate_0017.sqlite3` taken immediately before the token
migration.
