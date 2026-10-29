# D-06 / D-07 — media gate bypass: reproduction and verification

* `prod-media-wiring-used-for-repro.conf` — production's media-auth wiring
  copied verbatim (conf.d map + the two locations), pointed at the QA backend.
* `before-fix-prod-wiring.txt` — revision `42acfa5` (gate as in production):
  account `qa_e2e_manager`, entitled only to *Corolla Cross Hybrid S*,
  downloads an image of *4Runner Platinum* (HTTP 200, 8,143 bytes) through four
  path spellings; the plain path is correctly refused (403).
* `after-fix.txt` — revision `a9cd1b7` behind the QA proxy with the fixed
  cache key: every variant 403, the user's own car and the shared
  `_parts_assets` folder still 200.
* `production-edge-passthrough.log` — 2026-10-27 20:15 UTC, three
  **signed-out** requests sent through Cloudflare to production; production
  nginx logged the paths with `..`, `%2e%2e` and `//` intact, and they reached
  the auth gate (401) rather than being blocked by the WAF. Conclusion: the
  edge does not neutralize the bypass; production stays exposed until the
  release containing `eb32510` is promoted and A-02 (nginx files) is applied.
  No signed-in request was made against production.

Automated regressions: `KG_backend/api/test_qa_mediaauth_paths.py`,
`MediaAuthTests` in `KG_backend/api/test_qa_catalog.py`,
`qa/e2e/tests/media.spec.js`.
