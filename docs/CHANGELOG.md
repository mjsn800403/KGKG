# Changelog

Living log of shipped changes, newest first. One dated block per deploy/commit; keep lines
short and point at the doc section that was updated.

## Unreleased
- **Feature-discovery onboarding.** Measured first: over four months and 34 active seats,
  production showed 71,886 manual views, the parts catalogue opened by 6 people, the assistant
  asked by 9, and the search box used by nobody. People found the manuals and stopped looking,
  and nobody knew because every piece of onboarding state lived in `localStorage`.
  `api/onboarding.py` derives what each seat is entitled to and what it has actually found from
  the activity the product already records — no new tracking, no "mark as done", and entitlement
  computed by the existing `access.user_ai_eligible` / `user_package_set` rather than a second
  definition. An unentitled item is absent from the seat's checklist *and* from the metric's
  denominator. `GET/POST /api/auth/onboarding/` serves it; dismissal is a column, so it survives
  a device change. `components/OnboardingStrip.jsx` shows one collapsed line on `/browse`, never
  a modal. `feature_discovery` on the admin metrics is computed by the same function the
  checklist calls, so the figure management reads and the item the user sees cannot drift apart.
  Spec and plan: `docs/superpowers/specs|plans/2026-10-30-feature-discovery-onboarding*`.
- **Two governance gates, so the process is checked the way the code is** (`ops/governance/`,
  new `governance` job in CI, 27 tests, standard library only):
  * `check_traceability.py` refuses a pull request whose title and body reference no issue.
    Deliberately the weakest rule that still produces evidence — it does not care which item or
    whether it exists, only that the author said. A stricter rule would fail honest changes and
    teach people to paste a number they do not mean. Quoted references inside a code fence do
    not count: pasting someone else's log is not a claim about *this* change. It refused this
    branch's own pull request on the first run, and the description was fixed rather than the
    rule weakened.
  * `check_docs_freshness.py` + `docs/OWNERS.toml` give all 25 documents in `docs/` a named
    owner and a review interval; a document with no entry, no owner, or past
    `reviewed + review_days` fails the build. The staleness rule is literally the one the
    product applies to knowledge-base articles, so the repository and the product never
    disagree about what "stale" means. `docs/superpowers/specs/` is excluded — a dated design
    record cannot go stale. Ownership was then **confirmed by the maintainers**: both of them own all 25
    documents. `owner` takes one name or several, and a stale notice names every owner, so
    neither can assume the other was asked. The `reviewed` dates remain seeded from each
    file's last change — a proxy, not a review; the first real review of a document moves its
    date for the first time. Who owns which ADR is left for the maintainers to settle.
- **The tracker now holds planned work, not only remediation.** Milestones `1.2.0` and
  `Backlog` created and applied to every open issue (0 of 19 carried one before), `type:*` and
  `priority:*` labels added, and five epics filed from the roadmap (#43 ship the desk, #44 close
  the desk loop, #45 GitHub as the system of record, #46 knowledge base in use, #47 delivery and
  flow metrics), each with acceptance criteria. Refs #45.
- **Four fixes from automated review of the service-desk PR**, each with a test written first
  that fails on the previous code:
  * **A specialist never saw their own ticket move.** `events._scoped_qs` gives a plain user only
    their OWN 'user' events plus broadcasts, while the desk emitted 'company' events, which reach
    managers and analytics viewers only. Opening the channel to every seat therefore gave the
    newly admitted audience a dashboard that never updated. `_emit` now sends a user-scoped copy
    to the filer, skipping managers so nothing is announced twice.
  * **A ticket answered through `admin_note` stayed unmeasured** and drifted into a false SLA
    breach: only a `message` stopped the response clock, but `admin_note` *is* the platform's
    reply and the customer reads it. A non-empty note now stamps `first_response_at`; an internal
    note and a bare status change still do not, and an earlier response is never overwritten.
  * **CSAT response rate could exceed 100 %.** A ticket rated and then reopened keeps its score
    but is no longer closed, so the numerator sat outside its denominator. The ratio now counts
    rated tickets *within* the closed cohort; `csat.responses` still counts every score, so a
    reopening never erases a customer's answer.
  * **A slug the reader's route cannot match is refused at the point of writing.** An article with
    a space, a slash or Persian letters in its slug published fine, listed fine, and 404'd when
    opened — with no way to repair it from the editor. Same check on promote-to-article.
