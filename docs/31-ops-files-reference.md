# 31 — Ops files and units reference (observability, logging, analytics, offline RAG tools, security baselines)

Complements [25-ops-inventory.md](25-ops-inventory.md) (map of `ops/`). Everything here is read from files at `origin/work`
@ `f078878` **[C]**. Whether a stack is *running* on the host is **[U]** unless stated; the SSH restriction in force during
this work prevented fresh verification. Persian version: [fa/31-ops-files-reference.md](fa/31-ops-files-reference.md).

## 31.1 Frontend image — `ops/docker/frontend.Dockerfile`

Two-stage build on `node:20-bookworm-slim`.

1. **build**: `npm ci` from `kg_frontend/package-lock.json`, build argument `NEXT_PUBLIC_API_BASE` (default `/kg-api`) is baked
   into the bundle at build time, `npm run build`, then `npm prune --omit=dev`. Telemetry off.
2. **runtime**: OS packages upgraded (the pinned base lags the distribution's security fixes), `curl` kept for the health check,
   and `npm`, `npx`, `corepack`, `yarn` are **deleted** because they only add bundled dependencies to the vulnerability count; the
   server starts with `node_modules/.bin/next`. `ENV PORT=3000`, `KG_RELEASE` build argument becomes an env var.
   `HEALTHCHECK` every 15 s (timeout 5 s, start period 60 s, 4 retries) on `http://127.0.0.1:${PORT}/`.
   `CMD next start -p ${PORT} -H ${KG_BIND:-127.0.0.1}`.

Consequences: `NEXT_PUBLIC_*` cannot be changed at run time (rebuild the image); runtime secrets come only from the env file
passed by `ops/docker/containers.sh` (`KG_FE_ENV`). hadolint lints this file in CI (job `security`). The backend counterpart is
`ops/docker/backend.Dockerfile` (gunicorn, see [29](29-environment-reference.md) §29.3).

## 31.2 Observability stack — `ops/observability/`

Defined by `docker-compose.yml` (images pinned: Loki 3.4.2, Alloy v1.7.5, Grafana 11.5.2, Prometheus v3.2.1, node-exporter
v1.9.0, cAdvisor v0.52.1, blackbox-exporter v0.26.0). All ports bind **`127.0.0.1` only**; Grafana is reached through an SSH
tunnel (`ssh -L 3001:127.0.0.1:3001 root@<vps>`, header comment of the compose file). Memory limits: Loki 1 GB, Alloy 512 MB,
Grafana 512 MB, Prometheus 1 GB, cAdvisor 512 MB, node-exporter and blackbox 128 MB. Named volumes: `prometheus-data`,
`loki-data`, `alloy-data`, `grafana-data`.

```
 backend (/var/log/kgkg/*.jsonl) ─┐
 nginx access/error logs ─────────┼─► Alloy ─► Loki (90 d)  ─┐
 (further sources: see config.alloy) ─────┘                          ├─► Grafana (127.0.0.1:3001)
 backend /kg-metrics (bearer) ─┐                             │
 node-exporter :9100 ──────────┼─► Prometheus (30 d) ────────┘
 cAdvisor :8080 ───────────────┤        ▲
 blackbox :9115 probes ────────┘        └── alert_rules._infra reads 127.0.0.1:9090
```

| File | What it configures |
|---|---|
| `prometheus.yml` | `scrape_interval: 30s`. Jobs: `prometheus` (self), `kgkg_app` (path `/kg-metrics` on the loopback scrape listener `172.19.0.1:8081`, bearer token from the mounted file `/etc/prometheus/metrics_token`; never inline), `node` (`172.19.0.1:9100`), `cadvisor`, `probe` (module `http_2xx`, every 60 s, targets `https://kgtechvault.com/` and `…/kg-api/api/health/`), `probe_ext` (module `http_reachable`, targets `https://api.metisai.ir/` and `https://console.melipayamak.com/`, i.e. the LLM and SMS providers). Retention is set on the container command: `--storage.tsdb.retention.time=30d`. |
| `blackbox.yml` | Module `http_2xx` (10 s timeout, IPv4, custom User-Agent) and `http_reachable` which treats 200/301/302/400/401/403/404/405 as "reachable" because for third-party APIs an auth error still proves reachability. |
| `loki.yml` | Single-process Loki, filesystem storage, TSDB schema v13 from 2026-01-01, `retention_period: 90d`, ingestion 8 MB/s (burst 16), structured metadata allowed, analytics reporting off, `auth_enabled: false` (loopback only). |
| `config.alloy` | Ships logs to Loki. Django JSON logs `/var/log/kgkg/*.jsonl` (job `kgkg-backend`; labels `level`, `logger`; timestamp from the `ts` field), nginx `access.log`/`error.log` (job `nginx`, `stream`, status class label), and further sources further down the file (labels are kept low-cardinality by design; everything else is queried with `| json` or line filters). |
| `kgkg-watchdog.service` | See §31.5. |

Operational notes:

- The application raises its own alerts (SMS) from `api/alert_rules.py`, which includes an `_infra` section that reads the local
  Prometheus on `127.0.0.1:9090`. Grafana is for investigation, not the paging path. The thresholds are in
  [29](29-environment-reference.md) §29.5.
- Alert silence is a risk of its own: the watchdog (§31.5) exists because the alerting engine was once found dead unnoticed.
- **Not verified here [U]:** which Grafana dashboards exist in the running instance, and whether the stack is currently up. The
  repository provisions Grafana via mounts in the compose file; read it before assuming a dashboard exists.

## 31.3 Log rotation — `ops/nginx/logrotate-nginx.conf`, `logrotate-modsecurity.conf`

| File | Rule |
|---|---|
| `logrotate-nginx.conf` | `access.log` and `error.log` listed **explicitly, not globbed**: `/var/log/nginx/*.log` also matched `modsec_audit.log`, which another file declares; a duplicate entry makes logrotate skip the whole file, and nginx logs stopped rotating from 2026-10-27 until fixed (comment in the file). Daily, 14 kept, compressed with delay, `create 0640 www-data adm`, `nginx rotate` in postrotate. |
| `logrotate-modsecurity.conf` | `modsec_audit.log`: daily, 14 kept, compressed, `create 0640 www-data adm`, `dateext`, nginx reopened with `USR1`. Verbose by nature (full request headers per hit), so retention is short; the WAF decision is also summarised in nginx `error.log`, which is what fail2ban reads. |

Privacy: both logs contain client IPs and request lines; retention is therefore 14 days. Application logs are rotated by the
application (`KG_LOG_DIR`).

## 31.4 Product analytics — `ops/umami/`

Self-hosted Umami (`ghcr.io/umami-software/umami:postgresql-v2.15.1`) with its own `postgres:16-alpine` container and volume
`umami-db`. The dashboard binds `127.0.0.1:3002` (tunnel `ssh -L 3002:127.0.0.1:3002`); nginx publishes **only** the tracker
endpoints (header comment of the compose file). `setup.sh` (run once, in `/opt/umami`) rotates Umami's default admin password to
a random value written to `admin.secret` (mode 077) and registers the `kgtechvault.com` website, printing its `website_id`.
It never prints the password. Its database is separate from `kgkg`/`kgkg_vec`, so Umami data is **not** in any `kgkg` backup.
Usage events collected are web analytics only; the `kg_frontend` side of the integration is described in
[24-integrations.md](24-integrations.md).

## 31.5 systemd units

| Unit (repo path) | Type | Purpose and design |
|---|---|---|
| `ops/observability/kgkg-watchdog.service` (+ timer, 5-minute cadence) | oneshot | Runs `/usr/local/lib/kgkg/watchdog.py` with system python (`-I`, no venv, no Django, no DB), **independent of the app** so the failure that breaks the app cannot also break its only monitor. The script is copied there by `deploy.sh` on every promote (running from the git tree would let an untracked file block a fast-forward promote). Exit status 1 means "engine not watching and a page went out", so the unit is *meant* to show as failed in `systemctl list-units --failed`. Sandbox: `StateDirectory=kgkg-watchdog`, `ProtectSystem=strict`, writable only `/var/lib/kgkg-watchdog` and `/var/lib/node-exporter-textfile`, `ProtectHome=read-only` (not `yes`: the snapshot stamp lives under `/root` and `yes` made the check report "no stamp" under the unit while passing by hand), `CPUWeight=50`. Reads `.env.prod` for SMS credentials. Checks: alert sweep freshness, local health, failed units, off-host snapshot age. Tunables: [29](29-environment-reference.md) §29.6. |
| `ops/qa/kgkg-qa-nightly.service` | oneshot | Nightly QA: runs `qa/nightly.sh origin/work` from a **fresh detached worktree** of `origin/work` under `/opt/KGKG_qa/tree` (created from `/opt/KGKG_work`), never from the live tree. Browser E2E, passive DAST and a performance baseline on the isolated QA stack (`qa/stack.sh`); result written to `/var/lib/node-exporter-textfile/kgkg_qa.prom`, which feeds the `_qa` alert rule (`KG_ALERT_QA_STALE_H`). About 15 min per run, `TimeoutStartSec=90min`, `Nice=15`, `IOSchedulingClass=idle`; the QA containers carry their own CPU caps. See [32-testing-and-qa.md](32-testing-and-qa.md). |

Whether these units are enabled and when they last ran is **[U]** (host verification blocked). `systemctl list-timers` on the host
is the authoritative check.

## 31.6 Offline RAG evaluation tools — `ops/rag/`

These run by hand on a machine that has the models; they are **not** part of serving and not in CI.

| Script | Purpose | Input → output |
|---|---|---|
| `dump_cands.py` | For every gold question, dump the live pipeline's top-20 (retrieval order) and the KG-Reranker score of each candidate, so fusion weights can be swept offline instead of one 2-hour evaluation run per weight. Needs Django settings, `sentence_transformers`, `RAG_RERANK_MODEL` in env. | gold sets → `<out>.jsonl` |
| `fusion_sweep.py` | Fuses retrieval rank and reranker score per question: `a · z(ce) + (1 − a) · z(−rank)`; `a = 0` is the live pipeline, `a = 1` the reranker alone. Picks `a` by **2-fold cross-validation** (fold A chooses by mean nDCG@5 on EN+FA pooled, measured on fold B, and vice versa) so reported numbers are only on held-out questions; paired permutation test against the live order. | `<in>.jsonl` → console report |
| `paired_significance.py` | Paired permutation test (10 000 resamples, seed 0) and bootstrap (2 000) between two evaluation `results.json` files for `known_item_en`, `known_item_fa`, `known_item_fa_rev` on nDCG@5, P@1, R@10, MRR. | two `results.json` → console report |

Companion scripts documented earlier: `pgvec_load.py`, `pgfts_load.py`, `pgvec_bench.py` ([23](23-data-layer.md)). Interpretation of
results: [30-ai-assistant-deep-dive.md](30-ai-assistant-deep-dive.md) §30.11.

## 31.7 Security baselines — `ops/security/`

| File | Role |
|---|---|
| `bandit-baseline.json` | bandit's recorded baseline (generated 2026-10-29T14:26:35Z per its `generated_at`). `scan.sh` compares new findings against it, so only findings **not** in the baseline block CI and the deploy gate. Regenerating it hides findings: review the diff like code. |
| `npm-audit-allow.json` | Allow-list for Node advisories keyed by GHSA id, read by `npm_audit_gate.mjs`. `minSeverity` is `high`; `allow` is **empty** (goal and current state; `next@16.4.3` cleared everything on 2026-10-27). Adding an entry needs blocker, reachability and review (policy: `ops/security/README.md`). |

Gate matrix (shellcheck, hadolint, gitleaks, pip-audit, npm audit, trivy, bandit) and its server-side counterpart are defined in
`ops/security/README.md` and summarised in [32-testing-and-qa.md](32-testing-and-qa.md) §32.8.
