# ADR-0003 — Release as sha-tagged containers; backend swapped with SO_REUSEPORT

**Status:** Accepted · **Since:** 2026-10-16 · **Recorded:** 2026-10-29

## Context
Deploys used to be in-place edits plus restarts, with no record of exactly what was running.
Rollback meant restoring tarballs by hand. Customers use the portal during working hours,
and a restart drops in-flight assistant answers.

## Decision
* **Every release is a pair of images**, `kgkg-backend:<sha>` and `kgkg-frontend:<sha>`,
  built from a clean worktree of the exact commit (`ops/docker/`).
* **The backend has no downtime during a swap.** The new backend container starts next to
  the old one on `:8000` using `SO_REUSEPORT`. The old one stops only once the new one is
  healthy.
* **The frontend swap is a stop/start** of about one second.
* **A smoke test runs after the swap.** Any failure rolls back to the previous images.
  Migrations must be additive (`check_migrations.py`); they are not reversed, and the
  pre-deploy DB backup is kept.

## Consequences
* **"What is live" has one answer:** the image sha, exposed as `kgkg_release_info` in
  Prometheus.
* **Rollback is `deploy.sh --rollback`.** It is a container switch, not a restore.
* **Untagged build layers pile up.** The deploy prunes dangling images only. `prune -a`
  would delete the rollback target.
* **Host timers and pipeline jobs still run from the host checkout,** so the live tree
  matters too (deploy refuses a dirty tree).

## Evidence
`ops/deploy/deploy.sh` header, `docs/11-operations-deployment.md` §11.3, CHANGELOG 2026-10-16,
`audit-evidence/09-ci-cd/`.