- **Coverage floor.** The service-desk branch measured 61 % and raised its floor 56 → 60.
  Reconciling that branch with `work` merges two lineages that each raised the floor
  independently (`work` was at 57), over a combined codebase neither had measured, so the
  merge holds the floor at **57** until CI measures the merged tree and it is raised to what
  that run actually earns. The ratchet's rule — a floor moves up, never down to make CI pass —
  is about a lineage over time; it says nothing about which of two numbers survives a merge,
  and inheriting the higher one without measuring would be guessing.
- **The support desk now has an interface.** Everything below had been API-only, which meant no
  customer could use it. `/requests` is the customer side of the desk and is open to **every**
  seat: file a ticket, hold the conversation (`components/TicketThread.jsx`), see the SLA state
  and how long is left, reopen a closed ticket by replying to it, and rate the resolution
  (`components/CsatPrompt.jsx`). The kinds offered come from the server's `meta`, so a commercial
  kind is never shown to someone who would be refused. The sidebar's support link is shown to
  every seat too — while it was manager-only a specialist had no way in even after the API
  opened, and the navigation was the last part of the 403 that sent people to the telephone.
  (docs/07-frontend.md §7.1, §7.8)
- **Agent worklist** (`components/RequestsInbox.jsx`): SLA state and what is already late without
  opening anything, a "only what is late" filter, a channel filter, assignee selection, escalate,
  internal notes, "log a telephone call" so a call lands in the same system with the same clock,
  and promote-to-article on a closed ticket.
- **A page-feedback widget** (`components/FeedbackWidget.jsx`), mounted globally for signed-in
  seats by the guidance provider. It posts the current pathname — "the search is slow" is only
  actionable with the location — and is deliberately not a ticket.
- **The help panel searches the knowledge base**, not only the built-in guidance articles
  (`guidance/HelpCenter.jsx`). Debounced, signed-in seats only, silent on failure, bodies
  rendered as text, 👍/👎 per article. Every search is logged server-side with its result count:
  the misses are the work list of articles that should exist. (docs/13-guidance-system.md §13.10)
- **Three new admin sections** (`components/SupportAdmin.jsx`): support KPIs, the product-feedback
  feed, and knowledge-base authoring with named owners, review dates, a "needs review" filter and
  version history. A `null` from the metrics API renders as an em dash, never `۰` — a dashboard
  that prints `۰٪` compliance because nothing has been decided yet is worse than one that admits
  it does not know.
- **Tests:** frontend unit tests 179 → 208. `lib/support.js` holds the presentation rules (SLA
  tone and label, due-date text, channel labels, `canRate`, duration and rate formatting) with 29
  tests written first, because a wrong rule there would tell a customer their late ticket is on
  time. `qa/e2e/tests/support.spec.js` adds 10 Playwright tests covering the specialist's whole
  journey and the authorization of the new endpoints.
- **The support channel is open to every seat, and is now a service desk.** `api/requests_api.py`
  was gated end to end on `@require_manager`, so any seat without `can_manage_team` got 403 on
  every ticket endpoint and the telephone was its only channel — the technical cause of the
  evaluation's "customer feedback is collected by telephone" finding. Support requests are now
  self-service (commercial kinds stay manager-only); a ticket has a real conversation
  (`TicketMessage`, with admin-only internal notes) instead of one `admin_note` field; SLA
  response/resolution clocks with a stated policy (`api/sla.py`); `assignee` as a foreign key
  instead of the literal string `'admin'`; escalation; reopen on a customer reply; CSAT after
  closure; and a `source` field so a request taken by telephone is recorded in the same place and
  the shift to digital is measurable. New: `POST /api/admin/company-requests/` (log a call),
  `GET /api/admin/support/metrics/`. (docs/05-api-reference.md §5.7)
- **A general feedback channel** (`api/feedback.py`): `POST /api/feedback/submit/` from any seat,
  `GET /api/admin/feedback/` for the feed. Deliberately not a ticket. Before this the only digital
  feedback surface was the thumb on an assistant answer. (docs/05-api-reference.md §5.7a)
- **A knowledge base** (`api/knowledge.py`): articles with a **named owner** and a review interval
  (so staleness is a query, not an impression), append-only revisions, search with miss logging,
  and `POST /api/admin/company-requests/<id>/promote-to-article/` so a resolved ticket becomes a
  draft article instead of an answer buried in one ticket. (docs/05-api-reference.md §5.7b)
