# Changelog

Living log of shipped changes, newest first. One dated block per deploy/commit; keep lines
short and point at the doc section that was updated.

## Unreleased
- **The server gate runs the security scans.** `ops/deploy/gate.sh` now runs bandit, pip-audit
  and the npm audit gate first, through `ops/security/scan.sh`, which CI calls too, with the
  same exception files. Scanners come from a pinned venv (`/opt/KGKG_release/sectools`), and a
  scan that cannot run fails the deploy. Before this, `8fa94dd` was red on bandit in CI and
  still passed the server gate. (ops/security/README.md)
- **Fix (D-41):** a read of a missing RAG index created an empty `index.rag.db`, after which the
  assistant answered 500 ("no such table") instead of 503 until the file was removed by hand; one
  recommendations-panel view was enough. Read-only opens now raise `FileNotFoundError` and create
  nothing (`api/rag/store.py`, test `api/rag/test_store_ro.py`).
- **Fix (D-42):** malformed ids (`"abc"`) gave HTTP 500 on six admin inputs (pipeline job/ZIP
  actions, vehicle-specs `car_id`, admin user create `company_id`); now 404/400.
- **Tests:** backend 850 → 930. New suites for team analytics/invites and the PDF report
  (`test_team.py`), the admin operations API (`test_adminops.py`), shield keys and alerts, and the
  serving layer's search/diagnose filters (`rag/test_service_paths.py`). team 24→90 %, reporting
  0→98 %, adminops 37→77 %, shield 69→95 %, rag/service 61→90 %; total 53→56 %, CI floor 52→55.
- **Mutation testing** of the authorization modules (`qa/mutation/run.sh`, on-demand
  `mutation` workflow): 14 surviving mutants were real blind spots (same-rank peer management on
  the legacy path, purchase bypass by default flag, one bad grant entry dropping the rest, a
  query-string media-gate case, the nginx `X-Real-IP` admin-token check) and are now killed by
  tests (`test_access_rules.py` and others). Evidence: `audit-evidence/03-unit-testing/mutation/`.
- **Docs:** `docs/00-srs.md` (FR/NFR with verifying tests) and `docs/adr/` (six decisions).
  Tests 930 → 960 (incl. CSV exports); coverage floor 55 → 56.
- **Release gate:** `kgkg-promote` requires a passing full E2E run for the commit
  (`qa/run_e2e.sh` → `/opt/KGKG_release/e2e/<sha>.env`); overrides are typed and logged.

## 2026-10-28 — v1.0.0: test architecture, security fixes, audit evidence (branch `qa-audit`)
- **Security fixes found by the new tests** (each with a regression test; details in
  `audit-evidence/14-risk-and-corrective-actions/`): cross-company paid-media download through
  dot-segment paths and the nginx auth cache key (D-06/D-07, *needs `ops/nginx/kgkg.conf` and
  `kgkg-mediaauth.conf` installed with the release*); seats holding layers their company never
  bought (D-03/D-04); root widening admin exceptions (D-05); public `/api/eval/report/` (D-17);
  cross-vehicle diagnostics via a mismatched brand (D-30); `java\tscript:` XSS bypass in the
  sanitizer and unchecked model-written links (D-22/D-23); prompt fences forgeable (D-24).
- **Staging no longer writes into production's RAG feedback store** (`RAG_FEEDBACK_DB`, D-02).
- **Robustness:** 500s on hostile input fixed in auth, catalog, admin inbox and org graph;
  gunicorn recycles every 20,000 requests (was 2,000; recycling caused every load-test error).
- **Tests:** backend 427 → 850; first frontend unit suite (178, `node:test`); Playwright E2E (42,
  `qa/e2e/`); k6 load model (`qa/perf/`); ZAP baseline/full/API scans (`qa/dast/`); offline
  retrieval evaluation runner (`qa/eval/`); isolated QA stack (`qa/stack.sh`).
- **CI:** honest branch coverage (test files no longer counted; floor 50 → 52), JUnit/coverage
  artifacts, frontend tests, bandit SAST gate, frontend image hardened (Trivy 0 HIGH/CRITICAL).
  CI on this branch is green; `work` had been red for 14 of 19 runs.
- **Docs:** `docs/openapi.yaml` (all 90 routes, enforced by `test_openapi_routes`); API reference,
  security risks and operations docs corrected; `VERSION` + SemVer in deploy tags; defect and
  support issue templates; `audit-evidence/` package for the knowledge-based-company evaluation.

