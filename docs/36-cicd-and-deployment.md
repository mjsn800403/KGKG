# 36 — CI/CD, release and deployment (end to end)

How a change travels from a branch to production, which controls stop it, and how to roll back. Source: `.github/`, `ops/deploy/`, `ops/docker/`, `ops/security/`, `qa/` at `origin/work` @ `07f3ab5` **[C]**.
Operational narrative and runbooks: [11-operations-deployment.md](11-operations-deployment.md), [20-runbooks.md](20-runbooks.md). What was running on the host at any time is **[U]** unless a dated
observation is cited; production was not inspected for this document. Persian version: [fa/36-cicd-and-deployment.md](fa/36-cicd-and-deployment.md).

## 36.1 Branches, protection and pull requests

- **`work`** is the integration branch and the one GitHub shows development on; **`main`** is the GitHub default and is behind `work` in content. Both are protected. Feature branches are cut from `origin/work` and
  merged by pull request into `work` ([AGENTS.md](AGENTS.md) rule 1).
- **Protection on `work`** (read from the GitHub API on 2026-11-04 **[S-GitHub]**): required checks `backend`, `frontend`, `security`, `images`, `governance`; pull request required;
  required approving reviews **0**; stale reviews dismissed; code-owner review not required; `strict` (branch must be up to date) **off**; rules not enforced for admins. Merge style used in history: merge commits.
- **CODEOWNERS** routes the debt-exceptions file and `gen_inventory.py` to the repository owner ([28](28-team-workflow.md)).
- **PR template** (`.github/pull_request_template.md`): Jira key, GitHub issue, what/why, *how it was verified* (commands and output), checklist (test failed before the change; docs updated; inventory regenerated;
  OpenAPI updated; ADR if standing decision; no ratchet lowered; alert rules windowed; nothing needing a hand-install on the host), risk and rollback.
- **Traceability gate:** a PR title/body must reference an issue (`ops/governance/check_traceability.py`; references inside code fences do not count). PRs to `work` do not auto-close issues even with `fixes #N` **[D]**.
- **Dependabot** (`.github/dependabot.yml`): weekly grouped minor/patch PRs per ecosystem, at most 3 open, target `work`, nothing can reach production.

## 36.2 Workflows

| Workflow | Trigger | Jobs |
|---|---|---|
| `.github/workflows/ci.yml` | every push (all branches) and every pull request; concurrency group per ref, in-progress runs cancelled | `backend`, `support-chat-e2e`, `frontend`, `security`, `governance`, `images`, `stage` |
| `.github/workflows/mutation.yml` | manual (`workflow_dispatch`) | `mutmut` on authorization modules, 180-minute limit |
| CodeQL | GitHub code scanning (Python, JavaScript/TypeScript, Actions) | `Analyze (…)`, `CodeQL` |

Least privilege: workflow permissions are `contents: read`; no job writes to the repository.

### Job reference (what each proves) — details in [32-testing-and-qa.md](32-testing-and-qa.md)

| Job | Key steps | Failure means |
|---|---|---|
| `backend` (PostgreSQL 16 service, 30-min timeout) | system libs for WeasyPrint; `manage.py check`; `makemigrations --check`; full suite with branch coverage and `--shuffle`; coverage floor `ops/deploy/coverage_min`; artifacts `backend-test-reports-<sha>` | test failure, missing migration, coverage under the floor |
| `support-chat-e2e` | throwaway stack; negative check that a missing stack fails; Playwright support-chat spec; `support_chat_guard.py`; artifact record | chat regression or vacuous run |
| `frontend` | `npm ci`; ESLint with warning ratchet `ops/deploy/lint_max_warnings`; `node --test`; `next build` | lint count up, test or build failure |
| `security` | shellcheck on `ops/`; **operations tests** (gate roles, promote, CI evidence, prune, tip, detached prod, promote guard + wiring, E2E record, smoke fleet, support-chat guard, observability tests, staging sanitizer, watchdog, CI SSH); hadolint; gitleaks; bandit; QA suites parse; pip-audit; npm audit | a guard of the release process is broken, or a vulnerability/secret is introduced |
| `governance` | governance unit tests; ownership/freshness (`check_docs_freshness.py`); Persian twins (`check_i18n.py`); inventory + debt ratchet against the target branch (`gen_inventory.py --check --require-base`); PR traceability | docs not owned/in date, translation drift, new undocumented item, no issue reference |
| `images` | build backend and frontend images; backend boots (`manage.py check` in the image); trivy scan of both | broken Dockerfile or fixable HIGH/CRITICAL vulnerability |
| `stage` | **only on push to `work`**, after all five jobs are green: stage that exact commit on the server (below) | credential missing/invalid (job red — known risk), gate or smoke failure on the host |

