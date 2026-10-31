# Feature-discovery onboarding — design

Date 2026-10-30. Branch `claude/dev-infrastructure-evaluation-27b025`.
Status: approved in conversation, not yet implemented.

## The problem, measured

Production, 2026-10-30, four months of data, 34 seats with any activity:

| Feature | Uses | Seats that ever used it | Seats entitled | Discovery |
|---|---|---|---|---|
| Manuals (`view_node` / `view_section`) | 71,886 | ~34 | 36 | ~94 % |
| Parts catalogue (`parts_view`) | 314 | **6** | 36 | **17 %** |
| Assistant (`ask_assistant`) | 43 | **9** | ~18 | **~50 %** |
| Semantic search | **0 rows in `SearchLog`** | **0** | 36 | **0 %** |
| CSV export, labour times / SST (`download_csv`) | 3 | — | — | — |
| Team PDF report (`report_pdf`) | 8 | — | — | — |

The counts are exact (`api_activitylog`, `api_searchlog`). The *entitled*
column is not: 36 is every active seat with a car grant, and ~18 is the number
whose own flag and whose company's flag both allow the assistant — it does not
yet apply the third condition in `access.user_ai_eligible` (the seat must hold
the Repair Manual package), so the true denominator is **18 or fewer** and the
discovery rate is **50 % or better**. The implementation computes it properly;
the figure here is the floor, not the answer.

People found the manuals and very little else. The assistant — the capability
with a per-answer cost — has been *asked* 43 times in the platform's life.

**Why this went unnoticed for four months:** every piece of onboarding state
lives in `localStorage` (`kg_frontend/src/guidance/storage.js`): tour-seen,
hint-dismissed, help-opened. It is per browser, lost on a device change, and
invisible to the server. Nobody could ask "did this seat ever get started",
so nobody could see that most of them had not.

## What we are building

A checklist whose items are **earned by doing the thing**, derived from the
`ActivityLog` rows the product already writes, scoped to what each seat is
entitled to — plus two or three nudges fired by friction rather than by a
timer. One derivation function serves both the seat's checklist and the
admin's discovery metric, so the two can never disagree.

Rejected alternatives, with reasons, are at the end.

## Data model

**No new model for progress.** Completion is a question about `ActivityLog`,
which already carries `user`, `action`, `category`, `car` and `created_at` with
an index on `(user, created_at)`. Storing a second copy of "has used the
assistant" would create a thing that can disagree with the activity log, and
the disagreement would be invisible.

One new field:

```python
# api/models.py, PortalUser
onboarding_dismissed_at = models.DateTimeField(null=True, blank=True)
```

One timestamp. Server-side, so dismissal survives a device change — which
`localStorage` does not. Dismissed means gone, not snoozed: a checklist that
reappears next week is a nag, and a nag gets ignored along with everything else
the product says.

## Derivation rules

`api/onboarding.py`, one function, used by both surfaces:

| Item | Done when | Entitled when |
|---|---|---|
| `read_manual` | `ActivityLog(action__in=('view_node','view_section'))` ≥ 1 | the seat has any car grant |
| `use_search` | a `SearchLog` row for the seat ≥ 1 | any car grant |
| `ask_assistant` | `ActivityLog(action='ask_assistant')` ≥ 1 | `access.user_ai_eligible(user)` |
| `open_parts` | `ActivityLog(action='parts_view')` ≥ 1 | a car grant whose documents include `parts` |
| `export_times` | `ActivityLog(action='download_csv')` ≥ 1 | a grant including `standard_time` or `special_tools` |
| `ask_support` | a `CompanyRequest` filed by the seat ≥ 1 | always (every seat may file one — see the desk work on this branch) |
| `invite_colleague` | `ActivityLog(action='team_add')` ≥ 1 | `can_manage_team` |
| `read_team_report` | `ActivityLog(action='report_pdf')` ≥ 1 | `can_manage_team` |

Two decisions inside that table worth stating:

* **`ask_assistant`, not `open_assistant`.** 62 opens produced 43 questions
  across 9 people; opening a panel and leaving is not discovery, and counting
  it would flatter the number we are trying to move.
* **Entitlement is computed, not copied.** `user_ai_eligible` already exists in
  `api/access.py` and encodes three conditions (seat flag, company flag, the
  manual package). Re-expressing it here would create a second definition of
  who may use the assistant.

