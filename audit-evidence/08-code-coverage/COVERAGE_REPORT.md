# Code coverage (criterion 9)

Measured 2026-10-27 with coverage.py 7.17 (`--branch`), Django test runner,
on the remediation branch (product code identical to `f7d3856`). Every test
module (`test_*.py`, `tests.py`, `tests_*.py`) and migrations are excluded
from the measured code — the CI configuration before this release did not
exclude `tests.py`/`tests_parts.py`, which inflated its figure (defect D-01).
Raw per-file data: `backend-coverage-final.json`; baseline:
`../00-assessment/baseline-coverage-abdef81.json`.

## Backend totals

| | Baseline `abdef81` | Now | Change |
|---|---|---|---|
| Tests | 427 | **829** | +402 |
| Line coverage | 7,498 / 15,112 = 49.6 % | 8,348 / 15,187 = **55.0 %** | +5.4 pt |
| Branch coverage | 1,980 / 5,118 = 38.7 % | 2,413 / 5,144 = **46.9 %** | +8.2 pt |
| Combined (CI gate figure) | 46.9 % | **52.9 %** | CI floor raised 50 → 52 |

## By tier (now)

| Tier | Lines | Branches | Note |
|---|---|---|---|
| Request path: serving, auth, entitlements, RAG serving (9,134 statements) | **69.7 %** | **59.6 %** | What customers exercise |
| Ingestion / build pipeline (2,554) | 52.9 % | 42.8 % | Crawlers, parsers, index build — run by operators |
| Offline tooling: management commands, evaluation suite (3,499) | 17.9 % | 15.7 % | One-off and research commands; largely untested |

## Critical modules (line % / branch %)

| Module | Baseline | Now |
|---|---|---|
| `api/access.py` (entitlements) | 65 / 51 | **99 / 96** |
| `api/quota.py` (AI allowance) | 68 / 55 | **100 / 100** |
| `api/portal_auth.py` | 90 / 75 | **100 / 100** |
| `api/admin_auth.py` | 97 / 93 | **100 / 100** |
| `api/mediaauth.py` (paid media gate) | 22 / 0 | **100 / 100** |
| `api/ratelimit.py` | 52 / 39 | **100 / 97** |
| `api/orggraph_api.py` | 63 / 42 | **98 / 97** |
| `api/requests_api.py` (tickets) | 87 / 64 | **100 / 98** |
| `api/parts.py` | 68 / 51 | **97 / 90** |
| `api/views.py` (content serving) | 39 / 29 | 79 / 82 |
| `api/portal.py` (accounts, login, admin) | 56 / 42 | 67 / 56 |
| `api/orggraph.py` | 80 / 63 | 85 / 71 |
| `api/rag/scoring.py` | 98 / 95 | 98 / 95 |
| `api/rag/retrieve.py` | 77 / 60 | 77 / 60 |
| `api/rag/service.py` | 48 / 31 | 48 / 31 |
| `api/shield.py` | 72 / 58 | 72 / 58 |

## Frontend

`node --test --experimental-test-coverage` over `src/lib` (178 tests):
`chatPrompt.js` 100 / 92, `contextualize.js` 100 / 91, `sanitizeHtml.js`
98 / 94, `pricing.js` 100 / 100, `packages.js` 100 / 100,
`friendlyError.js` 100 / 100, `faTerms.js` 100 / 87, `manualContent.js`
51 / 90 (its DOM-mutating half needs a browser). React components are covered
by the E2E suite, not by unit coverage, and no figure is claimed for them.

## Against the directive's proposed targets

| Target | Status |
|---|---|
| ≥80 % line coverage on suitable application code | **Not met overall** (55 %; request path 70 %). |
| 70–80 % branch on testable logic | Not met overall (47 %; request path 60 %). |
| 90–95 %+ on critical deterministic and authorization logic | **Met** for entitlements, quota, both auth modules, media gate, rate limiter, org-graph API, tickets, parts. |

Justified exceptions, to be closed incrementally rather than excluded:
offline research commands (`run_evalsuite`, `build_goldset`, `eval_report`,
…) are exercised by running them, not by unit tests; crawler code depends on
third-party sites. Next increments by risk: `api/portal.py` admin
endpoints, `api/rag/service.py`, `api/shield.py`. The CI floor is a ratchet
(`ops/deploy/coverage_min`): it may only move up.

Coverage shows which lines ran, not that they are right. The assertions in
the new suites are behavioural (each new suite found real defects, see
`../14-risk-and-corrective-actions/`); mutation testing was not run in this
remediation (gap noted in the final report).
