# Release record — v<MAJOR.MINOR.PATCH>

| Field | Value |
|---|---|
| Version | |
| Commit (full sha) | |
| Previous production commit | |
| Classification | major / minor / patch / security patch |
| Date promoted (UTC) | |
| Deploy tag | `deploy-…` |
| Approved and promoted by | (name — the person who typed `promote`) |

## Verification

| Check | Result | Evidence (link or path) |
|---|---|---|
| CI run (tests, coverage %, security gates) | | |
| Staging smoke | | `/opt/KGKG_release/staging.env` |
| E2E suite (`qa/run_e2e.sh`) passed / total | | `qa/e2e/results/junit.xml` |
| Load profile within criteria (minor/major) | | `qa/perf/results/k6-load.txt` |
| DAST full scan reviewed (minor/major) | | `qa/dast/results/zap-full.html` |
| Open High/Critical defects | must be none | |

## Changes

(Summary from `docs/CHANGELOG.md`.)

## Rollback plan

`ops/deploy/deploy.sh --rollback` returns to the previous commit's images.
Migrations in this release: none / additive only (checked by the gate).
