# ADR-0006 — Documentation lives in the repository and ships with the change

**Status:** Accepted · **Since:** 2026-07 · **Recorded:** 2026-10-29

## Context
The team is small and much of the work is done with AI-assisted tooling across many
sessions. A separate wiki drifts out of step with the code. On the other hand, docs inside
the repository can be reviewed, diffed and tested with the code.

## Decision
* **Engineering knowledge lives in `docs/`.** That covers the system docs 01–15, this SRS,
  the ADRs, `openapi.yaml` and the CHANGELOG.
* **Audit evidence lives in `audit-evidence/`.**
* **A change that alters behaviour updates the affected section in the same commit**
  (`docs/README.md`, maintenance protocol).
* **User-facing help mirrors the docs** (`docRef` in the guidance content, doc 13).
* **Where cheap, drift is caught by tests.** The API spec must match the routes
  (`test_openapi_routes.py`).

## Consequences
* **Docs are versioned with the release they describe.** A deploy tag gives both.
* **There is no separate wiki,** and knowledge-management criteria are assessed on the
  repo. That is stated openly in `audit-evidence/12-knowledge-management/`.
* **Prose drift still happens where no test guards it.** Examples:
  * doc 05 listed removed endpoints (D-21);
  * doc 11 still said "There is no CI/CD" 11 days after CI/CD shipped, and "no external
    paging" after SMS paging shipped. Both were fixed in `1f8b544` on 2026-10-27.

  Owners and a review cadence are an open action in the criteria matrix.
* **`*.md` is gitignored globally,** so docs must be added with `git add -f`. That is a known
  gotcha (doc 11 §11.7).

## Evidence
`docs/README.md`, `api/test_openapi_routes.py`, `audit-evidence/12-knowledge-management/README.md`.
