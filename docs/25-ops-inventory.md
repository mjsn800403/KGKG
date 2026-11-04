# 25 — Operations inventory: host, units, containers, directories

Complements `11-operations-deployment.md` (how deploys and alerts work) and `20-runbooks.md` (what to do when it breaks).
This file is a **point-in-time inventory** of what exists, tagged by evidence. It is deliberately a list, so that
a difference from reality is easy to spot. Re-observe before relying on it. The repo-derived part is
generated: see `docs/generated/inventory.md` (systemd units shipped in `ops/`, every `ops/` file, CI jobs).

## 25.1 Host

One Ubuntu 24 server (`103.75.197.155`, hostname `srv8684671457`) runs production, staging, QA and the observability
stack. [C doc 11; D GitHub #25]. Disk `/` 290 GB, 75% used (216 GB) on 2026-11-04 [S].

## 25.2 Production state observed 2026-11-04 06:00 UTC [S, read-only]

- `/opt/KGKG` at `8a380f6` = `origin/work`; two untracked files `KG_backend/RECONSTRUCTED-ACTIVITY.md` and
  `KG_backend/pgcut-marks.json` (see risk R6). The earlier untracked docs 16-18 were moved to
  `/root/prod-untracked-backup/` on 2026-11-03 and now live in the repo. [D Slack]
- Containers: `kgkg-backend-<ts>` and `kgkg-frontend-<ts>` (healthy), observability stack (Prometheus, node-exporter,
  blackbox, Grafana, cAdvisor, Loki, Alloy), GlitchTip (web, worker, Postgres, Redis), Umami (app, Postgres).
- Host services running: Docker, nginx, PostgreSQL 16 (`postgresql@16-main`), `kgkg-hostjobs.service`
  (host-job bridge for the backend container, `ops/hostjobs/`), and, during a staging run, a transient
  `kgkg-stage-<ts>.service` executing `deploy.sh --staging <sha>`.
- `kgkg-backend.service` (the pre-container gunicorn unit) was **not running**. A session on 2026-11-02 stopped
  it because it was crash-looping on port 8000 alongside the container; it was left `disabled` with
  `Restart=always`. Whether it is now masked or removed is **[U]**. Do not follow older instructions that
  `systemctl restart kgkg-backend`. [D session f197e5f1]

## 25.3 Timers seen on the host [S]

| Timer | Doc'd elsewhere | Purpose |
|---|---|---|
| `kgkg-pipeline.timer` | doc 11 | `pipeline_tick` every 5 min |
| `kgkg-detect.timer` | doc 11 | `realtime_tick` every 30 s |
| `kgkg-alerts.timer` | doc 11 | `check_alerts` every 5 min |
| `kgkg-watchdog.timer` | doc 11 (`ops/observability/`) | watches the alert sweep |
| `kgkg-bizsnap.timer` | doc 11 | business snapshot for dashboards (`ops/observability/bizsnap.py`) |
| `kgkg-token-prune.timer` | doc 18 | daily prune of expired session tokens |
| `kgkg-qa-nightly.timer` | repo `ops/qa/` | 01:30 UTC; runs `qa/nightly.sh origin/work` from a worktree of `/opt/KGKG_work` (E2E, DAST baseline, performance baseline) |
| `kgkg-walcheckpoint.timer` | **undocumented** | hourly; purpose inferred from the name (SQLite WAL checkpoint) **[U]** |
| `kgkg-coverage.timer` | doc 04 | about 03:24 UTC daily; runs `manage.py check_coverage` (diagnostic and retrieval coverage per vehicle vs a baseline, per its docstring) [C docstring, S timer] |
| `kgkg-outbox.timer` | doc 11 says **not installed** | template in `ops/outbox/` has `ExecStart=/bin/true # REPLACE`; absent from the timer list, consistent with the doc [S] |

## 25.4 Directories under `/opt` [S listing, purposes from docs where available]

| Path | Purpose |
|---|---|
| `KGKG` | production checkout and deploy target. Never edit by hand |
| `KGKG_work` | development worktree used by the nightly QA |
| `KGKG_staging`, `KGKG_qa` | staging and QA stacks |
| `KGKG_release` | `staging.env`, `e2e/`, `promote-overrides.log`, `db-backups/` (last three `pg_dump` of `kgkg`) |
| `KGKG_backups` | backups (contents **[U]**) |
| `KGKG_wt22` | **undocumented**; looks like a leftover worktree **[U]** |
| `glitchtip`, `observability`, `umami` | compose projects for the self-hosted monitoring |
| `kgci-tools`, `kgci-trivy` | **undocumented**; CI gate tooling **[U]** |
| `partsouq`, `toyota_tis` | parts crawler (`api/partsouq_crawler.py`, `ops/partsouq/`) and TIS download data (doc 15) |
| `npmbuild*.log`, `npminstall.log`, `pipinstall.*` | build logs from the pre-container era **[U]** |

Also outside `/opt` (named in sessions, **[U]** whether still present): `/root/downloads` (source ZIPs),
`/root/parts_build`, `/root/partsouq_crawl`, `/root/pgmig`, `/root/prod-untracked-backup/`, `/root/backup_snapshot/`
(hourly off-host snapshot staging; `SNAPSHOT_AT` stamp read by the watchdog).

## 25.5 What is not inspected by documentation work

`.env.prod` (values never), live nginx configuration, PostgreSQL schema listings, cron files of other users,
backup contents, Cloudflare settings. Anything in those areas is tagged **[U]** wherever it appears in these docs.
A second read-only pass was attempted on 2026-11-04 and was refused by the permission layer; it needs the
owner's approval for the specific commands.

## 25.6 Drift control for this file

The repo half of this inventory is generated and CI-checked. The host half cannot be: it is a human or
agent observation. Re-run the checks in `docs/AGENTS.md` section 6 and the host commands in doc 11 section 11.1
after any change to units or directories, and move the date at the top of section 25.2 only when you did.

## 25.7 Map of `ops/` (purposes from each file's own header) [C]

| Path | Purpose |
|---|---|
| `ops/deploy/deploy.sh`, `kgkg-promote`, `gate.sh` | build, stage, promote, roll back; `gate.sh` is the quality gate run in a clean worktree with a scrubbed environment (no prod secrets, SMS, Sentry or Metis). Doc 11 §11.3 |
| `ops/deploy/ci_evidence.sh` | reports what GitHub CI says about one commit (`verdict <sha>` → pass/fail/unknown) so promotion can require green CI |
| `ops/deploy/ci_is_tip.sh` | exit 0 if a commit is still the tip of the branch CI is staging (CI cancels superseded runs) |
| `ops/deploy/prune_images.sh` | remove per-sha release images nothing needs; keeps the given SHAs and anything in use. Never `docker prune -a` |
| `ops/deploy/cutover_postgres.sh` | one-time portal DB move from SQLite to PostgreSQL (`--rehearse`, `--back`) |
| `ops/deploy/check_migrations.py` | refuses migrations the previous release cannot run against (rollback safety) |
| `ops/deploy/sanitize_staging_db.py` | builds the staging/QA copy of the portal DB with personal data masked, fails closed with `--strict-audit` |
| `ops/docker/*.Dockerfile`, `containers.sh`, `backend-requirements.lock` | production images (frontend bakes `NEXT_PUBLIC_*` at build); host-network containers bound to loopback; helpers sourced by `deploy.sh` |
| `ops/hostjobs/hostjobs_daemon.py` + `kgkg-hostjobs.service` | host side of `api/hostjobs.py`: spool of JSON requests from the backend container; fixed action list with validated parameters |
| `ops/nginx/*` | site config, limits, media auth, logrotate for nginx and ModSecurity (the modsec audit log rotates daily, 14 kept) |
| `ops/observability/*` | Loki, Alloy, Grafana provisioning, Prometheus, blackbox, `watchdog.py`, `bizsnap.py`, `delivery.py` (DORA metrics from deploy logs and git). Alerting stays in `api/alert_rules.py`; this stack is for searching and charting; everything binds to loopback (SSH tunnel) |
| `ops/umami/*` | cookieless analytics; nginx exposes only the tracker script and collect endpoint under `/stats/` |
| `ops/qa/*` | nightly QA service and timer (01:30 UTC) |
| `ops/outbox/*` | unit templates for the notification outbox (not installed; `ExecStart` is a placeholder) |
| `ops/rag/*` | offline experiments: pgvector/FTS loaders and benchmarks, fusion sweep, paired significance, candidate dump. The pgvector/FTS loaders populate the store that production reads (`RAG_VEC_BACKEND=pgvector`, `RAG_FTS_BACKEND=pg`, observed 2026-11-04); benchmarks and sweeps are offline |
| `ops/cardb/*` | PostgreSQL car loader and parity check ([23](23-data-layer.md)) |
| `ops/partsouq/partsouq_vin_crawl.py` | polite one-vehicle Partsouq crawl; stops on a persistent Cloudflare challenge |
| `ops/security/*` | bandit baseline, npm audit allow-list and gate (`npm_audit_gate.mjs`: fails only on non-allow-listed advisories at or above a severity) |
| `ops/governance/*` | docs freshness, PR traceability, generated inventory + drift check |
