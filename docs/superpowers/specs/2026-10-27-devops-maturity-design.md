# Operational maturity: CI/CD, monitoring, alerting, reliability

**Date:** 2026-10-27
**Status:** approved (design), implementation in progress
**Host:** `103.75.197.155` (single Ubuntu 24 VPS, 16 cores / 31 GB / 290 GB)

## 1. Why

External criticism of the product:

> "Manual code deployment, lack of an automated CI/CD pipeline, and absence of
> performance and error monitoring tools indicate insufficient operational
> infrastructure maturity and significant service stability risks."

Part of this is already out of date. A survey of the live host on 2026-10-27
found a gated deploy pipeline, per-SHA Docker images, zero-gap backend swaps,
auto-rollback, GitHub Actions CI on every branch, a Prometheus/Grafana/Loki
stack, GlitchTip error tracking wired into both Django and Next, and an SMS
alert engine. The criticism nevertheless lands on four real gaps, and the
documentation itself still claims "there is no CI/CD" — which is where a
reviewer would reasonably form that impression.

### What already exists (verified 2026-10-27)

| Area | State |
|---|---|
| Deploy | `ops/deploy/deploy.sh`: gate → per-SHA images → staging on a fresh prod-DB copy → smoke → promote (SO_REUSEPORT, no gap) → verify → auto-rollback. `--rollback`, `--status`, `--reload`. Release state in `/opt/KGKG_release/state.env`, per-deploy logs + DB backups, git tags `deploy-<ts>`. |
| Quality gate | `ops/deploy/gate.sh` in a throwaway worktree with a scrubbed env: Django check, migration drift, **rollback-safety of migrations**, full backend suite, `npm ci`, eslint ratchet, production build. |
| Smoke | `ops/deploy/smoke.sh`: read-only public checks + signed-in checks with a QA token minted in the staging DB copy. |
| CI | `.github/workflows/ci.yml` on every branch: backend suite, frontend lint+build, both production images build and the backend image boots. |
| Remote trigger | `/usr/local/bin/kg-deploy-gate` as an SSH `command=` forced command, key `restrict`ed; accepts only `deploy <40-hex>` for a commit on `origin/work`; `flock` single-flight; runs the deploy as a transient systemd unit so a dropped connection cannot kill it. |
| Monitoring | Prometheus + Grafana + Loki + Alloy + cAdvisor + node-exporter + blackbox (internal and external HTTP probes), all bound to localhost. |
| Error tracking | GlitchTip (Sentry wire-compatible), `SENTRY_DSN` set in prod, Django integration + Next `instrumentation.ts`. |
| App alerting | `manage.py check_alerts` every 5 min: disk, memory, DB liveness, per-endpoint 5xx and latency, login-failure spikes, admin-auth failures, SMS failures, AI degradation and cost, TLS expiry, container restarts → deduplicated `SystemAlert` rows + **SMS paging** to `KG_ALERT_PHONES`. |
| Analytics | Umami, self-hosted. |
| TLS | nginx :443 with Cloudflare origin certificates. |
| IaC | `ops/` is tracked in git; `/opt/observability/*.yml` matches `ops/observability/` byte for byte. |

### The real gaps

1. **G1 — No automated path from push to a verified staging release.** Every
   deploy to date was a human running `deploy.sh` over SSH. CI proves a commit
   is sound but never exercises it against a real database.
2. **G2 — `deploy.yml` auto-promotes to production.** On green CI for a push to
   `work` it calls the forced command's `deploy` verb, whose only brake is
   GitHub's `production` environment having required reviewers — not verifiable
   from the host, and directly contrary to the "never promote automatically"
   requirement. The path has never fired (gate log holds only local tests from
   2026-10-16), so this is a latent hazard rather than an incident.
3. **G3 — No application metrics in Prometheus.** It scrapes the host,
   containers and HTTP probes only. Request rate, error rate and latency live
   in Django's own tables, so they cannot drive Prometheus rules or Grafana.
4. **G4 — No Prometheus rules, no Alertmanager, no independent paging path.**
   Paging requires Django to be alive to send the SMS. If the app is down, the
   blackbox probes notice and tell nobody.
5. **G5 — CI has no supply-chain or security gates:** no dependency audit, no
   image scan, no secret scan, no shell/Dockerfile lint, no coverage signal.
6. **G6 — No off-host backup.** Single disk at 70 %. *Deferred by the owner;
   raised again in the final report.*
