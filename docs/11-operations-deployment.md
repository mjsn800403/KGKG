# 11 — Operations & Deployment

## 11.1 Server layout

Single Ubuntu 24 host `103.75.197.155` (16 cores / 31 GB RAM / 290 GB disk, ~64% used).
Everything lives in `/opt/KGKG` (git working copy = deployed copy). Python venv:
`KG_backend/.venv` (3.12). Node 20.

### systemd units

| Unit | What |
|---|---|
| `kgkg-backend.service` (retired; containers serve now — see 11.3) | gunicorn `KG_backend.wsgi` on `:8000` — 3 gthread workers × 8 threads, `--timeout 300 --max-requests 20000(+jitter)`; env from `.env.prod` + offline-HF vars + `KG_WARMUP=1` |
| `kgkg-frontend.service` (retired; containers serve now — see 11.3) | `npm run start` (Next.js) on `:3000`; env from `kg_frontend/.env.production` |
| `nginx` | Reverse proxy on `:80` (see 11.2) |
| `kgkg-alerts.timer` → service | `manage.py check_alerts` every 5 min (alert sweep + retention pruning) |
| `kgkg-outbox.timer` → service | `manage.py process_outbox` every minute. **Not installed**; unit templates in `ops/outbox/`. See "Notification outbox" below |
| `kgkg-watchdog.timer` → service | `ops/observability/watchdog.py` every 5 min — watches the alert sweep itself and pages by SMS if nobody is watching |
| `kgkg-pipeline.timer` → service | `manage.py pipeline_tick` every 5 min (watchdog / scheduler / autopilot) |
| `kgkg-detect.timer` → service | `manage.py realtime_tick` every 30 s (change detector → events) |
| `kgkg-pipeline-job<id>-a<n>` | Transient units for detached pipeline workers (systemd-run, Nice 15 / CPUWeight 25 / IO idle) |

### Notification outbox

Support SMS/email go through the `NotificationOutbox` table (`api/notifications/`), never straight
to a provider. Rows are sent by `process_outbox` (and an opportunistic thread), retried at
1/5/15/60/240 minutes, then marked `dead` and surfaced as the `notify:dead` alert.

| Variable | Default | Meaning |
|---|---|---|
| `KG_NOTIFY_SMS`, `KG_NOTIFY_EMAIL` | `off` | `off` writes rows as `suppressed` and sends nothing; `dry_run` renders and logs only; `live` contacts the provider. Any other value is `off` |
| `KG_NOTIFY_SMS_MAX_PER_HOUR` | `10` | Live SMS cap; rows over it are deferred 10 minutes, never dropped |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `KG_NOTIFY_FROM_EMAIL` | unset | SMTP settings; email fails closed (`email not configured`) without them |

`sent` means the provider accepted the message, not that it was delivered. Activation order:
install the timer (a person, on the server), set a channel to `dry_run`, review the rows, then
get the owner's explicit approval before `live`.

### Support chat (human-operated)

`api/support_chat/` serves the landing-page and customer conversations with real staff. It has no AI, LLM
or RAG dependency. Defaults below are initial values, changed by environment variable.

