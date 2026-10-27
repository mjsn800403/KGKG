# Risk-based test strategy and test plan

Applies to KGTechVault from revision `abdef81` onward. Owner: engineering
lead. Review: at every minor release, and whenever a subsystem below changes
its trust boundary.

## 1. Approach

Risk = impact × exposure, scored 1–5 each. Test depth follows risk: anything
that decides *who may see paid content* or *what a customer is billed for*
is tested exhaustively at unit and integration level and again end-to-end;
display-only code is tested where logic exists. Mocks are limited to true
externals (SMS provider, Cloudflare Turnstile, the LLM API, the embedding
model in CI); the database, the per-car SQLite manuals, the rate-limit store
and the org graph are always real.

## 2. Test levels and where they run

| Level | Tool | Location | Runs | Environment |
|---|---|---|---|---|
| Unit + integration (backend) | Django test runner, coverage.py (branch) | `KG_backend/api/test_*.py`, `tests*.py`, `api/rag/test_*.py` | Every push (CI) and in the server gate before staging | Throwaway SQLite, temp per-car DBs |
| Unit (frontend) | `node:test` with built-in coverage | `kg_frontend/src/**/__tests__/` | Every push (CI) | Node 20 |
| Operations tests | bash + unittest | `ops/deploy/test_gate_roles.sh`, `ops/observability/test_*.py`, sanitizer self-test | Every push | CI runner |
| Smoke | curl | `ops/deploy/smoke.sh` | Every staging and production deploy | Staging / production |
| End-to-end | Playwright 1.52 (Chromium; public pages also Firefox, Pixel 7) + axe-core | `qa/e2e/` via `qa/run_e2e.sh` | Before every promotion; after any auth/UI change | QA stack (`qa/stack.sh`) |
| Performance | k6 0.57 | `qa/perf/` via `qa/perf/run_perf.sh` | Before each minor release; after changes to retrieval, DB access or worker config | QA stack, capped resources |
| SAST | bandit 1.9.4 (baseline-gated) | CI `security` job | Every push | CI runner |
| Dependency / secrets / images | pip-audit, npm audit gate, gitleaks, Trivy, hadolint, shellcheck | CI `security` and `images` jobs | Every push | CI runner |
| DAST | OWASP ZAP (baseline + authenticated full scan) | `qa/dast/run_zap.sh` | Before each minor release | QA stack only (never production) |
| Retrieval quality | `manage.py run_evalsuite` / `eval_rag` on versioned gold sets | `KG_backend/Database_warehouse/_rag/eval/gold/` | After index rebuilds or ranking changes | Server, read-only index |

The QA stack (`qa/stack.sh`) is a throwaway backend + frontend + proxy on a
sanitized copy of the production database, with SMS, Sentry, Turnstile, the
LLM, host jobs and the production feedback store all cut off, and CPU/memory
caps so load and scans cannot starve production. Its proxy mirrors
production's routing, headers and media gate, without the WAF and rate
limits, so DAST and load tests measure the application itself.

## 3. Risk register for testing

| ID | Subsystem | Failure mode | I | E | Risk | Required levels | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| R1 | Entitlements (`access.py`, `orggraph*.py`) | A seat sees a car or document layer the company did not buy; a root widens an admin exception | 5 | 4 | 20 | Unit, integration, E2E | ≥95 % branch coverage on `access.py`/`quota.py`; every grant write path has a negative test; cross-tenant E2E refusals pass |
| R2 | Paid media gate (`mediaauth.py` + nginx) | Path tricks serve another company's images | 5 | 4 | 20 | Unit, E2E (raw HTTP), DAST | Dot-segment, encoded and double-slash variants refused; cache cannot be primed to leak |
| R3 | Authentication (`portal.py`, `admin_auth.py`) | Account takeover, enumeration, OTP brute force, session reuse | 5 | 4 | 20 | Unit, integration, E2E | Identical errors for unknown/wrong/invited; OTP 5-try and daily caps; single session; Turnstile fail-closed |
| R4 | Abuse controls (`ratelimit.py`, contentguard, shield) | Scraping of paid manuals; brute force | 4 | 4 | 16 | Unit, integration, E2E | Limits exact at boundary, shared across workers, fail-safe on store failure; bare API calls refused by the shield |
| R5 | Content serving (`views.py`, `parts.py`) | IDOR, traversal, SQL injection, 500s on bad input | 4 | 4 | 16 | Integration, DAST | No 5xx on hostile input; traversal → 404; metacharacters literal |
| R6 | Retrieval assistant (RAG) | Wrong or ungrounded answers, slow responses, data from another car | 4 | 3 | 12 | Unit, retrieval eval, load | Gold-set metrics not below last accepted run; p95 < 4 s at expected load |
| R7 | Purchase → company → login flow | Customer cannot get access after paying | 4 | 2 | 8 | Integration | End-to-end request→approval→login test passes |
| R8 | Staging / QA isolation | Test traffic alters production data | 4 | 3 | 12 | Integration, config tests | Staging and QA use their own feedback store; seeder refuses production DB |
| R9 | Availability under load | Slow pages, errors at peak | 3 | 2 | 6 | Load, stress, soak | See §4 |
| R10 | LLM output in the UI | XSS or link injection from model output | 4 | 2 | 8 | Frontend unit | Sanitizer strips script/handlers/`javascript:`; buttons limited to an allow-list |

I = impact, E = exposure (1–5).

## 4. Performance acceptance criteria (proposed, with derivation)

Observed production demand on 2026-10-27: 3,941 requests in 18 h, busiest
hour 792 requests (0.22 req/s). Expected-load target is set at 10 concurrent
technicians with 1–2 s think time (~19 req/s, about 88× the observed peak)
to leave headroom for growth.

| Metric | Criterion | Why this number |
|---|---|---|
| Error rate | < 1 % | Standard availability floor for an interactive product |
| Landing page p95 | < 1.5 s | Server-rendered page; the baseline single-user p95 was 18 ms, so 1.5 s flags real degradation, not noise |
| Signed-in API p95 (`me`, fleet, catalog) | < 500 ms | Single-user baseline p95 35 ms |
| Retrieval assistant p95 | < 4 s | CPU embedding + vector search; single-user baseline p95 1.26 s; the chat UI shows progress and the LLM step adds its own latency on top |
| Production impact during tests | Production `/api/health/` stays 200, latency within normal (≤ 50 ms) | Tests share the host with production |

These are engineering targets set by the team on measured baselines, not
external or contractual SLAs.

## 5. Entry and exit criteria for a release

Entry: CI green on the commit (tests, coverage floor, lint, build, all
security gates); staging smoke passed on that commit.

Exit (promotion): E2E suite green on the QA stack for that commit; no open
defect of severity High or Critical; load profile `load` within §4; DAST
full scan reviewed with no unresolved High finding; release notes written.

## 6. What is deliberately not automated

* Completing Cloudflare Turnstile. Automation must not solve a CAPTCHA, so
  E2E proves the server rejects an unverifiable token and drives signed-in
  journeys with sessions minted by `seed_qa_fixtures`; the full
  password + Turnstile + OTP success path is covered at integration level
  with only the two external services faked.
* LLM answer quality at scale. Each answer costs an external API call;
  answer-level evaluation (`run_answer_eval`) is run on demand, and domain
  correctness needs a qualified automotive technician (see
  `15-final-audit-report/AUDITOR_CHALLENGE.md`).
* Independent penetration testing. Automated SAST/DAST here is not a
  substitute; scope for an external test is in `07-security/`.
