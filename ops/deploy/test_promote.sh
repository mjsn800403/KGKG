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

now() { date -u -d "${1:-now}" +%Y-%m-%dT%H:%M:%SZ; }

reset() {  # fresh evidence: live=LIVE, SHA staged+smoked now, E2E full pass now
  rm -rf "$REL"; mkdir -p "$REL/e2e"
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

echo
echo "passed $PASS, failed $FAIL"
(( FAIL == 0 )) || exit 1
echo "PROMOTE TESTS PASSED"
