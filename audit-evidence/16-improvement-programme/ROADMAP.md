# Improvement programme — prioritised roadmap

Ordered by severity of the deficiency and by dependency, not by ease. Each
phase states its acceptance criteria, because "done" has to be falsifiable.

Phase 1 is partly built (`IMPLEMENTATION_PHASE1.md`); everything else here is
**planned, not built**, and nothing in this file should be read as a claim
about the current system.

## Dependency order

```
P1 service desk API  ──► P1b desk interface ──► P1c desk E2E + alerting
         │                      │
         │                      └──► P4 support KPIs on a dashboard
         ├──► P3 knowledge base interface + guidance integration
         └──► P2 GitHub as system of record ──► P4 delivery + flow KPIs
                                                      │
P5 docs ownership registry + CI staleness check ──────┘
```

Nothing in phases 2–5 depends on phase 1b, so they can run in parallel with
the interface work.

---

## Phase 1b — the desk interface (highest priority)

**Why first:** the phase 1 API closes the finding's root cause but a customer
cannot reach it. An API-only capability is not a capability.

Work: rebuild `kg_frontend/src/app/requests/page.jsx` as a thread view
(messages, reply box, SLA state, CSAT prompt after closure, reopen); add an
agent view to the admin panel (inbox with source, assignee, SLA state and
breach highlighting, internal notes, escalate, promote-to-article); add a
feedback widget reachable from any page; show the knowledge base to seats, with
search, and wire the existing `HelpCenter` to it so the hard-coded content
array stops being the only help.

**Accept when:** a specialist opens, reads, replies to and rates a ticket in
the browser; an agent works it; a Playwright spec in `qa/e2e/` covers both
journeys and runs in CI.

## Phase 1c — closing the loop on the desk

SLA breach rules in `api/alert_rules.py` (an open ticket past
`sla_resolve_due_at` pages, as the existing alert path already does for
infrastructure); e-mail or SMS to the customer on a public reply, respecting
the existing notification preferences in `api/notify.py`; attachments on
messages; k6 coverage of the desk endpoints; a ZAP pass over the new routes.

**Accept when:** a deliberately breached ticket produces a real page, captured
as evidence; the DAST report covers the new paths with no new finding above
Low.

## Phase 2 — GitHub as the verifiable system of record (Finding 1)

**Partly delivered 2026-10-30** (tracked as #45): milestones `1.2.0` and
`Backlog` exist and every open issue carries one — 0 of 19 did before; `type:*`
and `priority:*` labels added; five epics filed from this roadmap so the
tracker holds planned work rather than only remediation; and
`ops/governance/check_traceability.py` refuses a pull request that references
no tracked work. Still open: the Project board and the delivery dashboard.

No new tooling. Configure what exists:

* one milestone per release (`1.1.0`, `1.2.0`); every issue gets one;
* a backlog: an epic issue per product area, with child items that carry
  acceptance criteria — so the tracker holds planned work, not only
  remediation;
* a convention that every pull request references an issue, enforced by a
  `traceability` job in `.github/workflows/ci.yml` that fails a pull request
  whose body references none;
* labels already exist (`area:*`, `corrective-action`); add `type:*` and
  `priority:*`;
* a read-only delivery dashboard in the admin panel, fed by the GitHub API,
  showing issues by state, ageing work in progress, throughput per week and
  milestone burn-up.

**Accept when:** the CI job is seen to fail on a pull request with no
reference and pass on the next; milestones show closed/open counts; the
dashboard's numbers reproduce `gh issue list`; at least one release has been
cut as "the issues in milestone X".

**Explicitly not doing:** building a task module inside the product. Reasons in
`ROOT_CAUSE_ANALYSIS.md` §Finding 1 ·7.

## Phase 3 — knowledge base in daily use (Finding 3, customer half)

The store exists after phase 1. What is missing is use: seed it from the
`top_misses` list and from the resolved tickets already in the database;
integrate it with the guidance system so a hint can link to an article; add
article-level feedback review; put the stale-article list on the admin
dashboard so review is a visible chore rather than a good intention.

**Accept when:** 20+ published articles, each with a named owner and a review
date; a measured month where `knowledge.zero_result_rate` falls; at least five
articles with `source_request` set, proving the transfer loop runs.

## Phase 4 — the rest of BI (Finding 2)

Extend the registry discipline of `METRIC_DEFINITIONS.md` to the three
unmeasured domains:

* **delivery** — deployment frequency, lead time for change, change failure
  rate, MTTR, computed from git (`deploy-*` tags), the GitHub API (CI runs) and
  the deploy log;
* **quality trend** — coverage, test count, defect count per release, read
  from the artefacts already written under `audit-evidence/`;
* **task flow** — throughput and cycle time from phase 2's issues.

A collector (a management command on a timer, like the existing
`ops/observability/bizsnap.py`) writes a daily snapshot so trends exist;
Grafana keeps the operational time series; one admin page carries the
management view. Define before drawing: a metric without an entry in
`METRIC_DEFINITIONS.md` does not go on a dashboard.

**Accept when:** every dashboard number has a registry entry and a test; two
collection points exist for each series; a hand-run query reproduces each
figure.

## Phase 5 — documentation ownership and review (Finding 3, internal half)

A registry — `docs/OWNERS.yaml` — giving every document in `docs/` a named
owner and a review interval, plus a CI check that fails when a document is
past its review date or has no owner. The same `is_stale` rule as the
knowledge base, applied to the repository.

**Accept when:** the check is seen to fail on a stale document and pass after a
review commit; no document lacks an owner.

## Phase 6 — the self-service surface

Only after phases 1b and 3: contextual help that reads the knowledge base,
onboarding that resumes where a user left off, and a measured deflection rate
(tickets avoided after an article was read). Deflection needs real traffic
before it means anything, which is why it is last.

---

## What this roadmap deliberately refuses

* Installing a help-desk product, a wiki, a BI product or a project tracker.
  Each would add a service to a host that already runs production, staging, QA
  and observability (open issue `#25`), split customer data across two
  tenancy models, and leave the actual gaps — definitions, ownership,
  traceability — unfilled.
* Any dashboard whose numbers are not defined and tested first.
* A per-person productivity metric while the team is small enough that it
  would be theatre rather than measurement.
