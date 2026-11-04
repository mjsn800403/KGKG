#!/usr/bin/env bash
# Proof that the proposed deploy.sh change (docs/superpowers/specs/2026-11-04-deploy-guard-wiring.patch)
# is safe to apply, WITHOUT applying it. The patch is applied to a scratch copy of the committed
# deploy.sh, and the exact guard text from that copy is run against throwaway repositories.
#
#   ops/deploy/test_promote_guard_wiring.sh      (exit 0 = pass)
#
# Covered: the patch applies; the patched script parses; the guard sits after the fast-forward
# check and AFTER the rollback and reload exits (so recovery never depends on GitHub); a normal
# promote, an off-work commit, an unreachable origin and the one-command override behave as
# documented in full mode; staging, rollback, reload and status are never blocked.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
PATCH="$ROOT/docs/superpowers/specs/2026-11-04-deploy-guard-wiring.patch"

PASS=0; FAIL=0
ok() { printf '  ok    %s\n' "$1"; PASS=$((PASS+1)); }
no() { printf '  FAIL  %s\n          %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

# --- 1. the patch applies to the committed deploy.sh and the result parses ----------------------
git -C "$ROOT" show HEAD:ops/deploy/deploy.sh > "$T/deploy.sh" 2>/dev/null || { no "cannot read the committed deploy.sh"; exit 1; }
mkdir -p "$T/scratch/ops/deploy"
cp "$T/deploy.sh" "$T/scratch/ops/deploy/deploy.sh"
if git -C "$T/scratch" apply --unsafe-paths --directory=. "$PATCH" 2>"$T/apply.err" || (cd "$T/scratch" && git apply "$PATCH" 2>"$T/apply.err"); then
  ok "the patch applies to the committed deploy.sh"
else no "the patch does not apply" "$(cat "$T/apply.err")"; exit 1; fi
P="$T/scratch/ops/deploy/deploy.sh"
if bash -n "$P"; then ok "the patched deploy.sh parses"; else no "patched deploy.sh has a syntax error"; fi
if [[ $(git -C "$ROOT" diff --numstat HEAD -- ops/deploy/deploy.sh | wc -l) -eq 0 ]]; then
  ok "the real deploy.sh in this tree is unchanged (the patch is not applied)"
else no "deploy.sh in the tree differs from HEAD" "this test must not run with deploy.sh modified"; fi

# --- 2. where the guard sits ---------------------------------------------------------------------
line() { grep -n -F -- "$1" "$P" | head -1 | cut -d: -f1; }
ff=$(line 'merge-base --is-ancestor "$PREV" "$SHA"')
guard=$(line 'require_on_work "$PROD" "$SHA"')
rollback_exit=$(grep -n 'rollback_to "\$PREVIOUS"' "$P" | head -1 | cut -d: -f1)
reload_start=$(line 'if [[ $MODE == reload ]]; then')
[[ -n $ff && -n $guard && $guard -gt $ff ]] && ok "the guard runs after the fast-forward check" || no "guard not after the fast-forward check" "ff=$ff guard=$guard"
[[ -n $rollback_exit && $guard -gt $rollback_exit && $guard -gt $reload_start ]] \
  && ok "the guard is below the rollback and reload exits: recovery never needs GitHub" \
  || no "guard is not below rollback/reload" "reload=$reload_start rollback=$rollback_exit guard=$guard"

# --- 3. the exact guard text, run in each mode ---------------------------------------------------
start=$(grep -n -F '# Production runs only commits the repository contains' "$P" | cut -d: -f1)
end=$(awk -v s="$start" 'NR>s && /^fi$/ {print NR; exit}' "$P")
sed -n "${start},${end}p" "$P" > "$T/guard_block.sh"
cp "$ROOT/ops/deploy/promote_guard.sh" "$T/promote_guard.sh"

g() { git -C "$T/prod" -c user.name=t -c user.email=t@t "$@"; }
git init -q --bare "$T/origin.git"
git init -q -b work "$T/prod"
g remote add origin "$T/origin.git"
echo one > "$T/prod/f"; g add f; g commit -qm one; g push -q origin work
ON_WORK=$(g rev-parse HEAD)
echo two > "$T/prod/f"; g commit -qam "two, never pushed"
OFF_WORK=$(g rev-parse HEAD)
g checkout -q --detach "$ON_WORK"       # the production checkout is detached, as in life

# run MODE SHA [env...]: executes the guard block as deploy.sh would; prints CONTINUE or the abort.
run() {
  local mode=$1 sha=$2; shift 2
  ( cd "$T" || exit 3
    env "$@" bash -c '
      die() { echo "ABORT: $*"; exit 99; }
      PROD=$1; SHA=$2; MODE=$3
      BASH_SOURCE=("$4/deploy.sh")
      source "$5"
      echo CONTINUE
    ' _ "$T/prod" "$sha" "$mode" "$T" "$T/guard_block.sh" )
}
# the block sources promote_guard.sh next to deploy.sh: $T/promote_guard.sh is there.

out=$(run full "$ON_WORK" X=1 2>&1);            [[ $out == *CONTINUE* ]] && ok "full: a commit on origin/work continues" || no "full/on-work" "$out"
out=$(run full "$OFF_WORK" X=1 2>&1);           [[ $out == *"ABORT:"*"not on origin/work"* ]] && ok "full: a commit not on origin/work aborts with the reason" || no "full/off-work" "$out"
g remote set-url origin "$T/missing.git"
out=$(run full "$ON_WORK" X=1 2>&1);            [[ $out == *"ABORT:"*"fail closed"* ]] && ok "full: an unreachable origin aborts (fail closed)" || no "full/unreachable" "$out"
out=$(run full "$OFF_WORK" KGKG_ALLOW_OFF_WORK=1 2>&1); [[ $out == *CONTINUE* && $out == *WARNING* ]] && ok "full: KGKG_ALLOW_OFF_WORK=1 continues and warns (emergency override)" || no "full/override" "$out"
for m in staging rollback reload status; do
  out=$(run "$m" "$OFF_WORK" X=1 2>&1);         [[ $out == *CONTINUE* && $out != *ABORT* ]] && ok "$m: never blocked, even off-work with origin unreachable" || no "$m blocked" "$out"
done
g remote set-url origin "$T/origin.git"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[[ $FAIL -eq 0 ]]
