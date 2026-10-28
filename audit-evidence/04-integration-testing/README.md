# Integration testing

## What "integration" means here

The backend suites run Django views, the ORM, the real SQLite schema,
real per-vehicle manual databases built in temporary directories, the real
org graph, the shared rate-limit store and the session/token machinery
together, through Django's test client. Only true externals are replaced:
the SMS gateway, Cloudflare Turnstile verification and (in CI) the embedding
model. Suites added in this remediation (all under `KG_backend/api/`):

| Suite | Tests | Integrates |
|---|---|---|
| `test_qa_catalog.py` | 108 | HTTP → views → entitlement checks → per-car SQLite manuals, parts DBs, media gate |
| `test_qa_requests.py` | 28 | Ticket lifecycle across manager and admin APIs, events, cross-company isolation |
| `test_qa_orggraph_authz.py` | 30 | Org-graph API → permission store → user grants → effective access |
| `test_qa_auth.py` | 96 | Login → Turnstile → OTP challenge store → session issue → cookie → `/me` → logout |
| `test_qa_ratelimit.py` | 40 | Decorator → shared SQLite counter store across simulated workers → 429/Retry-After |
| `rag/test_feedback_isolation.py` | 3 | RAG feedback store ↔ environment configuration ↔ `deploy.sh` staging settings |
| `test_qa_fixtures.py` | 4 | Management command ↔ DB ↔ token issue ↔ `/api/auth/me` |
| `test_openapi_routes.py` | 11 | URL resolver ↔ `docs/openapi.yaml` (spec cannot drift from routes) |
| `test_qa_eval_report.py` | 3 | Admin guard on the evaluation endpoint |

Pre-existing integration suites kept and still passing include
`test_purchase_flow.py` (purchase request → admin approval → company →
OTP login), `test_pipeline*.py`, `test_orggraph.py`, `rag/test_service.py`.

System-level integration with real containers, nginx and the production
data shape is exercised by the E2E suite (`../05-e2e-testing/`) on the QA
stack, and by the staging smoke on every deploy.

Results: `../15-final-audit-report/TEST_SUMMARY_REPORT.md`.

## Retrieval (RAG) evaluation — AI component

The retrieval assistant is probabilistic, so unit tests are complemented by
offline evaluation against **versioned gold sets** (11 files, 1,559 rows,
in git under `KG_backend/Database_warehouse/_rag/eval/gold/`; SHA-256 of the
files used is recorded with each run). No LLM calls are made.

| Run | Code | Scope | Folder |
|---|---|---|---|
| 2026-08-05 | revision of that date | Full sets (EN 250, FA 250, out-of-scope 52, wrong-vehicle 60, diagnosis 453, 133 real queries) + 462 paid LLM answer evaluations + no-retrieval baseline | `rag-eval-2026-08-05/EVALUATION_REPORT.md` |
| 2026-10-27 | `f7d3856` (this release) | Production pipeline (`hybrid`) only, **first 100 rows** of each set (out-of-scope and wrong-vehicle complete) | `rag-eval-2026-10-27/` |

2026-10-27 results (`run.log`, `results.json`):

| Set | Metric | Result |
|---|---|---|
| Known-item English (n=100) | Hit@1 / MRR / nDCG@5 / Recall@10 | 66.0 % / 0.757 / 0.409 / 0.403 |
| Known-item Persian over English documents (n=100) | Hit@1 / MRR | 23.0 % / 0.322 |
| Out-of-scope: non-automotive (25), nonsense (15) | Correct refusal | 100 % / 100 % |
| Out-of-scope: automotive topic absent from corpus (12) | Correct refusal | 50 % [25–75 %] (August: 8 %) |
| Wrong vehicle (60) | Refused / claimed for the selected car | 14 / 46 |
| Diagnosis: exact DTC code (40) | Hit@1 | 100 % |
| Diagnosis: fault name without code (41) | Hit@1 / Hit@3 | 58.5 % / 95.1 % |
| Diagnosis: symptom (19) | Hit@1 | 100 % |

Reading these honestly:

* The October run uses the first 100 rows per set, not a random sample, so
  it is not statistically comparable with August's full-set figures; it is a
  regression check that the pipeline still performs in the same range.
* **Wrong-vehicle attribution is the weakest behaviour**: when asked about a
  component that the selected car's manual lacks, the pipeline usually
  returns material and presents it for the selected car (46 of 60), where it
  should refuse or name the other vehicle. This is an open product risk (R6);
  the LLM phrasing step and the link gate reduce, but do not remove, its
  effect on answers.
* Persian queries over English manuals remain much harder than English.
* Domain correctness of answers has **not** been reviewed by automotive
  experts. The tooling exists (`manage.py expert_sheet`), but no expert
  ratings have been collected, so none are claimed.

Prompt-injection and output-safety controls are tested at unit level in the
frontend (`kg_frontend/src/lib/__tests__/chatPrompt.test.mjs`: fence and
quote neutralisation, link allow-list, history sanitisation) and summarised
in `../07-security/SECURITY_ASSESSMENT.md`.
