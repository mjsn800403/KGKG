# Root-cause analysis of the four evaluation findings

Written 2026-10-30 on branch `claude/dev-infrastructure-evaluation-27b025`
(base `main` = `9d214ef`). Every claim below is either a direct reading of the
code in this repository, a count taken from a file in this repository, or
labelled as a judgement. Nothing here is inferred from a document that merely
claims a capability; where the only evidence is a document, it says so.

The evaluators raised four deficiencies. This document takes each one apart in
the ten-step form requested, then states what was built in response and what
was not.

Status vocabulary used throughout, consistent with
`../15-final-audit-report/CRITERIA_MATRIX.md`:
**Verified** · **Partially Verified** · **Implemented but Not Verified** ·
**Not Implemented** · **Blocked**.

---

## Finding 1 — "Lack of verifiable team and task management tools"

### 1. What the evaluators identified as inadequate
That the organisation could not *demonstrate* structured team collaboration,
project management and task tracking. The operative word is demonstrate: the
claim is about absent evidence, not necessarily absent work.

### 2. Why the current implementation failed the requirement
The work was real but its record was scattered across media that cannot be
audited as a task system:

* Planning lived in conversation and in prose inside `docs/CHANGELOG.md`.
* The corrective-action register (`../14-risk-and-corrective-actions/CORRECTIVE_ACTIONS.md`)
  was a Markdown table — a document, not a tracker: no state transitions, no
  assignee, no dates per transition, no query interface.
* GitHub Issues existed but only from 2026-10-29. As of this writing the
  repository has **19 issues (numbered `#15`–`#35`), 5 closed, 14 open**, all
  labelled `corrective-action` plus an `area:*` label
  (`gh issue list --state all --limit 100 --json number -q 'length'` → 19;
  `--state closed` → 5). **No issue carries a milestone**
  (`gh api repos/mjsn800403/KGKG/milestones --jq 'length'` → 0) and there is
  **no backlog of planned work** — every issue is a remediation item from the
  2026-10-29 audit. Whether a GitHub Project board exists could not be checked
  from this session: `gh project list` fails with
  `your authentication token is missing required scopes [read:project]`. No
  board is referenced from any issue or document in the repository.
* Nothing connects a commit or pull request to an issue. Branch names are
  `claude/*`, `fix/*`, `docs/*`; commit subjects follow Conventional Commits
  but carry no issue reference, so "which change closed which task" is not
  answerable mechanically.
* `api/models.py` has an `ActivityLog` and an `AuditLog` for *customer* and
  *admin* actions. There is no model representing a unit of internal
  engineering work.

### 3. Missing capabilities, processes, documentation, components
A backlog with a defined shape (epic → item → acceptance criteria); ownership
and status per item; iteration or milestone boundaries; the link from item to
commit, pull request and release; and a view that shows throughput and ageing.

### 4. Nature of the underlying issue
**Organisational and evidential, not architectural.** The platform that can
hold this already exists and is already paid for and in daily use (GitHub).
It was never configured as the system of record, and no convention forced work
through it.

### 5. What already exists and can be improved
GitHub Issues with a working label taxonomy; three issue templates
(`.github/ISSUE_TEMPLATE/defect.yml`, `support-escalation.yml`, `config.yml`);
Conventional Commits in force since 2026-06; 25+ `deploy-*` tags mapping
deployments to commits; a CI workflow (`.github/workflows/ci.yml`) that can
host a traceability check.

### 6. What new capability is genuinely necessary
A convention (every change references an issue), a machine check that the
convention held, milestones that make a release a set of closed items, and one
read-only dashboard so that management can see the state without using the
developer tool. Nothing more.

