#!/usr/bin/env bash
# Refuse to promote a commit that is not on origin/work.
#
# NOT YET WIRED INTO deploy.sh. It is a function library with a test
# (ops/deploy/test_promote_guard.sh) so the rule can be reviewed and approved on its
# own; see docs/superpowers/specs/2026-11-03-promote-drift-prevention.md for the gap it
# closes and the two-line change that would enable it.
#
#   source ops/deploy/promote_guard.sh
#   require_on_work "$PROD" "$SHA" || die "$GUARD_MESSAGE"
#
# Rule: a full deploy (the path that fast-forwards the live tree) may only ship a commit
# that is an ancestor of origin/work. kgkg-promote already enforces this; deploy.sh run
# directly did not, which is how production came to run commits no branch contained
# (#50, and 3a65964 on 2026-11-03).
#
# Fails closed: if origin/work cannot be fetched the commit cannot be verified, so it is
# refused. The single escape hatch is KGKG_ALLOW_OFF_WORK=1 in the environment of that one
# command; it is accepted but announced, so the log shows it was a decision, not an accident.
# Staging (--staging) must not use this: CI stages only what is already on work.

GUARD_MESSAGE=

# GUARD_MESSAGE is read by the sourcing script (die "$GUARD_MESSAGE"), not here.
# shellcheck disable=SC2034
require_on_work() {
  local prod=$1 sha=$2
  GUARD_MESSAGE=
  if ! git -C "$prod" fetch -q origin work 2>/dev/null; then
    if [[ ${KGKG_ALLOW_OFF_WORK:-} == 1 ]]; then
      echo "WARNING: could not fetch origin/work; continuing only because KGKG_ALLOW_OFF_WORK=1" >&2
      return 0
    fi
    GUARD_MESSAGE="could not fetch origin/work, so ${sha:0:9} cannot be verified; refusing (fail closed)"
    return 1
  fi
  if git -C "$prod" merge-base --is-ancestor "$sha" origin/work 2>/dev/null; then
    return 0
  fi
  if [[ ${KGKG_ALLOW_OFF_WORK:-} == 1 ]]; then
    echo "WARNING: ${sha:0:9} is NOT on origin/work; continuing only because KGKG_ALLOW_OFF_WORK=1" >&2
    echo "         push it to a branch, review it and merge it to work afterwards, or production will drift" >&2
    return 0
  fi
  GUARD_MESSAGE="${sha:0:9} is not on origin/work. Merge it to work first (a PR), then promote; production must only run commits the repository contains. To override once, knowingly: KGKG_ALLOW_OFF_WORK=1"
  return 1
}
