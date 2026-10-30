# Release record — v1.1.0 (open)

Opened 2026-10-30, at the moment `VERSION` was bumped, which is the point the
policy actually asks for. Rows are filled as the evidence arrives; a row that
is empty is empty on purpose and says what is still owed.

| Field | Value |
|---|---|
| Version | **1.1.0** |
| Commit (full sha) | *(the commit promoted; filled at promotion)* |
| Previous production commit | `5e4543a3db2b519c54f1538e34beaa2bec4b7138` |
| Classification | **minor** — new capability since 1.0.0 was tagged, plus the infrastructure work below |
| Date promoted (UTC) | *(filled at promotion)* |
| Deploy tag | *(`deploy-…`, written by `deploy.sh`; it will state version 1.1.0)* |
| Approved and promoted by | *(the person who types `promote`)* |

## Verification

| Check | Result | Evidence |
|---|---|---|
| CI run (tests, coverage %, security gates) | *(pending)* | — |
| Staging smoke | *(pending)* | `/opt/KGKG_release/staging.env` |
| E2E suite passed / total | *(pending)* | `/opt/KGKG_release/e2e/<sha>.env` |
| Load profile within criteria | **required for a MINOR** — owed, and not run on either 1.0.0 commit | `qa/perf/run_perf.sh load` → `audit-evidence/06-performance-and-load/` |
| DAST full scan reviewed | **required for a MINOR** — owed, and not run on either 1.0.0 commit | `qa/dast/run_zap.sh full` → `audit-evidence/07-security/dast-final/` |
| Open High/Critical defects | must be none | `../14-risk-and-corrective-actions/CORRECTIVE_ACTIONS.md` |

The two "owed" rows are the honest difference between this record and the last
one. The policy has required load and DAST for a MINOR release since
2026-10-27 and neither has been run on a commit that was actually promoted.
**This release is not to be promoted until both rows are filled** — which is
the whole point of opening the record before the promote rather than after it.

A new gate also applies to this release and did not exist for 1.0.0:
`kgkg-promote` now reads GitHub's verdict on the exact commit through
`ops/deploy/ci_evidence.sh` and refuses anything that is not four green
required jobs, counting an unreachable GitHub as a refusal. Note that the
installed `/usr/local/bin/kgkg-promote` is refreshed from the tree *after* a
promote, so this release is the first that the CI gate will actually judge.

## Changes

`docs/CHANGELOG.md`, `## 1.1.0`. Infrastructure and governance throughout:
the CI gate on promotion, alert rules that cannot starve silently, failed-unit
paging that survives a deploy, a transient unit that no longer outlives its
run, branch protection on `main`, the governance files, `.mailmap`, the
markdown ignore fix, and three documents corrected against the host.

No customer-visible behaviour changes in this release. That is worth stating
because it bears on the load and DAST rows: there is no new request path to
profile, which is a reason to expect the runs to be clean, not a reason to
skip them.

## Rollback plan

`ops/deploy/deploy.sh --rollback` returns to `5e4543a`'s images. Migrations in
this release: none — to be re-confirmed by the gate's "migrations are
rollback-safe" step, which refuses a migration that would break the previous
release.

One rollback consequence specific to this release: reverting the code also
reverts `/usr/local/lib/kgkg/watchdog.py` and `/usr/local/bin/kg-deploy-gate`,
because `deploy.sh` refreshes both from the deployed tree. A rollback would
therefore restore the failed-unit blindness and the transient-unit residue.
That is acceptable for a short rollback and is not acceptable as a resting
state; if 1.1.0 is rolled back, re-apply those two files by hand and say so
here.