- **Metric definitions as a deliverable.** Every field the new metrics endpoint returns has a
  calculation, a source column, a hand-reproducible query and a test, in
  `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md`. Rates and averages return
  `null`, not `0`, when their denominator is empty; SLA `pending` is excluded from compliance.
- **Root-cause analysis of the 2026-10-30 evaluation findings** in
  `audit-evidence/16-improvement-programme/`, with a prioritised roadmap, the ten-criteria matrix
  and an explicit list of what is **not** done — principally that all of the above is API-only
  and has no interface yet, and that this branch has not had a CI run.
- **Tests:** backend 1,059 → 1,154 (+95, all written test-first): `api/test_helpdesk.py` (60),
  `api/test_knowledge.py` (35). Three pre-existing tests that asserted the old manager-only 403
  and the literal `handled_by='admin'` were updated, each with a comment recording why the
  behaviour changed. Nine new paths added to `docs/openapi.yaml`, caught by the spec gate.
  Migrations `0035_helpdesk_thread_sla_csat`, `0036_knowledge_base` — additive only.
## 1.1.0 — 2026-10-30 (`deploy-20261030-053247`, `8f6df94`)

Infrastructure and governance. Nothing here changes what a customer sees; all
of it changes what can reach them and what an evaluator can check.

Promoted with the full evidence set gathered on the promoted commit — CI green,
staging gate and smoke, E2E 42/42 at full scope, k6 load passing all four
thresholds with production measured untouched, and the ZAP full scan at 141
pass / 0 fail. The first release in this project's history for which the load
and DAST runs the policy has required since 2026-10-27 were actually performed
on the commit that shipped. Record:
`audit-evidence/10-release-management/RELEASE_RECORD_v1.1.0.md`.

The first promote attempt was **refused by the gate**, which found D-43 below
on a commit whose CI had passed.

- **The pipeline is now the only road into production.** `kgkg-promote` refuses
  a commit whose GitHub CI is not green, via `ops/deploy/ci_evidence.sh`, and
  treats an unreachable GitHub as "not green" rather than "fine". The gap this
  closes is not hypothetical: `536ac91` went live on 2026-10-29 with CI red on
  the coverage ratchet, because the server gate proves a release *runs* and
  never saw GitHub's verdict. `test_promote.sh` 22 → 40 checks.
- **The alerting engine can no longer go quiet.** Every infra rule was shaped
  `<metric> == 0`, which matches nothing once the exporter behind it dies — read
  by the engine as healthy. `up{job="kgkg_app"}` was 0 for 49 minutes on
  2026-10-27 and nobody was told. Rules now watch the exporters themselves,
  with `absent()` guards, and `RuleShapeTests` fails any future rule written
  the old way. Postmortem in `audit-evidence/11-operations-and-support/`.
- **Failed systemd units page**, and the fix arrived through the release rather
  than by hand, so the next promote cannot revert it — which is exactly what
  happened to the first attempt.
- **A transient staging unit no longer outlives its run.** The first failed
  staging after the above was one watchdog tick from an SMS every 12 hours
  about a run already reported red in CI. `kg-deploy-gate` resets its own unit;
  the launch path has tests for the first time (`test_gate_roles.sh` 21 → 24).
- **`main` is protected**: required checks, pull request required, admins
  included, no force-push, no deletion. CI was advice until now.
- **Governance**: `README.md`, `LICENSE` (proprietary — the repository is public
  but not open source), `NOTICE`, `SECURITY.md`, `CONTRIBUTING.md`,
  `CODEOWNERS`, a pull-request template, and `.mailmap` folding nine author
  identities into two people plus the assistant and two automations.
- **`.gitignore` no longer ignores all markdown.** It carried a blanket `*.md`
  with no negations, so the SRS, the six ADRs and the whole audit-evidence
  package are tracked only because someone used `git add -f`, and any new
  document would silently never have been committed. ADR-0006 is titled "docs
  as code".
- **Documentation corrected against the host**: the Cloudflare Tunnel that two
  documents described in the present tense is not running (CI uses direct SSH),
  and the "future PostgreSQL move" in `docs/01`/`docs/02` happened on
  2026-10-29.
