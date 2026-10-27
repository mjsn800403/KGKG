# Versioning and release management

## What exists and is enforced by tooling

| Control | Mechanism | Evidence |
|---|---|---|
| Every production deployment is identified | `deploy.sh` creates an annotated tag `deploy-<UTC timestamp>` on the deployed commit and pushes it | 25 `deploy-*` tags 2026-10-15 → 2026-10-27 (`git tag -l 'deploy-*'`) |
| Build identifier inside the running product | Images are tagged with the commit sha and built with `KG_RELEASE=<sha>`; `/api/metrics/` exposes the live sha (`kgkg_release_info`) | `docker ps` shows `kgkg-backend:<sha>`; Grafana release panel |
| Nothing reaches production untested | Gate (tests, migrations check, lint, build) → staging on a sanitized prod-DB copy → smoke → only then promotable | `ops/deploy/gate.sh`, `deploy.sh`, `/opt/KGKG_release/staging.env` |
| Only a person promotes | `kgkg-promote <sha>`: refuses unstaged or >72 h stale commits, requires typing `promote`; CI's key has no deploy verb | `ops/deploy/kgkg-promote`, `ops/deploy/kg-ci-gate`, `test_gate_roles.sh` |
| Rollback | `deploy.sh --rollback`; automatic rollback when the post-deploy smoke fails; pre-deploy DB backup kept | `deploy.sh` §rollback, `/opt/KGKG_release/db-backups/` |
| Migrations are rollback-safe | `check_migrations.py` refuses migrations that would break the previous release | gate step "migrations are rollback-safe" |

## Semantic versioning (introduced 2026-10-27)

`VERSION` at the repository root holds the product version, `MAJOR.MINOR.PATCH`:

* **MAJOR** — a change customers must act on (removed feature, changed URL
  scheme of manuals, incompatible API for integrators).
* **MINOR** — new capability (a new package, vehicle family, assistant feature).
* **PATCH** — fixes only, including security fixes.
* Pre-releases carry `-rc.N` while on staging; the promoted commit carries the
  plain version.

`deploy.sh` copies the `VERSION` of the deployed commit into the deploy tag's
message, so each `deploy-*` tag states which product version it shipped. The
first version under this policy is **1.0.0**, which becomes real when the
release containing it is promoted; no earlier release is retroactively given a
version number.

Classification used so far, honestly: the product has run as a continuously
deployed service since 2026-06 without alpha/beta/stable channels. Staging
(sanitized production data) plays the role of the release-candidate channel;
there is no public beta channel, and none is claimed.

## Release procedure

1. Merge to `work`; CI must be green (tests + coverage floor, lint, build, all
   security gates, image scan).
2. CI stages the commit; staging smoke must pass.
3. On the QA stack for the same commit: `qa/run_e2e.sh` green; for a MINOR or
   MAJOR release also `qa/perf/run_perf.sh load` within criteria and
   `qa/dast/run_zap.sh full` reviewed.
4. Bump `VERSION` and add the release block to `docs/CHANGELOG.md`.
5. Fill a release record (`RELEASE_RECORD_TEMPLATE.md`) and keep it with the
   evidence; the approver is the person who runs `kgkg-promote`.
6. `kgkg-promote <sha>`; the deploy tag records version and time.
7. Post-deploy: smoke (automatic), Grafana release panel shows the new sha,
   no new GlitchTip error class within one hour.

Steps 3 and 5 are procedure, not yet enforced by `kgkg-promote`. That gap is
recorded in the criteria matrix.