## 2026-10-27 — delivery, monitoring and supply-chain maturity
- **CI stages every push to `work`; only a person promotes.** `.github/workflows/deploy.yml`
  would have promoted to production on green CI (held back only by a GitHub environment
  setting) — deleted. Deploy keys are now pinned to role-scoped forced commands: the CI key
  can `stage` and `status`, and has no `deploy` verb, so it cannot reach production by
  construction. Promotion is `kgkg-promote <sha>`, which refuses an unstaged or stale-staged
  commit and requires a typed confirmation. 18 access-control tests. (doc 11 §11.3)
- **Staging data sanitized.** The staging copy of the production database had live session
  tokens, phone numbers, e-mails and password hashes. `ops/deploy/sanitize_staging_db.py`
  empties credential tables, neutralises hashes, replaces identifiers and masks audit IPs
  while keeping row counts and relationships. (doc 11 §11.3, doc 12 §12.1)
- **Application metrics in Prometheus.** `GET /api/metrics/` exposes requests, 4xx/5xx and
  latency per route group, open alerts, index and DB size, pipeline jobs and the live release
  sha — read from the shared tables rather than per-worker counters, because a scrape lands on
  one gunicorn worker. Own credential (`KG_METRICS_TOKEN`), denied on the public path, scraped
  over a loopback-plus-bridge listener on :8081. (doc 11 §11.2, §11.5)
- **The alerting is now watched.** Nothing checked that `check_alerts` still ran; a stalled
  timer looked exactly like a healthy system. `ops/observability/watchdog.py` (5-minute timer,
  standard library only, independent of Django) pages by SMS when the paging path is broken and
  stays quiet otherwise. 24 tests. (doc 11 §11.5)
- **Security gates in CI, failing closed:** shellcheck, hadolint, gitleaks, pip-audit, npm
  audit and trivy on both images, with dated exceptions in `ops/security/`. Their first run
  found the installed Next.js inside the vulnerable range for several advisories including
  unauthenticated RCE (16.2.9 → 16.4.3) and WeasyPrint arbitrary code execution on the PDF
  path (69.0 → 70.0); Django, pillow, urllib3, sqlparse, soupsieve, certifi, anyio, brotli,
  fsspec, filelock and setuptools were also bumped, and the backend image now applies
  distribution security updates. Both images scan clean of fixable HIGH/CRITICAL.
  (ops/security/README.md)
- **Smoke covers the reverse proxy:** proxied landing and health, the public metrics path
  refused, the scrape listener serving only metrics, security headers, and no stray files in
  `sites-enabled` (one broke an nginx reload today). Coverage ratcheted at 50%.
- **Verified:** 402 backend tests in the upgraded image, 14 new metrics tests, 24 watchdog
  tests, 18 gate-role tests, the sanitizer against a real database copy, and 24 smoke checks
  against live production. A full staging run through the CI path was exercised end to end.
- **Correction (same day):** this entry first said no off-host backup existed, repeating a
  stale claim in doc 11 without checking. It was wrong — an hourly off-host snapshot
  already existed (internal server pulls `/root/backup_snapshot`, built with the SQLite
  online backup API). Verified by a restore test: integrity ok, business tables matching
  live exactly. Doc 11 §11.6 and doc 12 §12.2 now describe it. What remains open is
  retention on the far side, which is a question for that server, not a missing system.
- **Still open:** the torch upgrade, deferred pending a re-embed window.

## 2026-08-05 — security hardening: secrets, rate limiting, WAF, error monitoring
- **Secrets**: `.env.prod` / `.env.production` / `db.sqlite3` and ~24 stray backup copies were
  world-readable (0644) — now 0600 root-only. Both production secrets rotated. (doc 18 §1)
- **Session tokens hashed + expiring**: `AuthToken`/`AdminAuthToken` stored the bearer value in
  plaintext and never expired. Now sha256-at-rest with idle/absolute TTLs (user 14d/90d, admin
  12h/7d) and a rolling `touch()`. Migration 0017 deletes the 89 pre-existing plaintext rows —
  everyone re-logs in once. (doc 18 §1)
- **Rotation tooling**: `manage.py rotate_secrets` (atomic env rewrite, `SECRET_KEY_FALLBACKS`
  retention) and `manage.py rotate_tokens` (prune/revoke), plus `kgkg-token-prune.timer`.
- **nginx rate limiting**: six tiers + connection limits, 429s logged for fail2ban. Loopback is
  exempt — SSR fetches the public URL, so counting them would throttle the whole site. (doc 18 §2)
- **WAF**: ModSecurity 3 + OWASP CRS 3.3.5 at PL1, blocking. Tuned from a DetectionOnly run:
  CRS 920271 and 920350 removed (Persian/UTF-8 and the domain-less numeric Host header fired on
  112/112 legitimate requests), free-text SQLi/XSS scoring lifted off named search/chat args.
  Plus four fail2ban jails. (doc 18 §3)