### 7. Practical alternatives
| Option | Assessment |
|---|---|
| Build a task module inside KG_backend | Rejected. Duplicates GitHub, needs auth/UI/notifications of its own, and would be an interface that exists for the evaluation rather than a system of record. The code in `api/` is a customer-facing product; internal engineering administration does not belong in it. |
| Adopt a third-party tracker (Jira, ClickUp, Linear) | Out of scope by instruction, and a fourth place for the same facts. |
| **Configure GitHub as the system of record, enforce traceability in CI, expose a read-only dashboard** | **Chosen.** Zero new infrastructure; the evidence is produced by doing the work, not by describing it. |

### 8. Why the chosen solution is best
The record is a by-product of the engineering workflow, so it cannot drift from
reality: an issue closes because a merged pull request closed it. Reliability
and maintainability are GitHub's problem, not ours. Feasibility is hours, not
weeks.

### 9. How it should be implemented and validated
Implementation: milestones per release; a backlog epic per product area; a
`traceability` CI job that fails a pull request whose body references no issue;
`gh`-sourced metrics written into the BI collector (Finding 2). Validation: the
CI job must fail on a pull request with no reference and pass on one with a
reference, demonstrated in a run; the dashboard must reproduce
`gh issue list` counts.

### 10. Evidence that would demonstrate resolution
A GitHub Project board with items in several states; milestones with closed
and open counts; a CI run where the traceability job failed, and the next run
where it passed; issue ageing and throughput computed from the GitHub API with
the query recorded.

### Status now
**Partially Verified.** The register is now a real tracker (20 issues with
labels and state), which is more than existed at the evaluation. The board,
milestones, backlog and the traceability check are **Not Implemented** — see
`ROADMAP.md`, phase 2. This document does not claim otherwise.

---

## Finding 2 — "Absence of Business Intelligence infrastructure"

### 1. What the evaluators identified as inadequate
No established infrastructure for systematic data analysis, performance
monitoring, reporting and business intelligence.

### 2. Why the current implementation failed the requirement
Measurement exists, abundantly, but it is **fragmented and undefined**:

* Product analytics: `api/insights.py` (200 lines) serves three admin
  endpoints — `/api/admin/insights/search/`, `/funnel/`, `/ai-cost/` — with
  real aggregates over `SearchLog`, `ActivityLog`, `ChatLog`, `VisitorSeen`,
  `PurchaseRequest`.
* `api/reporting.py` (408 lines) renders a designed Persian PDF for a company
  manager; `api/recommend.py` serves manager insights.
* Infrastructure telemetry: Prometheus, Grafana, Loki, Alloy, blackbox probes
  (`ops/observability/`), with `api/metrics_exposition.py` exposing app
  metrics and `api/alert_rules.py` evaluating alert rules.
* Engineering and quality data exist only as artefacts: coverage JSON, k6 JSON,
  ZAP JSON, mutation TSVs under `audit-evidence/`, plus CI run JSON.

Three concrete failures follow from that shape:

1. **No metric definitions.** Nowhere states what a KPI means, how it is
   calculated, from which table, over which window. "Active user" means one
   thing in `insights.admin_funnel_view` (`action='login'`) and another in
   `team.team_analytics_view`. An evaluator cannot audit a number whose
   definition is implicit in a query.
2. **No management view.** Every number above is reachable only by an admin
   token against a JSON endpoint, or by a Grafana login. There is no page that
   answers "how is the organisation performing" in one place.
3. **Whole domains unmeasured.** Delivery (deploy frequency, lead time, change
   failure rate, MTTR), quality trend (coverage and defect trend over
   releases), support (first response time, resolution time, SLA compliance,
   CSAT), knowledge (document staleness, article usage) — none of these is
   collected at all. The data for the first two exists in git and in CI; the
   last two did not exist before this branch.

### 3. Missing capabilities
A metric registry (definition, source, calculation, owner, interpretation); a
collector that computes each metric from its stated source on a schedule; a
store for the time series so trends exist; one dashboard per audience; and the
instrumentation needed for metrics whose data is not collected yet.

### 4. Nature of the underlying issue
**Architectural in the small, organisational in the large.** The data layer is
healthy; what is missing is a semantic layer (definitions) and a presentation
layer (one dashboard), plus discipline about defining a metric before drawing
it.

