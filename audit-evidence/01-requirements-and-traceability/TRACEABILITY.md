# Requirements → risk → tests → results → defects → verification

Requirements are the product's security and business rules as implemented
and documented (`docs/01`, `docs/06`, `docs/08`); risk ids refer to
`TEST_STRATEGY.md` §3, defect ids to `../14-risk-and-corrective-actions/CORRECTIVE_ACTIONS.md`.
Latest results: `../15-final-audit-report/TEST_SUMMARY_REPORT.md`.

| Req | Requirement | Risk | Automated tests (level) | Defects found → fixed | Verification |
|---|---|---|---|---|---|
| RQ-01 | A seat can open only vehicles and document layers its company bought or the platform admin granted | R1 | `test_qa_access.py` (89, unit/integration), `test_qa_orggraph_authz.py` (29), `tests.py`, `test_orggraph.py`; E2E `authz.spec.js` | D-03, D-04, D-05 | Regression tests fail before / pass after `b76c47a`; full suite green |
| RQ-02 | Users of one company never see another company's data (requests, org graph, users, manuals) | R1, R5 | `test_qa_requests.py`, `test_qa_orggraph_authz.py`, `test_qa_catalog.py`; E2E `authz.spec.js` "another company cannot see" | — | Passing |
| RQ-03 | Paid media is served only to entitled users, whatever the path spelling | R2 | `test_qa_mediaauth_paths.py`, `MediaAuthTests`; E2E `media.spec.js` (raw HTTP, cache priming) | D-06, D-07, D-08 | Reproduced on production wiring before; 403 after (`07-security/media-gate/`) |
| RQ-04 | Login resists enumeration, brute force and session reuse; bot check fails closed | R3 | `test_qa_auth.py` (OTP caps, single session, identical errors, Turnstile), `test_security.py`, `test_purchase_flow.py`; E2E `auth.spec.js` | D-14 | Passing |
| RQ-05 | Signed-out users cannot reach signed-in pages or APIs; logout revokes the session server-side | R3 | E2E `auth.spec.js` (redirect with `next=`), `session.spec.js` (logout revokes token); smoke | — | Passing (41/41 E2E) |
| RQ-06 | Rate limits are exact, shared across workers and fail safe | R4 | `test_qa_ratelimit.py`, `api/rag/test_ratelimit.py` | D-15 | Passing |
| RQ-07 | Manual content cannot be scraped with a bare API client | R4 | E2E `session.spec.js` "content shield"; `test_shield.py`, `test_contentguard.py` | — | Passing |
| RQ-08 | Hostile input never causes server errors or query manipulation | R5 | `test_qa_catalog.py` (metacharacters, traversal), `test_qa_auth.py` (non-string JSON); DAST | D-10, D-11, D-12, D-13, D-14 | Passing; DAST results in `07-security/` |
| RQ-09 | The assistant answers only from the selected vehicle's manuals and never shows a link it did not retrieve | R6, R10 | `api/rag/test_*.py` (scoring, retrieval, service), frontend `chatPrompt.test.mjs` (link gate, prompt fences), offline gold-set evaluation | Frontend link gate + fences (commit `359776f`) | Unit tests pass; retrieval metrics in `04-integration-testing/` |
| RQ-10 | Rendered manual / model HTML cannot execute script | R10 | `sanitizeHtml.test.mjs` (XSS vectors) | `java\tscript:` bypass fixed (`359776f`) | Passing |
| RQ-11 | A customer's purchase request becomes a working login | R7 | `test_purchase_flow.py` (request → approval → company → OTP login) | — | Passing |
| RQ-12 | Test and staging traffic never changes production data | R8 | `api/rag/test_feedback_isolation.py`, `test_qa_fixtures.py` (seeder guards) | D-02, D-09 | Passing; 39 polluted rows remain pending approval (A-01) |
| RQ-13 | Interactive pages stay fast at expected load without affecting production | R9 | k6 profiles `qa/perf/` | P-02 worker recycling 502s → `--max-requests 20000` | `06-performance-and-load/PERFORMANCE_REPORT.md` |
| RQ-14 | Public pages meet WCAG 2.1 A/AA with no critical violations | — | E2E `a11y.spec.js` (axe-core) | — | Passing (no critical) |
| RQ-15 | No known-vulnerable dependency or committed secret ships | — | CI pip-audit, npm audit gate, Trivy, gitleaks, bandit | D-16 | CI |