- **Error monitoring**: self-hosted GlitchTip on 127.0.0.1:8010 (SSH tunnel only — no TLS on this
  box yet), Django + Next.js reporting, JSON logs in `/var/log/kgkg` with secret redaction.
  Two silent compatibility traps documented (Brotli, DSN hyphens). (doc 18 §4)
- **Verified**: 305 backend tests green (40 new in `api/test_security.py`); 44/44 external
  security probe; 39/39 whole-site sweep.
- **Found, not fixed**: `/admin/<anything>` returns 500 (pre-existing — `[brand]/[year]` catch-all
  plus no `not-found.tsx`/`error.tsx` boundary); orphaned staging `next-server` on :3123.

## 2026-08-03 — platform-wide vehicle filtering
- **Shared filter component** (`components/VehicleFilter.jsx`): `useVehicleFilter()` +
  `VehicleFilterBar`. Facets on **brand, model and model year only**, plus search. Appears
  automatically above 4 vehicles, hides dimensions with a single option, counts each facet
  against all *other* filters. (doc 07 §7.7)
- **Scope correction, same day:** attribute facets (trim, drivetrain, powertrain,
  transmission) were built, then removed on request — brand/model/year is the whole filter.
  Search still matches the full vehicle name, so "AWD" or "Hybrid" still find their cars.
  The admin *status* facets (completeness / processing / indexing) stay: they are health
  indicators, not vehicle specifications.
- **Adopted everywhere vehicles are listed**: `/browse` fleet, `/[brand]/[year]` and
  `/assistant` pickers (new `VehicleCardGrid` replaces the raw `CardGrid` — 200+ cards were
  unfiltered), admin catalogue, the access editors behind **both** user and company grants,
  data-quality, vehicle specs, and the org-graph seat panel. Bulk grant/revoke now acts on
  the filtered set.
- **Admin health indicators on the catalogue** (`/api/admin/cars/`): per-vehicle data
  completeness %, missing/empty sections, RAG + diagnostic + image indexing, schema.org
  spec field count, outstanding processing — joined from the last `DataQualityRun` via
  `dataquality.latest_health_by_car()` (one row read, no warehouse I/O). Filterable as
  status facets. (doc 05, doc 07 §7.7)
- **`company_cars` gains `model` + `year`** (`orggraph_api`) so the seat panel can facet
  rather than substring-match a joined label.
- **Model-family fix**: `Grand Highlander`, `Crown Signia`, `GR Corolla`/`GR Supra` were
  grouping under `Grand`/`Crown`/`GR`; multi-word family list corrected, and the `" (YYYY)"`
  multi-year stem suffix is now stripped before grouping.
- 243 backend tests green (`api/test_vehiclefilter.py` new).

## 2026-07-19 — parallel parsing + max-power toggle
- **Parse stage parallelised** (commit 8fc1ff1): one ZIP per subprocess
  (`ProcessPoolExecutor` spawn, `api/parse_worker.py`) so the GIL-bound html5lib
  crawl uses many cores instead of one. ~1 → ~14 effective cores. (doc 15 §6b)
- **Max-power toggle** (`PipelineSettings.max_power`, migration 0014; admin
  switch «حداکثر توان پردازش»): normal = half cores at low priority (site stays
  responsive) vs max = cores-1 at full priority. `pipeline.power_plan` +
  `launch_worker` set worker counts + Nice/IO/CPUWeight; `apply_power` action
  restarts the active job to apply immediately. 268 tests green. (doc 15 §6b)

## 2026-07-18 (b) — ingestion pipeline + vehicle schema
- **Pipeline front half shipped** (commit 8e5c4ba): new `download` and `parse` stages ahead
  of catalog/rag/diag/audit; `DownloadRequest` + `ZipPackage` queues (migration 0013);
  `manage.py scan_zips` inbox scanner with KGTV filename normalization and a
  stem-level duplicate guard; disk guard (pause < 20 GB free). (doc 15)
- **source downloader integrated**: importable by the worker, `--filter` flag, output
  renamed to the `KGTV <year> <brand> <model>.zip` convention. (doc 15)
- **Multi-year stems**: non-2025 model years get a `" (YYYY)"` stem suffix
  (`htmlparser_logical.warehouse_stem`); suffix-aware `car_meta`/`display_name`;
  dataquality treats a year suffix as NOT a copy marker. (doc 15 §3)
- **schema.org vehicle specs** (`api/vehicleschema.py`, `VehicleSpec`, `schema` pipeline
  stage): per-field provenance (catalog/stem/manual/curated), strict leave-null policy;
  surfaced via `?spec=1`, public JSON-LD on catalog pages, chatbot SPECS grounding block,
  admin «مشخصات خودروها» section. (doc 15 §4–5)
