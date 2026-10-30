# Evaluation criteria compliance matrix (13 criteria)

Status vocabulary: **Verified** (implemented and checked by execution or
direct inspection, evidence attached) · **Partially Verified** · **Implemented
but Not Verified** · **Not Implemented** · **Blocked** (needs records or
decisions the repository cannot provide). A document existing is never by
itself a "Verified".

| # | Criterion | Components | Status | Evidence | Verification method and latest result | Remaining gaps | Risk | Corrective action |
|---|---|---|---|---|---|---|---|---|
| 1 | Design & architecture documentation (SRS, backlog, big picture, diagrams) | `docs/01–15`, `docs/openapi.yaml`, `02-architecture/` | **Partially Verified** | `02-architecture/README.md`, `docs/openapi.yaml`, `01-requirements-and-traceability/` | Deployment diagram checked against `docker ps`/nginx/systemd; OpenAPI validated and enforced by `test_openapi_routes` (90/90 routes); two stale doc sections found and corrected | No formal SRS document, no backlog-tool export, no standalone ADR files; much design rationale lives inline | Medium | Write a short SRS from the traceability matrix; start ADRs for new decisions |
| 2 | Knowledge-management infrastructure & policies | `docs/` (in-repo), guidance content, CHANGELOG | **Partially Verified** | `12-knowledge-management/README.md`, `docs/README.md` maintenance protocol | Protocol in force since 2026-07 (docs ship with the change); 12 doc commits; onboarding path reproduced while building the QA stack | No separate wiki platform; ownership assigned by role, not yet to named people | Low–Medium | Assign named owners (from team records); quarterly doc review |
| 3 | Technical infrastructure for development | Git/GitHub, Docker images, GitHub Actions, staging, QA stack, Prometheus/Grafana/Loki/GlitchTip | **Verified** | `09-ci-cd/`, `02-architecture/`, `qa/` | Every tool exercised during this work (builds, staging-style stack, scans, monitoring probes) | No issue tracker history (templates just added); project-management tool not evidenced | Low | Use GitHub Issues with the new templates |
| 4 | Source-code history & traceability | Git (GitHub + server), 25+ deploy tags | **Partially Verified** | `00-assessment/BASELINE.md` §4; `git log` | 163 commits since 2026-06-19 inspected; recent commits explain the why; deploy tags map deployments to commits | **No history before 2026-06-19**; earlier messages inconsistent; several author identities for 2 people | Medium | Keep Conventional Commits (this work: every commit typed, explained, co-authorship attributed); unify author identities |
| 5 | CI/CD infrastructure | `.github/workflows/ci.yml`, `ops/deploy/` gate/stage/promote | **Verified** | `09-ci-cd/ci-run-*.{json,txt}` (first green run 40600862764; final-code run 40609938821), `REPRODUCE.md` | CI run 40609938821: all jobs green (850 backend tests, frontend unit tests, SAST, deps, secrets, image scans 0 HIGH/CRITICAL); staging and promotion gates in `ops/deploy` with role tests | CI on `work` had been red for 14 of 19 runs before this work (D-19, fixed); E2E/load/DAST run on the server, not triggered by CI | Medium | Make `kgkg-promote` require an E2E pass record for the sha |
| 6 | Versioning & release management | `VERSION`, deploy tags, `kgkg-promote`, rollback | **Partially Verified** | `10-release-management/` | Deploy tagging, staging-before-promote, typed promotion and rollback exist and are tested; SemVer introduced (1.0.0) and stamped into deploy tags | No alpha/beta channels (staging plays the RC role, stated honestly); no SemVer release has been promoted yet; release records start now | Medium | Promote 1.0.0 with a filled release record |
| 7 | QA/QC processes & tools | Test suites, gates, scanners, strategy | **Verified** (for this release) | `01-…/TEST_STRATEGY.md`, `03`–`08`, `TEST_SUMMARY_REPORT.md` | Unit, integration, E2E, load, SAST, DAST, dependency and image scanning all executed with machine output; 30 defects found, 29 fixed with regression tests | No TestRail/SonarQube (equivalents: JUnit artifacts, bandit, coverage reports); no formal QA sign-off record yet | Low | Fill a release record per release |
| 8 | Post-release support & service management | In-product tickets (`CompanyRequest`), GlitchTip, alerting, issue templates | **Partially Verified** | `11-operations-and-support/SUPPORT_AND_INCIDENTS.md` | Ticket lifecycle verified by 28 tests; live usage counted (5 tickets, 9 purchase requests); alerting/watchdog running | Low volume (small customer base); no SLA; GitHub defect templates have no history yet | Medium | Track SLAs on tickets; file defects via templates |
| 9 | Automated test coverage | coverage.py (branch), node test coverage | **Verified (measured), target partially met** | `08-code-coverage/` | Honest backend 55.0 % lines / 46.9 % branches; critical auth/authz modules 96–100 % branch; CI floor 52 % enforced | Overall below the 80 % ambition; offline tooling 18 % | Medium | Raise floor each release; next: `portal.py`, `rag/service.py`, `shield.py` |
| 10 | DevOps maturity | Containers, gated deploy, monitoring, incident tooling | **Verified** | `02-architecture/`, `09-ci-cd/`, `11-operations-and-support/`, `06-performance-and-load/` | Containerized blue/green backend swap with auto-rollback; monitoring stack and paging watchdog running; load tests showed production unaffected; restore of off-host backup verified 2026-10-27 (per `docs/11`) | Two nginx files had been hand-maintained (D-08, now versioned, still installed by hand); staging shares the production host | Medium | Install nginx from the release (A-03) |
| 11 | Team mastery of domain & market | Domain model, ingestion, diagnostics, terminology, RAG in code | **Partially Verified** (technical); **Blocked** (market) | `13-team-and-domain-evidence/README.md` | Domain depth visible and verifiable in code and evaluation work | No competitor/market analysis or customer-research records in the package | Medium | Add dated market and customer evidence (template T-11) |
| 12 | Human-resource participation per lifecycle role | — | **Blocked** | template T-12 | Repository cannot evidence roles or allocation; commit counts are not staffing data | All | High (for the evaluation) | Fill T-12 from contracts/insurance records |
| 13 | Key personnel expertise & qualifications | — | **Blocked** | template T-13 | No personnel records were provided; none were invented | All | High (for the evaluation) | Fill T-13 with CVs and diplomas |