An unentitled item is **not shown and not counted** — neither in the
numerator nor the denominator. Telling a seat to try something the company has
not bought would manufacture support tickets, two days after we built the
support desk to handle them.

## Surfaces

**`GET /api/auth/onboarding/`** (portal auth) returns, for the calling seat:

```json
{"items": [{"id": "ask_assistant", "done": false, "entitled": true,
            "title": "…", "why": "…", "href": "/assistant"}],
 "done": 2, "total": 5, "dismissed": false}
```

`POST /api/auth/onboarding/ {"dismissed": true}` sets the timestamp.

**The strip.** A collapsed one-line strip on `/browse` — "۲ از ۵ قدم" — that
expands on click. Never a modal, never blocking, never over content. It
disappears for good when every entitled item is done, or when dismissed.

**The nudges**, through the existing `HintLayer`, fired by friction rather
than by elapsed time, at most one per surface per session, each dismissible
for good:

1. a search that returned nothing → the assistant answers questions a search
   box cannot;
2. a long reading run (≥ 25 section views, assistant entitled, never asked) →
   ask it instead of hunting;
3. viewing a car whose grant includes `parts` while `parts_view` is still zero
   → one pointer, once.

Each rule reads the same payload as the strip. No new signals, no timers.

**Hint dismissals stay in `localStorage`; only the strip's dismissal moves to
the server.** The distinction is deliberate: the strip's state is *progress* —
a fact about the person that should follow them to a new machine — while a hint
dismissal is *noise control* for one surface on one device, and syncing it
would mean a write to the database every time someone closes a tooltip. If the
nudges later prove to matter more than that, moving them is a small change;
starting there would be building a sync layer for tooltips.

## The metric

A `feature_discovery` block on `GET /api/admin/support/metrics/`, computed by
the **same function** the seat's checklist calls:

```json
{"ask_assistant": {"entitled": 18, "discovered": 9, "rate": 0.5}}
```

Defined in `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md` with
its source and a hand-reproducible query, like every other metric on this
branch. The rate's denominator is **entitled seats**, so it answers "of the
people who could use this, how many have" — the only version of the question
that can be acted on.

## Testing

Derivation and entitlement are pure questions about the database, so they are
tested directly, test-first, with fixture rows:

* each item done / not done, built from real `ActivityLog` rows;
* each entitlement boundary, including the three-condition AI rule;
* an unentitled item absent from the payload **and** from the metric's
  denominator;
* dismissal persisting across sessions and devices (two tokens, one seat);
* the metric and the checklist agreeing on the same fixture — the property
  that justifies sharing one function;
* frontend: the strip's pure state helpers (`lib/onboarding.js`) under
  `node --test`.

## What this will not do

* No modal, no blocking wizard, no progress bar the user must clear.
* No "mark as done" button: an item the user can tick without doing the thing
  turns the metric into decoration.
* No re-nagging after dismissal.
* No copy containing a statistic we cannot derive from this installation's own
  data.
* No change to the existing tours. They are not the failure — all 34 seats saw
  one, and the features went undiscovered anyway, because discovery fails three
  weeks in, not at minute one.

## Rejected alternatives

* **Nudges alone, no checklist.** Smallest change, but dismissals would stay in
  `localStorage` — the exact blind spot that hid this for four months — and the
  seat would still never see what else exists.
* **A bigger branching tour.** A one-shot tour at first login already ran. The
  moment that matters is later: someone deep in brake diagrams who has never
  had a reason to look up.
* **A separate `OnboardingProgress` table written by the client.** A second
  record of truth that can disagree with the activity log, and one the client
  could write without the user doing anything.

## Open questions, to settle during implementation

1. **Is search broken or merely undiscovered?** `SearchLog` has zero rows.
   `insights.record_search` is called from `views.search_view`; if the endpoint
   works and nobody has used it, `use_search` is a legitimate checklist item.
   If the instrumentation is broken, that is a defect to file separately and
   the item is worthless until it is fixed. **Resolve before building the
   `use_search` item.**
2. **`last_login_at` is unreliable** — 14 active seats have logins in the
   activity log (latest 2026-08-12) and a null `last_login_at`, so
   `insights.admin_funnel_view`'s `dormant_accounts` is wrong for them. Out of
   scope here; file as a defect.
3. **Does the strip belong anywhere besides `/browse`?** Start with `/browse`
   only; a seat's first destination after login. Revisit with the metric.
