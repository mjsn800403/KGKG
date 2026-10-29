#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# The security scans, in one place, so CI (.github/workflows/ci.yml) and the
# server's release gate (ops/deploy/gate.sh) run exactly the same checks with
# the same exception files. Before 2026-10-29 only CI ran them, so a commit
# whose CI was red on bandit (8fa94dd) passed the server gate and shipped.
#
#   ops/security/scan.sh bandit       SAST, medium+ severity, new findings fail
#   ops/security/scan.sh pip-audit    Python lock vs advisories, reviewed ids ignored
#   ops/security/scan.sh npm          Node advisories >= high, allowlist applies
#   ops/security/scan.sh all          all three, stop at the first failure
#
# Tools: bandit and pip-audit are taken from $KG_SECTOOLS_BIN when set (the
# gate points it at a pinned venv), else from PATH. Policy and the exception
# files: ops/security/README.md.
#
# Exit 0 = pass. Anything else = fail, including a scanner that could not run
# (no network for the advisory database, tool missing): a broken scan must
# never look like a pass.
# ---------------------------------------------------------------------------
set -Eeuo pipefail
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SEC=$REPO/ops/security
BIN=${KG_SECTOOLS_BIN:+$KG_SECTOOLS_BIN/}

tool() {  # name -> path, or fail loudly
  local t="${BIN}$1"
  command -v "$t" >/dev/null 2>&1 || { echo "scan: $1 not found (${BIN:-PATH})" >&2; exit 2; }
  printf '%s' "$t"
}

run_bandit() {
  local b; b=$(tool bandit)
  echo "== bandit (baseline: $(grep -c '"test_id"' "$SEC/bandit-baseline.json") triaged findings)"
  # Relative paths on purpose: the baseline records findings by file name as
  # seen from the repository root, and an absolute path never matches it.
  ( cd "$REPO" && "$b" -q -r KG_backend/api KG_backend/KG_backend \
      -x '*/test_*,*/tests.py,*/tests_parts.py,*/migrations/*' \
      -ll -b ops/security/bandit-baseline.json )
  echo "bandit: PASS"
}

run_pip_audit() {
  local p lock; p=$(tool pip-audit)
  # The lock pins torch to a +cpu local version that exists only on PyTorch's
  # index; strip the local label so the advisory database can be queried.
  lock=$(mktemp); trap 'rm -f "$lock"' RETURN
  sed 's/+cpu$//' "$REPO/ops/docker/backend-requirements.lock" > "$lock"
  local ignores=()
  mapfile -t ignores < <(grep -vE '^\s*(#|$)' "$SEC/pip-audit-ignore.txt" | sed 's/^/--ignore-vuln=/')
  echo "== pip-audit (ignoring ${#ignores[@]} reviewed advisory id(s))"
  "$p" --no-deps --progress-spinner off -r "$lock" "${ignores[@]}"
  echo "pip-audit: PASS"
}

run_npm() {
  command -v node >/dev/null 2>&1 || { echo "scan: node not found" >&2; exit 2; }
  echo "== npm audit gate"
  node "$SEC/npm_audit_gate.mjs"
}

case ${1:-} in
  bandit)    run_bandit ;;
  pip-audit) run_pip_audit ;;
  npm)       run_npm ;;
  all)       run_bandit; run_pip_audit; run_npm ;;
  *) echo "usage: scan.sh bandit|pip-audit|npm|all" >&2; exit 2 ;;
esac
