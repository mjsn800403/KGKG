#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# The production checkout is detached. These are the git operations deploy.sh
# performs on it, proved against a throwaway repository with a detached HEAD.
#
#   ops/deploy/test_detached_prod.sh      (exit 0 = pass)
#
# Why this file exists. /opt/KGKG was checked out on a branch —
# `rag-db-improvements` — and deploy.sh ended every promote with
#
#     git push origin "HEAD:$(git rev-parse --abbrev-ref HEAD)" "$TAG"
#
# so the production checkout's branch was defined by whatever production
# happened to be running. That is how the live commit 536ac91 came to sit on
# `rag-db-improvements` while `work` and `main` had never seen it, with its CI
# red (#15), and it started a second CI run on the already-promoted sha every
# time (#33). The live tree is an artefact of a release, not a place to
# develop, so it is detached and only the tag is pushed.
#
# Detaching is safe only if everything deploy.sh does still works without a
# current branch. `git merge --ff-only` is the one that would be easy to get
# wrong: on a detached HEAD it moves HEAD rather than a branch ref, which is
# exactly what is wanted here — but "exactly what is wanted" is a claim, and
# this file is the evidence.
# ---------------------------------------------------------------------------
set -uo pipefail

PASS=0; FAIL=0
ok() { printf '  ok    %s\n' "$1"; PASS=$((PASS+1)); }
no() { printf '  FAIL  %s\n          %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
g() { git -C "$T/prod" -c user.name=t -c user.email=t@t "$@"; }

git init -q --bare "$T/origin.git"
git init -q -b work "$T/prod"
echo one > "$T/prod/f"; g add f; g commit -qm one
A=$(g rev-parse HEAD)
# A middle commit, so A..C is a real line rather than a single step; its sha
# is not needed, since the refusal case uses the divergent $D below.
echo two > "$T/prod/f"; g commit -qam two
echo three > "$T/prod/f"; g commit -qam three
C=$(g rev-parse HEAD)
g remote add origin "$T/origin.git"; g push -q origin work
# A commit that is NOT on the line A..C, for the refusal case. An *ancestor*
# would not test anything: `merge --ff-only <ancestor>` is a legitimate
# already-up-to-date no-op, which cost me one wrong assertion writing this.
g checkout -q -b side "$A"; echo side > "$T/prod/f"; g commit -qam side
D=$(g rev-parse HEAD); g checkout -q work

# Detach at A, the way the production checkout now sits.
g checkout -q --detach "$A"

[[ $(g rev-parse --abbrev-ref HEAD) == HEAD ]] \
  && ok "the checkout is detached (abbrev-ref says HEAD)" \
  || no "the checkout is detached" "$(g rev-parse --abbrev-ref HEAD)"

# --- the operations deploy.sh performs, in the order it performs them ------

g fetch -q origin work && ok "fetch origin work" || no "fetch origin work"

[[ $(g rev-parse HEAD) == "$A" ]] && ok "rev-parse HEAD names the live commit" || no "rev-parse HEAD"

[[ -z $(g status --porcelain) ]] && ok "status --porcelain is empty (prod_clean)" || no "prod_clean"

g merge-base --is-ancestor "$A" "$C" \
  && ok "merge-base --is-ancestor: the target contains the live commit" \
  || no "merge-base --is-ancestor"

g worktree add -q --detach "$T/w" "$C" && ok "worktree add --detach (the gate's clean tree)" || no "worktree add --detach"

# The one that matters: on a detached HEAD this must move HEAD to the target.
if g merge -q --ff-only "$C" 2>"$T/err"; then
  if [[ $(g rev-parse HEAD) == "$C" ]] && [[ $(g rev-parse --abbrev-ref HEAD) == HEAD ]]; then
    ok "merge --ff-only moves a detached HEAD to the target"
  else
    no "merge --ff-only left HEAD wrong" "$(g rev-parse HEAD) / $(g rev-parse --abbrev-ref HEAD)"
  fi
else
  no "merge --ff-only failed on a detached HEAD" "$(cat "$T/err")"
fi

# ... and must still refuse a commit that is not a descendant. `$D` diverges
# from A; `$B` would not do, being an ancestor of C and so a valid no-op.
if g merge -q --ff-only "$D" 2>/dev/null; then
  no "merge --ff-only accepted a divergent commit" "moved to $(g rev-parse HEAD)"
else
  [[ $(g rev-parse HEAD) == "$C" ]] \
    && ok "merge --ff-only refuses a divergent commit and leaves HEAD put" \
    || no "HEAD moved despite the refusal" "$(g rev-parse HEAD)"
fi

g reset -q --hard "$A" && [[ $(g rev-parse HEAD) == "$A" ]] \
  && ok "reset --hard (undo_code / rollback) works detached" || no "reset --hard"

g merge -q --ff-only "$C" >/dev/null 2>&1
TAG=deploy-test-$$
g tag -a "$TAG" -m "deployed ${C:0:9} version 9.9.9" "$C" && ok "annotated deploy tag" || no "annotated deploy tag"

[[ $(g show "$C:f") == three ]] && ok "show <sha>:VERSION-style read" || no "show <sha>:path"

# The push deploy.sh now performs: the tag, and nothing else.
if g push -q origin "$TAG"; then
  ok "pushing the tag alone succeeds"
else
  no "pushing the tag alone"
fi
[[ -z $(git -C "$T/origin.git" rev-parse --verify --quiet refs/heads/HEAD 2>/dev/null) ]] \
  && ok "no refs/heads/HEAD was created on the remote" || no "a refs/heads/HEAD appeared on the remote"
[[ $(git -C "$T/origin.git" rev-parse refs/heads/work) == "$C" ]] \
  && ok "the remote branch was left where it was (the tag push touched no branch)" \
  || no "the remote branch moved" "$(git -C "$T/origin.git" rev-parse refs/heads/work)"

# The old behaviour, for contrast: this is what used to run, and on a detached
# HEAD it would try to push a ref literally named HEAD.
g push -q origin "HEAD:$(g rev-parse --abbrev-ref HEAD)" 2>"$T/err2" \
  && no "the old push form silently created a branch" "$(git -C "$T/origin.git" for-each-ref --format='%(refname)' | tr '\n' ' ')" \
  || ok "the old push form fails on a detached HEAD (why it had to go)"

g worktree remove --force "$T/w" 2>/dev/null; g worktree prune
ok "worktree remove / prune"

echo
echo "passed $PASS, failed $FAIL"
(( FAIL == 0 )) || exit 1
echo "DETACHED PROD TESTS PASSED"
