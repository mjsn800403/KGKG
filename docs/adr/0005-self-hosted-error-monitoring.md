# ADR-0005 — Self-hosted error monitoring and observability

**Status:** Accepted · **Since:** 2026-08-05 (GlitchTip), 2026-10-13 (Prometheus/Loki/Grafana) · **Recorded:** 2026-10-29

## Context
The product serves Iranian companies from a host in Iran. Foreign SaaS monitoring may be
unreachable or legally awkward. Error reports carry request data, which the operator wants
kept on the host. There is no budget for paid observability.

## Decision
* **Errors go to self-hosted GlitchTip** (Sentry wire protocol), from both Django and the
  Next.js server.
* **Metrics, logs, dashboards and uptime run on the same host:** Prometheus with blackbox
  uptime probes, Loki with Alloy, and Grafana. All are provisioned from `ops/observability/`.
* **Alerting runs in the app** (`check_alerts`). Pages go out by SMS, and a standalone
  watchdog pages if the alerting itself stops.
* **Monitoring UIs are reachable only through an SSH tunnel or the admin console,** never
  publicly.

## Consequences
* **No data leaves the host** for monitoring.
* **Monitoring shares the host's fate.** If the host dies, so does its monitoring. External
  detection relies on probes that can reach the host and on customers.
* **Two silent compatibility traps are documented:** Brotli bodies and hyphens in the DSN
  (doc 12).
* **The browser is not instrumented,** by design.

## Evidence
`KG_backend/KG_backend/settings.py` (Sentry init), `kg_frontend/src/instrumentation.ts`,
`ops/observability/`, `docs/11-operations-deployment.md` §11.5, CHANGELOG 2026-08-05 and
2026-10-27.