7. **G7 — Documentation describes an architecture that no longer exists**
   (doc 11 §11.3 "There is no CI/CD").

## 2. Principles

- Production is never promoted without a human. No exceptions, no timers.
- CI credentials can reach staging and nothing else — enforced on the server by
  a forced command, not by configuration in GitHub.
- Every increment lands on its own, is verified against the real system, and
  has a stated rollback.
- Prefer extending what works over introducing new infrastructure. No new
  daemon earns its place unless it closes a gap nothing else can.
- Alerts that nobody would act on are noise; every rule gets a documented
  response.

## 3. Design

### 3.1 CI/CD (G1, G2)

**Split the forced command by privilege.** `kg-deploy-gate` grows a verb set
and a strict notion of who may use which verb:

| Verb | Allowed to | Effect |
|---|---|---|
| `stage <sha>` | the CI key | `deploy.sh --staging <sha>`: gate, build images, staging on a fresh sanitized DB copy, smoke. Production untouched. |
| `status` | the CI key | prints release + staging state. Read-only. |
| `deploy <sha>` | **operator keys only** | the full promote pipeline. Refused for the CI key. |

The distinction is carried by `KG_GATE_ROLE`, set per key through
`environment=` in `authorized_keys`, so a key's privilege is a property of the
key rather than of the client's good behaviour. The existing GitHub deploy key
is repointed to the CI role: if its secret were ever misused, the worst
available outcome is a staging deploy.

`deploy.yml` loses its automatic trigger. Promotion becomes:

- **Primary:** on the server, `kgkg-promote <sha>` — a wrapper that refuses any
  SHA which has not passed staging, shows what will change, requires typed
  confirmation, then calls `deploy.sh`.
- **Secondary:** `promote.yml`, `workflow_dispatch` only, guarded by the
  `production` environment, for when the owner would rather click than SSH. It
  uses a separate operator key, and the workflow fails closed if the staging
  record for that SHA is missing.

**Staging provenance.** `deploy.sh --staging` records
`/opt/KGKG_release/staging.env` (`STAGED_SHA`, `STAGED_AT`, `SMOKE`,
`GATE`), which is what `kgkg-promote` checks and what a node-exporter textfile
collector turns into `kgkg_staging_*` metrics. A release that was never staged
cannot be promoted by accident, and the gap between "staged" and "live" is
visible on a dashboard.

**Database sanitization for staging.** Staging already runs against a copy, with
SMS, Sentry, Metis and host jobs disabled. The copy is additionally scrubbed:
session tokens dropped, user phone numbers and e-mails masked, admin tokens
replaced, invite links invalidated. A staging smoke failure must never be
explained by "it used real credentials".

**CI changes** (`ci.yml`): keep the three existing jobs; add `security`
(dependency audit, secret scan, shell and Dockerfile lint, image vulnerability
scan, coverage report) and `stage` (on `work` only, after everything else is
green, calls `stage <sha>` over the restricted key). `stage` is the only job
that touches the server, and it cannot touch production.

### 3.2 Application metrics (G3)

A `/api/metrics/` endpoint in Django in Prometheus exposition format, built on
the counters the middleware already keeps, so no request-path cost is added:

- `kgkg_http_requests_total{route_class,method,status_class}`
- `kgkg_http_request_duration_seconds_bucket{route_class}` (histogram)
- `kgkg_db_up`, `kgkg_rag_up`, `kgkg_cardb_pool_*`
- `kgkg_pipeline_state{stage}`, `kgkg_pipeline_last_success_timestamp`
- `kgkg_alerts_active{severity}`
- `kgkg_build_info{sha,deployed_at}`
- `kgkg_ai_requests_total{outcome}`, `kgkg_ai_cost_estimate`

Route labels are bounded to a fixed set of route classes; no per-URL labels, no
unbounded cardinality. The endpoint requires `KG_METRICS_TOKEN` (bearer) and is
additionally denied at nginx for external clients, so it is reachable by
Prometheus on the internal network only.

### 3.3 Alerting (G4)

Alertmanager joins the observability compose stack, bound to localhost. Rules
are split by ownership:

- **Prometheus rules** — infrastructure and black-box truth: probe failure,
  target down, 5xx ratio, p95 latency, container restart loops, OOM kills,
  disk/inode/memory pressure, certificate expiry, staging/deploy failure,
  release drift (staged ≠ live for too long), Loki error-rate spikes.
- **Django `check_alerts`** — business and domain truth: data-quality
  regressions, login-failure spikes, AI degradation and cost, quota anomalies.
  Unchanged, and deliberately not duplicated in Prometheus.