- **`3389/tcp` closed.** It was open to the internet, v4 and v6, with `xrdp`
  listening behind it and no human session in the server's history.
- **SemVer is applied again.** `VERSION` had read `1.0.0` since before
  `8fa94dd` and shipped two deploys without moving; see the release records
  under `audit-evidence/10-release-management/`.
- **Fix (D-43):** `/api/shield/key/` computed `int(EPOCH - now % EPOCH)` on a
  float, so for the final second of every 600-second epoch the result truncated
  to `0` and the endpoint told the client its freshly minted key had already
  expired — one call in 600. The client already clamped
  (`Math.max(5, k.ttl - 5)`), so the cost was one spurious key refetch and no
  user-visible error; the real cost was a deploy gate that failed at random.
  Integer arithmetic throughout, plus two tests red on the old form
  (`api/test_shield.py`, 13 → 15 tests). Found by the gate re-running the suite
  on the exact commit, which is the repetition the policy calls deliberate.
- **Image retention runs on the staging path**, not only at the end of a
  promote. Each staging builds a 3.46 GB image pair; six runs in nine hours had
  left ~21 GB and taken the root filesystem from 74.5 % to 77 %.
  `ops/deploy/prune_images.sh` (8-case selftest, in CI) keeps the live release,
  the rollback target, the staged sha, anything a container references, and the
  newest few others.

## 1.0.0, second deploy — 2026-10-29 (`deploy-20261029-191834`, `5e4543a`)

Shipped under an **unchanged** `VERSION` of 1.0.0, which is the versioning
lapse recorded in `RELEASE_RECORD_v1.0.0.md`: this content is new capability
(pgvector dense retrieval) and should have been 1.1.0. It is listed under the
number it actually shipped as, not the number it deserved. Promoted with
complete evidence — CI run 40934280389 green, staging gate and smoke pass, E2E
42/42 at full scope — the first release to satisfy all three gates.

- **Dependabot cleanup** (nothing in the production images was exposed). `KG_backend/requirements.txt`
  minimums raised to the lock's versions (Django 5.2.17, cryptography 50.0, sentence-transformers
  5.6, sentry-sdk 2.8, torch 2.12). Frontend dev/build dependencies `npm audit fix`ed (postcss,
  browserslist, js-yaml, brace-expansion, zod). Playwright 1.52 → 1.64.1, package and runner
  image together. Two junk "requirements" files deleted. One alert remains on purpose: torch
  2.13 (GHSA-rrmf-rvhw-rf47), deferred in `ops/security/pip-audit-ignore.txt`.
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

### CI can reach the server (2026-10-29)
- **Why `work` was red:** the `stage` job's secrets (`DEPLOY_HOST`, `DEPLOY_SSH_KEY`,
  `DEPLOY_KNOWN_HOSTS`) had never been set: the old `deploy.yml` dialled an empty host name from
  2026-10-17, and `stage` has stopped at "missing repository secret(s)" since it was added. Only
  the server can create the key.
- **Through a Cloudflare Tunnel:** the runner reaches sshd with `cloudflared access ssh` and an
  Access service token, so port 22 stays closed to the internet (direct SSH remains an option).
- **`ops/deploy/setup_ci_access.sh --tunnel <host>`** (run once on the server as root): dedicated
  CI key pinned to `kg-ci-gate` with `restrict`; installs the connector; logs in through
  Cloudflare back to the server with the host key pinned; checks Access refuses token-less
  requests; secrets set with `gh` or printed to paste.
- **`ops/deploy/ci_ssh.sh`** runs the `stage` job's connection: validates the secrets (CRLF,
  public-vs-private key, passphrase, `user@host:port`), then names the fix for each failure,
  including an expired Access token, a non-Service-Auth policy and a stopped connector (read from
  the HTTP status, since `cloudflared` only says "bad handshake"); refuses a CI key the server
  would let promote (`status` now prints `key role:`). 68 tests in `ops/deploy/test_ci_ssh.sh`.
- **`DEPLOY_KNOWN_HOSTS` is required** (code-scanning finding on #7): without it the job used to warn
  and connect with `accept-new`, which on a fresh runner verifies nothing; now it stops like the
  other missing secrets.
- **Docs:** `ops/deploy/README.md` rewritten for the stage/promote pipeline (it still described the
  deleted auto-deploy); doc 11 §11.3 corrected: the old `deploy.yml` still fires from `main`.


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