## 36.3 Promotion pipeline

```mermaid
flowchart LR
  A[PR merged to work] --> B[CI: backend frontend security images governance]
  B -->|all green| C[stage job: SSH as CI key]
  C --> D[kg-ci-gate: verbs stage, status only]
  D --> E[deploy.sh --staging: gate in clean worktree]
  E --> F[build images kgkg-backend:sha kgkg-frontend:sha]
  F --> G[staging on :8110/:3107 vs sanitized DB copy]
  G --> H[smoke.sh + QA token checks]
  H --> I{{A person}}
  I -->|types kgkg-promote sha on the server| J[deploy.sh full pipeline]
  J --> K[DB backup, fast-forward, migrate in new image]
  K --> L[new backend beside old on :8000, old stops when new healthy]
  L --> M[frontend stop/start about 1 s]
  M --> N[smoke; any failure rolls back to previous images]
```

- **CI can never promote.** Its SSH key is pinned on the server to `/usr/local/bin/kg-ci-gate`, whose role has no `deploy` verb (matrix tested by `ops/deploy/test_gate_roles.sh`). A leaked CI secret buys a staging run.
  Promotion is `kgkg-promote <sha>` typed by a person on the host (ADR-0004); this document, CI and agents never run it.
- **Connection:** `ops/deploy/ci_ssh.sh` validates the five secrets (`DEPLOY_HOST`, `DEPLOY_KNOWN_HOSTS`, `DEPLOY_SSH_KEY`, `DEPLOY_CF_ACCESS_CLIENT_ID`, `DEPLOY_CF_ACCESS_CLIENT_SECRET`) before dialling and names the fix per failure.
  The intended design is a Cloudflare Tunnel with an Access service token; per `ops/deploy/README.md` the live configuration on 2026-10-29 was direct SSH on port 22 with key-only sshd and fail2ban **[S 2026-10-29]**; current state **[U]**.
  Installer: `ops/deploy/setup_ci_access.sh` (pins the host key; refuses if sshd serves a different one).
- **Gate** (`gate.sh`, clean worktree, scrubbed environment: no prod secrets, SMS, Sentry or Metis; `KG_ENV_FILE` points at a throwaway file): security tools, system check, migrations match models, migrations rollback-safe,
  full backend suite on a throwaway PostgreSQL database, frontend `npm ci`, lint ratchet, unit tests, production build. A gate failure leaves production untouched.
- **Evidence for promotion:** CI success for the sha (`ci_evidence.sh`, required jobs `backend frontend security images` by default), staging and a recorded full E2E run for that sha (`qa/run_e2e.sh` writes `$KG_REL_DIR/e2e/<sha>.env`;
  a filtered run is `scope=partial` and does not count), and "is this still the tip of `work`" (`ci_is_tip.sh`). Overrides are logged. A guard library (`promote_guard.sh`: refuse a commit not on `origin/work`) exists with tests but its header states
  it was **not yet wired into `deploy.sh`** at this revision; `kgkg-promote` enforces the rule on its path.
- **Zero-gap swap** (ADR-0003): the new backend container starts next to the old on `:8000` (`SO_REUSEPORT`); the old stops only when the new reports healthy through its private health port. Frontend is stop/start. Smoke failure ⇒ automatic rollback to previous images.
  Migrations are **not** reversed (additive only); the pre-deploy database backup is retained.
