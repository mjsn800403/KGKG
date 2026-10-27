# CI/CD pipeline and how to reproduce every check locally

## Pipeline (`.github/workflows/ci.yml`, every push and pull request)

| Job | Steps | Fails the build when |
|---|---|---|
| `backend` | Django system check → migrations match models → full test suite with **branch** coverage (all test modules excluded from the denominator) and JUnit XML → coverage floor (`ops/deploy/coverage_min`, ratchet: may only rise) → coverage XML/HTML + test reports uploaded as artifacts (90 days) | any test fails; coverage below floor; model change without migration |
| `frontend` | `npm ci` → ESLint with a warnings ratchet → **unit tests** (`npm test`, node:test with coverage) → production build | lint error or warnings above cap; any unit test fails; build fails |
| `security` | shellcheck (ops/, qa/) → operations tests (deploy-gate roles, watchdog, staging sanitizer self-test) → hadolint → gitleaks (filesystem, report asserted to exist) → **bandit SAST** against triaged baseline → QA-suite parse check → pip-audit (lockfile) → npm audit gate | any new finding; any unreviewed advisory |
| `images` | build backend and frontend images → backend image boots (`manage.py check`) → Trivy HIGH/CRITICAL (fixable) on both | build fails; fixable HIGH/CRITICAL |
| `stage` (branch `work` only, after all above) | asks the server to stage that sha: server-side gate again in a clean worktree → images → staging on a sanitized prod-DB copy → smoke | any server gate or smoke failure |

Promotion to production is never automatic: `kgkg-promote <sha>` on the
server, by a person (see `10-release-management/RELEASE_POLICY.md`).

Pre-release suites that need the server's data and run on the QA stack, not
on GitHub runners: E2E (`qa/run_e2e.sh`), load (`qa/perf/run_perf.sh`),
DAST (`qa/dast/run_zap.sh`). They are documented release steps; they are not
yet triggered automatically by CI (gap recorded in the criteria matrix).

## Reproduce locally

Backend (Python 3.12):

```bash
cd KG_backend
python -m venv .venv && . .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install "Django>=4.2,<6" "django-cors-headers>=4.0" "beautifulsoup4>=4.12" "html5lib>=1.1" \
  "numpy>=1.26,<2" "sqlite-vec>=0.1.6" "sentence-transformers>=2.7" "sentry-sdk>=2.0,<3" \
  weasyprint pillow requests coverage unittest-xml-reporting
export DJANGO_DEBUG=true KG_ADMIN_TOKEN=ci-dummy-token KG_ENV_FILE=/tmp/ci-dummy.env \
       HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 KG_WARMUP=0
python manage.py check && python manage.py makemigrations --check --dry-run
coverage run --branch --source=api --omit='*/test_*,*/tests.py,*/tests_*.py,*/migrations/*' manage.py test --noinput
coverage report --fail-under="$(cat ../ops/deploy/coverage_min)"
```

Frontend (Node 20):

```bash
cd kg_frontend && npm ci && npx eslint src --max-warnings "$(cat ../ops/deploy/lint_max_warnings)" && npm test && npm run build
```

SAST:

```bash
pip install bandit==1.9.4
bandit -r KG_backend/api KG_backend/KG_backend -x '*/test_*,*/tests.py,*/tests_parts.py,*/migrations/*' -ll -b ops/security/bandit-baseline.json
```

QA-stack suites (on the server, Docker required):

```bash
qa/stack.sh up <git-ref>
qa/run_e2e.sh
KG_QA_BACKEND_ENV="KG_RL_DISABLE=1 KG_CG_PAGE_BLOCK=1000000 KG_CG_PAGE_WARN=1000000" qa/stack.sh up <git-ref>
qa/perf/run_perf.sh load
qa/dast/run_zap.sh full
qa/stack.sh down
```
