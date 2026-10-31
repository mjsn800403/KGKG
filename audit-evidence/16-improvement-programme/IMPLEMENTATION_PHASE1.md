# Phase 1 — what was actually built, tested and left out

Branch `claude/dev-infrastructure-evaluation-27b025`, based on `main` =
`9d214ef`. Date 2026-10-30.

This file is deliberately narrow: it records what changed, what proves it, and
what is **not** done. Analysis is in `ROOT_CAUSE_ANALYSIS.md`; later phases are
in `ROADMAP.md`.

## Scope decided before any code was written

Three choices, confirmed with the product owner:

1. The **system of record for team and task management stays GitHub** —
   configured properly and surfaced in a dashboard — rather than a task module
   inside the product. Reasoning in `ROOT_CAUSE_ANALYSIS.md` §Finding 1 ·7.
2. **Strategy plus a phase-1 slice**, not a document alone and not everything.
3. The slice is the **support desk and the feedback channel first**, because
   it is the weakest implementation and the one customers touch.

## Verification environment

The project's own `python manage.py test api` on SQLite, Django 5.2.18, local
machine. The RAG model stack (torch, sentence-transformers) is not installed
here, so seven `api.rag.*` modules and ten other tests that need native or
network dependencies fail **identically before and after** this work. To keep
that honest, the full suite was run on a clean worktree at `9d214ef` first and
the two failure sets were compared:

| Run | Tests | Failing | Evidence |
|---|---|---|---|
| Baseline, clean worktree at `9d214ef` | 1,059 | 17 (environment only) | `evidence/baseline-failures-9d214ef.txt` |
| This branch | **1,154** (+95) | **the same 17** | `evidence/branch-failures.txt` |

`diff` of the two files is empty — no regression, and no test "fixed" by
accident. The new suites run clean on their own:
`evidence/new-suites-verbose.txt` (123 tests: 60 service desk, 35 knowledge
base, 28 pre-existing request tests).

The suite still fails on this branch for the 17 environment reasons above, so
**a green CI run on GitHub is required before any of this is promoted**. That
has not happened yet; see "Not done".

## 1. The support channel is open (Finding 4, root cause)

`api/requests_api.py` was gated end to end on `require_manager`. Any seat
without `can_manage_team` received 403 on every ticket endpoint, so an ordinary
user's only channel was the telephone.

* New gate `require_portal_user` (`api/portal_auth.py`): any signed-in seat.
* Per-kind authorisation moved into the view: `support` and `other` are
  self-service; `vehicle_access`, `seats`, `ai_assistant` and `documents` stay
  manager-only, because they commit the company to cost or scope.
* Visibility follows the same logic: a seat sees the tickets they filed, a
  manager sees the company's.

Tests: `api/test_helpdesk.py::ChannelAccessTests` (8).

Three pre-existing tests asserted the old 403 and were updated with a comment
explaining why the behaviour changed, rather than deleted:
`test_qa_requests.test_non_manager_may_use_the_support_channel_but_not_commercial_kinds`,
`test_events.test_specialist_can_file_a_support_request_but_not_a_commercial_one`,
`test_qa_access.test_anonymous_rejected_and_a_non_manager_sees_only_their_own`.

## 2. A conversation instead of one text field

`CompanyRequest.admin_note` was a single `TextField`; a reply overwrote it, and
cancellation concatenated into it. New model `TicketMessage`: one author
(customer *or* platform), a body, and an `internal` flag for admin-only notes
that are filtered out of the customer's queryset rather than hidden by the
client. A ticket's opening body seeds the first message, so the thread is
complete from the start.

Tests: `ThreadTests` (8), including that an internal note never reaches the
customer and that a customer message on a closed ticket reopens it.

## 3. SLA clocks (new module `api/sla.py`)

Targets per priority — high 2 h/8 h, normal 8 h/48 h, low 24 h/120 h — stamped
at creation. `first_response_at` is set by the first **public** admin message;
an internal note is not a response. A reopen restarts the resolution clock and
leaves the response clock alone. State is `met` / `breached` / `pending`, and
`pending` is excluded from compliance so an unexpired target cannot be reported
as a success.

Calendar hours, not business hours — stated in the module and in
`METRIC_DEFINITIONS.md`, because the organisation has no agreed working
calendar and inventing one would make every figure unauditable.

Tests: `SlaPolicyTests` (5, pure functions) and `SlaOnTicketTests` (6, through
HTTP).

## 4. Ownership and escalation

