# 11 — Operations & Deployment

## 11.1 Server layout

Single Ubuntu 24 host `103.75.197.155` (16 cores / 31 GB RAM / 290 GB disk, ~64% used).
Everything lives in `/opt/KGKG` (git working copy = deployed copy). Python venv:
`KG_backend/.venv` (3.12). Node 20.

### systemd units

| Unit | What |
|---|---|
| `kgkg-backend.service` | gunicorn `KG_backend.wsgi` on `:8000` — 3 gthread workers × 8 threads, `--timeout 300 --max-requests 2000(+jitter)`; env from `.env.prod` + offline-HF vars + `KG_WARMUP=1` |
| `kgkg-frontend.service` | `npm run start` (Next.js) on `:3000`; env from `kg_frontend/.env.production` |
| `nginx` | Reverse proxy on `:80` (see 11.2) |
| `kgkg-alerts.timer` → service | `manage.py check_alerts` every 5 min (alert sweep + retention pruning) |
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

One default server on :80: gzip for JSON/text; `location ^~ /kg-api/media/` → alias to
`static_warehouse/` (30d immutable; www-data needs read access on new car dirs);
`location = /kg-api/api/events/stream/` → unbuffered SSE proxy (3600s read timeout);
`location /kg-api/` → `127.0.0.1:8000/`; `location /` → `127.0.0.1:3000` (with upgrade
headers). Config: `/etc/nginx/sites-enabled/` (single site). **No TLS yet** — see doc 12.

## 11.3 Deploy process (the pattern that works)

There is no CI/CD; deploys are rsync/edit-in-place + restart, and **prod-mutating steps are
gated** (get explicit user/owner approval; the automation classifier blocks them otherwise).

1. **Stage:** copy code to `/root/kgtest` (rsync `KG_backend/api/` + frontend src; symlink
   per-car DBs; `_rag` may need a real copy; `node_modules` must be `cp -al` hardlinks —
   Turbopack rejects out-of-root symlinks). Run backend suite
   (`KG_RL_DISABLE=1 manage.py test api` with env sourced) + `npm run build`.
2. **Backup:** `cp db.sqlite3 db.sqlite3.bak_<tag>_$(date +%s)` (online is fine in WAL) +
   tar the code dirs being replaced (`/root/*_bak_*` convention).
3. **Apply:** rsync staged code into `/opt/KGKG`, `manage.py migrate` if needed, rebuild
   frontend (`npm run build` in `/opt/KGKG/kg_frontend`), then restart:
   `systemctl restart kgkg-backend kgkg-frontend` (+ `nginx -t && systemctl reload nginx`
   only if config changed).
4. **Verify live:** `/api/health/`, a login, one gated content fetch, one SSE ready-frame,
   and whatever the change touched. Reference E2E battery from 2026-07-11 lives in that
   session's scripts (22 public checks).
5. **Git:** commit on `rag-db-improvements`, push to `origin`
   (`github.com/mjsn800403/KGKG`). Remember: docs need `git add -f docs/` (`*.md` is
   gitignored); never commit `db.sqlite3`, warehouses, or `.env*`.

Rollback = restore the backup tar + previous db backup, restart services.

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

- **Metrics:** middleware → hourly `TrafficStat` + exact daily uniques (`VisitorSeen`,
  salted irreversible hashes). Admin «پایش سیستم» shows resources, DB/RAG status, traffic
  series, per-endpoint latency/error, feature usage. Public probe: `/api/health/`.
- **Alerts:** `check_alerts` (5 min) evaluates disk (warn 85%/crit 93%), memory (92%),
  DB liveness, per-endpoint 5xx rate (5% over ≥50 req), latency (5s), data-quality
  regressions → deduplicated `SystemAlert` rows, auto-resolve. Thresholds via `KG_ALERT_*`.
  Alerts appear on the admin dashboard (+ events). No external paging yet.
- **Data quality:** admin «سلامت داده‌ها» or `manage.py audit_vehicles [--fix]`. Audits
  completeness (canonical sections, powertrain-aware), duplicates (content fingerprint),
  catalog/static/RAG/diag backlog, integrity. Fix mode merges duplicates (grants+activity
  repointed) and quarantines — never deletes. Current status: 38/38 complete; quarantine
  holds 5 partial bZ4X/RAV4 crawls + 1 true duplicate.
- **Retention:** events ~20k rows; visitor rows ~90 days; alert history pruned by
  `check_alerts`.

## 11.6 Backups & recovery

Ad-hoc but consistent conventions: timestamped `db.sqlite3.bak_*` next to the DB before
every migration/remediation; code tars under `/root/*_bak_*`; deploy scripts write
`/root/deploy_bak_<ts>/`. The warehouse + `_rag` are large (21 GB) — backed up only before
targeted operations (e.g. `/root/linkfix_bak/`). **No off-host backup exists — single-disk
risk** (doc 12 limitation). The RAG tier is rebuildable; the warehouse and `db.sqlite3` are
not.

## 11.7 Operational runbook snippets

```bash
# status
systemctl status kgkg-backend kgkg-frontend nginx
journalctl -u kgkg-backend -n 100 --no-pager

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
5. Stale QA gunicorn may occupy staging ports (e.g. :8100) — pick another.
6. Admin creds cross the wire in cleartext (HTTP) until TLS lands.
7. WeasyPrint fonts: only the bundled full Vazirmatn TTFs render correctly.
8. `NEXT_PUBLIC_API_BASE` is baked at build time — rebuild after env change.
9. An idle `paused` ProcessingJob row (#1) is historical — job #2 completed the fleet
   backfill; don't resume #1 blindly.