## The evaluator's stated deficiency

"Failure to implement and verify any software testing activities (unit,
integration, E2E, performance/load, security/penetration)": see
`DEFICIENCY_CLOSURE.md`. Short form: unit, integration, E2E,
performance/load and automated security testing are now implemented,
executed and evidenced; independent penetration testing is **not** done.

## Update 2026-10-29 (branch `claude/testing-cicd-assessment-review-1u9yhl`, based on `work` 174654d)

The 2026-10-28 rows above are kept as written. This update changes the following rows; every
claim below is backed by a commit and a test on that branch, and CI was green on each push.

| # | Status now | What changed | Evidence | Still open |
|---|---|---|---|---|
| 1 | **Partially Verified** (narrower gap) | Formal SRS: 20 FR + 14 NFR, ISO/IEC/IEEE 29148 / ISO 25010, each naming its verifying tests. Six ADRs for standing decisions, with their real dates | `docs/00-srs.md`, `docs/adr/` | No backlog-tool export |
| 5 | **Verified** | First fully green staging on the server (`1ce029a`, run 40891553053); CI's key refused `deploy` by the gate (run 30 of the retired workflow). The corrective action is implemented: `kgkg-promote` requires a passing, full, ≤72 h E2E record for the exact commit (written by `qa/run_e2e.sh`); an override is a typed phrase and is logged | `ops/deploy/kgkg-promote`, `ops/deploy/test_promote.sh` (22 checks; 15 fail on the previous script), CI "Operations tests" | The E2E gate is not yet exercised on the server. The server gate does not run bandit or the audits, so `8fa94dd` shipped with red CI |
| 6 | **Partially Verified** | Release step 3 (E2E on the same commit) is now enforced by tooling | `RELEASE_POLICY.md`, ADR-0004 | 1.0.0 promoted 2026-10-29 (`8fa94dd`, tag `deploy-20261029-084649`); release record and load/DAST steps are still procedure |
| 7 | **Verified** | Mutation testing of the authorization modules; 14 surviving mutants were real blind spots and are now killed. Two new defects found and fixed (D-41, D-42) | `03-unit-testing/mutation/`, `api/test_access_rules.py`, `CORRECTIVE_ACTIONS.md` | Equivalent and cosmetic survivors listed with reasons |
| 9 | **Verified (measured), target partially met** | Backend 850 → 1141 tests after merging `work` (PostgreSQL, random order); combined coverage 52.9 → 60 %. CI floor 56. team 24→90 %, reporting 0→98 %, adminops 37→77 %, shield 69→95 %, rag/service 61→90 %, labortimes/sst → 91 % | CI runs on the branch; `api/test_team.py`, `test_adminops.py`, `test_exports.py`, `rag/test_service_paths.py` | 80 % overall ambition not met; `portal.py` 64 % is next |

