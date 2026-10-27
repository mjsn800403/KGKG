# Corrective action register

Defects found by the testing introduced on 2026-10-27. Each row traces
detection → root cause → change → regression test → verification. Commit ids
are on branch `qa-audit` (merged into `work` for release). "Verified" means
the regression test failed before the change and passes after it, and the
full backend suite passed with the change in place.

Severity: Critical (cross-tenant data or money), High, Medium, Low.

| ID | Sev | Found by | Defect | Root cause | Fix (commit) | Regression test | Status |
|---|---|---|---|---|---|---|---|
| D-01 | Medium | Baseline review | CI coverage counted `tests.py` and `tests_parts.py` (~510 lines of test code) as covered application code | Omit pattern `*/test_*` did not match those names; statement-only coverage | Omit all test modules, branch coverage on, XML/HTML + JUnit published (CI change, this release) | CI step itself; figure re-measured in `08-code-coverage/` | Fixed |
| D-02 | High | Code review while building the QA stack; measured in production data | Staging wrote its assistant queries into **production's** `_rag/feedback.db`: 39 of 561 query-log rows (7 %) were staging smoke traffic, 2026-10-15 → 2026-10-27. Ratings from staging would have re-ranked live search | Staging mounts the production RAG warehouse read-write and the store path was fixed under it | `RAG_FEEDBACK_DB` override; staging and QA point it at their own DB copy (`9895abd`) | `api/rag/test_feedback_isolation.py` (3 tests incl. a check that `deploy.sh` passes the override) | Fixed. The 39 polluted rows are still in production; deleting them needs the owner's approval (data change) |
| D-03 | Critical | `test_qa_access` | A seat kept document layers its company never bought (e.g. `manual`), and with `manual` became AI-eligible | `effective_documents()` returned an explicit grant list without intersecting the company scope | Clamp explicit lists to the company scope at read time (`b76c47a`) | `PackageEntitlementTests.test_purchase_grant_is_clamped_to_company_scope`, `AiEligibilityTests.test_manual_requested_but_not_purchased_does_not_qualify` | Fixed |
| D-04 | High | `test_qa_access` | Admin narrowing a company's layers for a car left its seats' layers (and AI eligibility) intact | Re-scope pruned removed cars only; read path did not clamp | Same read-time clamp (`b76c47a`) | `test_admin_layer_rescope_revokes_layer_for_seats` | Fixed |
| D-05 | High | `test_qa_orggraph_authz` | A company root could widen a platform-admin exception to all five packages | Posting only non-held layers stored `documents=[]` on an admin grant; `[]` means "all" | Narrow-to-nothing drops the grant; empty post preserves it (`b76c47a`) | `AdminExceptionTests.test_admin_exception_cannot_be_widened_by_posting_unheld_layer` | Fixed |
| D-06 | Critical | `test_qa_catalog` (integration); reproduced end-to-end on production's exact nginx wiring | Any signed-in user could download another company's paid manual images via `/_parts_assets/../<car>/`, `%2e%2e`, `nonexistent/../`, `//` | Gate read the first folder of the raw `$request_uri`; nginx serves the normalized path | `mediaauth._folder()` normalizes like nginx and fails closed (`eb32510`) | `api/test_qa_mediaauth_paths.py` (5), `MediaAuthTests.test_dot_segments_cannot_bypass_the_car_check`, `qa/e2e/tests/media.spec.js` (raw HTTP) | Fixed in code; reproduction before/after in `07-security/media-gate/`. **Production exposed until promotion:** Cloudflare and the WAF pass these paths through unchanged (verified signed-out, 2026-10-27 20:15 UTC) |
| D-07 | High | Analysis of D-06 | Even with D-06 fixed, the nginx auth cache keyed on the raw folder would serve a cached allow for `_parts_assets` to a dot-segment request for 60 s | `map $request_uri $kg_media_car` | Key on the normalized path (`set $kg_media_path $uri`) (`eb32510`) | `media.spec.js` "a cached allow for a shared folder does not leak" | Fixed in repo and verified on the QA proxy. **Production nginx must be updated on deploy** — `deploy.sh` does not install nginx files (see D-08) |
| D-08 | Medium | Comparing server to repo | `conf.d/kgkg-limits.conf` and `conf.d/kgkg-mediaauth.conf` existed only on the server | Hand-edited production config | Both versioned under `ops/nginx/` (`eb32510`) | — (configuration) | Versioned; installation is still manual (open action A-02) |
| D-09 | Low | QA stack bring-up | Staging only worked because of a hand-made symlink `/opt/KGKG_staging/db/Database_warehouse` (created 2026-09-22) | Not scripted | `deploy.sh` recreates it every staging run (this release) | Staging run itself | Fixed |
| D-10 | Medium | `test_qa_catalog` | Signed-out callers could tell real cars (401) from unknown ones (404) | Car lookup before sign-in check | Sign-in check first (`7bed8a7`) | `test_qa_catalog` existence tests | Fixed |
| D-11 | Low | `test_qa_catalog` | `%` and `_` in manual search, cross-link lookup and part search acted as wildcards (`q=%` listed every node) | User text placed in LIKE patterns unescaped (values were bound — not SQL injection) | `cardb.like_escape` + `ESCAPE '\'` (`7bed8a7`) | `test_qa_catalog` wildcard tests | Fixed |
| D-12 | Low | `test_qa_catalog` | `?page=..` returned HTTP 500 | Directory accepted as a page file | `is_file()` check (`7bed8a7`) | `test_qa_catalog` | Fixed |
| D-13 | Low | `test_qa_requests` | Admin inbox `?company_id=abc` returned HTTP 500 | Unvalidated int filter | 400 on non-numeric (`7bed8a7`) | `test_qa_requests` | Fixed |
| D-14 | Medium | `test_qa_auth` | Login, OTP verify/resend, password reset and admin login returned HTTP 500 when a JSON field was a number, list or object; a numeric OTP code failed | `.strip()` on raw JSON values | `str()` coercion (`ebd9487`) | `test_qa_auth` non-string tests | Fixed |
| D-15 | Low | `test_qa_ratelimit` | `KG_RL_<NAME>="0/0"` documented as "off" but kept the default limit | Parser rejected zero | Accept `0/0` as off (`ebd9487`) | `test_qa_ratelimit` | Fixed |
| D-16 | Low | bandit | Invisible bidi control characters in source (Trojan-Source pattern); SHA-1 fingerprints not marked non-security | — | Escapes; `usedforsecurity=False` (this release) | bandit gate in CI | Fixed |

## Open actions

| ID | Action | Owner | Needs |
|---|---|---|---|
| A-01 | Delete the 39 staging rows from production `feedback.db` (query: `query='engine oil capacity' AND model='Corolla Cross'`, 2026-10-15..27) | Product owner | Approval to change production data |
| A-02 | Install `ops/nginx/kgkg.conf` and `ops/nginx/kgkg-mediaauth.conf` on production in the same window as the release that contains `eb32510`; `nginx -t` then reload | Operations | Maintenance window; the app-side fix alone leaves the 60 s cache leak (D-07) |
| A-03 | Decide whether `deploy.sh` should install nginx files from the release (removes D-08 class of drift) | Engineering lead | Design decision |