`handled_by` was a free-text field defaulting to the literal string `'admin'`.
Added `assignee` as a foreign key to `PlatformAdmin`, and `admin_auth.py` now
attaches the acting admin to the request (`acting_admin`), so `handled_by`
records who actually acted. `escalate` stamps `escalated_at`, raises priority
to high, re-stamps the targets and emits `request.escalated`; it is idempotent.

Tests: `AssignmentTests` (6).

## 5. Satisfaction

`csat_score` (1–5), `csat_comment`, `csat_at`. Asked once, after closure, of
the person who filed the ticket — or of a manager when the platform side logged
it (a telephone call has no filer). Out-of-range, repeat and premature ratings
are rejected.

Tests: `CsatTests` (5).

## 6. `source` — making the finding measurable

New field with `portal` / `phone` / `email` / `sms` / `in_person`. A client can
never set it: a ticket filed through the portal is `portal` by definition. The
admin endpoint gained `POST /api/admin/company-requests/` so that a call or an
e-mail is recorded in the same system, with the same SLA clock.

Without this field the evaluation finding cannot be answered with evidence at
all — "feedback now arrives digitally" is only a claim unless the share of
`phone` against `portal` can be shown falling.

Tests: `SourceTests` (5).

## 7. A feedback channel that is not a ticket (new module `api/feedback.py`)

`Feedback`: page, optional 1–5 rating, optional comment, rate-limited, emitted
to the admin audience so nobody has to remember to look. Either a rating or a
comment is required; an empty submission is rejected rather than stored.
Kept separate from tickets on purpose — an opinion is not a request, and
merging them would corrupt both the support load and the feedback volume.

Tests: `FeedbackChannelTests` (8).

## 8. Support metrics (new module `api/support_metrics.py`)

`GET /api/admin/support/metrics/?days=30`, admin only: volumes, first-response
and resolution times (mean and p90 by nearest rank), SLA compliance, CSAT,
`by_source`, `by_kind`, current backlog with ageing and breaches, feedback and
knowledge blocks. Every field is defined in `METRIC_DEFINITIONS.md` with its
source column and a hand-reproducible query, and every field has a test.

Rates and averages return `null`, never `0`, when their denominator is empty.

Tests: `SupportMetricsTests` (9).

## 9. Knowledge base (new module `api/knowledge.py`)

Three models: `KnowledgeArticle` (slug, title, category, body, audience
customer/internal, status draft/published/archived, **named owner**, review
interval, version, view and vote counters, optional `source_request`),
`KnowledgeRevision` (append-only history), `KbSearchLog` (what was asked for
and how many hits it got).

The three mechanisms, each against a stated root cause:

* **ownership and staleness** — `is_stale` is never-reviewed or past the
  article's own interval, so decay is a query rather than an impression;
* **revisions** — a text edit appends a revision and bumps the version, while
  a review, a status change or a reassignment does not (a reviewer confirming
  an article has not written a new version of it);
* **promotion** — `POST /api/admin/company-requests/<id>/promote-to-article/`
  turns a closed ticket into a **draft** seeded with the customer's words, the
  public thread and the resolution. A draft, not a publication: someone still
  has to edit it, and that human step is deliberate.

Search misses are the useful output: `knowledge.top_misses` is a work list of
articles that should exist.

Tests: `api/test_knowledge.py` (35) across reading, search and logging, votes,
authoring, staleness, promotion and metrics.

## Interface and documentation changes

* `docs/openapi.yaml`: nine new paths. The existing
  `api/test_openapi_routes.py` enforces that every route is specified — it
  caught the omission, which is the docs-as-code gate (ADR-0006) working.
* Migrations `0035_helpdesk_thread_sla_csat` and `0036_knowledge_base`.
  Additive only: new nullable columns and new tables, no data migration, no
  column dropped or retyped, so the deploy is reversible by rolling back the
  images.

## Honest statement of what is NOT done

