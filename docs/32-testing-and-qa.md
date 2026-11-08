# 32 — Testing, QA and verification

How to verify any change in KGtechvault, what each mechanism proves, and what is **not** covered. Source revision `origin/work`
@ `f078878` **[C]**. No pass rate or coverage figure appears unless it is stated in a file in the repository and tagged with
where it comes from; the live numbers are in the CI run summaries. Persian version:
[fa/32-testing-and-qa.md](fa/32-testing-and-qa.md). Related: [17-evaluation.md](17-evaluation.md) (AI evaluation),
[11-operations-deployment.md](11-operations-deployment.md), [31-ops-files-reference.md](31-ops-files-reference.md), `audit-evidence/`
(the 2026 audit pack, dated evidence, not a live status).

## 32.1 Map of mechanisms

| # | Mechanism | Where it runs | Trigger | Blocks merge? |
|---|---|---|---|---|
| 1 | Backend Django test suite (112 `test_*`/`tests*.py` modules under `KG_backend/`) with branch coverage | CI job `backend` (PostgreSQL 16 service) | every push and PR | yes |
| 2 | Migration checks (`makemigrations --check`, additive-only, `ops/deploy/check_migrations.py`) | `backend` job; deploy gate | push/PR; deploy | yes |
| 3 | Coverage ratchet (`ops/deploy/coverage_min`, currently **59**) | `backend` job | push/PR | yes |
| 4 | Frontend lint ratchet (`ops/deploy/lint_max_warnings`, currently **116**), unit tests (`node --test`, 21 files), production build | CI job `frontend` | push/PR | yes |
| 5 | Operations tests (deploy gate roles, promote evidence, guard wiring, CI SSH, watchdog, staging sanitizer, smoke fleet) | CI job `security` | push/PR | yes |
| 6 | Security gates: shellcheck, hadolint, gitleaks, bandit, pip-audit, npm audit, trivy (images), CodeQL | CI jobs `security`, `images`, CodeQL workflow | push/PR | yes |
| 7 | Governance: docs ownership/freshness, generated inventory + debt ratchet, PR traceability | CI job `governance` | push/PR | yes |
| 8 | Support-chat E2E (Playwright) on a throwaway stack | CI job `support-chat-e2e` | push/PR | yes (it ran and passed on PR #88) |
| 9 | Full browser E2E, passive DAST, performance baseline on the QA stack | host: `qa/nightly.sh` via `ops/qa/kgkg-qa-nightly.timer/.service` | nightly | no (alerts via `_qa` rule) |
| 10 | Load / stress / soak (k6) | on demand: `qa/perf/run_perf.sh <profile>`, `qa/k6/support_chat_poll.js` | manual | no |
| 11 | Mutation testing of authorization modules (mutmut) | workflow `mutation.yml`, `qa/mutation/run.sh` | manual (`workflow_dispatch`) | no |
| 12 | Offline RAG evaluation (gold sets, zero LLM calls) | `qa/eval/run_rag_eval.sh`, `manage.py run_evalsuite` | manual | no |
| 13 | Deploy gate, staging deploy, post-deploy smoke | host: `ops/deploy/gate.sh`, `deploy.sh`, `smoke.sh`, `smoke_fleet.py` | each stage/promote | yes (for deploy) |
| 14 | Promote-time evidence (CI success of the sha, E2E record, tip check) | `kgkg-promote`, `ci_evidence.sh`, `ci_is_tip.sh`, `promote_guard.sh` | each promotion by a person | yes |

## 32.2 Backend tests

- **Layout:** Django `TestCase`/`SimpleTestCase` modules named `test_*.py` next to the code (`api/`, `api/rag/`, `api/support_chat/`, `api/evalsuite/`, etc.)
  plus `tests.py` and `tests_parts.py`. 112 files at the revision above **[C]**.
- **Database:** PostgreSQL 16 in CI (`KG_DB_ENGINE=postgres`, service container with CI-only credentials); a per-run test database name is possible via
  `KG_PG_TEST_NAME`. The deploy gate uses the host's PostgreSQL over the local socket with a per-run name (`test_kgkg_gate_$$`).
- **Offline by design:** `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `KG_WARMUP=0`, dummy `KG_ADMIN_TOKEN`/`KG_ENV_FILE` in CI: no model downloads, no external calls.
- **Order randomisation:** `--shuffle`; the log prints `Using shuffle seed: N`. Reproduce: `python manage.py test --shuffle N`.
- **Run locally** (from `KG_backend/`, with the lock-file dependencies installed):

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput --shuffle           # whole suite
python manage.py test api.rag --noinput             # one package
python manage.py test api.test_qa_auth --noinput    # one module
```

  Without PostgreSQL set `KG_DB_ENGINE` unset to use SQLite (development default); PostgreSQL-only behaviour (for example `cardb_pg`) needs the CI-like environment.
- **Coverage:** `coverage run --branch --source=api --omit='*/test_*,*/tests.py,*/tests_*.py,*/migrations/*' manage.py test ...`. Test modules and migrations are excluded
  so the figure cannot be inflated by tests covering themselves. `coverage report --fail-under=$(cat ops/deploy/coverage_min)`. The file is a **floor that may only move up**
  and must be raised in the same commit that adds the tests. Reports (JUnit XML, `coverage.xml`, HTML) are uploaded as artifact `backend-test-reports-<sha>`; the
  totals appear in the job's step summary. The current measured value is **not recorded in the repository**; read the latest run summary **[U]**.
- **Failure interpretation:** a red `Full test suite` step with a shuffle seed → rerun with that seed to separate a real failure from an order dependency; a red
  `Coverage ratchet` step → coverage fell below the floor (add tests; do not lower the file); a red `Migrations match models` step → generate and commit the migration.
- **Notable suites:** authorization (`test_qa_auth.py`, access and media-auth modules; these are the modules mutation testing targets), RAG (`api/rag/test_*.py`,
  see [30](30-ai-assistant-deep-dive.md) §30.11), support chat (`api/support_chat/`, see [22](22-support-chat.md)), car-database PostgreSQL translator
  (`test_cardb_pg.py`), host jobs (`test_hostjobs.py`), OpenAPI contract (`docs/openapi.yaml` is test-enforced — a view change without the spec change fails).

## 32.3 Frontend tests

- **Runner:** Node's built-in test runner: `npm test` = `node --test --experimental-test-coverage src/` (no Jest/Vitest). Files are `*.test.mjs` next to the
  code, mainly in `kg_frontend/src/lib/__tests__/` (21 files at this revision: `chatPrompt`, `contextualize`, `faTerms`, `safeUrl`, `sanitizeHtml`, `support`, `desk`,
  `pricing`, `packages`, `onboarding`, `manualContent`, `vehicleContent`, `friendlyError` and others) **[C]**. They test pure logic (prompt building, link sanitising,
  sanitisation, Persian terminology), not React rendering; there is no component-test framework in `package.json`.
- **Lint:** ESLint (`npm run lint`) with a **warning ratchet** (`ops/deploy/lint_max_warnings`, 116): the count may only go down.
- **Build:** `npm run build` (Next.js production build) must succeed in CI.
- **Guidance sync:** `kg_frontend/scripts/check-guidance-sync.mjs` checks the guidance-tour data against its source (see [13-guidance-system.md](13-guidance-system.md)).
- **Run locally:**

```bash
cd kg_frontend && npm ci --no-audit --no-fund
npm run lint && npm test && npm run build
```

## 32.4 Support-chat E2E (CI)

Job `support-chat-e2e` brings up a throwaway backend + frontend stack (`qa/e2e/support-chat-stack.sh`; Windows: `local-support-chat-stack.ps1`), installs Playwright,
and runs `npx playwright test support-chat.spec.js --project=chromium`. Two guards stop it from passing vacuously: a **negative check** that a missing stack *fails*
instead of skipping, and `qa/e2e/support_chat_guard.py` which reads `results.json` and fails unless **every** support-chat test ran and passed (no skipped, no
missing). The suite record is uploaded as `support-chat-e2e-<sha>`. See [22-support-chat.md](22-support-chat.md) for what the tests assert.

## 32.5 Full browser E2E, DAST and performance baseline (QA stack, nightly)

- **QA stack** (`qa/stack.sh up|down|reseed|status`): own labelled containers on loopback ports 8120 (backend), 3117 (frontend), 8130 (single-origin proxy
  `qa/nginx-qa.conf`; its `/kg-api/` location must send `Host $http_host`, with the port, because `OriginGuardMiddleware` compares the browser's
  `Origin` (`http://127.0.0.1:8130`) with the request's own scheme+host and answers 403 to a cookie-authenticated write when they differ), never production (8000/3000) or staging (8110/3107). Data is a **fresh sanitized copy** of the production DB (PostgreSQL `pg_dump` clone named
  `<db>_qa`, or SQLite online backup) run through `ops/deploy/sanitize_staging_db.py`, so no real account can log in and no real phone/e-mail exists; SMS, Sentry,
  Turnstile, Metis and host jobs are disabled; the RAG feedback store is redirected (`RAG_FEEDBACK_DB`); CPU/memory are capped. Test accounts come from
  `manage.py seed_qa_fixtures` (guarded by `KG_QA_STACK=1` and a per-run `KG_QA_PASSWORD` minted into a mode-600 file). The comment in `stack.sh` states what makes it
  safe; it does not say that `kgkg_vec` is cloned, and the car content therefore comes from the host's warehouse mount **[U]** (see risk R5, [27](27-open-risks-and-decisions.md)).
- **Playwright E2E** (`qa/e2e/tests/`: `public`, `auth`, `authz`, `session`, `media`, `a11y`, `support`, `support-chat`): locale `fa-IR`, one worker, **zero retries**
  ("a flaky test is a finding"), trace/screenshot on failure; the config refuses to run if the origin looks like production. Run on the stack:
  `qa/run_e2e.sh` (outputs `qa/e2e/results/{junit.xml,results.json,html/}`; also writes an evidence record `$KG_REL_DIR/e2e/<sha>.env` via `qa/e2e_record.py`
  that `kgkg-promote` reads; a filtered run is recorded as `scope=partial` and does not count).
- **DAST:** `qa/dast/run_zap.sh baseline` — passive OWASP ZAP baseline, no attack traffic; rule dispositions in `qa/dast/rules.tsv` (default WARN; entries only with a
  triage reason).
- **Performance baseline:** `qa/perf/run_perf.sh baseline` using `qa/perf/k6-kgkg.js`: single user for 2 min. **Thresholds:** error rate < 1 %; page p95 < 1500 ms;
  API p95 < 500 ms; assistant (RAG) p95 < 4000 ms. Other profiles: `load` (10 VUs, ~6.5 min), `stress` (10→25→50 VUs, no thresholds — it looks for the breaking point),
  `soak` (8 VUs, 20 min).
- **Nightly orchestration:** `qa/nightly.sh [ref]` (flock guard; fresh detached worktree; steps stack up → E2E → DAST → perf → stack down, each recorded even if
  an earlier step fails). Results: `/opt/KGKG_qa/nightly/<UTC>-<sha9>/` (30 runs kept); metrics `kgkg_qa.prom` in the node-exporter textfile directory; the `_qa` alert rule
  pages when the last result is older than `KG_ALERT_QA_STALE_H` (36 h) or failed. Whether the timer is enabled and when it last passed is **[U]** (host verification blocked).

## 32.6 Load testing the support chat

`qa/k6/support_chat_poll.js` drives visitor polling (default 100 VUs for 60 s; `VUS`, `DURATION` environment overrides) to measure the cost of polling vs SSE.
Findings and decisions are in [22-support-chat.md](22-support-chat.md) and [09-realtime-sse.md](09-realtime-sse.md).

## 32.7 Mutation testing

`qa/mutation/run.sh [module …]` (default `admin_auth mediaauth access`) runs mutmut 2.4.5 on a throwaway `git archive HEAD` copy so the working tree is not touched. Coverage
says a line ran; a surviving mutant means a change in authorization logic that no test would notice. It takes about an hour per large module, is run on demand (workflow
`mutation`, `workflow_dispatch`, 180 min limit) and its results are release evidence when copied to `audit-evidence/03-unit-testing/mutation/`. No result is committed in
`docs/`; the latest figures are in `audit-evidence/` if present **[U]**.

## 32.8 Static analysis and supply-chain gates

| Gate | Tool and scope | Blocks on | Exception file |
|---|---|---|---|
| Shell lint | shellcheck on `ops/**/*.sh` and `ops/deploy/kg-deploy-gate` | any warning | — |
| Dockerfile lint | hadolint on `ops/docker/*.Dockerfile` | any warning | `.hadolint.yaml` |
| Secret scan | gitleaks (tree + pushed commits) | any finding | `.gitleaks.toml` allow-list |
| SAST | bandit on Python | findings not in baseline | `ops/security/bandit-baseline.json` |
| Python deps | pip-audit on `ops/docker/backend-requirements.lock` | advisory not ignored | `pip-audit-ignore.txt` |
| Node deps | npm audit (production), `npm_audit_gate.mjs`, severity ≥ high | advisory not allowed | `ops/security/npm-audit-allow.json` (empty) |
| Image scan | trivy on both production images, fixable HIGH/CRITICAL | finding not ignored | `.trivyignore.yaml` |
| CodeQL | GitHub code scanning for Python, JavaScript/TypeScript and Actions | alerts per repository policy | — |

The same three server-side scans run in the **deploy gate** (`ops/security/scan.sh`, scanners from a pinned venv; a scanner that cannot run fails the gate). Details:
`ops/security/README.md`.

## 32.9 Operations tests (job `security`, step "Operations tests")

Standard-library-only tests of the machinery that guards production: `test_gate_roles.sh`, `test_promote.sh`, `ci_evidence.sh --selftest`, `prune_images.sh --selftest`,
`ci_is_tip.sh --selftest`, `test_detached_prod.sh`, `test_promote_guard.sh`, `test_promote_guard_wiring.sh`, `qa/e2e_record.py --selftest`, `ops/deploy/smoke_fleet.py --selftest`,
`qa/e2e/support_chat_guard.py --selftest`, the observability unit tests, `sanitize_staging_db.py --selftest`, `watchdog.py --selftest`, `test_ci_ssh.sh`. Run any of them
locally with `bash ops/deploy/<name>` or `python3 <path> --selftest`.

## 32.10 Governance tests

`python3 -m unittest discover` inside `ops/governance/` (also executed by the `governance` job) covers the freshness check, the traceability check and the inventory ratchet
(14 tests build temporary git repositories to prove that regenerating the debt file cannot bypass the target branch's baseline). Commands: [AGENTS.md](AGENTS.md) §6.

## 32.11 Deployment verification

- **Gate** (`ops/deploy/gate.sh`, run by `deploy.sh` before anything changes): migration additivity check against `KG_MIGRATION_BASE`, the backend suite on a throwaway
  PostgreSQL database, security scans, logs under `$REL/logs/gate-<ts>`. A failing gate leaves production untouched.
- **Stage** (CI job `stage`, only on `work` pushes with the credential present; skipped on PRs): builds, stages the sha on separate containers (`kgkg-stg-*`), runs migrations
  against a sanitized clone, seeds, and smoke-tests. A missing staging secret turns the job red (known risk).
- **Smoke** (`ops/deploy/smoke.sh`): health, reverse-proxy check with a `Host:` header, the scrape listener must answer 403 for anything but metrics, and
  `smoke_fleet.py` opens `KG_SMOKE_SAMPLE` (default 3, 1..20) vehicles per category with a token.
- **Do not equate a green deploy or HTTP 200 with health:** also check container health, GlitchTip and metrics ([AGENTS.md](AGENTS.md) rule 7).

## 32.12 How to verify a change (decision table)

| You changed | Minimum local verification | CI gate that will check it |
|---|---|---|
| Backend logic / model / view | `manage.py test <package>`; `makemigrations --check`; update `docs/openapi.yaml` and docs | `backend`, `governance` |
| A migration | additive only; `ops/deploy/check_migrations.py` | `backend`, deploy gate |
| Retrieval / ranking / prompt | `manage.py test api.rag`; for ranking changes run the offline evaluation (`qa/eval/run_rag_eval.sh`) and compare with `paired_significance.py` | `backend`, manual |
| Authorization (`access.py`, `admin_auth.py`, `mediaauth.py`) | unit tests + consider `qa/mutation/run.sh <module>` | `backend`, `mutation` on demand |
| Frontend logic | `npm run lint && npm test && npm run build` | `frontend` |
| Support chat | backend tests + `support-chat.spec.js` on the throwaway stack | `support-chat-e2e` |
| `ops/` script or unit | `shellcheck`; its `--selftest`; docs row in 31 | `security`, `governance` |
| Docs only | `check_docs_freshness.py`, `gen_inventory.py --check`, `check_i18n.py` | `governance` |

## 32.13 Known gaps (stated, not hidden)

- No component/DOM-level frontend tests and no frontend coverage gate; `node --experimental-test-coverage` prints a report but nothing enforces a floor.
- The backend coverage floor is 59 %; the measured value and its trend are not stored in the repository.
- Browser E2E (other than support chat) is **not** in per-PR CI; it runs nightly on the host, so regressions are found after merge.
- Load tests are manual; there is no recorded baseline committed to the repository **[U]**.
- AI answer quality has no automated check in CI; evaluation is offline and manual (§30.11).
- PostgreSQL-specific behaviour of car-content storage (`kgkg_vec`) is tested through the translator unit tests; a test against a populated 58 GB `kgkg_vec` does not exist.
- The QA stack's data source for car content is **[U]** (see §32.5).
