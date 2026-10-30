#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Is this commit still the tip of the branch CI is staging?
#
#   ci_is_tip.sh <sha> [branch]     exit 0 = yes, 1 = superseded, 2 = unknown
#   ci_is_tip.sh --selftest
#
# Why. `.github/workflows/ci.yml` sets `cancel-in-progress: true` at workflow
# level, which overrides the `stage` job's own `cancel-in-progress: false` —
# a second push cancels the whole run, `stage` included. But the gate launches
# staging under `systemd-run --wait`, deliberately, so that a dropped SSH
# connection cannot kill a deploy. The same property means a cancelled CI job
# *orphans* the staging run rather than stopping it: on 2026-10-30 a full gate
# (1170 tests, both images, every scanner) ran to completion for a commit CI
# had already given up on, on the single host that also serves production.
#
# Staging a commit that is no longer the branch tip is pointless, so the cheap
# fix is to not start. This check is CI-side on purpose: `deploy.sh --staging
# <older sha>` is legitimate for an operator investigating a specific commit,
# and the server must not refuse that.
#
# It narrows the window, it does not close it: a push that lands *during*
# staging still orphans that run. Closing that needs the gate to stop a
# superseded unit, which touches its locking, and is tracked separately.
#
# KG_TIP_CMD replaces the `git ls-remote` call (tests).
# ---------------------------------------------------------------------------
set -uo pipefail

BRANCH=${2:-work}

tip() {
  if [[ -n ${KG_TIP_CMD:-} ]]; then $KG_TIP_CMD "$BRANCH"; return; fi
  git ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | cut -f1
}

check() {
  local sha=${1:-}
  [[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo "not a 40-hex sha: ${sha:-<empty>}" >&2; return 2; }
  local t
  t=$(tip)
  if [[ ! $t =~ ^[0-9a-f]{40}$ ]]; then
    # Fail open: an unreachable remote must not stop a staging run that would
    # otherwise be correct. The caller decides; this only reports.
    echo "cannot read the tip of $BRANCH" >&2
    return 2
  fi
  if [[ $t == "$sha" ]]; then
    echo "$sha is the tip of $BRANCH"
    return 0
  fi
  echo "superseded: $BRANCH is at ${t:0:9}, this run is ${sha:0:9}"
  return 1
}

selftest() {
  local fails=0 A B T
  A=$(printf 'a%.0s' {1..40}); B=$(printf 'b%.0s' {1..40})
  T=$(mktemp -d); trap 'rm -rf "$T"' RETURN

  # KG_TIP_CMD is invoked as `$KG_TIP_CMD <branch>`; the stub ignores the
  # branch and prints whatever the case under test wants ls-remote to have
  # said, so one line and only one line.
  stub() { printf '#!/bin/sh\nprintf "%%s" "%s"\n' "$1" > "$T/tip"; chmod 755 "$T/tip"; }

  t() {  # name expected-rc remote-answer sha
    stub "$2"
    local out rc
    out=$(KG_TIP_CMD="$T/tip" bash "$0" "$3" 2>&1); rc=$?
    if (( rc == $4 )); then printf '  ok    %s\n' "$1"
    else printf '  FAIL  %s\n          want rc=%s got rc=%s (%s)\n' "$1" "$4" "$rc" "$out"; fails=$((fails+1)); fi
  }

  t "the tip itself is the tip"          "$A" "$A"      0
  t "a superseded commit is reported"    "$A" "$B"      1
  t "an unreadable remote is unknown"    ""   "$A"      2
  t "garbage from the remote is unknown" "nonsense" "$A" 2
  t "a short sha is refused"             "$A" "abc123"  2
  t "an empty sha is refused"            "$A" ""        2
  # An uppercase sha is not a sha git would print; refuse rather than guess.
  t "an uppercase sha is refused"        "$A" "$(printf 'A%.0s' {1..40})" 2

  if (( fails )); then echo "ci_is_tip selftest: $fails failure(s)" >&2; return 1; fi
  echo "ci_is_tip selftest: all checks passed"
}

case ${1:-} in
  --selftest) selftest ;;
  *)          check "$@" ;;
esac
