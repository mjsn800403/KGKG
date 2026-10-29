# Unit testing

## Backend

Framework: Django test runner (`unittest`), run by CI on every push and by
the server gate before every staging/production deploy. Unit-level suites
added in this remediation test pure decision logic directly:

| Suite | Tests | Logic under test |
|---|---|---|
| `KG_backend/api/test_qa_access.py` | 88 | Role ladder, package/document resolution, AI eligibility, seat-plan validation, grant writing by admin vs manager, quota boundaries (5th question allowed, 6th refused, concurrent race for the last one), locked/inactive/expired accounts |
| `KG_backend/api/test_qa_mediaauth_paths.py` | 5 | Media-folder resolution under dot-segments, encodings, slash runs, root escape, query smuggling |
| `KG_backend/api/test_qa_ratelimit.py` (unit part) | — | Rule parsing, window boundaries, proxy-header trust |

Pre-existing unit suites (still passing): RAG scoring, retrieval, embedding
contract, FTS query building, terminology, evaluation metrics
(`KG_backend/api/rag/test_*.py`), vehicle schema, parsers, alert rules,
SMS body formatting, flags, recommendation logic.

Characteristics: positive, negative and boundary cases; each defect found
has a named regression test; no mocking of the code under test; time is
controlled by fake clocks, never `sleep`.

## Frontend

Framework: Node's built-in `node:test` with built-in coverage
(`npm test` in `kg_frontend/`), no added dependencies; run in CI and in the
server gate. 178 tests in `kg_frontend/src/lib/__tests__/`:

| Module | What is asserted |
|---|---|
| `sanitizeHtml.js` | Script/handler/`javascript:`/`data:` stripping, SVG and MathML vectors, CSS expressions, malformed nesting, entity-encoded and control-character URL tricks; legitimate manual HTML (tables, images, relative links, Persian text) preserved |
| `chatPrompt.js` | History role/length/count caps, link allow-list for model output (buttons and plain links), prompt fences and quotes cannot be forged by user, history or crawled text |
| `pricing.js`, `packages.js` | Plan price rules, seat tiers, AI quotas, annual vs monthly relation, boundaries |
| `contextualize.js`, `faTerms.js`, `friendlyError.js`, `manualContent.js` | Follow-up detection, DTC recognition, terminology mapping, error messages |

One test is skipped deliberately: per-seat price rises from 29 to 30 seats
because the 30-seat list price (145) sits above the pricing formula
(142.8). Whether that is intended is a business decision; the test
documents it and waits for that decision.

`sanitizeHtml` is tested with a small DOM stand-in (`miniDom.mjs`); browser
parser quirks (mutation XSS) need a real browser and are not claimed.

## Mutation testing

Not performed in this remediation. `mutmut` is installed in the QA venv;
running it on `access.py` and `mediaauth.py` is the recommended next step
to measure how many injected faults the new assertions catch.

Results and counts: `../15-final-audit-report/TEST_SUMMARY_REPORT.md`.
