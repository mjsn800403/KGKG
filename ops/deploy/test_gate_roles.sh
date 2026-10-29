#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Access-control tests for ops/deploy/kg-deploy-gate.
#
# This file exists because the gate is where a mistake is a production
# incident: the whole claim that "CI cannot promote" rests on one case
# statement. The tests assert the full role x verb matrix in dry-run mode, so
# nothing is deployed and nothing is staged.
#
#   ops/deploy/test_gate_roles.sh      (exit 0 = pass)
# ---------------------------------------------------------------------------
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
GATE=$HERE/kg-deploy-gate
SHA=0123456789abcdef0123456789abcdef01234567
PASS=0
FAIL=0

run() {  # role, command-string -> sets RC and OUT
  OUT=$(KG_GATE_ROLE="$1" KG_GATE_DRYRUN=1 KG_GATE_LOG=/dev/null \
        SSH_ORIGINAL_COMMAND="$2" bash "$GATE" 2>&1)
  RC=$?
}

ok() { printf '  ok    %s\n' "$1"; PASS=$((PASS+1)); }
no() { printf '  FAIL  %s\n       -> rc=%s out=%s\n' "$1" "$RC" "$OUT"; FAIL=$((FAIL+1)); }

expect_allowed() {  # role, command, description
  run "$1" "$2"
  if (( RC == 0 )) && [[ $OUT == *"would run"* ]]; then ok "$3"; else no "$3"; fi
}

expect_denied() {   # role, command, description
  run "$1" "$2"
  if (( RC != 0 )) && [[ $OUT == denied:* || $OUT == *denied* ]]; then ok "$3"; else no "$3"; fi
}

echo "role x verb matrix:"
expect_allowed ci       "stage $SHA"   "ci may stage"
expect_allowed ci       "status"       "ci may read status"
expect_denied  ci       "deploy $SHA"  "ci may NOT deploy"
expect_allowed operator "deploy $SHA"  "operator may deploy"
expect_allowed operator "stage $SHA"   "operator may stage"
expect_allowed operator "status"       "operator may read status"

echo "argument validation:"
expect_denied ci       "stage"                       "stage without a sha is refused"
expect_denied ci       "stage not-a-sha"             "stage with a non-sha is refused"
expect_denied ci       "stage ${SHA:0:39}"           "stage with a short sha is refused"
expect_denied ci       "stage $SHA extra"            "stage with extra arguments is refused"
expect_denied ci       "stage $SHA; rm -rf /"        "shell metacharacters are refused"
expect_denied ci       "status please"               "status with arguments is refused"
expect_denied ci       ""                            "an empty command is refused"
expect_denied ci       "shell"                       "an unknown verb is refused"
expect_denied ci       "STAGE $SHA"                  "verbs are case-sensitive"
expect_denied nonsense "status"                      "an unknown role is refused"

echo "status names the key's role (CI's preflight checks it):"
run ci "status";       if [[ $OUT == *"key role: ci"* ]];       then ok "ci key reports role ci";             else no "ci key reports role ci"; fi
run operator "status"; if [[ $OUT == *"key role: operator"* ]]; then ok "operator key reports role operator"; else no "operator key reports role operator"; fi

echo "injection attempts cannot smuggle a verb:"
expect_denied ci "stage $SHA deploy $SHA"            "a second verb is refused"
expect_denied ci "deploy $SHA stage $SHA"            "deploy is still refused for ci"

echo
echo "passed $PASS, failed $FAIL"
(( FAIL == 0 )) || exit 1
echo "GATE ROLE TESTS PASSED"