### 5. What already exists and can be improved
`api/insights.py` is a good base for product metrics. Prometheus/Grafana is
already installed, authenticated through `api/grafanaauth.py`, and is the
correct home for time series — a second time-series store would be waste.
`ops/observability/bizsnap.py` already snapshots business figures.

### 6. What new capability is genuinely necessary
A metric registry as data (not prose), a collector that reads from git, the
GitHub API, the database and the `audit-evidence` artefacts, and one dashboard.
Not a data warehouse, not an ETL framework, not a BI product.

### 7. Practical alternatives
| Option | Assessment |
|---|---|
| Install a BI product (Metabase, Superset) | Another service on a host that already runs production, staging, QA and observability (open issue `#25`). It would still need the definitions, which are the actual missing piece. Rejected for now. |
| Grafana dashboards only | Grafana is right for operational time series but weak for delivery and quality metrics that come from git and from JSON artefacts, and a Grafana login is the wrong interface for management. |
| **Metric registry + collector + one admin dashboard, with Grafana kept for operational telemetry** | **Chosen.** |

### 8. Why
Every number carries its definition and its query, so it is auditable. No new
service, no new host pressure. The collector is ordinary Python under test.

### 9. Implementation and validation
Phase 3 of `ROADMAP.md`. Validation: each registry entry must be reproducible
by running the stated query by hand and getting the dashboard's number; the
collector gets unit tests with fixture data; a deliberately wrong definition
must fail its test.

### 10. Evidence
The registry file; collector test output; a dashboard screenshot beside the
hand-run queries that reproduce its numbers; a stored series showing at least
two collection points.

### Status now
**Not Implemented** (as a BI capability). Component parts are **Verified** to
exist and work. The support-side metrics this branch adds
(`/api/admin/support/metrics/`, below) are the first slice built to the
registry discipline: every field has a stated definition in
`METRIC_DEFINITIONS.md` and a test.

---

## Finding 3 — "Lack of formal knowledge transfer mechanisms"

### 1. What the evaluators identified as inadequate
No structured process or system for documenting, sharing, preserving and
transferring knowledge.

### 2. Why the current implementation failed the requirement
Documentation is genuinely strong; *transfer* is what is absent.

What exists: `docs/00-srs.md` (20 functional and 14 non-functional
requirements), `docs/01`–`15` covering architecture, data model, backend, API,
RBAC, frontend, RAG, SSE, analytics, operations, security, guidance,
terminology, vehicle schema; six ADRs in `docs/adr/`; `docs/openapi.yaml`
enforced by `api/test_openapi_routes.py`; `docs/CHANGELOG.md`; and a stated
docs-as-code protocol (ADR-0006).

What is missing, and why each matters:

* **No ownership.** `../12-knowledge-management/README.md` assigns ownership
  *by role*, not to a named person. Unowned documents are not maintained.
* **No review cycle.** No document carries a "last reviewed" date or a review
  interval, so staleness is invisible. The 2026-10-28 audit found two stale
  sections by reading them — a method that does not scale.
* **No check.** CI validates code, not documentation currency. A document can
  silently decay for a year without any signal.
* **Knowledge is developer-shaped only.** Everything is in `docs/` in the
  repository, in English, in Markdown. A support agent answering a customer,
  or a customer trying to self-serve, has no access path to it. The in-product
  help (`kg_frontend/src/guidance/`, 1,371 lines: `TourEngine`, `HintLayer`,
  `HelpCenter`, 567 lines of content) is a **hard-coded tour and hint system** —
  content ships in a JavaScript file and can only change by deploying the
  frontend. It is onboarding, not a knowledge base: no search over articles, no
  authoring, no versioning, no link to a ticket.
* **Nothing closes the loop.** A recurring customer problem is solved in a
  ticket's `admin_note`, which no one can search and which never becomes an
  article. The same question is answered from scratch every time. This is the
  precise mechanism by which an organisation fails to transfer knowledge, and
  it is structural here.

