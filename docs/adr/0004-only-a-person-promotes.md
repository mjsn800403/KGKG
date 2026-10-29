# ADR-0004 — CI stages; only a person promotes, on staging and E2E evidence

**Status:** Accepted · **Since:** 2026-10-27 (E2E evidence: 2026-10-29) · **Recorded:** 2026-10-29

## Context
A `deploy.yml` workflow would have promoted every green CI run to production. The only
thing holding it back was a GitHub environment setting. Releases had shipped while CI on
`work` was red (D-19). And the release policy listed "E2E green on the same commit" as a
step that nothing enforced.

## Decision
* **CI's key can only stage and read status.** It is pinned to a forced command
  (`kg-deploy-gate`, role `ci`) and has no `deploy` verb.
* **Promotion is `kgkg-promote <sha>` on the server.** It shows the commits, files and
  migrations to apply, and requires the word `promote` to be typed.
* **The normal phrase is refused unless the commit has both kinds of evidence:**
  * a passing staging run, at most 72 h old (`staging.env`);
  * a passing **full** browser E2E run, at most 72 h old (`e2e/<sha>.env`, written by
    `qa/run_e2e.sh`).
* **Promoting without evidence takes a longer phrase** that names what is missing. Each such
  override is logged to `promote-overrides.log`.
* **No timer, cron or workflow can reach promotion.**

## Consequences
* **Production cannot move without a person,** and that person sees what will change.
* **An emergency fix can still ship without E2E,** but it leaves a record.
* **Promotion takes longer:** the E2E suite (about 40 s plus stack start) must run first.
* **The `stage` CI job needs a staging credential secret in GitHub.** Without it, every
  push to `work` shows a red `stage` job (open on 2026-10-29).

## Evidence
`ops/deploy/kgkg-promote`, `ops/deploy/kg-deploy-gate`, `test_gate_roles.sh` (18 checks),
`test_promote.sh` (22 checks), `qa/e2e_record.py --selftest`, CHANGELOG 2026-10-27,
`audit-evidence/10-release-management/RELEASE_POLICY.md`.
