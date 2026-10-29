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

echo "the transient unit does not outlive its run:"
# The gate launches each staging/deploy under a uniquely named transient unit.
# A non-zero exit used to leave that unit in `failed` for ever, and once the
# watchdog began paging for failed units (2026-10-29) one red staging became an
# SMS every 12 hours about a run that had already been reported red to CI. The
# launch path is exercised here with stubs for the three systemd commands.
TD=$(mktemp -d); trap 'rm -rf "$TD"' EXIT
# The launch path only runs for a sha that is already on origin/work, so give
# the gate a throwaway repository with one, the way test_promote.sh does.
git init -q --bare "$TD/origin.git"
git init -q -b work "$TD/prod"
gg() { git -C "$TD/prod" -c user.name=t -c user.email=t@t "$@"; }
echo one > "$TD/prod/f"; gg add f; gg commit -qm one
gg remote add origin "$TD/origin.git"; gg push -q origin work 2>/dev/null
REAL_SHA=$(gg rev-parse HEAD)
cat > "$TD/journalctl" <<'EOF'
#!/bin/sh
exit 0
EOF
cat > "$TD/systemctl" <<'EOF'
#!/bin/sh
echo "$@" >> "$TD_CALLS/systemctl"
EOF
mkstub() {  # exit-code -> a systemd-run stub whose run exits with it
  cat > "$TD/systemd-run" <<EOF
#!/bin/sh
echo "\$@" >> "\$TD_CALLS/systemd-run"
exit $1
EOF
  chmod 755 "$TD/systemd-run"
}
chmod 755 "$TD/journalctl" "$TD/systemctl"

launch() {  # exit-code -> RC, and $TD/calls/* hold what was invoked
  rm -rf "$TD/calls"; mkdir -p "$TD/calls"
  mkstub "$1"
  OUT=$(KG_GATE_ROLE=operator KG_GATE_LOG=/dev/null \
        KG_GATE_LOCK="$TD/lock" \
        KG_DEPLOY_SH=/bin/true \
        TD_CALLS="$TD/calls" \
        KG_GATE_SYSTEMD_RUN="$TD/systemd-run" \
        KG_GATE_SYSTEMCTL="$TD/systemctl" \
        KG_GATE_JOURNALCTL="$TD/journalctl" \
        KG_PROD_DIR="$TD/prod" \
        SSH_ORIGINAL_COMMAND="stage $REAL_SHA" bash "$GATE" 2>&1)
  RC=$?
}

launch 1
if (( RC == 1 )); then ok "a failed run is reported with its own exit status"; else no "a failed run is reported with its own exit status"; fi
if grep -q 'reset-failed kgkg-stage-' "$TD/calls/systemctl" 2>/dev/null; then
  ok "a failed run clears its transient unit"
else
  RC=$RC; OUT="systemctl calls: $(cat "$TD/calls/systemctl" 2>/dev/null)"; no "a failed run clears its transient unit"
fi

launch 0
if (( RC == 0 )); then ok "a clean run still exits 0"; else no "a clean run still exits 0"; fi
if [[ ! -s $TD/calls/systemctl ]]; then
  ok "a clean run resets nothing"
else
  OUT="systemctl calls: $(cat "$TD/calls/systemctl")"; no "a clean run resets nothing"
fi

echo
echo "passed $PASS, failed $FAIL"
(( FAIL == 0 )) || exit 1
echo "GATE ROLE TESTS PASSED"
