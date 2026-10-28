# Test summary report

| | |
|---|---|
| Product | KGTechVault (KGKG) — automotive technical documentation platform with retrieval assistant |
| Version | 1.0.0 (first SemVer version; becomes a release when promoted) |
| Code under test | branch `qa-audit` (based on production-candidate `abdef81`); CI-verified at `1a0eba8`; later commits add only a CSS fix, a JSON-LD escape and documents |
| Period | 2026-10-27 – 2026-10-28 |
| Environments | GitHub Actions (ubuntu-24.04); production host's isolated QA stack (`qa/stack.sh`, sanitized DB copy, capped resources); production host QA venv |
| Prepared by | Development team, with AI-assisted engineering (Claude). Not an independent audit |

Every number below comes from a machine-generated file in this package; the
file is named next to it.

## 1. Executed suites

| Suite | Level | Executed | Passed | Failed | Skipped | Evidence |
|---|---|---|---|---|---|---|
| Backend (Django) | Unit + integration | 843 | 842 | 0 | 1 (needs a local crawl dataset) | CI run 40600862764 (`09-ci-cd/`); JUnit + coverage artifact retained to 2027-01-25 |
| Frontend (`node:test`) | Unit | 178 | 177 | 0 | 1 (pricing — business decision D-28) | CI run 40600862764 |
| Operations (deploy gate roles, watchdog, sanitizer) | Unit | 32 | 32 | 0 | 0 | CI run 40600862764 |
| E2E (Playwright: Chromium, Firefox, Pixel 7) | System | 41 | 41 | 0 | 0 | `05-e2e-testing/results/` (commit `1a0eba8`) |
| Load — baseline / load / stress / soak | Performance | 4 profiles, 39,521 requests | thresholds met in baseline, load, soak | stress 0.64 % errors (D-20) | — | `06-performance-and-load/run1-recycle-2000/` |
| Stress re-test after D-20 fix | Performance | 10,866 requests | 0.00 % errors | 0 | — | `06-performance-and-load/` (run 2) |
| Retrieval evaluation (offline, gold sets) | AI quality | 5 sets, hybrid pipeline | — (metrics, not pass/fail) | — | — | `04-integration-testing/rag-eval-2026-10-27/` |
| SAST (bandit) | Security | full backend | no new issues | 0 | 40 triaged baseline | CI |
| Dependency, secret, image scans | Security | pip-audit, npm, gitleaks, Trivy ×2 | all pass | 0 | 3 dated pip exceptions | CI |
| DAST (ZAP) | Security | baseline, full, API | 0 FAIL rules in completed scans | 0 | — | `07-security/` |

Baseline before remediation (`abdef81`): 427 backend tests, no frontend,
E2E, load, SAST or DAST.

## 2. Coverage

Backend, honest measure (test modules excluded, branches on): lines
**55.0 %**, branches **46.9 %**, combined **52.9 %** (baseline 49.6 / 38.7 /
46.9). Request-path code 69.7 % lines / 59.6 % branches; authorization,
authentication, media gate, rate limiter, quota and ticket modules 96–100 %
branch. Frontend tested modules 87–100 % branch. Details and exceptions:
`08-code-coverage/COVERAGE_REPORT.md`. CI floor ratcheted 50 → 52.

## 3. Defects

29 recorded (`14-risk-and-corrective-actions/CORRECTIVE_ACTIONS.md`), plus one unresolved observation (O-1):

| Severity | Found | Fixed in code | Open |
|---|---|---|---|
| Critical | 2 (D-03 entitlement leak, D-06 cross-company paid media) | 2 | 0 in code — **both still live in production until promotion** |
| High | 7 | 7 | 0 in code (D-07 also needs the nginx files installed, A-02) |
| Medium | 11 | 11 | 0 |
| Low | 9 | 8 | 1 (D-28, business decision) |

Every fixed defect has a regression test that failed before the fix and
passes after it, except configuration-only items (D-08, D-09) and D-27
(verified manually).

## 4. Performance (QA stack, capped resources, same host as production)

| Profile | Throughput | Errors | Landing p95 | API p95 | Assistant p95 |
|---|---|---|---|---|---|
| Load, 10 users | 19.5 req/s (~88× production's busiest hour) | 0.00 % | 21 ms | 38 ms | 2.24 s |
| Soak, 8 users, 20 min | 17.9 req/s | 0.04 % | 20 ms | 37 ms | 2.28 s |
| Stress to 50 users (after fix) | 30.2 req/s | 0.00 % | 28 ms | 1.90 s | 11.8 s |

Production health during all load runs: 607 samples, all 200, max 9 ms.
Capacity knee between 10 and 25 users (embedding is CPU-bound; recommendation
A-06).

## 5. Security findings by severity (after remediation)

No open Critical or High finding in the code. Open: CSP `style-src
'unsafe-inline'` (Medium, accepted with reason), CSRF defence relies on
SameSite=Lax (Medium, recommendation), COEP not set (Low, intentional).
Production exposure remains for D-06, D-07, D-17 until release + A-02.

## 6. Limitations and unverified areas

* No independent penetration test; automated scans are not a substitute.
* Turnstile + SMS OTP success path not exercised end-to-end (by design;
  integration-tested).
* No expert (automotive technician) review of answer correctness.
* LLM answer quality last measured 2026-08-05 (462 paid calls); not re-run.
* Admin console, team-management UI, SSE dashboard, PDF reports and WebKit
  are not in the E2E suite.
* Mutation testing not performed.
* Load tests share the production host; numbers are conservative, not lab
  figures.

## 7. Release readiness

The code on `qa-audit` meets the exit criteria in
`01-requirements-and-traceability/TEST_STRATEGY.md` §5 except the
documented gaps above. Recommendation: **promote as a security release
without delay** (D-06 is exploitable in production today), install the two
nginx files in the same window (A-02), and re-run E2E on the promoted
commit. This is a recommendation; the promotion decision and approval belong
to the release owner.
