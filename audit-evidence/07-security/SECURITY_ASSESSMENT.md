# Security assessment

Scope: KGTechVault backend, frontend, container images, delivery and edge
configuration, as of the remediation branch (2026-10-27/28). This is an
**automated and code-review assessment by the development side. It is not
an independent penetration test** — see §6.

## 1. Controls and what each one actually checked

| Control | Tool / method | Where it runs | Latest result |
|---|---|---|---|
| SAST | bandit 1.9.4, medium+ severity, triaged baseline | CI `security` job, every push | No new issues (CI run 40609938821). 46 baseline findings: 6 fixed, 40 triaged false positives with written reasons (`ops/security/README.md#bandit`) |
| Dependency audit (Python) | pip-audit 2.9 on the image lockfile | CI | Pass; 3 reviewed, dated exceptions (`ops/security/pip-audit-ignore.txt`) |
| Dependency audit (Node) | npm audit gate | CI | Pass |
| Secret detection | gitleaks 8.21 (filesystem scan, report asserted to exist) | CI | 0 findings |
| Container scanning | Trivy 0.58, HIGH/CRITICAL fixable | CI `images` job | Backend 0 / 0. Frontend was **5 CRITICAL + 33 HIGH** → fixed (OS upgrade in runtime stage, package managers removed) → **0 / 0** |
| Dockerfile / shell lint | hadolint, shellcheck | CI | Pass |
| Security regression tests | Django + node:test suites (authz, auth, rate limits, media gate, XSS, prompt fences) | CI and server gate | All pass (850 backend, 177 frontend) |
| DAST | OWASP ZAP: passive baseline; authenticated active full scan; authenticated **API scan from `docs/openapi.yaml`** | QA stack only (`qa/dast/run_zap.sh`), before releases | See §3 |
| Edge | ModSecurity 3 + OWASP CRS 3.3.5, `limit_req`, Cloudflare | Production nginx | Configuration reviewed; not re-tested (QA proxy deliberately has no WAF) |

## 2. Threats reviewed against the code (OWASP Top 10 / API Top 10)

| Threat | Finding | Evidence |
|---|---|---|
| Broken access control / IDOR (A01, API1) | **Confirmed and fixed:** cross-company paid-media download (D-06/D-07, *critical*), seats keeping unpurchased layers and AI (D-03/D-04), root widening admin exceptions (D-05), unauthenticated evaluation report (D-17), cross-vehicle diagnostics via a mismatched brand (D-30). Cross-company isolation of requests, org graph, users, manuals verified by tests | `../14-risk-and-corrective-actions/CORRECTIVE_ACTIONS.md`; `media-gate/` |
| Broken authentication (A07, API2) | Enumeration equalised; OTP 5-try and daily caps; single session; Turnstile fails closed; HttpOnly+Secure+SameSite=Lax session cookie. Non-string JSON caused 500s (D-14), fixed | `KG_backend/api/test_qa_auth.py` |
| Injection (A03) | All SQL values bound; LIKE wildcards in user input now escaped (D-11, not injection). No `shell=True`, subprocess argument lists fixed | bandit triage; `test_qa_catalog.py` |
| XSS | Manual HTML and model output sanitised client-side; **bypass with `java\tscript:` found and fixed**; React escaping elsewhere; per-request CSP nonce, `frame-ancestors 'none'` | `kg_frontend/src/lib/__tests__/sanitizeHtml.test.mjs`; E2E `public.spec.js` |
| CSRF | Session cookie `SameSite=Lax`; JSON bodies. No CSRF tokens on cookie-authenticated mutations → residual risk, defence-in-depth recommended (Origin check) | `docs/12-security.md` §12.2 row 5 |
| SSRF / unsafe URL fetch | All outbound URLs are constants (SMS, Turnstile, LLM, loopback health) | bandit B310 triage |
| Path traversal / unsafe files | Media gate fixed (D-06); `?page=..` 500 fixed (D-12); manual pages restricted to regular files inside the car folder | `test_qa_catalog.py`, `test_qa_mediaauth_paths.py` |
| Sensitive data exposure | Staging/QA strip phones, e-mails, hashes, tokens; staging had been writing to production's query log (D-02); eval report was public (D-17) | `ops/deploy/sanitize_staging_db.py`; `rag/test_feedback_isolation.py` |
| Rate limiting / scraping | Per-endpoint limits shared across workers; content shield seals manual content per session; content guard per-user ceilings | `test_qa_ratelimit.py`; E2E content-shield test |
| Vulnerable components (A06) | Gated in CI (above); frontend image cleaned | CI run 40609938821 |
| Security misconfiguration (A05) | Two nginx files existed only on the server (D-08), now versioned; COOP/CORP added; COEP intentionally off (Turnstile iframe) | `ops/nginx/` |
| Logging & monitoring (A09) | Structured logs to Loki, GlitchTip, alert rules with SMS paging and an independent watchdog; auth events in the audit log | `docs/11-operations-deployment.md` |

