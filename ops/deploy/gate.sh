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

# ---- backend ---------------------------------------------------------------
cd "$W/KG_backend"
step "backend: system check"
"${clean_env[@]}" "$VENV/python" manage.py check > "$LOGS/check.log" 2>&1 || fail "manage.py check" "$LOGS/check.log"

step "backend: migrations match models"
"${clean_env[@]}" "$VENV/python" manage.py makemigrations --check --dry-run > "$LOGS/migrations.log" 2>&1 \
  || fail "model changes without a migration (run makemigrations)" "$LOGS/migrations.log"

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

step "frontend: production build"
# Build-time env is only NEXT_PUBLIC_*; runtime secrets are not needed here.
grep -E '^NEXT_PUBLIC_' /opt/KGKG/kg_frontend/.env.production > .env.production || true
nice -n 10 npm run build > "$LOGS/build.log" 2>&1 || fail "next build" "$LOGS/build.log"
git -C "$W" checkout -q -- kg_frontend/tsconfig.json 2>/dev/null || true

echo; echo "GATE PASSED"