| Not done | Consequence |
|---|---|
| **No CI run on this branch.** Verified locally only; 17 pre-existing environment failures mean a green GitHub Actions run is required before promotion. | No promotion is permitted (`ops/deploy/kgkg-promote` requires a passing E2E record anyway). |
| **E2E written but not executed**; no load or DAST on the new endpoints. | `qa/e2e/tests/support.spec.js` exists and needs the seeded QA stack to run; `qa/perf/k6-kgkg.js` does not exercise the desk. |
| **No accessibility scan** of the new surfaces. | `qa/e2e/tests/a11y.spec.js` covers four public pages only; the desk, the widget and the knowledge panel are unscanned. |
| **No SLA breach alerting.** `api/alert_rules.py` can carry a rule; none was added. Breaches are visible on request, not pushed. | An ageing ticket still needs someone to look. |
| **No notification to the customer** when an admin replies, beyond the existing SSE event. No e-mail or SMS on reply. | A customer who is not on the page learns nothing. |
| **No attachments** on tickets or messages. | A screenshot still goes by other means. |
| **GitHub milestones, project board and the CI traceability check** (Finding 1) are not implemented. | Finding 1 remains **Partially Verified**. |
| **Delivery, quality-trend and task-flow metrics** (Finding 2) are not collected. | Finding 2's BI capability remains **Not Implemented** beyond this support slice. |
| **The `docs/` ownership registry and its CI staleness check** (Finding 3, internal half) are not implemented. | Internal documentation still has no named owners. |
| **No production data was touched**, and no figure in this document comes from production. | The live volumes in `../11-operations-and-support/SUPPORT_AND_INCIDENTS.md` (5 tickets) still stand as the last measured state. |

## 10. The interface (phase 1b, same branch)

The API above was unusable by a customer until this part shipped. What it adds:

| Surface | What it does |
|---|---|
| `/requests` (`components/RequestsView.jsx`) | The customer side: file a ticket, hold the conversation, see the SLA state and the time left, reopen a closed ticket by replying, rate the resolution. The kinds offered come from the server's `meta`, so a commercial kind is never shown to a seat that would be refused |
| `components/TicketThread.jsx` | The conversation, shared by both sides. Internal notes are filtered out **server-side** for a customer; nothing in the client is relied on to keep them private |
| `components/CsatPrompt.jsx` | Five faces and an optional comment, shown only when `lib/support.canRate` agrees with the server's rule |
| `components/RequestsInbox.jsx` | The agent worklist: SLA state and what is already late without opening anything, an "only what is late" filter, a channel filter, assignee select, escalate, internal notes, **log a telephone call**, and promote-to-article on a closed ticket |
| `components/FeedbackWidget.jsx` | Page feedback for any signed-in seat, mounted globally by the guidance provider, carrying the current pathname. Not a ticket |
| `components/SupportAdmin.jsx` | Three admin sections — support KPIs, the product-feedback feed, knowledge-base authoring with owners, review dates, a "needs review" filter and version history |
| `guidance/HelpCenter.jsx` | The help panel now searches the knowledge base alongside the built-in articles, debounced, signed-in seats only, with a 👍/👎 per article |
| `components/Sidebar.jsx` | The support link is shown to **every** seat. While it was manager-only a specialist had no way in even after the API opened — the navigation was the last part of the 403 |
| `lib/support.js` | The presentation rules (SLA tone and label, due-date text, channel labels, `canRate`, duration and rate formatting), pure and tested first: a wrong rule here would tell a customer their late ticket is on time |

Verification:

| Check | Result |
|---|---|
| Frontend unit tests | 179 → **208** (`node --test src/lib/__tests__/*.mjs`); the 29 new ones were written before `lib/support.js` existed |
| `npm run lint` against the CI ratchet (`ops/deploy/lint_max_warnings` = 116) | **115 warnings, 0 errors** — one below the cap, so the gate passes and the ratchet tightens rather than slackens |
| `npm run build` | passes |
| Live journey in a real browser against a real backend | `evidence/ui/README.md`, with two screenshots and the metrics the journey produced |

That live run found three defects, all fixed here: the CSAT score rendered in
Latin digits beside Persian ones; a promoted draft repeated the ticket's
opening paragraph (now pinned by a test that fails on the previous code); and
`/requests` was unreachable for a specialist because the sidebar link was
manager-gated.

Playwright coverage was **written** (`qa/e2e/tests/support.spec.js`, 10 tests
for the specialist's whole journey and the authorization of the new endpoints)
but **not run here** — it needs the seeded QA stack from `qa/stack.sh`.

## Acceptance criteria for calling phase 1 complete

1. ✅ done by hand (`evidence/ui/README.md`), ⬜ not yet by a repeatable spec:
   a seat without `can_manage_team` can open, read and reply to a support
   ticket **from the interface**, verified by `qa/e2e/tests/support.spec.js`
   running in CI.
2. A GitHub Actions run on this branch is green.
3. `GET /api/admin/support/metrics/` on staging returns figures that match
   hand-run queries against the staging database, captured as evidence.
4. One real resolved ticket has been promoted into a published article, and the
   article is reachable by a seat.
5. `by_source` shows at least one `phone` ticket logged by a human — proof the
   telephone channel is being captured rather than bypassed.