- **Backlog queued**: 216 inbox ZIPs scanned → 164 new vehicles queued, 52 duplicates
  skipped; ~45 GB extraction residue purged; Corolla Cross 2023 (9) + 2024 (10) download
  requests queued; pipeline job #3 started. Tests 259 green (33 new).

## 2026-07-18
- **Bilingual terminology store shipped** (`_rag/terms.db`, `api/rag/terms.py`,
  `manage.py build_terms`): Book1.csv + translation.sql unified and cleaned (1,602 part
  pairs + 107 curated service terms); `Book1.csv` and the new `terms_en_fa.json` display
  dictionary are now GENERATED artifacts (hot-reload, atomic, dated backups). (doc 14)
- **Professional bilingual chat display**: chat source titles/buttons render
  «فارسی (English)» via `src/lib/faTerms.js` (token-index matcher, 1,644 entries,
  60s hot-reload, built-in fallback); Metis prompt gains a mandatory TERMINOLOGY block.
  (doc 08 §8.5)
- **Conversational assistant**: client sends recent thread; deterministic follow-up
  contextualizer (`src/lib/contextualize.js`, no LLM cost) joins anaphoric follow-ups
  for retrieval; HISTORY block in the prompt; 2-4 follow-up suggestion chips per answer;
  clarify mode (one Persian clarifying question + system chips) for ambiguous
  low-confidence queries; hardened history validation. (doc 08 §8.5)
- **QA-gated machine translation** (`manage.py translate_terms`): 2-sample
  self-consistency + bge-m3 back-translation gate, budget caps, lockfile, pipeline
  yielding, review CSV workflow; mining/report/fa-gap commands in `build_terms`. (doc 14)
- Backend tests 221 green (28 new); frontend node tests 4 suites green; sandbox E2E
  batteries (phase 1: bilingual display; phase 2: multi-turn/clarify/chips) all pass.

## 2026-07-15
- **Documentation suite created** (`docs/01…13`, this changelog). Source of truth going
  forward; maintenance protocol in `docs/README.md`.
- **User guidance system shipped** (`kg_frontend/src/guidance/`): role-based onboarding
  tours (visitor / user / manager / admin), searchable on-demand help center (`?` button +
  `Shift+?`), admin guide covering every admin section, contextual smart hints
  (rule-based, frequency-capped). Replaces the old two-page `SiteTour`. See doc 13.

## 2026-07-14
- Org-chart consistency overhaul deployed: strict supervisor-outranks invariant +
  auto-repair (`enforce_org_consistency`), string-id coercion fix at API boundary, SSE
  team sync, empty-position assign UX, «شما» labels. Tests 193 green. (docs 06, 07)
- Assistant link integrity: `_enc(safe='')`, tolerant year resolution, catalog fallback in
  `config.car_meta`, `NX 250 FWD (1)` purged from index, occurrences.year backfilled
  (1.52M rows), 414k diag URLs rewritten; 1.66M+181k URLs verified zero-fail. (doc 08)
- Dummy/test companies purged from prod (companies 2 & 6); prod = 1 real company.
- All prior uncommitted work committed as 2da813d + 347d6e3.

## 2026-07-11
- Real-time platform deployed: Event/SSE backbone, company requests, live admin/manager
  dashboards, recommendations engine, `ActivityLog.app_url` (migrations 0011–0012);
  4 security/robustness fixes (allow-list threading B-01, body clamps, grant clamp B-03,
  JSON hardening G12); gunicorn threads 8/timeout 300; nginx SSE location; detect timer.
  (docs 03, 05, 09, 10, 12)
- Flexible org hierarchy (OrgRole, migration 0010), PDF team reports (WeasyPrint),
  admin hub + `/admin/login`. (docs 03, 06, 10)

## 2026-07-10
- Data-quality engine + monitoring/alerting/traffic stack + cardb pool + admin ops panels
  (migration 0008, commit 2c949d1); processing pipeline with detached workers + watchdog
  timer (0009, commit 318f255). Fleet remediated: 38/38 complete, duplicates quarantined.
  `db.sqlite3` untracked from git. (docs 04, 11)

## 2026-07-09
- Backend content paywall enforced (per-car gates, SSR cookie, chat gating, per-IP rate
  limits). Company self-service team management + invites + analytics (migration 0007).
  (docs 05, 06, 12)

## 2026-07-08
- PlatformAdmin password rotated (was admin/admin); all admin sessions invalidated.
  RAG scope-leak gate (`car_not_indexed`). (docs 08, 12)

## Earlier (June 2026)
- Initial platform: parser + warehouse, Django content serving, Next.js portal, purchase
  flow, RBAC packages + platform admin (migrations 0001–0006), RAG index + diagnostic
  engine + Metis-phrased assistant, eval harness.
