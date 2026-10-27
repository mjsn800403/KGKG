# Post-release support, defect and incident handling

## Channels that exist in the product (verified 2026-10-27)

| Channel | What it is | Live usage (production DB, read-only count) |
|---|---|---|
| In-product requests (ticketing) | Company managers file requests from `/requests` (kinds: vehicle access, seats, AI assistant, documents, support, other; priority low/normal/high). The platform admin works them in the admin inbox with a status lifecycle `pending → in_progress → completed / rejected`; status changes stamp `resolved_at` and notify the requester over the event stream. Code: `api/requests_api.py`, model `CompanyRequest`; tests: `api/test_qa_requests.py` (lifecycle, isolation, admin filters) | 5 requests: 1 completed, 1 in progress, 3 rejected |
| Purchase / onboarding requests | Public `/purchase` form → admin review → company and accounts created | 9 requests: 4 approved, 3 rejected, 1 reviewing, 1 new |
| Error monitoring | Self-hosted GlitchTip (Sentry protocol) for backend and frontend, release-tagged | Running (`glitchtip-*` containers) |
| Metrics and alerting | Prometheus + Grafana; alert rules evaluated by `check_alerts`; SMS paging; a watchdog that pages if alerting itself stops | Running; see `docs/11-operations-deployment.md` §11.5 |
| Logs | Structured JSON logs (backend), nginx logs, shipped to Loki via Alloy | Running |

Usage volume is small because the customer base is small (9 companies,
36 seats on 2026-10-27). The figures are reported as they are.

## Defect handling (procedure from 2026-10-27)

1. **Record.** Every defect gets a GitHub issue from the *Defect* template
   (`.github/ISSUE_TEMPLATE/defect.yml`): severity, source, version + commit,
   reproduction, evidence. Customer tickets that need engineering are
   escalated with the *Customer support escalation* template, referencing the
   in-product request id, never customer personal data.
2. **Triage** within one working day. Severity definitions are in the
   template. Critical: work starts immediately; production exposure is
   assessed (as was done for D-06).
3. **Fix test-first.** A test that reproduces the defect is written and seen
   to fail, then the fix makes it pass; the full suite must stay green.
4. **Release** through the normal gate → staging → promote path. A Critical
   security fix may be promoted as a PATCH release outside the usual cadence;
   the gate and staging are never skipped.
5. **Close** with root cause, commit, regression-test name, and the version
   it shipped in.

The 16 defects found during the 2026-10-27 remediation were handled this way;
their register is `../14-risk-and-corrective-actions/CORRECTIVE_ACTIONS.md`.
The GitHub templates are new with this release, so there is no history of
issues filed through them yet.

## Incident response

| Step | Mechanism |
|---|---|
| Detect | Alert rules + SMS paging; watchdog on the alerting path; blackbox probes; GlitchTip new-issue notifications |
| Classify | SEV1 site down or data exposure · SEV2 a core journey broken · SEV3 degraded |
| Mitigate | `ops/deploy/deploy.sh --rollback` (previous images, seconds); feature flags (`api/flags.py`) to switch features off |
| Recover data | Pre-deploy DB backups in `/opt/KGKG_release/db-backups/`; hourly off-host snapshot pulled by an internal server, restore-verified 2026-10-27 (`ops/observability/verify_restore.py`) |
| Learn | Blameless post-incident note in `docs/CHANGELOG.md` and a regression test, as for every defect |
