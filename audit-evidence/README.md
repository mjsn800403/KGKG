# Audit evidence — KGTechVault quality remediation (2026-10-27/28)

Start here:

1. `15-final-audit-report/TEST_SUMMARY_REPORT.md` — what was tested, results, defects, readiness
2. `15-final-audit-report/CRITERIA_MATRIX.md` — the 13 evaluation criteria, status and evidence
3. `15-final-audit-report/DEFICIENCY_CLOSURE.md` — the evaluator's stated deficiency, discipline by discipline
4. `15-final-audit-report/AUDITOR_CHALLENGE.md` — adversarial self-review and remaining weaknesses
5. `15-final-audit-report/EXECUTIVE_SUMMARY_FA.md` — خلاصهٔ مدیریتی فارسی

| Folder | Content |
|---|---|
| `00-assessment` | Verified baseline before any change (tests, coverage, SAST at `abdef81`) |
| `01-requirements-and-traceability` | Risk-based test strategy and plan; requirement → risk → test → defect → verification matrix |
| `02-architecture` | Architecture document index, verified deployment diagram |
| `03-unit-testing` | Unit suites (backend, frontend) |
| `04-integration-testing` | Integration suites; retrieval (RAG) evaluations 2026-08-05 and 2026-10-27 |
| `05-e2e-testing` | Playwright suite, journeys, JUnit/JSON results |
| `06-performance-and-load` | k6 report, raw results and resource samples for two runs |
| `07-security` | Security assessment, media-gate reproduction, DAST reports |
| `08-code-coverage` | Coverage report and per-file data |
| `09-ci-cd` | Pipeline description, local reproduction, green CI run record |
| `10-release-management` | Versioning and release policy, release record template |
| `11-operations-and-support` | Ticketing, defect and incident process |
| `12-knowledge-management` | Knowledge stores, update process, internal vs third-party knowledge |
| `13-team-and-domain-evidence` | Domain evidence from code; templates for team records (pending) |
| `14-risk-and-corrective-actions` | Defect register (29), open actions, unresolved observation |

Test code itself lives with the product: `KG_backend/api/test_*.py`,
`kg_frontend/src/lib/__tests__/`, `qa/` (QA stack, E2E, load, DAST,
evaluation runners), `docs/openapi.yaml`.

Nothing here contains credentials or customer personal data: the QA stack
runs on a sanitized database copy, seeded test accounts have per-run
passwords that are not stored in the repository, and the one log excerpt
from production has the tester's IP masked.