| Variable | Default | Meaning |
|---|---|---|
| `KG_SC_POLL`, `KG_SC_SEND`, `KG_SC_SEND_HOUR`, `KG_SC_CONTACT`, `KG_SC_CSAT`, `KG_SC_REOPEN` | `30/60`, `20/60`, `30/3600`, `10/60`, `5/60`, `5/60` | per-thread limits as `count/seconds`; `0/0` switches one off. Poll windows are per gunicorn worker |
| `KG_SC_CREATE_IP`, `KG_SC_BAD_TOKEN_IP`, `KG_SC_STATUS_IP` | `20/600`, `30/60`, `60/60` | per-IP: new threads, FAILED token checks only, status reads |
| `KG_SUPPORT_CHAT_ENABLED` | unset (off) | kill switch. Only `1` turns the public chat on: the API then accepts NEW visitor threads (existing threads and staff replies work either way) and, set for the web server too, the landing/purchase widget is rendered. A person flips it, never a deploy; do not set it before the launch gate (docs/superpowers/plans, G2) |
| `KG_SUPPORT_RBAC` | unset (`off`) | support role enforcement: `off` (today's flat admin model), `audit` (same access, id-only audit row for each request enforcement would deny) or `enforce` (default deny, role and intent scoped, no fallback). Unset, blank and the explicit spellings `off`, `0`, `false`, `no`, `disabled`, `none` mean `off`; **any other unrecognised value (a typo such as `enforc`) is ENFORCED** (fails closed, logged once, 403 `rbac_invalid_mode`, flagged by `support_roles check`), so a mistake can never silently disable RBAC. Move `off` to `audit` to `enforce` only after `manage.py support_roles check --for-enforce` exits 0; rollback is setting it back to `off`. Governs only `/api/admin/support-chat/*` |
| `KG_SUPPORT_OWNERS` | unset | comma-separated administrator usernames who hold `support_owner` regardless of any table (bootstrap and recovery); matched case-insensitively against ACTIVE admins; a misspelling grants nothing, so `support_roles check` reports it. Never a secret |
| `NEXT_PUBLIC_SUPPORT_INBOX_REFRESH_S` | `20` | build-time only: the staff inbox's fallback refresh when the event stream is down. Leave at the default; the E2E stack sets it to 3600 to prove the stream alone delivers |
| `KG_PRIVACY_DRAFT_PAGE` | unset (off) | web server only. `1` serves the DRAFT `/privacy` page (never indexed, banner says not approved); without it the route is a 404 |
| `KG_SUPPORT_REOPEN_DAYS` | `14` | how long a visitor may reopen their own closed thread |
| `KG_SUPPORT_REPLY_TARGET_MINUTES` | unset | published reply target; unset means no promise is shown |
| `KG_SUPPORT_PRESENCE_WINDOW_S` | `60` | how long a staff ping counts as connected |
| `KG_SUPPORT_WAIT_WARN_S`, `KG_SUPPORT_WAIT_CRIT_S` | `300` / `900` | thresholds for `manage.py support_health` (visitors waiting for a human reply); invalid or non-positive values fall back to the defaults; nothing alerts on them yet |
| `KG_SUPPORT_ALERTS` | unset (off) | unanswered-visitor alert on the alert engine (`api/alert_rules.py`): `1` = warning `support:unanswered` (dashboard only, never an SMS), `page` = also a critical `support:unanswered:critical` past `KG_SUPPORT_WAIT_CRIT_S` that the existing delivery SMSes once; any other value is off. Counts only in the alert, never message or contact data |
| `KG_SUPPORT_RETENTION_*_DAYS`, `KG_SUPPORT_RETENTION_ENABLED` | proposals / unset | `purge_support_chat` reports against proposed periods; deletion needs `ENABLED=1` and `--apply`, and no policy is approved yet |

Chat routes are excluded from `AuditLog` request bodies (`api/audit.py` skip list); staff actions are
audited by id only. Backups keep deleted data until their own retention expires.

### Environment files

`KG_backend/.env.prod`: `DJANGO_SECRET_KEY` (required — refuses to boot without),
`DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CORS_ORIGINS`/`_ALLOW_ALL`,
`KG_ADMIN_TOKEN` (static ops admin token), `KG_TRUST_PROXY=1` (per-IP rate limiting behind
nginx). Optional knobs: `KG_ALERT_*` thresholds, `KG_RL_*` rate rules, `KG_METRICS_FLUSH_S`,
`KG_CARDB_POOL`, `KG_INVITE_EMAIL` (invite e-mail off by default — no SMTP),
`KG_FRONTEND_BASE_URL` (invite-link base).

`kg_frontend/.env.production`: runtime settings and secrets for the frontend container (`NEXT_PUBLIC_API_BASE` is not here any more: it is the
build argument of `ops/docker/frontend.Dockerfile`, default `/kg-api`; the older absolute `http://<ip>/kg-api` value is historical), `BACKEND_URL=http://127.0.0.1:8000` (SSR + chat), `METIS_API_KEY`,
`METIS_BOT_ID` (paid LLM — server-side only).

## 11.2 nginx

Config: `/etc/nginx/sites-enabled/kgkg`, tracked in git as `ops/nginx/kgkg.conf`.
Backups belong in `/etc/nginx/config-backups/`, **never** in `sites-enabled/` —
anything left there is included by nginx and breaks every reload (it did, on
2026-10-27).

Public server, `:80` and `:443` (Cloudflare origin certificates in
`/etc/nginx/cloudflare/`): gzip for JSON/text; `^~ /kg-api/media/` aliases the
static warehouse (30d immutable; `www-data` needs read access on new car dirs);
`= /kg-api/api/events/stream/` is an unbuffered SSE proxy (3600s read timeout);
`^~ /grafana/` is admitted only with a valid admin ticket cookie
(`api/grafanaauth.py`) and then gets `X-WEBAUTH-USER` set server-side;
`/kg-api/` proxies to `127.0.0.1:8000`; `/` proxies to `127.0.0.1:3000`.

Two things exist only for monitoring:

- `= /kg-api/api/metrics/` is **denied outright**. Exact match, so it beats the
  `/kg-api/` prefix: application internals are not something the internet gets
  to ask for, token or no token.
- A second server on `:8081` serves exactly one location, `= /kg-metrics`,
  proxied to `/api/metrics/`, allow-listed to `172.19.0.0/16` and loopback.
  This exists because ufw admits `80/443` only from Cloudflare ranges — the
  right posture for an origin behind a CDN, and not something to widen for a
  scrape. ufw admits `8081` from the docker bridge alone. Three independent
  locks: firewall scope, nginx allow-list, bearer token.

  It deliberately does **not** include `snippets/kgkg-backend-proxy.conf`: that
  snippet sets `Host $host`, a second `proxy_set_header` appends rather than
  replaces, and Django then sees two Host values and answers 400.

## 11.3 Delivery: CI, staging, promotion

**Production is never promoted without a person.** No timer, cron or CI path
can do it. That is enforced on this host, by which command a key is pinned to,
not by a setting in GitHub.

### The path a change takes

1. **Work on branch `work`**, in the `/opt/KGKG_work` worktree or on a laptop.
   Production (`/opt/KGKG`) is never edited by hand; `deploy.sh` refuses a
   dirty live tree and only fast-forwards.
2. **Push.** `.github/workflows/ci.yml` runs on every branch: the backend suite
   with a coverage ratchet (`ops/deploy/coverage_min`), frontend lint (warning
   ratchet in `ops/deploy/lint_max_warnings`) and production build, both
   production images built and booted, and the security gates — shellcheck,
   hadolint, gitleaks, pip-audit, npm audit, and a trivy scan of both images.
   Policy and the exception files: `ops/security/README.md`.
3. **Staging, automatically.** On a push to `work` with everything green, the
   `stage` job asks this server to stage that exact commit. The server runs
   `ops/deploy/deploy.sh --staging <sha>`: gate in a throwaway worktree with a
   scrubbed environment (security scans first — bandit, pip-audit, npm audit via
   `ops/security/scan.sh`, the same as CI — then tests, lint, build), build both images, run them on `:8110`/`:3107` against
   a **sanitized copy** of the production database, migrate it, and smoke the
   signed-in paths with a QA token minted in the copy. Production is untouched.
   The result is recorded in `/opt/KGKG_release/staging.env`.

   The signed-in smoke includes `ops/deploy/smoke_fleet.py` (read-only GETs):
   for the vehicles the QA account is granted, the `/api/auth/fleet/` flags
   `has_manual` / `has_parts` must agree with the manual and parts endpoints,
   and a parts catalog must be walkable to a leaf with part rows. It sees only
   what that account is granted, so a category with no vehicle prints `SKIP`
   (the check did not run, it did not pass); `KG_SMOKE_STRICT=1` fails the run
   on such a skip. Staging shares the production `kgkg_vec` and `_parts`, so
   these checks are real-data evidence, and they prove the flags and endpoints,
   not that the chip renders. Its own tests: `smoke_fleet.py --selftest`.
4. **Promotion, by hand:**

   ```bash
   kgkg-promote <sha>     # or bare, to promote whatever CI last staged
   kgkg-promote --status  # live release, last staged, what would change
   ```

   It refuses a commit with no passing staging record, or one staged more than
   72h ago, and a commit with no passing **full** browser E2E run recorded by
   `qa/run_e2e.sh` (`/opt/KGKG_release/e2e/<sha>.env`, also 72h), unless you
   type a longer deliberate phrase (`promote <sha> without staging|e2e|staging
   and e2e`); every such override is appended to
   `/opt/KGKG_release/promote-overrides.log`. It prints the commits
   and files to apply, whether migrations are involved and whether the
   dependency lock changed, then requires the word `promote`. There is no
   `--yes`.

   `deploy.sh` then re-runs the gate and staging on that commit before touching
   production: CI's result is evidence, not permission.

5. **nginx config is part of the release.** `ops/nginx/kgkg.conf`,
   `kgkg-limits.conf` and `kgkg-mediaauth.conf` are validated against the
   running nginx *before* the gate (a bad config aborts with production
   untouched) and installed *after* the container swap, so the config pairs
   with the code now serving. A config nginx rejects is restored and the
   release rolls back. This exists because the media-gate fix needs both
   halves — the normalized path check in `api/mediaauth.py` and the normalized
   cache key in nginx — and a security fix must not depend on someone
   remembering a manual step. Backups go to `/etc/nginx/config-backups/`.

5. **Promote itself:** DB backup → fast-forward → migrate in the new image →
   the new backend container starts *beside* the old one on `:8000`
   (SO_REUSEPORT) and the old one stops only once the new one is healthy, so
   there is no gap; the frontend is a stop/start of about a second. Then smoke,
   including the reverse-proxy checks. Any failure rolls back to the previous
   images automatically. Migrations are **not** reversed — keep them additive;
   the pre-deploy DB backup is the way back.

### Keys and privilege

| Forced command | Role | Verbs |
|---|---|---|
| `/usr/local/bin/kg-ci-gate` | `ci` | `stage`, `status` |
| `/usr/local/bin/kg-deploy-gate` | `operator` | `stage`, `status`, `deploy` |

The key in the repository's `DEPLOY_SSH_KEY` secret is pinned to `kg-ci-gate`.
It **cannot** promote: the role has no `deploy` verb. A leaked CI secret buys a
staging run. Both mutating verbs accept only a 40-hex commit already on
`origin/work`, hold `flock` so two runs cannot interleave, and execute as a
transient systemd unit so a dropped SSH connection cannot kill a deploy
half-way. The matrix is tested: `ops/deploy/test_gate_roles.sh`.

**How GitHub reaches this server, today (checked 2026-10-29 18:30 UTC):**
**direct SSH to the public port**, not the tunnel described below. On the host
`systemctl is-active cloudflared` answers `inactive` and the binary is not
installed; `ufw status` admits `22/tcp` from Anywhere; and the `stage` job of
CI run 40907083135 printed `direct SSH: not needed`, which is the line
`ci_ssh.sh` emits when `~/.ssh/kgkg-target` does not say `TRANSPORT=cloudflare`.
This paragraph exists because the paragraphs after it described the tunnel in
the present tense for two days while it was not running, and a document that is
wrong about the thing an auditor can check in one command costs more
credibility than the configuration gap itself.

What protects the open port in the tunnel's absence: sshd accepts keys only
(`passwordauthentication no`, `permitrootlogin without-password`, both read
back from `sshd -T`), and `fail2ban` is active with an `sshd` jail among four.
Roughly 430 failed authentication attempts arrive per day and none can succeed
without a key. The exposure that was real — `3389/tcp` open to Anywhere with
`xrdp` listening behind it, and no recorded human session ever using it — was
closed on 2026-10-29 (`ufw delete allow 3389/tcp`; the rule files are backed up
at `/root/ufw-user*.rules.bak-20261029-183306`). `xrdp` is still installed and
enabled, so removing the service itself is still worth doing.

**The intended design, not yet activated:** a Cloudflare Tunnel. The
`cloudflared` connector here dials out to Cloudflare; the runner comes in with
`cloudflared access ssh` and a Cloudflare Access service token (an Access
application with a single *Service Auth* policy guards the hostname), lands on
sshd at `localhost:22` and is pinned to `kg-ci-gate` as above. Port 22 does not
have to be open to the internet. Three locks in a row: the Access token, the
SSH key, the forced command.

Setting it up is four steps in the Cloudflare dashboard and one command, as
root: `bash /opt/KGKG/ops/deploy/setup_ci_access.sh --tunnel <hostname>`
(`ops/deploy/README.md` has both, and the three lines that run it from
`origin/work` before it is in the live release). It creates the dedicated key
`/root/.ssh/kgkg-github-ci`, pins it to `kg-ci-gate` with `restrict`, installs
the connector, then logs in through Cloudflare back to this machine exactly as
CI will, with the host key pinned, and checks that Access refuses requests
without the token. It sets the secrets with `gh` or prints them to paste.
Re-running it is safe; `--rotate` replaces the key. Without `--tunnel` it sets
up direct SSH to the public address instead (port 22 open, password logins off).
On the runner, `ops/deploy/ci_ssh.sh` validates the secrets and names the fix
for each failure (wrong or expired Access token, a policy that is not Service
Auth, connector down, wrong key, stale host key, a key that could promote);
`ops/deploy/test_ci_ssh.sh` tests it. Until 2026-10-29 none of these secrets had
ever been set, so the `stage` job had never reached the server.

`.github/workflows/deploy.yml` used to promote automatically on green CI, held
back only by a GitHub environment having reviewers configured. It was deleted
from `work` on 2026-10-27. It is a `workflow_run` workflow, and GitHub runs
those from the **default branch** (`main`), so it keeps firing after every CI
run on `work` until that deletion is merged into `main`.

### Staging data

`ops/deploy/sanitize_staging_db.py` rewrites the copy before anything is served
from it: credential tables emptied, password hashes replaced with an unusable
sentinel, phone numbers replaced by deterministic format-preserving fakes,
e-mails pointed at `.invalid`, audit IPs masked to the `/24`. Row counts,
foreign keys, grants and vehicle data are kept — staging has to stay
representative. Support chat (#79): `contact_phone` and `contact_email` are
masked like the others, `contact_name` becomes `Staging Visitor`, message
bodies become `[sanitized message, N chars]`, the referrer is cut to its
origin, the visitor token hash is made unusable; `source_page` (our own path)
is kept. Empty values stay empty.

It fails closed: staging (`deploy.sh`) and the QA stack (`qa/stack.sh`) pass
`--strict-audit`, so a table carrying an identifying column the script does not
handle fails the build instead of printing a warning (add it to
`MASK_COLUMNS`). After rewriting, every masked column is re-checked and any
surviving value fails the run, printing counts only. `api/test_sanitizer_coverage.py`
walks the Django models in CI, so a new phone/e-mail column fails before it
reaches a copy.

### Other deploy verbs

```bash
ops/deploy/deploy.sh --status           # what is live, and the previous release
ops/deploy/deploy.sh --rollback         # back to the previous release
ops/deploy/deploy.sh --reload          # restart the live release, no gap
                                        # (picks up .env.prod changes)
ops/deploy/deploy.sh --staging <ref>    # stage without promoting
```

Logs: `/opt/KGKG_release/logs/`. DB backups: `/opt/KGKG_release/db-backups/`
(last three). Release state: `/opt/KGKG_release/state.env`. Every promote also
tags `deploy-<ts>` and pushes it.

## 11.4 Data-processing pipeline (admin-operated)

Admin panel → «پردازش داده‌ها» (`/api/admin/pipeline/`). One button runs every pending step:
catalog sync → RAG ingest/embed/graph → per-car diag → audit refresh, with live per-stage
progress, observed-throughput ETA, schedule/resume/cancel, and an autopilot
(`PipelineSettings.auto_enabled`) that starts processing new data when 1-min load per core
< threshold (default 0.55).

Guarantees: detached worker (survives deploys/browser close; serving outranks it on
CPU/IO), per-stage incremental & kill-safe (embed commits in windows; `vec_blobs` always a
contiguous prefix), single-flight (atomic DB claim + /proc scan vs shell-launched builds),
watchdog resume (heartbeat + pid liveness, bounded attempts), progress computed from
artifacts (truthful after crashes).

**Adding a vehicle end-to-end:** drop `<car>.db` into `Database_warehouse/` + images dir
into `static_warehouse/<car>/` (ensure www-data read) → pipeline picks it up (auto mode) or
admin presses start → done. `sync_car_catalog` alone registers the row if you only need
browsing before the index catches up.

## 11.5 Monitoring, alerting, data quality

### What watches what

| Layer | Where | Covers |
|---|---|---|
| Host and containers | Prometheus + node-exporter + cAdvisor | CPU, memory, disk, NIC, per-container state and restarts |
| Uptime and TLS | blackbox-exporter, every 60s | the site, the API health endpoint, and the two paid upstreams (Metis, the SMS provider); TLS expiry |
| Application | `GET /api/metrics/` (`api/metrics_exposition.py`), job `kgkg_app` | requests, 4xx/5xx and mean/worst latency per route group, open alerts by severity, RAG index and DB size, data-quality results, pipeline jobs, live release sha |
| Logs | Alloy → Loki | backend, nginx and journal, searchable in Grafana |
| Errors | GlitchTip (Sentry-compatible), `127.0.0.1:8010` | Django and Next exceptions with stack traces |
| Business | `ops/observability/bizsnap.py` → sqlite → Grafana | signups, purchases, usage |
| Alerting | `manage.py check_alerts`, every 5 min | disk, memory, DB liveness, per-endpoint 5xx and latency, login brute force, admin-auth failures, SMS failures, AI degradation and cost, data-quality regressions, container restarts, probe failures, TLS expiry → deduplicated `SystemAlert` rows + **SMS** to `KG_ALERT_PHONES` |
| The alerting itself | `ops/observability/watchdog.py`, every 5 min | that the engine is still running at all |

The alert engine reads Prometheus for the infrastructure rules
(`api/alert_rules.py`, `_infra`), and it is deliberately smarter than a
threshold: a probe must fail for `KG_ALERT_PROBE_DOWN_MIN` minutes before it
pages, nearly-all-probes-down is treated as the server's own network rather
than a service outage, and a public-path failure while the backend answers on
loopback is a warning about DNS, not a page about the backend. That distinction
was learnt on 2026-10-22. Thresholds are env-tunable (`KG_ALERT_*`) so they can
move without a deploy.

### The watchdog

Nothing watched the engine before 2026-10-27: if `kgkg-alerts.timer` stalled or
its service failed every run, the result was silence, and silence is what a
healthy system looks like.

`ops/observability/watchdog.py` (`kgkg-watchdog.timer`) checks the paging path —
timer active, last sweep recent and exit 0, Prometheus answering — plus the
services (backend health, production containers, disk). It pages **only** when
the paging path is broken, carrying the service state in the same message,
because if the engine is down those are the only facts anyone will get. While
the engine is healthy it stays quiet and lets the engine own every alert.

It shares nothing with the application: standard library only, no Django, no
virtualenv, no database. Credentials come from `.env.prod`. Messages are
scrubbed of links because the SMS provider refuses a body containing one.
Every check is also written to `/var/lib/node-exporter-textfile/` and scraped,
so Grafana shows the state continuously without adding noise.

### Dashboards

`https://kgtechvault.com/grafana/` (admin ticket required), provisioned from
`ops/observability/provisioning/dashboards/json/`:

- **KGKG — Service health & delivery** — is anybody watching, what is live,
  traffic and errors per route group, guarded error ratio, latency, scrape
  health
- **KGKG — Server & containers** — host and container resources
- **KGKG — Logs overview** — Loki
- **KGKG — Business** — the bizsnap snapshot

Admin «پایش سیستم» remains the in-product view, and «سلامت داده‌ها» runs the
data-quality audit (`manage.py audit_vehicles [--fix]`): completeness,
duplicates by content fingerprint, catalog/static/RAG/diag backlog, integrity.
Fix mode merges duplicates and quarantines — it never deletes.

Retention: Prometheus 30d; events ~20k rows; visitor rows ~90 days; alert
history pruned by `check_alerts`.

## 11.6 Backups & recovery

**There is an hourly off-host backup, and it was verified on 2026-10-27.**

An internal company server (`81.12.110.58`) connects once an hour through a
forced-command key (`/usr/local/bin/kg-sync-gate`, which accepts only an rsync
sender and the snapshot script — no shell) and:

1. runs `/root/kgkg_snapshot.py`, which builds `/root/backup_snapshot/` from
   the state that cannot be rebuilt from the source ZIPs — `db.sqlite3`,
   `terms.db`, `translation.db` (all three via the SQLite **online backup
   API**, because these run in WAL mode and a byte-copy taken mid-transaction
   is torn), plus the terminology export, the evaluation gold sets, the nginx
   config and the backend/frontend source;
2. pulls that snapshot (~650 MB, of which `db.sqlite3` is ~600 MB);
3. pulls `/root/downloads/` (~13 GB of source ZIPs) and `/var/log/nginx/`.

Secrets are deliberately excluded: no `.env.prod`, no Cloudflare origin key.
That is the right call for a copy leaving the host, and it means a bare-metal
rebuild needs those values from wherever they are kept — they are not in any
backup by design.

What this covers, and what it does not. The 2026-10-27 verification covered the application database and the small
side databases. It did **not** establish that vehicle content can be recovered. Manual content of 222 cars lives only in
PostgreSQL database `kgkg_vec` (about 58 GB): `cardb_pg.adopt()` deletes a car's SQLite file once it is loaded, the deploy-time
`pg_dump` covers database `kgkg` only, and no backup of `kgkg_vec` was found in the hourly snapshot (observed 2026-11-03, sessions;
re-verify). The 15 parts-only catalogs and the static images are on the same disk with no copy found. The source ZIPs are copied
off-host hourly, but whether every car can be rebuilt from them, and how long that takes, has **not** been demonstrated, so
this section makes no claim that the warehouse is rebuildable. The RAG index (`_rag/`) is derived from the content stores and
is the only part treated as disposable. See [23-data-layer.md](23-data-layer.md) and risk R1 in
[27-open-risks-and-decisions.md](27-open-risks-and-decisions.md).

Also **[U]**: the snapshot description above names `db.sqlite3`, the former production database (frozen 2026-10-29). Which
PostgreSQL databases the hourly snapshot now includes was not re-inspected; a session reported that only `kgkg` (133 MB) is
dumped.

On top of that, the hosting provider takes a full server backup monthly (5th).
That bounds a total-host-loss scenario; the hourly snapshot is what bounds
everyday loss to an hour.

Local, same-disk copies also exist and are the fastest way back from a bad
deploy rather than a disaster: `/opt/KGKG_release/db-backups/` (the last three,
taken before each promote) and timestamped `db.sqlite3.bak_*` beside the
database.

### Verifying it (do this occasionally — a backup nobody restores is a guess)

```bash
# integrity + row counts of the snapshot against live, read-only
python3 -I /root/verify_restore.py
```

The 2026-10-27 run: `quick_check ok`, and `api_portaluser`, `api_company`,
`api_companycaraccess`, `api_usercaraccess`, `api_activitylog`, `api_chatlog`
and `api_systemalert` all matched the live database exactly, with only
`api_trafficstat` 7 rows behind — the expected drift for an hourly snapshot.

### What is NOT guaranteed from this host

- **Retention on the far side.** If the internal server mirrors rather than
  keeping versions, a corruption here propagates within the hour and the good
  copy is gone. The monthly provider backup is then the only older restore
  point. Worth confirming on that server, not here.
- **That the pull is still happening.** `kgkg_watchdog_check{check="backup_snapshot"}`
  covers this: it reads `/root/backup_snapshot/SNAPSHOT_AT` and goes to 0 when
  the snapshot is older than `KG_WATCHDOG_SNAPSHOT_MAX_H` (default 6 hours).

## 11.7 Operational runbook snippets

```bash
# what is live, what was staged
ops/deploy/deploy.sh --status
kgkg-promote --status

# status (the serving pair are containers, not systemd units)
docker ps --filter label=kgkg.env=prod
journalctl -t kgkg-backend -n 100 --no-pager
systemctl status nginx kgkg-hostjobs

# is the alerting alive? (dry run never sends an SMS)
python3 -I /opt/KGKG/ops/observability/watchdog.py --dry-run
systemctl list-timers 'kgkg-*' --no-pager

# the smoke suite, read-only, safe against production
KG_SMOKE_NGINX=http://127.0.0.1 ops/deploy/smoke.sh \
  http://127.0.0.1:8000 http://127.0.0.1:3000

# the metrics Prometheus sees
curl -s -H "Authorization: Bearer $(cat /opt/observability/metrics_token)" \
  http://127.0.0.1:8081/kg-metrics | head -40

# django shell with prod env
cd /opt/KGKG/KG_backend && set -a && . ./.env.prod && set +a && .venv/bin/python manage.py shell

# tests (staging copy, never prod DB)
KG_RL_DISABLE=1 .venv/bin/python manage.py test api

# pipeline status from CLI
curl -s -H "Authorization: Bearer $KG_ADMIN_TOKEN" http://127.0.0.1:8000/api/admin/pipeline/ | python3 -m json.tool

# who is logged in / recent activity
.venv/bin/python manage.py shell -c "from api.models import ActivityLog; [print(a.user.username, a.action, a.created_at) for a in ActivityLog.objects.all()[:20]]"
```

### Known operational gotchas (cost real time — respect them)

1. `*.md` is gitignored globally → `git add -f` for docs.
2. Node titles/paths can contain `/` encoded as U+2044 in `path` columns.
3. Pooled car-DB connections must never be closed by views.
4. `vec_blobs` counting requires `vec_blobs_rowids`.
5. Staging uses :8110/:3107. :8100 is a different project on this host — not ours.
6. TLS is live (Cloudflare origin certificates); ufw admits 80/443 only from
   Cloudflare ranges, so do not expect to reach the site by IP.
7. WeasyPrint fonts: only the bundled full Vazirmatn TTFs render correctly.
8. `NEXT_PUBLIC_API_BASE` is baked at build time — rebuild after env change.
9. An idle `paused` ProcessingJob row (#1) is historical — job #2 completed the fleet
   backfill; don't resume #1 blindly.
10. nginx config backups go in `/etc/nginx/config-backups/`, never in
    `sites-enabled/` — nginx includes everything there and the reload fails.
11. A gitleaks scan in git mode exits 0 when it cannot read the repository, so
    CI scans the filesystem and asserts a report was written. Do not "simplify"
    it back.
12. `torch` pins `setuptools<82`, which caps two advisories we therefore carry
    deliberately (`ops/security/pip-audit-ignore.txt`). The torch upgrade needs
    a planned re-embed window, not a lock bump.
13. SMS bodies have a contract the provider enforces silently: a Persian body
    without the trailing opt-out line is refused (Value 11), and anything that
    looks like a link or an @domain is refused (Value 14) — a dotted number
    such as an IP or a percentage counts. Use the same envelope as
    api/alert_rules.deliver / ops/observability/watchdog.py sms_body(), and
    check the returned Value: a long record id means sent, anything else means
    nobody was paged.
