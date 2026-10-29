# End-to-end testing

Tool: Playwright 1.52 (official container image), axe-core 4.10 for
accessibility. Suite: `qa/e2e/`. Runner: `qa/run_e2e.sh`, which re-issues
the seeded sessions so every run starts from the same state. Target: the QA
stack (`qa/stack.sh`) — real backend and frontend images of the commit under
test, nginx proxy mirroring production's routing, headers and media gate, a
sanitized copy of the production database, production manuals and RAG
index (read). The config refuses production URLs.

## Journeys covered (42 tests)

| Spec | Journeys | Browsers |
|---|---|---|
| `public.spec.js` | Landing renders with product and links; pricing page; real 404 with heading; per-request CSP nonce, anti-framing, nosniff, no `x-powered-by`; no uncaught script errors | Chromium, Firefox, Pixel 7 |
| `auth.spec.js` | 5 protected routes redirect signed-out visitors to `/login?next=<route>`; login button disabled without bot check; server rejects an unverifiable bot-check token (403, no session cookie); forged session cookie rejected | Chromium |
| `session.spec.js` | Profile identifies account and company; fleet lists the granted vehicle; fleet → vehicle → manual table of contents renders; content API sealed against bare clients; retrieval assistant answers with scored hits; settings page; **UI logout revokes the session server-side** (old token then gets 401, protected page redirects) | Chromium |
| `authz.spec.js` | Specialist without grant cannot read the manual; specialist refused on admin/team/org APIs; another company sees none of QA-E2E-A's data; a mismatched brand cannot unlock another vehicle's diagnostics or assistant answers (D-30); metrics never exposed publicly | Chromium |
| `media.spec.js` | Signed-out media refused; another car's media refused under 5 path spellings (raw HTTP); a cached allow for a shared folder does not leak to another car | Chromium |
| `a11y.spec.js` | axe WCAG 2.1 A/AA scans of `/`, `/login`, `/purchase`, `/recover`; critical and serious violations fail | Chromium |

Seeded accounts (`manage.py seed_qa_fixtures`, QA database only): a
manager with one granted vehicle, a specialist without grants, a locked
account, and a manager of a second company.

## Results

| Run | Commit | Result |
|---|---|---|
| 2026-10-27 19:24 UTC | `c43998c` | 41/41 passed, then again 41/41 on an immediate second run (repeatability) |
| 2026-10-27 23:16 UTC | `1a0eba8` | 41/41 passed, 0 flaky, 0 skipped |
| 2026-10-28 00:38 UTC (final) | `2f65a1d` | **42/42 passed, 0 flaky, 0 skipped**, 36.8 s, including the D-30 regression and the stricter accessibility gate — `results/junit.xml`, `results/results.json` |

Failures met while building the suite, and what they were:

* Signed-in pages showed the login form: the fixture set only the session
  cookie, while a real login also stores a user snapshot the UI keys on. The
  fixture now reproduces the real post-login state (test defect, not product).
* `/api/assist/` returned 503 and manuals 404 on the QA stack: the backend
  finds the warehouses next to its database, which staging satisfied only
  through a hand-made symlink (product defect D-09, fixed in `deploy.sh`).
* Paid media of another car was downloadable (product defect D-06/D-07,
  fixed; `media.spec.js` now guards it).

Accessibility: the only WCAG A/AA violation found was `link-in-text-block`
(serious) on `/login`; fixed in commit `0a2e00a` and the gate tightened to
fail on serious violations. Re-verified in the closing run recorded in
`../15-final-audit-report/TEST_SUMMARY_REPORT.md`.

## Not covered by E2E (by design or not yet)

* Completing Cloudflare Turnstile and receiving a real SMS code: automation
  must not solve a CAPTCHA, and the QA stack has SMS disabled. The full
  password → Turnstile → OTP → session path is covered at integration level
  (`test_qa_auth.py`, `test_purchase_flow.py`) with only those two external
  services faked.
* Admin console journeys (platform admin login needs 2FA), team management
  UI, PDF report download, SSE live dashboard, and the LLM chat answer (the
  QA stack has no LLM key, deliberately).
* Safari/WebKit.
