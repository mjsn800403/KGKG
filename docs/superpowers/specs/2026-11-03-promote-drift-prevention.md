# Preventing production drift: how `deploy.sh` bypasses the `work` check

Date: 2026-11-03. Status: **recommendation, not enabled.** Nothing in `deploy.sh`, `kgkg-promote`, the
gate or the server was changed. The guard exists as an unwired, tested function
(`ops/deploy/promote_guard.sh`, tests in `ops/deploy/test_promote_guard.sh`).

## What happened (confirmed)

* Production ran `3a65964` on 2026-11-03 (deploy tag `deploy-20261103-123544`, tagged by `deploy.sh`).
  The commit was on no branch, so `work` did not contain the live commit and the server's staging step
  aborted every run ("does not contain the live commit; prod only fast-forwards"). Resolved by merging it
  into `work` (#72). Earlier occurrence: five unpushed commits (#50, rescued in #51).

## Why the check was bypassed (confirmed in code; how it was invoked is unverified)

| Control | `kgkg-promote <sha>` | `deploy.sh <ref>` (full mode, run directly) |
|---|---|---|
| New commit must be an ancestor of `origin/work` | **yes** (`kgkg-promote:99`) | **no** |
| Needs a passing staging record for that sha | **yes** | no (it stages itself, then promotes) |
| New commit must contain the live commit (fast-forward) | via deploy.sh | yes (`deploy.sh:350`) |
| Ref can be any object in the production checkout | no (must be on `work`) | **yes** (`git rev-parse "$REF^{commit}"`) |

`deploy.sh` is documented as the engine behind `kgkg-promote`, but it is also directly runnable by
anyone with a root shell. Its only ancestry rule protects the live tree from going backwards; it does not
protect the repository from the live tree containing something the repository does not. Any commit that is
a child of the live commit passes, wherever it came from, including one built on a developer's unpushed
branch and fetched into `/opt/KGKG`. Which command Ali actually ran is not recorded in what I can read;
the tag message format matches `deploy.sh` (`deploy.sh:562`), which is consistent with a direct run but does
not prove it.

## Recommendation (minimal, developer-friendly)

Make `deploy.sh` enforce the same rule as `kgkg-promote`, in its **full (promote) mode only**, after the
fast-forward check:

```bash
source "$(dirname "$0")/promote_guard.sh"
[[ $MODE == full ]] && { require_on_work "$PROD" "$SHA" || die "$GUARD_MESSAGE"; }
```

Properties, all covered by `test_promote_guard.sh` (7 cases):

* a commit on `origin/work` passes, so the normal path (PR, merge, `kgkg-promote`) is unchanged;
* a commit that exists only in the production checkout is refused with a message that says what to do
  (merge it to `work` first); this is the exact `3a65964` shape;
* an unreachable `origin` refuses (fail closed): an unverifiable commit is not promoted;
* one deliberate escape hatch, `KGKG_ALLOW_OFF_WORK=1` on that single command: accepted, printed in the
  log with the reason it is risky, and only the exact value `1` counts, so an emergency hotfix is possible
  but never silent;
* staging (`--staging`, used by CI) and rollback/reload are untouched.

Developer impact: none on the supported path. Someone who runs `deploy.sh` directly with an unmerged
commit now gets a clear refusal and the one-line fix instead of a silent drift. Cost: one `git fetch`.

## Optional second layer (separate approval)

A daily read-only check (`git merge-base --is-ancestor <live> origin/work`, exit 1 and a message if not),
run from the existing watchdog timer, so drift that does happen is noticed within a day rather than when
staging fails. Not built here.

## To enable

Approve the two lines above in `deploy.sh`; they ship through the normal PR (CI runs the guard test);
promotion of that change stays a person's `kgkg-promote`. Until then the guard is inert.
