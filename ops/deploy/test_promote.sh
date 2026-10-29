#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Tests for ops/deploy/kgkg-promote: which evidence lets the normal "promote"
# through, and that everything else needs the longer phrase and is logged.
#
# Runs the real script against a throwaway git repository (with its own
# origin/work), throwaway staging/E2E records and a stub in place of
# deploy.sh, so nothing is built, staged or deployed.
#
#   ops/deploy/test_promote.sh      (exit 0 = pass)
# ---------------------------------------------------------------------------
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROMOTE=$HERE/kgkg-promote
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
PASS=0
FAIL=0

# --- a repository with two commits on origin/work; the first one is "live" --
git init -q --bare "$T/origin.git"
git init -q -b work "$T/prod"
g() { git -C "$T/prod" -c user.name=t -c user.email=t@t "$@"; }
echo one > "$T/prod/f"; g add f; g commit -qm one
LIVE=$(g rev-parse HEAD)
echo two > "$T/prod/f"; g commit -qam two
SHA=$(g rev-parse HEAD)
SHORT=${SHA:0:9}
g remote add origin "$T/origin.git"; g push -q origin work 2>/dev/null

REL=$T/rel
mkdir -p "$REL/e2e"
cat > "$T/deploy.sh" <<'EOF'
#!/usr/bin/env bash
echo "STUB DEPLOY $1"
EOF

# Stands in for ops/deploy/ci_evidence.sh: prints whatever $T/ci-verdict says,
# so each case can set GitHub's answer without a network call. ci_evidence.sh
# has its own tests for turning real check-run JSON into these verdicts.
cat > "$T/ci_evidence.sh" <<'EOF'
#!/usr/bin/env bash
cat "$(dirname "$0")/ci-verdict"
EOF
ci() { printf '%s\n' "$1" > "$T/ci-verdict"; }

now() { date -u -d "${1:-now}" +%Y-%m-%dT%H:%M:%SZ; }

reset() {  # fresh evidence: CI green, live=LIVE, SHA staged+smoked now, E2E full pass now
  rm -rf "$REL"; mkdir -p "$REL/e2e"
  ci pass
  printf 'CURRENT=%s\nPREVIOUS=\n' "$LIVE" > "$REL/state.env"
  printf 'STAGED_SHA=%s\nSTAGED_AT=%s\nSMOKE=pass\nGATE=pass\n' "$SHA" "$(now)" > "$REL/staging.env"
  e2e "$SHA" full pass "$(now)"
}

e2e() {  # sha scope result at
  printf 'E2E_SHA=%s\nE2E_AT=%s\nE2E_SCOPE=%s\nE2E_RESULT=%s\nE2E_PASSED=42\nE2E_FAILED=%s\n' \
    "$1" "$4" "$2" "$3" "$([[ $3 == pass ]] && echo 0 || echo 1)" > "$REL/e2e/$SHA.env"
}

run() {  # reply -> RC, OUT
  OUT=$(printf '%s\n' "$1" | KG_PROD_DIR="$T/prod" KG_REL_DIR="$REL" KG_DEPLOY_SH="$T/deploy.sh" \
        KG_CI_EVIDENCE_SH="$T/ci_evidence.sh" \
        bash "$PROMOTE" "$SHA" 2>&1)
  RC=$?
}

ok() { printf '  ok    %s\n' "$1"; PASS=$((PASS+1)); }
no() { printf '  FAIL  %s\n       -> rc=%s\n%s\n' "$1" "$RC" "$(sed 's/^/          /' <<<"$OUT" | tail -15)"; FAIL=$((FAIL+1)); }

deployed()     { [[ $OUT == *"STUB DEPLOY $SHA"* ]]; }
expect_deploy() { run "$1"; if (( RC == 0 )) && deployed; then ok "$2"; else no "$2"; fi; }
expect_refuse() { run "$1"; if (( RC != 0 )) && ! deployed; then ok "$2"; else no "$2"; fi; }
logged() { [[ -f $REL/promote-overrides.log ]] && grep -q "$SHA without $1" "$REL/promote-overrides.log"; }

echo "full evidence:"
reset; expect_deploy "promote" "staged + full E2E pass: plain 'promote' deploys"
[[ ! -f $REL/promote-overrides.log ]] && ok "no override is logged" || { RC=-; OUT=$(cat "$REL/promote-overrides.log"); no "no override is logged"; }
reset; expect_refuse "yes" "anything but the exact word is refused"