## 3. DAST results

All scans: OWASP ZAP (`ghcr.io/zaproxy/zaproxy:stable`, image id in each
`env-*.txt`), against the QA stack only, signed in as the seeded manager.
Final reports: `dast-final/` (commit `2f65a1d`).

| Scan | Final result (`2f65a1d`) | History |
|---|---|---|
| Baseline (passive spider) | 63 rules pass, **0 fail**; warnings: CSP `style-src 'unsafe-inline'` (Medium), COEP absent (Low), cache/content-type notes (Info) | Same on every run |
| **API scan** (active; all 209 operations of `docs/openapi.yaml`, logout removed) | 118 rules pass, **0 fail, 0 server errors**; warnings: CSP `script-src 'unsafe-inline'` on non-page responses (nginx fallback policy), unexpected content type (Info), COEP (Low) | First runs provoked HTTP 500s on `/api/org/nodes/*` (→ D-29) and `/api/diagnose/` (→ investigation found D-30, a cross-vehicle entitlement bypass); a "SQL injection" heuristic on `events/recent?limit=102-2` was a false positive (invalid integers fall back to the default limit) |
| Full (active, classic + AJAX spider) | 141 rules pass, **0 fail**; warnings on our origin: CSP `style-src 'unsafe-inline'` (Medium, accepted), COEP absent (Low). The browser-driven spider also loaded third-party hosts (Cloudflare Turnstile, Google); their header findings are listed in the report and are outside our control. No request reached production or staging (production traffic table checked for the scan hour) | Earlier runs: same pass/fail. The classic spider alone reaches only ~6 URLs of this SPA, which is why the API scan exists |

Accepted: CSP `style-src 'unsafe-inline'` (React and manual content use
inline styles; scripts on pages are nonce-restricted). Recommendation: the
nginx fallback CSP (applied to API/static responses) still allows
`script-src 'unsafe-inline'`; JSON responses do not execute, but the
fallback can be tightened to `script-src 'none'` for `/kg-api/`.

Scan-scope incident, recorded for transparency: during one full scan the
spider extracted the frontend bundle's server-side fallback URL
`http://127.0.0.1:8000` (production backend's loopback port) from
JavaScript and sent **one passive `GET /`** to it. Production's traffic table
for that hour shows exactly that single request to the public brand list and
no errors; no attack payload reached production (out-of-scope hosts receive
no active rules). The scanner now excludes production and staging ports and
the public domain outright.

Unresolved observation O-1 (`../14-risk-and-corrective-actions/`): in one
session where two scans ran concurrently, one QA backend worker was wedged by
SQLite `disk I/O error`s until restart; not reproduced since.

## 4. AI-specific trust boundaries

| Boundary | Control | Verified by |
|---|---|---|
| Prompt injection via user text or history | Fence markers and guillemets flattened before interpolation; history roles allow-listed and length-capped; explicit refusal rule in the prompt | `chatPrompt.test.mjs` (regressions for forged fences) |
| Malicious instructions inside retrieved manual text | Same flattening applied to retrieved context so it cannot close the context fence | `chatPrompt.test.mjs` |
| Model inventing links | Server allow-list: only links that retrieval returned survive, for buttons and plain markdown links; renderer refuses `//host` | `chatPrompt.test.mjs`; August eval: 14 % attempted, 100 % caught |
| Unsafe model output rendering | Sanitiser + React escaping; no `dangerouslySetInnerHTML` of raw model text | `sanitizeHtml.test.mjs` |
| Cross-tenant retrieval | Assistant and search pass through the same per-car entitlement guard as manuals | `test_qa_catalog.py` (assist/diagnose access checks) |
| Tool invocation | The LLM has no tools; it only phrases retrieved content | Code review (`route.js`, `chatPrompt.js`) |

Not tested: adversarial prompt suites against the live LLM (cost, external
API), jailbreak resistance of the model itself.

## 5. Residual risks (prioritised)

1. **Production still runs the vulnerable media gate, entitlement logic,
   diagnose gate and public eval report** until this release is promoted and
   the nginx files are installed (A-02). Severity Critical for the media gate
   and the entitlement leak.
2. Wrong-vehicle attribution in the assistant (domain-trust risk, see
   `../04-integration-testing/`).
3. CSRF relies on `SameSite=Lax` only.
4. Staging and QA run on the production host (isolation by containers,
   caps and data sanitisation, not by separate hardware).

## 6. Penetration testing — status

No independent penetration test has been performed. Recommended scope for
an external tester: authenticated multi-tenant access control (company,
role, per-car and per-layer grants), media gate and content shield, OTP and
recovery flows, admin console, nginx/WAF configuration, AI chat route
(prompt injection, link injection). Prerequisites ready: QA stack with
seeded accounts, OpenAPI spec, this assessment.