## Update 2026-10-30 (Tier-2 governance and release management, branch `tier2/governance-and-release`)

The rows above are kept as written. The full audit that drove this work, with
per-criterion scores before and after, is
[`INFRA_MATURITY_ASSESSMENT_2026-10-29.md`](INFRA_MATURITY_ASSESSMENT_2026-10-29.md).

| # | Status now | What changed | Evidence | Still open |
|---|---|---|---|---|
| 1 | **Partially Verified** (narrower again) | Three documents corrected against the host: the Cloudflare Tunnel described in the present tense is not running (CI uses direct SSH), and the "future PostgreSQL move" in `docs/01` and the `db.sqlite3` box in the `docs/02` topology diagram both became true on 2026-10-29 | `docs/01-overview.md`, `docs/02-architecture.md`, `docs/11-operations-deployment.md` | No backlog-tool export |
| 2 | **Partially Verified** (materially better) | `.gitignore` carried a blanket `*.md` with **no negations**, so every document in the repository — the SRS, the six ADRs, this whole package — was tracked only because someone used `git add -f`, and any new document would silently never have been committed. ADR-0006 is titled "docs as code". Narrowed to `/*.md` plus named negations | `.gitignore`, PR #13 | No wiki platform; owners still assigned by role, not to named people |
| 3 | **Verified** | `CODEOWNERS` routes review by area; a pull-request template makes the verification claim and the rollback plan part of every change | `.github/CODEOWNERS`, `.github/pull_request_template.md` | Issue tracker now seeded (below), but with days of history, not months |
| 4 | **Verified** | `main` protected: four required checks, strict, PR required, `enforce_admins`, no force-push, no deletion, conversation resolution. `.mailmap` folds nine author identities into two people plus the assistant and two automations — `git log --format='%aN <%aE>'` now reports 5 distinct identities, down from 9, with history byte-identical | branch protection API; `.mailmap` | No history before 2026-06-19 |
| 5 | **Verified** | Unchanged from 2026-10-29 plus: `main` is now a gate rather than a suggestion | — | E2E, k6 and ZAP still not CI-triggered |
| 6 | **Partially Verified → substantially closed** | `v1.0.0` tagged and released with a **filled** release record reconstructed from machine evidence, stating plainly that it was promoted with CI red, that no record was filled at the time, and that load and DAST were run on neither of its commits. `VERSION` bumped 1.0.0 → 1.1.0 — it had not moved across two deploys, one of which carried new capability — and `RELEASE_RECORD_v1.1.0.md` is **open before** the promote, with the two owed rows named as blocking | `RELEASE_RECORD_v1.0.0.md`, `RELEASE_RECORD_v1.1.0.md`, `docs/CHANGELOG.md`, tag `v1.0.0` | Still no alpha/beta channel (staging is the RC, stated honestly); 1.1.0 must not ship until load and DAST are run |
| 7 | **Verified** | Unchanged | — | No independent penetration test |
| 8 | **Partially Verified → substantially closed** | First written **SLA** (99.5 % monthly, chosen because the measured 7-day figures were 100/99.99/98.80/98.63 % and 99.9 % would already be a breach), P1–P4 response targets, business hours, maintenance policy, and a four-level on-call and escalation path with its limitations stated — two people, no rota, SMS-only paging, no severity routing. First **postmortem**, for the 49-minute loss of application-metrics visibility on 2026-10-27. Open actions filed as GitHub issues | `SLA_AND_ONCALL.md`, `postmortem-2026-10-27-app-metrics-blind.md`, repository issues | No financial remedy, no 24/7 rota; error-budget-burn alerting not implemented |
| 9 | **Verified (measured), target partially met** | Unchanged at 58 %, floor 57 | — | 80 % ambition unmet |
| 10 | **Verified** | `SECURITY.md` gives a private reporting channel with stated response targets and states, in the document itself, that no independent penetration test has been commissioned | `SECURITY.md` | Single host; no SLO burn alerting; `xrdp` still installed |
| 11–13 | **Blocked**, unchanged | Nothing was invented | templates T-11/T-12/T-13 | Needs contracts, CVs, market research |

### The licence question, which was not on anyone's list

The repository is **public** and had no `LICENSE`, no `NOTICE` and no
`SECURITY.md`. For a commercial product that is an unforced ambiguity: the code
was readable by anyone with no stated terms. Resolved on the owner's decision —
a proprietary all-rights-reserved notice that permits reading for evaluation,
audit and security research and nothing else, plus a `NOTICE` pointing at where
third-party licences are pinned. The repository stays public so that this
evidence package remains inspectable.