- **Other deploy verbs:** `deploy.sh --staging <ref>`, `--rollback`, `--status`, `--reload` (restart the live release to pick up `.env.prod` changes, e.g. after `rotate_secrets`). A deploy lock with `KG_DEPLOY_LOCK_WAIT` (1800 s) serialises runs; staging containers are removed afterwards unless `KG_KEEP_STAGING=1`.
- **Prune:** `prune_images.sh` keeps the last 4 releases' images.

## 36.4 Build artifacts and images

`ops/docker/backend.Dockerfile` (gunicorn gthread; health on a private port; locked requirements `ops/docker/backend-requirements.lock`) and `frontend.Dockerfile` ([31](31-ops-files-reference.md) §31.1). Tags are the commit sha.
Containers run with `--network host`, loopback binding, `--restart unless-stopped`, `--stop-timeout 40` (`containers.sh`). No registry push is configured in the repository; images are built on the host **[C]**. Test and coverage reports are the only CI artifacts
(`backend-test-reports-<sha>`, `support-chat-e2e-<sha>`).

## 36.5 Environments

| Environment | Where | Data | Differences |
|---|---|---|---|
| CI | GitHub runners | throwaway PostgreSQL service, no content warehouse | offline models, dummy tokens |
| Throwaway chat stack | runner | own SQLite, DEBUG | support-chat only |
| Staging | host, `:8110` / `:3107`, `/opt/KGKG_staging` | sanitized copy of the portal DB; SMS/Sentry/Metis/host jobs disabled | **read production `kgkg_vec` with the warehouse mounted read-write (observed 2026-11-03, risk R5)** |
| QA | host, `:8120` / `:3117` / `:8130` | sanitized copy (`<db>_qa`); test accounts | CPU/memory caps; used nightly ([32](32-testing-and-qa.md) §32.5) |
| Production | host `/opt/KGKG`, `:8000` / `:3000` | live | changed only by a person via `kgkg-promote` |

Release state lives under `/opt/KGKG_release` (`state.env`, `logs/`, `db-backups/`, e2e evidence); working worktree `/opt/KGKG_work`.

## 36.6 Monitoring after a release

Do not treat a green deploy or HTTP 200 as health: check container health (`docker ps`), GlitchTip, metrics and alerts. Blackbox probes (`https://kgtechvault.com/`, `/kg-api/api/health/`), Prometheus targets, the 5-minute alert sweep and the independent
watchdog are described in [31](31-ops-files-reference.md) §31.2/31.5. `deploy.sh` publishes "what is live / how long since staged" as node-exporter textfile metrics.

## 36.7 Rollback and recovery

1. `ops/deploy/deploy.sh --rollback` (previous images; migrations stay applied — keep migrations additive).
2. If data is damaged: restore the pre-deploy database backup from `/opt/KGKG_release/db-backups` (covers the portal database engine in use; `kgkg_vec` coverage is **not verified**, R1).
3. `deploy.sh --status` shows what is live and the previous release.
4. Disaster recovery of the host is **not demonstrated** (no restore drill on record; SRS NFR-07 is manual). See [27](27-open-risks-and-decisions.md).

## 36.8 Secrets and configuration management

Runtime secrets live in `/opt/KGKG/KG_backend/.env.prod` and `/opt/KGKG/kg_frontend/.env.production` (never in git; mounted read-only into containers). `manage.py rotate_secrets` rotates them and `deploy.sh --reload` applies. gitleaks
scans every push; `.gitleaks.toml` is the allow-list. Variable names and defaults: [29](29-environment-reference.md). CI secrets are the five `DEPLOY_*` values above.

## 36.9 Security gates in the pipeline

shellcheck, hadolint, gitleaks, bandit (baseline), pip-audit, npm audit, trivy, CodeQL; the same bandit/pip-audit/npm audit run again inside the server gate. Exceptions are files with reasons: [32](32-testing-and-qa.md) §32.8.

## 36.10 Known limitations

Single host and no registry; production promotion depends on a person and on host access; `stage` turns red when the staging secret is missing; `strict` up-to-date branches is off and no reviews are required on `work`
(protection read 2026-11-04); `promote_guard.sh` not wired into `deploy.sh`; staging reads production vehicle content (R5); no demonstrated restore (R1); the host's actual timers and legacy units were not re-inspected **[U]**.
