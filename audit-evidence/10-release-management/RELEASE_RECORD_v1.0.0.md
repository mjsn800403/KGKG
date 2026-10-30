# Release record — v1.0.0

The first release under the semantic-versioning policy introduced 2026-10-27
(`RELEASE_POLICY.md`). Written retrospectively on 2026-10-30, which is itself a
finding: the policy called for a record at promotion time and none was filled,
so this one is reconstructed from machine evidence that was captured at the
time — CI runs, `/opt/KGKG_release/` state files, deploy tags and deploy logs.
Nothing here is reconstructed from memory.

| Field | Value |
|---|---|
| Version | **1.0.0** |
| Commit (full sha) | `8fa94dd4d93f03ec53b33f280cf353c756e9ae19` |
| Previous production commit | `c3b796869` (pre-SemVer; no version number is claimed for it) |
| Classification | major — first versioned release of a service already in production since 2026-06 |
| Date promoted (UTC) | 2026-10-29 08:46 |
| Deploy tag | `deploy-20261029-084649` — annotated `deployed 8fa94dd4d version 1.0.0` |
| Approved and promoted by | the person at the host who typed `promote`; `kgkg-promote` admits no other path |

## A second deploy shipped under the same number

`VERSION` was not bumped after this release, so `5e4543a3db2b519c54f1538e34beaa2bec4b7138`
was promoted on 2026-10-29 at 19:18 (`deploy-20261029-191834`, annotated
`deployed 5e4543a3d version 1.0.0`) carrying new capability — pgvector dense
KNN retrieval, the KG query adapter and reranker tooling. Under this project's
own rules that is a MINOR and should have been 1.1.0.

It is recorded here under the number it actually shipped as rather than
corrected in hindsight, because the deploy tag on the server says 1.0.0 and a
record that disagreed with the artefact would be worse than the lapse. The
corrective action is in effect: `VERSION` is now 1.1.0 and
`RELEASE_RECORD_v1.1.0.md` is open and being filled as the evidence arrives.

That second deploy is the better-evidenced of the two, and its verification is
tabulated below alongside this one.

## Verification

| Check | v1.0.0 at `8fa94dd` | Second deploy at `5e4543a` | Evidence |
|---|---|---|---|
| CI run | **Red on bandit.** It passed the server gate and was promoted anyway, because the gate did not then run the security scanners | **Green**, all five jobs including `stage` | run 40934280389; `docs/CHANGELOG.md` entry "The server gate runs the security scans" |
| Backend tests | 930 (per the CHANGELOG entry for this release) | **1170** on PostgreSQL, randomised order | server gate log `deploy-20261029-185331.log` |
| Frontend unit tests | — not separately recorded | **178**, 0 failed | same log |
| Coverage | 56 %, CI floor 55 | **58 %**, floor raised 56 → 57 | run 40934280389; `ops/deploy/coverage_min` |
| Security gates (bandit, pip-audit, npm audit) | red in CI; **not run by the server gate at the time** | **all PASS**, in CI *and* in the server gate | `ops/security/scan.sh`; gate log |
| Image scan (Trivy, HIGH/CRITICAL fixable) | 0 / 0 | 0 / 0 | CI `images` job |
| Staging smoke | pass | **pass** — `STAGED_SHA=5e4543a…`, `GATE=pass`, `SMOKE=pass` | `/opt/KGKG_release/staging.env` |
| E2E suite | **not run for this commit.** The E2E gate in `kgkg-promote` was added later the same day | **42 passed / 42, 0 flaky, scope=full** | `/opt/KGKG_release/e2e/5e4543a….env`; `qa/e2e/results/junit.xml` |
| Load profile within criteria | last run 2026-10-27 on an earlier commit, not on this one | not re-run on this commit | `audit-evidence/06-performance-and-load/` |
| DAST full scan reviewed | last run 2026-10-27 on an earlier commit, not on this one | not re-run on this commit | `audit-evidence/07-security/dast-final/` |
| Production smoke after promote | pass | **22 checks, all pass**, incl. metrics refused publicly (403) and `sites-enabled` clean | deploy log `deploy-20261029-191834.log` |
| Open High/Critical defects | none open at promotion (D-06, D-17, D-30 were fixed in this release and ceased to be production exposures on promoting it) | none | `../14-risk-and-corrective-actions/CORRECTIVE_ACTIONS.md` |

Two rows of the policy's step 3 — load and DAST on the exact commit — are
honestly "not run on this commit" for both deploys. The policy requires them
for a MINOR or MAJOR release; this is the gap that
`RELEASE_RECORD_v1.1.0.md` has to close, not paper over.

## Changes

`docs/CHANGELOG.md`, under `## 2026-10-28 — v1.0.0` for this commit and
`## 1.0.0, second deploy — 2026-10-29` for the second. In summary: the test
architecture (unit, integration, E2E, load, DAST, mutation), the security
fixes found by it — including the cross-company paid-media bypass (D-06), the
entitlement leak (D-03) and the unauthenticated eval report (D-17) — the
PostgreSQL cutover, and the audit-evidence package itself.

## Rollback plan

`ops/deploy/deploy.sh --rollback` returns to the previous commit's images; the
images for the previous release are retained, and a pre-deploy database backup
is written to `/opt/KGKG_release/db-backups/`. Migrations in this release:
the PostgreSQL cutover was a data migration verified row-for-row after the
event, so the SQLite file — frozen, not deleted — is the way back for the data,
while `--rollback` is the way back for the code. The two are separate, and that
asymmetry is the single riskiest thing about this release.

## What this record is evidence of, and what it is not

It shows that every deployment is identified, reproducible from machine state,
and tied to a commit, a tag and a set of test results. It also shows, without
dressing it up, that v1.0.0 was promoted with CI red, that no record was filled
at the time, that the version number then failed to move for a release that
should have moved it, and that load and DAST were not run on either commit. All
four are now either fixed in tooling or carried as open actions.
