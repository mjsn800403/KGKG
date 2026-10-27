# Technical baseline assessment

Verified starting condition of KGTechVault before the 2026-10-27 quality
remediation. Every figure here was produced by a command run on that date
against the revision named below; the raw outputs sit next to this file.

| Item | Value |
|---|---|
| Revision assessed | `abdef81` (branch `work`, production-candidate, staged 2026-10-27 16:07 UTC) |
| Assessed on | 2026-10-27, production host 103.75.197.155 (Ubuntu 24.04, 16 vCPU, 31 GiB) |
| Method | Read the repository; ran the full backend suite with branch coverage; ran bandit; inspected CI, deploy, nginx and running containers |

## 1. What the product is (verified, not taken from the docs)

| Area | Verified implementation |
|---|---|
| Backend | Django 5.2 (`KG_backend/`, app `api`, ~23 kLOC Python excluding tests), gunicorn gthread 3 workers × 8 threads, in Docker (`ops/docker/backend.Dockerfile`) |
| Frontend | Next.js 16.4 / React 19 (`kg_frontend/`, ~7.2 kLOC TS/TSX/CSS + JSX components), Node 20, in Docker |
| Persistence | SQLite (`db.sqlite3`, ~630 MB) for accounts, grants, logs; one SQLite DB per vehicle manual (237 vehicles in the catalog) under `Database_warehouse/` (~142 GB); manual media under `static_warehouse/` (~65 GB) |
| AI / retrieval | Local RAG: bge-m3 embeddings (sentence-transformers, CPU), sqlite-vec index `_rag/index.rag.db` (~11 GB), FTS5, hybrid scoring, semantic cache, human-feedback store; a deterministic DTC/symptom rule engine per car (`/api/diagnose`); answer phrasing by an external LLM API (Metis) from the Next.js `/api/chat` route |
| AuthN | Username/e-mail + password (PBKDF2), Cloudflare Turnstile, SMS one-time code when a phone is on file; HttpOnly session cookie, single session per account; separate platform-admin login with 2FA |
| AuthZ | Company → seat (4-level role ladder) → per-car and per-document-layer grants; org graph with root/limited views; AI eligibility tied to the "manual" package; per-user AI quota |
| Edge | Cloudflare → nginx (ModSecurity 3 + OWASP CRS, `limit_req` zones, security headers, auth_request media gate) → containers on loopback |
| Async / jobs | Host-job spool bridge (`ops/hostjobs`), systemd timers (alerts, watchdog), SSE event stream |
| Observability | Prometheus, Grafana, Loki/Alloy, cAdvisor, node-exporter, blackbox, GlitchTip (Sentry protocol), SMS-paging watchdog |
| Delivery | GitHub Actions CI on every push; server-side gate → staging on a sanitized copy of the production DB → manual `kgkg-promote <sha>` → blue/green backend swap with automatic rollback |

## 2. Test and quality controls that already existed

| Control | State at `abdef81` |
|---|---|
| Backend automated tests | **427 tests, all passing**, 135 s (`baseline-test-run-abdef81.txt`). Django `TestCase`/`unittest`; 37 test modules covering RAG scoring/retrieval, feedback, rate limiting, purchase→login flow, recovery, security headers, org graph, pipeline, parsers |
| Coverage measurement | In CI, statement coverage, floor 50 % (`ops/deploy/coverage_min`) |
| Frontend tests | **None** (no test runner in `kg_frontend/package.json`) |
| End-to-end tests | **None.** `ops/deploy/smoke.sh` runs ~25 HTTP status checks against staging and production |
| Performance / load tests | **None** |
| SAST | **None** (no static security analyser in CI) |
| DAST | **None** |
| Supply chain / secrets | pip-audit, npm-audit gate, gitleaks, Trivy (both images), hadolint, shellcheck — all failing closed in CI |
| Lint | ESLint with a warnings ratchet (116) |

## 3. Measured quality at baseline

Honest coverage (all test modules excluded, branch coverage on), from
`baseline-coverage-abdef81.json`:

| Metric | Value |
|---|---|
| Line coverage | 7,498 / 15,112 = **49.6 %** |
| Branch coverage | 1,980 / 5,118 = **38.7 %** |
| Combined (coverage.py "total") | **46.9 %** |

The CI figure was higher than this because its omit pattern (`*/test_*`)
did not exclude `api/tests.py` and `api/tests_parts.py`, so ~510 lines of test
code counted as covered application code. Recorded as defect D-01.

Lowest-covered request-path modules: `views.py` 36 %, `adminops.py` 37 %,
`rag/service.py` 43 %, `ratelimit.py` 49 %, `portal.py` 52 %,
`orggraph_api.py` 57 %, `access.py` 61 %.

Bandit (medium+ severity, `baseline-bandit-abdef81.json`): 46 findings —
3 HIGH B324 weak hash, 3 HIGH-confidence B613 bidi characters, 29 B608
string-built SQL, 10 B310 urlopen, 1 B108 temp path. Triage in
`07-security/SECURITY_ASSESSMENT.md`.

## 4. Source history available

163 commits on `work` from 2026-06-19 to 2026-10-27 (172 including this
remediation's first commits at the time of counting), 7 author identities
(2 people plus CI/deploy bots), 25 `deploy-*` tags. Roughly a third of
subjects follow Conventional Commits. **No history exists before
2026-06-19** — earlier development of the crawler, parser and catalog is not
in version control, and nothing in this package claims otherwise.

## 5. Highest-risk gaps found at baseline

1. No E2E, load, DAST or SAST evidence — the four disciplines the evaluator named beyond unit tests.
2. Authorization and entitlement logic (`access.py`, `orggraph*.py`) under-tested for a paid, multi-tenant product.
3. Media gate correctness depends on nginx/app agreement that nothing tested.
4. Configuration drift: two nginx files and a staging symlink existed only on the server.
5. Staging shared production's writable RAG feedback store.
6. Coverage figure in CI overstated by counting test files.

Items 2–6 each turned into a confirmed defect; see
`14-risk-and-corrective-actions/CORRECTIVE_ACTIONS.md`.