### 3. Missing capabilities
Named document owners with a review interval and a machine check; a knowledge
base with articles, categories, search, versions and an author; a path from a
resolved ticket to an article; and visibility of what people search for in the
knowledge base and do not find.

### 4. Nature
**Architectural for the customer-facing half** (there is no article store at
all) and **organisational for the internal half** (ownership and review are
policy, not code).

### 5. What exists and can be improved
`docs/` as the internal knowledge store — keep it, add a registry with owners
and review dates plus a CI check. The guidance system is a good delivery
surface — keep the tour, give it an article store behind it instead of a
hard-coded array. `api/insights.py`'s `record_search` is the right pattern for
measuring knowledge-base misses.

### 6. What is genuinely new
A `KnowledgeArticle` model with revisions, a search endpoint, an authoring
surface in the admin panel, and a ticket → article promotion action.

### 7. Alternatives
| Option | Assessment |
|---|---|
| A wiki (Wiki.js, BookStack) | New service, new auth, and it splits knowledge from the product the customer is already in. Out of scope by instruction. |
| GitHub Wiki / `docs/` for everything | Good for engineers, useless for a customer in the portal. |
| **`docs/` + registry + CI check for internal knowledge; an in-product knowledge base for product and support knowledge, fed by resolved tickets** | **Chosen.** Two audiences, two surfaces, one authoring discipline. |

### 8. Why
It puts the knowledge where its reader already is, and it makes transfer a
by-product of support work rather than an extra task that never happens.

### 9. Implementation and validation
Phase 2 of `ROADMAP.md`. Validation: the registry check must fail on a document
past its review date; an article promoted from a ticket must be retrievable by
search; knowledge-base searches with no result must appear in the metrics.

### 10. Evidence
The registry with named owners and dates; a CI run failing on a stale document;
the article store with revision history; search-miss counts.

### Status now
**Partially Verified** for internal documentation (strong content, no ownership
or review mechanism). **Not Implemented** for a knowledge base. This branch
adds the data the promotion step will need — a threaded, searchable ticket
conversation instead of a single `admin_note` field — but not the article store.

---

## Finding 4 — "Traditional and manual customer feedback collection"

### 1. What the evaluators identified as inadequate
Feedback arrives by telephone rather than through an integrated, digital,
traceable, systematically managed mechanism.

### 2. Why the current implementation failed the requirement
This is the finding with the clearest *technical* root cause, and the previous
audit missed it. Reading `api/requests_api.py` as it stood at `9d214ef`:

```python
@csrf_exempt
@require_manager          # line 82 — list and create
def company_requests_view(request):
```

`require_manager` (`api/portal_auth.py`) returns **403** unless the portal user
has `can_manage_team`. So:

* **Only a company manager can file a ticket.** On 2026-10-27 production held
  9 companies and 36 seats (figure from
  `../11-operations-and-support/SUPPORT_AND_INCIDENTS.md`). Only seats carrying
  `can_manage_team` can reach the endpoint; the per-company split of managers
  to specialists was not read from production in this session, so the exact
  number of users locked out is not stated here. Structurally, every
  non-manager seat has exactly one channel available: the telephone. The phone-based feedback the evaluators
  observed is not a cultural habit — **it is what the authorisation model
  forces**. This is the single highest-value fix in the programme and it is a
  decorator change plus a scoping rule.
* **There is no conversation.** `CompanyRequest` has one `admin_note`
  `TextField`. A clarifying question from the admin overwrites, or is manually
  appended to, the resolution text. Cancellation literally string-concatenates
  into the same field (`requests_api.py`, `company_request_detail_view`). So
  anything needing a back-and-forth moves to the phone *even for a manager*,
  and the exchange is then lost.
* **There is no ownership.** `handled_by` is a free-text
  `CharField(max_length=100)` defaulted to the literal string `'admin'`. No
  foreign key to `PlatformAdmin`, so "who is working this" is not a queryable
  fact and no workload can be balanced.
