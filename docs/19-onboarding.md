# 19 — Engineer onboarding

How a new engineer goes from nothing to a reviewed change running in
production. Each step names the document that holds the detail and the check
that proves the step is done, so a mentor can tell where someone is without
asking. Runbooks for when things go wrong are in [20 — Runbooks](20-runbooks.md).

## Day 1 — access and the map

| Do | Done when |
|---|---|
| GitHub: be added to `mjsn800403/KGKG` with **Write** (Maintain for release managers) | `gh api repos/mjsn800403/KGKG --jq .permissions.push` prints `true` |
| Server: an SSH key of your own on the production host (root access is granted by a maintainer, never shared) | `ssh root@<host> 'ops/deploy/deploy.sh --status'` from `/opt/KGKG_work` |
| Read, in order: [README](README.md) → [01 overview](01-overview.md) → [02 architecture](02-architecture.md) → [06 RBAC](06-permissions-rbac.md) → [11 operations](11-operations-deployment.md) | you can say where a vehicle's manual lives, who may see it, and how a change reaches production |
| Read [CONTRIBUTING](../CONTRIBUTING.md) and the [ADRs](adr/README.md) | you know why only a person promotes (ADR-0004) |
| Join the alert recipients if you will be on call (`KG_ALERT_PHONES`) | a dry run of the watchdog lists your number |

## Week 1 — run it, then change it

1. **Run the tests.** Backend: `KG_RL_DISABLE=1 .venv/bin/python manage.py test api`
   (PostgreSQL, on a gate database — never the production one). Frontend:
   `npm test` in `kg_frontend/`. Both must be green before you touch anything.
2. **Bring up the QA stack** and run the browser journeys:
   `qa/stack.sh up <ref>` then `qa/run_e2e.sh`.
3. **Pick a `good first issue` or `priority:normal` issue** from the current
   milestone on GitHub. Every pull request must reference an issue —
   `ops/governance/check_traceability.py` fails CI otherwise.
4. **Make the change test-first** on a branch off `work`, open a pull request
   into `work`, get one review.
5. **Ship it with a maintainer watching:** the merge to `work` makes CI stage
   that exact commit on the server (gate → staging → smoke). Production changes
   only when a maintainer runs `kgkg-promote <sha>` on the host
   ([11.3](11-operations-deployment.md), ADR-0004); it rolls back automatically
   on failure. You do not promote in your first week. Never edit `/opt/KGKG` by hand.
6. **Update the docs in the same commit** and move the document's `reviewed`
   date in `docs/OWNERS.toml` — CI enforces both.

## Month 1 — own an area

| Area | Start from | Owner check |
|---|---|---|
| Vehicle data pipeline (download → parse → PostgreSQL → RAG → diag) | [15 vehicle schema](15-vehicle-schema.md), [11.4](11-operations-deployment.md) | add one vehicle end to end and watch every stage including `pgcar` |
| AI assistant and retrieval | [08](08-ai-assistant-rag.md), [17 evaluation](17-evaluation.md) | run the gold-set evaluation and reproduce the published numbers |
| Help desk and knowledge base | `audit-evidence/16-improvement-programme/` | resolve a ticket and promote it to a knowledge-base article |
| Operations | [11](11-operations-deployment.md), [18](18-security-hardening.md), [20 runbooks](20-runbooks.md) | do a rollback and a restore check on staging |

## How knowledge keeps moving

* **Docs as code** (ADR-0006): behaviour changes and their docs ship together.
* **Named owners and review dates** for every document (`docs/OWNERS.toml`,
  enforced by `ops/governance/check_docs_freshness.py`).
* **Decisions** go in an ADR; **incidents** get a blameless postmortem under
  `audit-evidence/11-operations-and-support/` and a regression test.
* **Customer knowledge**: a resolved ticket that others will hit becomes a
  knowledge-base article with its own owner and review interval.
* **Hand-over**: before someone leaves an area, they walk the next owner
  through its runbook on staging and move ownership in `OWNERS.toml`. Taking over
  the whole project with nobody to ask: [48 — Handoff](48-handoff.md).
