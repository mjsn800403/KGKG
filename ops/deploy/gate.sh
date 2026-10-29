#!/usr/bin/env bash
# KGKG quality gate: everything a release must pass before it may touch
# staging or production. Runs inside a clean checkout (a git worktree), never
# in the live tree, and with a scrubbed environment: no prod secrets, no SMS,
# no Sentry, no Metis, and KG_ENV_FILE pointed at a throwaway file so a test
# can never rewrite the real .env.prod.
#
# Usage: ops/deploy/gate.sh <checkout-dir>        (exit 0 = pass)
set -Eeuo pipefail
W=${1:?usage: gate.sh <checkout-dir>}
VENV=${KG_VENV:-/opt/KGKG/KG_backend/.venv/bin}
LOGS=${KG_GATE_LOGS:-$W/.gate-logs}
mkdir -p "$LOGS"
step() { printf '\n== %s  [%s]\n' "$1" "$(date -u +%H:%M:%S)"; }
fail() { echo "GATE FAILED: $1 (log: $2)"; tail -40 "$2" || true; exit 1; }

clean_env=(env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/root LANG=C.UTF-8
  DJANGO_DEBUG=true KG_ADMIN_TOKEN=gate-dummy-token KG_ENV_FILE=/tmp/kg-gate-dummy.env
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 KG_WARMUP=0)
# Test on the engine production runs. With PostgreSQL the suite connects as
# the `root` role over the local socket (peer auth; it may create databases)
# and gets a per-run test database, so a CI gate and a deploy gate running at
# the same time cannot drop each other's.
if grep -qiE '^KG_DB_ENGINE=["'"'"']?postgres' "${KG_PROD_ENV:-/opt/KGKG/KG_backend/.env.prod}" 2>/dev/null; then
  clean_env+=(KG_DB_ENGINE=postgres KG_PG_HOST= KG_PG_USER=root KG_PG_NAME=kgkg_gate
              KG_PG_TEST_NAME="test_kgkg_gate_$$")
  echo "gate: tests run on PostgreSQL"
fi

# ---- security scans (same script and exception files as CI) ----------------
# Before 2026-10-29 only CI ran these, so 8fa94dd, red on bandit in CI, passed
# this gate and shipped. They run first: they take seconds, the suite minutes.
# bandit and pip-audit come from a pinned tool venv beside the release state,
# created on first use; a scanner that cannot run (no network for the advisory
# databases) fails the gate rather than being skipped.
SECTOOLS=${KG_SECTOOLS:-/opt/KGKG_release/sectools}
SECTOOLS_PINS=(bandit==1.9.4 pip-audit==2.9.0)
step "security: tools (${SECTOOLS_PINS[*]})"
if ! "$SECTOOLS/bin/python" -m pip freeze 2>/dev/null | grep -qxF -e "${SECTOOLS_PINS[0]}" \
   || ! "$SECTOOLS/bin/python" -m pip freeze 2>/dev/null | grep -qxF -e "${SECTOOLS_PINS[1]}"; then
  { "$VENV/python" -m venv --clear "$SECTOOLS" \
    && "$SECTOOLS/bin/python" -m pip install --quiet "${SECTOOLS_PINS[@]}"; } > "$LOGS/sectools.log" 2>&1 \
    || fail "could not install the scanners into $SECTOOLS" "$LOGS/sectools.log"
fi
for scan in bandit pip-audit npm; do
  step "security: $scan"
  KG_SECTOOLS_BIN="$SECTOOLS/bin" bash "$W/ops/security/scan.sh" "$scan" > "$LOGS/sec-$scan.log" 2>&1 \
    || fail "$scan (exceptions and policy: ops/security/README.md)" "$LOGS/sec-$scan.log"
  tail -1 "$LOGS/sec-$scan.log"
done

# ---- backend ---------------------------------------------------------------
cd "$W/KG_backend"
step "backend: system check"
"${clean_env[@]}" "$VENV/python" manage.py check > "$LOGS/check.log" 2>&1 || fail "manage.py check" "$LOGS/check.log"

step "backend: migrations match models"
"${clean_env[@]}" "$VENV/python" manage.py makemigrations --check --dry-run > "$LOGS/migrations.log" 2>&1 \
  || fail "model changes without a migration (run makemigrations)" "$LOGS/migrations.log"

step "backend: migrations are rollback-safe"
BASE=${KG_MIGRATION_BASE:-$(git -C /opt/KGKG rev-parse HEAD)}
"${clean_env[@]}" "$VENV/python" ../ops/deploy/check_migrations.py "$BASE" > "$LOGS/migsafety.log" 2>&1   || fail "a new migration would break rollback (see ops/deploy/check_migrations.py)" "$LOGS/migsafety.log"
cat "$LOGS/migsafety.log"

step "backend: full test suite"
"${clean_env[@]}" timeout 1200 "$VENV/python" manage.py test --noinput > "$LOGS/tests.log" 2>&1 \
  || fail "backend tests" "$LOGS/tests.log"
grep -E '^Ran [0-9]+ tests' "$LOGS/tests.log" || true

# ---- frontend --------------------------------------------------------------
cd "$W/kg_frontend"
step "frontend: npm ci"
npm ci --no-audit --no-fund > "$LOGS/npm.log" 2>&1 || fail "npm ci" "$LOGS/npm.log"

step "frontend: lint (ratchet)"
MAXW=$(cat "$W/ops/deploy/lint_max_warnings")
npx eslint src --max-warnings "$MAXW" > "$LOGS/lint.log" 2>&1 \
  || fail "lint: new errors, or warnings above the cap of $MAXW (ops/deploy/lint_max_warnings)" "$LOGS/lint.log"
tail -2 "$LOGS/lint.log"

step "frontend: unit tests"
npm test > "$LOGS/fe-tests.log" 2>&1 || fail "frontend unit tests" "$LOGS/fe-tests.log"
grep -E '^# (tests|pass|fail)' "$LOGS/fe-tests.log" || true

step "frontend: production build"
# Build-time env is only NEXT_PUBLIC_*; runtime secrets are not needed here.
grep -E '^NEXT_PUBLIC_' /opt/KGKG/kg_frontend/.env.production > .env.production || true
nice -n 10 npm run build > "$LOGS/build.log" 2>&1 || fail "next build" "$LOGS/build.log"
git -C "$W" checkout -q -- kg_frontend/tsconfig.json 2>/dev/null || true

echo; echo "GATE PASSED"