* **There is no clock.** No SLA target, no first-response timestamp, no breach
  state. `resolved_at` exists, but nothing defines what resolution time was
  supposed to be, so compliance is undefined and unmeasurable.
* **There is no satisfaction measurement.** Nothing asks the customer whether
  the resolution was any good. There is no CSAT, no NPS, no survey.
* **There is no reopen.** A closed request that was not actually fixed can only
  be re-filed as a new one, so the real resolution time of a problem is
  unknowable.
* **There is no escalation.** No rule promotes an ageing or breaching ticket,
  and nothing notifies anyone: `_emit_created` pushes an SSE event to whoever
  happens to have a dashboard open. If no one is looking, nothing happens.
* **There is no feedback channel that is not a request.** A customer who wants
  to report a rough edge, rate a page or suggest something has no digital
  surface. The one exception is assistant answers, which *do* have real digital
  feedback — `api/chatlog.py` `feedback_view` records a thumb verdict, a reason
  and a comment per exchange, and `api/views.py` adds expert pins and an admin
  review feed. That is a genuine, working, digital feedback loop; it is simply
  narrow, covering only AI answers.

Live volume, counted from production on 2026-10-27: **5 requests** (1
completed, 1 in progress, 3 rejected) and 9 purchase requests. Five tickets in
the lifetime of a product with 9 customer companies is not evidence of a
healthy support channel; it is evidence that the channel is not usable.

### 3. Missing capabilities
Open the channel to every user; a threaded conversation with internal notes;
real assignment; SLA policy with first-response and resolution clocks and a
breach state; escalation with notification; reopen; CSAT after closure; a
general feedback channel; attachments; and support metrics computed from all of
the above.

### 4. Nature
**Functional and architectural.** The model and the authorisation gate are
wrong for the job, and no amount of process fixes a 403.

### 5. What exists and can be improved
A great deal, which is why this is an extension rather than a rewrite:
`CompanyRequest` with its kind/status/priority vocabulary in Persian, tenant
isolation that is tested against IDOR (`api/test_qa_requests.py`, 28 tests),
the SSE event backbone (`api/events.py` with `emit`, `emit_company`,
`emit_user`), an SMS and notification layer (`api/notify.py`), an alert-rule
engine (`api/alert_rules.py`) that can carry SLA breach rules, an audit log,
rate limiting (`api/ratelimit.py`), and a `/requests` page in the frontend.
**Nothing here should be rebuilt.**

### 6. What is genuinely new
`TicketMessage` (the thread), SLA fields and policy, an assignee foreign key,
a `source` field so the phone-to-digital shift is measurable at all, CSAT
fields, a reopen transition, and a support-metrics endpoint.

### 7. Alternatives
| Option | Assessment |
|---|---|
| A help-desk product (Zammad, FreeScout, Zendesk) | Out of scope by instruction; also a second identity system, a second tenancy model, and customer data in a second place. The existing IDOR-tested tenant isolation would have to be re-earned. |
| Email-based support | Untraceable, unmeasurable, no SLA — this is the finding, in a different medium. |
| **Extend `CompanyRequest` into a real service desk in place** | **Chosen.** Keeps the tenancy guarantees and the real-time layer; the customer stays in one product. |

### 8. Why
The expensive, risky parts — multi-tenant authorisation, real-time delivery,
notification, audit — already exist and are tested. What is missing is a
thread, a clock, an owner, and a question at the end. That is an afternoon of
model work and a week of interface work, against months for an integration
that would still not know what a company's seats are.

### 9. Implementation and validation
Built on this branch, test-first. Validation: every new rule gets a test that
fails before the change; the full backend suite must stay green; SLA
arithmetic is tested against frozen clocks, not wall time.

### 10. Evidence
Migration + model diff; the new test module with its count; full-suite output
before and after; the metrics endpoint's numbers reproduced by hand from the
same rows.

### Status now
See `IMPLEMENTATION_PHASE1.md` for exactly what was built, tested and what was
left out.