**Notification** goes through `kgkg-smsd`: a ~100-line stdlib-only HTTP
receiver (systemd unit, not a container, `127.0.0.1` only) that renders an
Alertmanager webhook into one SMS per alert group and posts it to the existing
SMS provider. It reads credentials from a root-only env file. Because it is
independent of Django, Gunicorn and Docker, the app being down does not silence
paging.

**Deadman.** Prometheus emits a constant `Watchdog` alert; Alertmanager routes
it to `kgkg-smsd`, which keeps a heartbeat file. A systemd timer
(`kgkg-deadman`) reads that file and SMSes directly if the heartbeat is stale —
so the monitoring stack failing is itself an alertable event, through a path
that shares nothing with the stack it watches.

Severity routing: `critical` pages by SMS immediately; `warning` groups into a
digest; `info` reaches Grafana only. Every rule carries a `runbook` annotation
pointing at a heading in the operations doc.

### 3.4 Dashboards

Four provisioned Grafana dashboards, as code under `ops/observability/`:
service health (RED + probes + error budget), delivery (deploy timeline, stage→
promote lag, gate and smoke outcomes), host and containers, logs and errors
(Loki + GlitchTip volume).

### 3.5 Reliability hardening

- `shellcheck` clean across `ops/`, enforced in CI.
- `ops/deploy/selftest.sh`: exercises the forced command's argument parsing and
  role enforcement, the promote wrapper's refusal paths, and the sanitizer —
  the parts where a bug is a security bug. Runs in CI and before any change to
  the gate.
- `smoke.sh` extended: security headers, SSE ready-frame, media alias, metrics
  endpoint requires auth, admin surface rejects anonymous access.
- `ops/backup/backup.sh`: nightly consistent SQLite snapshot + config and
  secrets archive, checksummed, retained with a documented policy, verified by
  a restore-and-query test, and surfaced as `kgkg_backup_*` metrics with an
  alert when the last good backup is too old. The remote target is a pluggable
  destination, left disabled pending the owner's decision (G6).

### 3.6 Documentation

Doc 11 rewritten to the implemented architecture; a new doc covering CI/CD and
observability end to end; one runbook section per alert rule; this spec kept as
the design record.

## 4. Increments

Each is independently verifiable and independently revertible.

| # | Increment | Rollback |
|---|---|---|
| 1 | CI security and supply-chain gates | revert workflow file |
| 2 | `/api/metrics/` + scrape job + dashboards | endpoint is additive; remove scrape job |
| 3 | Alertmanager + rules + `kgkg-smsd` + deadman | `systemctl disable`, drop compose service |
| 4 | Gate roles: `stage` verb, CI key repointed, auto-promote removed | restore previous gate script + `authorized_keys` line |
| 5 | `kgkg-promote`, staging provenance, DB sanitizer | wrapper is additive; `deploy.sh` keeps working |
| 6 | shellcheck, selftest, smoke expansion | revert |
| 7 | Backup job (local target only) | `systemctl disable` |
| 8 | Documentation | revert |

## 5. Verification

No increment is claimed without evidence from the live system:

1. **CI gates** — a real run on a real commit, pass and deliberate-fail.
2. **Metrics** — `curl` the endpoint (401 without the token, 200 with it),
   `promtool check` the rules, the target `up` in Prometheus, a panel showing
   data.
3. **Alerting** — fire a synthetic alert end to end: rule → Alertmanager →
   `kgkg-smsd` → provider accepted (a real SMS to the owner's number, once),
   plus a forced deadman trip.
4. **Gate roles** — the CI key is *shown* to be refused for `deploy` and
   accepted for `stage`; an operator key still promotes.
5. **Staging** — a full `stage <sha>` run from CI, smoke green, prod SHA
   unchanged before and after.
6. **Promote wrapper** — refuses an unstaged SHA, refuses without confirmation,
   and a real promote of the current SHA succeeds with no downtime (probe
   series continuous across the swap).
7. **Backup** — restore the snapshot into a scratch directory and query it.
8. **No regression** — `deploy.sh --status`, all timers still active, smoke
   green against production, GlitchTip still receiving, and a before/after
   comparison of the public surface.

## 6. Out of scope

Off-host backup (G6, owner deferred), multi-host or HA topology, Kubernetes,
log-based SLO burn-rate alerting beyond error-rate spikes, secret management
beyond the existing rotation script, and paging schedules or on-call rotation
(single operator).
