#!/usr/bin/env bash
# Proof of the promote guard (ops/deploy/promote_guard.sh) against throwaway repositories.
#
#   ops/deploy/test_promote_guard.sh      (exit 0 = pass)
#
# The scenarios are the ones that happened or could: a commit on work (allowed), a commit
# only in the production checkout (refused), the 2026-11-03 shape (a child of a work commit
# that was never pushed), an unreachable origin (refused, fail closed), and the explicit
# one-off override (allowed and announced).
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=ops/deploy/promote_guard.sh
source "$HERE/promote_guard.sh"

PASS=0; FAIL=0
ok() { printf '  ok    %s\n' "$1"; PASS=$((PASS+1)); }
no() { printf '  FAIL  %s\n          %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
g() { git -C "$T/prod" -c user.name=t -c user.email=t@t "$@"; }

git init -q --bare "$T/origin.git"
git init -q -b work "$T/prod"
g remote add origin "$T/origin.git"
echo one > "$T/prod/f"; g add f; g commit -qm one
ON_WORK=$(g rev-parse HEAD)
g push -q origin work
echo two > "$T/prod/f"; g commit -qam "two (never pushed)"
LOCAL_ONLY=$(g rev-parse HEAD)          # child of a work commit, like 3a65964 was
g checkout -q --detach "$ON_WORK"
echo three > "$T/prod/g"; g add g; g commit -qm "unrelated"
UNRELATED=$(g rev-parse HEAD)


if require_on_work "$T/prod" "$ON_WORK"; then ok "a commit on origin/work is allowed"; else no "on-work commit refused" "$GUARD_MESSAGE"; fi

if require_on_work "$T/prod" "$LOCAL_ONLY"; then no "local-only child of a work commit was allowed (the 3a65964 shape)"; else
  case $GUARD_MESSAGE in *"not on origin/work"*) ok "a commit that exists only in the production checkout is refused, with a reason";;
    *) no "refused without the expected message" "$GUARD_MESSAGE";; esac; fi

if require_on_work "$T/prod" "$UNRELATED"; then no "unrelated commit allowed"; else ok "an unrelated commit is refused"; fi

# Work moves on: a later commit pushed to work is allowed, and the older one stays allowed.
g checkout -q work; g push -q origin work   # pushes LOCAL_ONLY now
if require_on_work "$T/prod" "$LOCAL_ONLY"; then ok "once pushed to work, the same commit is allowed"; else no "pushed commit still refused" "$GUARD_MESSAGE"; fi

# Fail closed when origin cannot be reached.
g remote set-url origin "$T/missing.git"
if require_on_work "$T/prod" "$ON_WORK" 2>/dev/null; then no "unreachable origin was allowed"; else
  case $GUARD_MESSAGE in *"fail closed"*) ok "an unreachable origin refuses (fail closed)";; *) no "wrong message" "$GUARD_MESSAGE";; esac; fi
g remote set-url origin "$T/origin.git"

# The explicit override is accepted and announced.
out=$(KGKG_ALLOW_OFF_WORK=1 require_on_work "$T/prod" "$UNRELATED" 2>&1); rc=$?
if [[ $rc -eq 0 && $out == *"KGKG_ALLOW_OFF_WORK=1"* ]]; then ok "KGKG_ALLOW_OFF_WORK=1 allows one off-work promote and says so"; else no "override" "rc=$rc out=$out"; fi

# Only the exact value 1 counts.
if KGKG_ALLOW_OFF_WORK=yes require_on_work "$T/prod" "$UNRELATED" 2>/dev/null; then no "override accepted a value other than 1"; else ok "only KGKG_ALLOW_OFF_WORK=1 overrides"; fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[[ $FAIL -eq 0 ]]