echo "missing or bad E2E evidence:"
for case in missing fail partial othersha stale; do
  reset
  case $case in
    missing)  rm -f "$REL/e2e/$SHA.env" ;;
    fail)     e2e "$SHA" full fail "$(now)" ;;
    partial)  e2e "$SHA" partial pass "$(now)" ;;
    othersha) e2e "$LIVE" full pass "$(now)" ;;
    stale)    e2e "$SHA" full pass "$(now '-80 hours')" ;;
  esac
  expect_refuse "promote" "E2E $case: plain 'promote' is refused"
  [[ $OUT == *"promote $SHORT without e2e"* ]] && ok "E2E $case: the prompt names the phrase" || no "E2E $case: the prompt names the phrase"
done
reset; rm -f "$REL/e2e/$SHA.env"
expect_refuse "promote $SHORT without staging" "the staging phrase does not cover missing E2E"
expect_deploy "promote $SHORT without e2e" "the e2e phrase deploys"
logged e2e && ok "the e2e override is logged" || no "the e2e override is logged"

echo "missing staging, and both missing:"
reset; printf 'STAGED_SHA=%s\nSTAGED_AT=%s\nSMOKE=pass\n' "$LIVE" "$(now)" > "$REL/staging.env"
expect_refuse "promote" "unstaged: plain 'promote' is refused"
expect_deploy "promote $SHORT without staging" "the staging phrase deploys when E2E is fine"
logged staging && ok "the staging override is logged" || no "the staging override is logged"
reset; rm -f "$REL/staging.env" "$REL/e2e/$SHA.env"
expect_refuse "promote $SHORT without e2e" "with both missing, one phrase is not enough"
expect_deploy "promote $SHORT without staging and e2e" "the combined phrase deploys"
logged "staging and e2e" && ok "the combined override is logged" || no "the combined override is logged"

echo "CI evidence (the gap that put a red commit in production):"
reset; ci 'fail backend=failure'
expect_refuse "promote" "CI red: plain 'promote' is refused"
[[ $OUT == *"GitHub CI did not pass"* && $OUT == *"backend=failure"* ]] \
  && ok "CI red: the refusal names the job that failed" || no "CI red: the refusal names the job that failed"
[[ $OUT == *"promote $SHORT without ci"* ]] && ok "CI red: the prompt names the phrase" || no "CI red: the prompt names the phrase"
expect_refuse "promote" "CI red: a second plain 'promote' is still refused"
reset; ci 'fail backend=failure'
expect_deploy "promote $SHORT without ci" "the ci phrase deploys"
logged ci && ok "the ci override is logged" || no "the ci override is logged"
grep -q 'backend=failure' "$REL/promote-overrides.log" \
  && ok "the log records why CI was red" || { RC=-; OUT=$(cat "$REL/promote-overrides.log"); no "the log records why CI was red"; }

for v in 'unknown GitHub is unreachable (curl exit 7)' 'unknown still running: backend' 'unknown no check run named images' 'nonsense'; do
  reset; ci "$v"
  expect_refuse "promote" "CI '${v:0:28}': plain 'promote' is refused"
done
reset; ci 'unknown GitHub is unreachable (curl exit 7)'
expect_deploy "promote $SHORT without ci" "an unreachable GitHub can still be overridden"

echo "CI evidence does not shadow the other gates:"
reset; ci 'fail backend=failure'; rm -f "$REL/e2e/$SHA.env"
expect_refuse "promote $SHORT without ci" "the ci phrase alone does not cover missing E2E"
expect_deploy "promote $SHORT without ci and e2e" "the combined ci+e2e phrase deploys"
logged "ci and e2e" && ok "the ci+e2e override is logged" || no "the ci+e2e override is logged"
reset; ci 'fail backend=failure'; rm -f "$REL/staging.env" "$REL/e2e/$SHA.env"
expect_deploy "promote $SHORT without ci and staging and e2e" "all three missing: the full phrase deploys"
logged "ci and staging and e2e" && ok "the three-way override is logged" || no "the three-way override is logged"
reset; run "promote"
[[ $OUT == *"CI evidence     : $SHORT passed"* ]] \
  && ok "a green CI is stated in the normal path" || no "a green CI is stated in the normal path"

echo
echo "passed $PASS, failed $FAIL"
(( FAIL == 0 )) || exit 1
echo "PROMOTE TESTS PASSED"
