# 11 — Operations & Deployment

## 11.1 Server layout

Single Ubuntu 24 host `103.75.197.155` (16 cores / 31 GB RAM / 290 GB disk, ~64% used).
Everything lives in `/opt/KGKG` (git working copy = deployed copy). Python venv:
`KG_backend/.venv` (3.12). Node 20.

### systemd units

| Unit | What |
|---|---|
| `kgkg-backend.service` (retired; containers serve now — see 11.3) | gunicorn `KG_backend.wsgi` on `:8000` — 3 gthread workers × 8 threads, `--timeout 300 --max-requests 2000(+jitter)`; env from `.env.prod` + offline-HF vars + `KG_WARMUP=1` |
| `kgkg-frontend.service` (retired; containers serve now — see 11.3) | `npm run start` (Next.js) on `:3000`; env from `kg_frontend/.env.production` |
| `nginx` | Reverse proxy on `:80` (see 11.2) |
| `kgkg-alerts.timer` → service | `manage.py check_alerts` every 5 min (alert sweep + retention pruning) |
| `kgkg-watchdog.timer` → service | `ops/observability/watchdog.py` every 5 min — watches the alert sweep itself and pages by SMS if nobody is watching |
| `kgkg-pipeline.timer` → service | `manage.py pipeline_tick` every 5 min (watchdog / scheduler / autopilot) |
| `kgkg-detect.timer` → service | `manage.py realtime_tick` every 30 s (change detector → events) |
| `kgkg-pipeline-job<id>-a<n>` | Transient units for detached pipeline workers (systemd-run, Nice 15 / CPUWeight 25 / IO idle) |

### Environment files

`KG_backend/.env.prod`: `DJANGO_SECRET_KEY` (required — refuses to boot without),
`DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CORS_ORIGINS`/`_ALLOW_ALL`,
`KG_ADMIN_TOKEN` (static ops admin token), `KG_TRUST_PROXY=1` (per-IP rate limiting behind
nginx). Optional knobs: `KG_ALERT_*` thresholds, `KG_RL_*` rate rules, `KG_METRICS_FLUSH_S`,
`KG_CARDB_POOL`, `KG_INVITE_EMAIL` (invite e-mail off by default — no SMTP),
`KG_FRONTEND_BASE_URL` (invite-link base).

`kg_frontend/.env.production`: `NEXT_PUBLIC_API_BASE=http://103.75.197.155/kg-api`
(baked at build), `BACKEND_URL=http://127.0.0.1:8000` (SSR + chat), `METIS_API_KEY`,
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
   scrubbed environment, build both images, run them on `:8110`/`:3107` against
   a **sanitized copy** of the production database, migrate it, and smoke the
   signed-in paths with a QA token minted in the copy. Production is untouched.
   The result is recorded in `/opt/KGKG_release/staging.env`.
4. **Promotion, by hand:**

   ```bash
   kgkg-promote <sha>     # or bare, to promote whatever CI last staged
   kgkg-promote --status  # live release, last staged, what would change
   ```

   It refuses a commit with no passing staging record, or one staged more than
   72h ago, unless you type a longer deliberate phrase. It prints the commits
   and files to apply, whether migrations are involved and whether the
   dependency lock changed, then requires the word `promote`. There is no
   `--yes`.

   `deploy.sh` then re-runs the gate and staging on that commit before touching
   production: CI's result is evidence, not permission.

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

`.github/workflows/deploy.yml` used to promote automatically on green CI, held
back only by a GitHub environment having reviewers configured. It was deleted
on 2026-10-27 — a deleted workflow cannot fire.

### Staging data

`ops/deploy/sanitize_staging_db.py` rewrites the copy before anything is served
from it: credential tables emptied, password hashes replaced with an unusable
sentinel, phone numbers replaced by deterministic format-preserving fakes,
e-mails pointed at `.invalid`, audit IPs masked to the `/24`. Row counts,
foreign keys, grants and vehicle data are kept — staging has to stay
representative. Any table carrying an identifying column that the script does
not handle is reported; add it to `MASK_COLUMNS`.

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

What exists, and it is on one disk:

- **Before every promote:** a consistent copy of `db.sqlite3` via the SQLite
  online backup API into `/opt/KGKG_release/db-backups/` (last three kept).
  This is the way back from a migration, since migrations are forward-only.
- **Before migrations and remediation:** timestamped `db.sqlite3.bak_*` beside
  the database.
- **Code:** every release is a git commit, tagged `deploy-<ts>` and pushed, and
  the previous release's images stay on the host for `--rollback`.
- **Warehouse and `_rag` (21 GB):** copied only before targeted operations.

**There is still no off-host backup.** A disk or host loss takes the main
database and the warehouse with it; the RAG tier is rebuildable, those two are
not. This is the largest remaining operational risk and it is open
deliberately — it needs a decision about where the copies go. Everything else
in this doc has been automated; this is the one that has not.

Recovery, in the order worth trying: `ops/deploy/deploy.sh --rollback` (code
and containers, seconds); restore a `db-backups/` snapshot and
`--reload`; rebuild the RAG tier from the warehouse (`run_rag_build.sh`).

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
