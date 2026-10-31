# The ten evaluation criteria — status on 2026-10-30

The earlier package answered thirteen criteria
(`../15-final-audit-report/CRITERIA_MATRIX.md`). This matrix answers the ten
criteria of the current evaluation and the four critical findings, and states
what this branch changed. Same vocabulary: **Verified** means checked by
execution with evidence attached; a document existing is never a Verified.

| # | Criterion | Status | What exists | What this branch changed | Remaining gap |
|---|---|---|---|---|---|
| 1 | Design and architecture documentation | **Partially Verified** | `docs/00-srs.md` (20 FR, 14 NFR, ISO/IEC/IEEE 29148), `docs/01–15`, six ADRs, `docs/openapi.yaml` enforced by `api/test_openapi_routes.py` | Nine new paths specified; the spec gate caught the omission | No backlog-tool export (phase 2); no "big picture" diagram for the new desk |
| 2 | Knowledge management systems | **Partially Verified** → improving | Strong `docs/`, docs-as-code protocol (ADR-0006), CHANGELOG | A knowledge base with named owners, review intervals, revisions, search, miss logging, and promotion from resolved tickets (`api/knowledge.py`, 35 tests) | No interface yet (phase 1b/3); `docs/` still has no named owners or staleness check (phase 5); zero articles in production |
| 3 | Technical infrastructure for development | **Verified** | Git/GitHub, Docker, GitHub Actions, staging, QA stack, Prometheus/Grafana/Loki/GlitchTip | — | No milestones, board or backlog in the tracker (phase 2) — the substance of Finding 1 |
| 4 | Source-code history and traceability | **Partially Verified** | 170+ commits since 2026-06-19, Conventional Commits, 25+ `deploy-*` tags | Every commit on this branch typed and explained | No history before 2026-06-19; no commit↔issue link and no CI check for one (phase 2) |
| 5 | CI/CD infrastructure | **Verified** | `.github/workflows/ci.yml`, `ops/deploy/` gate/stage/promote with role tests, promote requires a ≤72 h E2E record | — | This branch has **not** had a CI run; E2E/load/DAST still run on the server |
| 6 | Versioning and release management | **Partially Verified** | SemVer, `VERSION` = 1.0.0, deploy tags, typed promotion and rollback, `RELEASE_POLICY.md` | — | No alpha/beta channels (staging is the RC); release record per release still procedure |
| 7 | QA/QC processes | **Verified** | Unit, integration, E2E, k6 load, ZAP DAST, bandit, dependency and image scanning, mutation testing of the authorisation modules | +95 tests, all test-first; 3 pre-existing tests updated where behaviour deliberately changed, with reasons recorded | No E2E/load/DAST for the new endpoints (phase 1c) |
| 8 | Post-development support and service management | **Partially Verified** → materially improved | Ticket lifecycle, GlitchTip, alerting, SMS paging, GitHub issue templates | The channel opened to every seat; threads with internal notes; SLA policy with clocks and breach state; assignee as a foreign key; escalation; reopen; CSAT; `source`; a feedback channel; a metrics endpoint | API only — no interface (phase 1b); no breach alerting or customer notification (phase 1c); no attachments |
| 9 | Automated test coverage | **Verified (measured), target partially met** | Backend 60 % combined at the last audit; auth/authz modules 95–100 % branch; CI floor enforced | New modules arrived with tests first; coverage **not re-measured on this branch** | Coverage must be re-measured in CI; the 80 % ambition is unmet; issue `#22` tracks it |
| 10 | DevOps maturity | **Verified** | Containerised blue/green swap with auto-rollback, monitoring, paging watchdog, restore-verified off-host backups | — | One host runs production, staging, QA and observability (issue `#25`); nginx still installed by hand |

## The four critical findings

| Finding | Root cause established | Status now | Evidence |
|---|---|---|---|
| **No verifiable team and task management** | Organisational, not architectural: GitHub was never configured as the system of record. 19 issues exist, all remediation items; no milestone on any of them; no commit↔issue link | **Partially Verified** — tracker in use, mechanisms absent | `ROOT_CAUSE_ANALYSIS.md` §1; counts from `gh`; plan in `ROADMAP.md` phase 2 |
| **No BI infrastructure** | Measurement is abundant but fragmented and **undefined**; whole domains (delivery, quality trend, support, knowledge) uncollected | **Not Implemented** as a capability; the support and knowledge slice is built to the registry discipline | `METRIC_DEFINITIONS.md` (every field defined, sourced and tested), `evidence/support-metrics-sample.json`, `ROADMAP.md` phase 4 |
| **No formal knowledge transfer** | Documentation is strong but unowned, unreviewed, developer-shaped and disconnected from support; a solved ticket never became knowledge | **Partially Verified** — the store, ownership, review rule and ticket→article loop exist in the API | `api/knowledge.py`, `api/test_knowledge.py` (35 tests), `ROOT_CAUSE_ANALYSIS.md` §3 |
| **Telephone-based customer feedback** | **Technical, not cultural**: the whole ticket API was gated on `can_manage_team`, so every non-manager seat got 403 and had no digital channel; and with one `admin_note` field even a manager had to telephone for any back-and-forth | **Partially Verified** — root cause removed in the API, interface outstanding | `api/requests_api.py`, `api/sla.py`, `api/feedback.py`, `api/test_helpdesk.py` (60 tests), `IMPLEMENTATION_PHASE1.md` |

## Claims this package does **not** make

* That any of the new capability is usable by a customer today. It is API-only.
* That the support metrics describe production. The sample is from a throwaway
  database built by `evidence/reproduce_metrics.py`.
* That CI is green on this branch. It has not run.
* That the knowledge base contains knowledge. It contains a mechanism.
* That Findings 1 and 2 are resolved. They are analysed and planned.
