# Feature-discovery onboarding — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a seat discover the features it is entitled to, by showing a checklist whose items are earned from activity the product already records, and measure the result.

**Architecture:** One derivation function in `api/onboarding.py` answers "which items does this seat have, and which has it done" from `ActivityLog`, `SearchLog`, `CompanyRequest` and the existing entitlement helpers. Two consumers call it: the seat's own endpoint (`/api/auth/onboarding/`) and the admin discovery metric, so the figure management reads and the item the user sees cannot drift apart. The frontend adds a collapsed strip on `/browse` and three friction-triggered nudges through the existing `HintLayer`.

**Tech Stack:** Django 5.2 (standard library and existing dependencies only), Next.js 16 / React 19, `node --test` for frontend units, Django test runner for the backend.

**Spec:** `docs/superpowers/specs/2026-10-30-feature-discovery-onboarding-design.md`

## Global Constraints

- No new model for progress. Completion is a query over `ActivityLog` / `SearchLog` / `CompanyRequest`; the only new column is `PortalUser.onboarding_dismissed_at`.
- Entitlement for the assistant is `api.access.user_ai_eligible(user)` — called, never re-expressed.
- An unentitled item is absent from the payload **and** from the metric's denominator.
- A rate with an empty denominator is `None`, never `0` — the rule already stated in `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md`.
- UI copy is Persian; engineering docs and code comments are English.
- Tests are written before the code they describe. After every task the full backend suite's failure set must stay identical to the baseline in `audit-evidence/16-improvement-programme/evidence/baseline-failures-9d214ef.txt`.
- Frontend: `npx eslint src --max-warnings $(cat ops/deploy/lint_max_warnings)` must pass. Backend coverage floor `ops/deploy/coverage_min` = 60.
- Every new route is added to `docs/openapi.yaml` in the same task; `api/test_openapi_routes.py` enforces it.

## Review Focus

1. **A seat with no grants at all** (freshly invited, nothing assigned): every item unentitled. The payload must be an empty item list with `total: 0`, the strip must not render, and the metric must report `rate: None` rather than dividing by zero. — Tasks 2, 3, 4
2. **Entitlement revoked after discovery** (used parts, then the grant is removed): the item leaves both numerator and denominator. `discovered` must never exceed `entitled`. — Tasks 2, 4
3. **Another company's activity**: derivation is per seat by `user_id`; a colleague's or another tenant's rows must never complete an item. — Task 2
4. **A seat with tens of thousands of activity rows** (the heaviest production seat has ~47k): derivation must use `exists()`/`aggregate`, never load rows, or `/browse` slows for exactly the most engaged users. — Task 2
5. **Dismissal is idempotent and independent of progress**: POSTing twice is not an error, dismissing with items outstanding hides the strip for good, and a later new entitlement does not resurrect it. — Task 3

---

### Task 1: Settle whether search is instrumented

The spec records an open question: `SearchLog` has zero rows in production. If `record_search` does not fire, the `use_search` checklist item is worthless and this is a defect, not an onboarding gap. A test answers it.

**Files:**
- Test: `KG_backend/api/test_qa_search_instrumentation.py` (create)

**Interfaces:**
- Produces: a decision recorded in the plan's Task 2 — keep or drop the `use_search` item.

- [ ] **Step 1: Write the failing test**

```python
class SearchIsInstrumentedTests(TestCase):
    def test_a_search_by_a_signed_in_seat_writes_a_searchlog_row(self):
        # seat with a car grant, as api/test_qa_access.py sets one up
        r = self.c.get(f'/api/search/?q=brake&car={self.car.car_name}', **self.h_user)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(SearchLog.objects.filter(user=self.user).count(), 1)
```

- [ ] **Step 2: Run it**

Run: `python manage.py test api.test_qa_search_instrumentation -v 2`
Two outcomes, both actionable:
- **PASS** → search works and is merely undiscovered. Keep `use_search` in Task 2. Commit the test as a regression guard.
- **FAIL** → `record_search` is not firing. Do **not** fix it here: file a defect issue (`type:defect`, `area:qa`, milestone `1.2.0`) quoting the assertion, drop `use_search` from Task 2's table, and note the issue number in Task 2's docstring.

- [ ] **Step 3: File the second open question as a defect**

Unrelated to onboarding and out of this plan's scope, but recorded by the spec
and easy to lose: 14 active seats have `login` rows in `ActivityLog` (latest
2026-08-12) and a null `last_login_at`, so `insights.admin_funnel_view`'s
`dormant_accounts` is wrong for them. File it (`type:defect`, `area:qa`,
milestone `Backlog`) with that sentence and the query that shows it. Do not fix
it here.

- [ ] **Step 4: Commit**

```bash
git add KG_backend/api/test_qa_search_instrumentation.py
git commit -m "test(search): pin that a signed-in search is recorded"
```

---

### Task 2: The derivation function

**Files:**
- Create: `KG_backend/api/onboarding.py`
- Create: `KG_backend/api/test_onboarding.py`

**Interfaces:**
- Consumes: `api.access.user_ai_eligible(user)`, `api.access.user_package_set(user)`, models `ActivityLog`, `SearchLog`, `CompanyRequest`, `UserCarAccess`.
- Produces:
  - `ITEMS: tuple[Item, ...]` where `Item` is a `NamedTuple(id: str, title: str, why: str, href: str)` — `title`/`why` Persian.
  - `progress_for(user) -> list[dict]` — one dict per **entitled** item: `{'id', 'title', 'why', 'href', 'done': bool}`, in `ITEMS` order.
  - `discovery_counts(users) -> dict[str, dict]` — `{item_id: {'entitled': int, 'discovered': int, 'rate': float | None}}` over an iterable of seats.

- [ ] **Step 1: Write the failing tests**

```python
class EntitlementTests(TestCase):
    def test_a_seat_with_no_grants_gets_no_items(self):
        self.assertEqual(progress_for(self.bare_seat), [])

    def test_the_assistant_item_follows_user_ai_eligible_exactly(self):
        # flip each of the three conditions in turn; the item appears only
        # when access.user_ai_eligible agrees
    def test_the_parts_item_needs_a_grant_that_includes_parts(self): ...
    def test_manager_items_need_can_manage_team(self): ...

class CompletionTests(TestCase):
    def test_asking_the_assistant_completes_it_but_opening_does_not(self):
        ActivityLog.objects.create(user=self.seat, action='open_assistant')
        self.assertFalse(self._done(self.seat, 'ask_assistant'))
        ActivityLog.objects.create(user=self.seat, action='ask_assistant')
        self.assertTrue(self._done(self.seat, 'ask_assistant'))

    def test_a_colleagues_activity_does_not_complete_my_item(self): ...
    def test_a_filed_ticket_completes_ask_support(self): ...

class DiscoveryCountsTests(TestCase):
    def test_an_unentitled_seat_is_in_neither_numerator_nor_denominator(self): ...
    def test_discovered_never_exceeds_entitled_after_a_grant_is_revoked(self): ...
    def test_a_rate_with_no_entitled_seats_is_none_not_zero(self): ...

class QueryCostTests(TestCase):
    def test_progress_does_not_grow_queries_with_activity_volume(self):
        # 500 ActivityLog rows for one seat
        with self.assertNumQueries(len(ITEMS) + 2):
            progress_for(self.seat)
```

- [ ] **Step 2: Run them**

Run: `python manage.py test api.test_onboarding -v 2`
Expected: FAIL — `No module named 'api.onboarding'`.

- [ ] **Step 3: Implement `api/onboarding.py`**

Derivation table from the spec (`use_search` included or dropped per Task 1):

| id | done when | entitled when |
|---|---|---|
| `read_manual` | `ActivityLog(action__in=('view_node','view_section'))` exists | any `UserCarAccess` |
| `use_search` | `SearchLog(user=...)` exists | any `UserCarAccess` |
| `ask_assistant` | `ActivityLog(action='ask_assistant')` exists | `access.user_ai_eligible(user)` |
| `open_parts` | `ActivityLog(action='parts_view')` exists | a grant whose documents include `parts` |
| `export_times` | `ActivityLog(action='download_csv')` exists | a grant including `standard_time` or `special_tools` |
| `ask_support` | `CompanyRequest(created_by=user)` exists | always |
| `invite_colleague` | `ActivityLog(action='team_add')` exists | `user.can_manage_team` |
| `read_team_report` | `ActivityLog(action='report_pdf')` exists | `user.can_manage_team` |

Use `.exists()` per item — never `list()` or `count()` over activity. A grant's empty `documents` list means "every layer the company grants", matching `access.user_car_documents`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test api.test_onboarding -v 2` → PASS

- [ ] **Step 5: Commit**

```bash
git add KG_backend/api/onboarding.py KG_backend/api/test_onboarding.py
git commit -m "feat(onboarding): derive feature discovery from activity the product already records"
```

---

### Task 3: The seat's endpoint and dismissal

**Files:**
- Modify: `KG_backend/api/models.py` (add `PortalUser.onboarding_dismissed_at`)
- Create: `KG_backend/api/migrations/00XX_onboarding_dismissed.py` (via `makemigrations`)
- Modify: `KG_backend/api/onboarding.py` (add the two views)
- Modify: `KG_backend/api/urls.py`, `docs/openapi.yaml`
- Modify: `KG_backend/api/test_onboarding.py`

**Interfaces:**
- Consumes: `progress_for` (Task 2), `api.portal_auth.require_portal_user`.
- Produces: `GET/POST /api/auth/onboarding/` → `{'items': [...], 'done': int, 'total': int, 'dismissed': bool}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_signed_out_is_401(self): ...
def test_the_payload_counts_done_against_entitled_items_only(self): ...
def test_a_seat_with_no_grants_gets_an_empty_payload_with_total_zero(self): ...
def test_posting_dismissed_sets_the_timestamp_and_is_idempotent(self): ...
def test_dismissal_survives_a_new_session(self):
    # dismiss with one token, read with a second token for the same seat
def test_a_new_entitlement_after_dismissal_does_not_resurrect_the_strip(self): ...
```

- [ ] **Step 2: Run them**

Run: `python manage.py test api.test_onboarding -v 2` → FAIL (404 / missing field)

- [ ] **Step 3: Implement**

`onboarding_dismissed_at = models.DateTimeField(null=True, blank=True)` on `PortalUser`; `makemigrations api --name onboarding_dismissed`. Views gated by `require_portal_user`; POST accepts `{'dismissed': true}` only. Add both methods for `/api/auth/onboarding/` to `docs/openapi.yaml` (`x-kg-auth: portal`).

- [ ] **Step 4: Run tests and the spec gate**

Run: `python manage.py test api.test_onboarding api.test_openapi_routes -v 2` → PASS

- [ ] **Step 5: Commit**

```bash
git add KG_backend/api docs/openapi.yaml
git commit -m "feat(onboarding): the seat's checklist endpoint, with dismissal that survives a device change"
```

---

### Task 4: The discovery metric

**Files:**
- Modify: `KG_backend/api/support_metrics.py`
- Modify: `KG_backend/api/test_helpdesk.py` (the `SupportMetricsTests` class)
- Modify: `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md`

**Interfaces:**
- Consumes: `onboarding.discovery_counts` (Task 2).
- Produces: a `feature_discovery` key on `GET /api/admin/support/metrics/`.

- [ ] **Step 1: Write the failing tests**

```python
def test_feature_discovery_counts_entitled_and_discovered_seats(self): ...
def test_feature_discovery_and_the_seat_checklist_agree(self):
    """The property that justifies one shared function."""
    # same fixture: every item marked done in progress_for(seat) is counted
    # in discovery_counts([seat])['...']['discovered']
def test_feature_discovery_rate_is_none_when_nobody_is_entitled(self): ...
```

- [ ] **Step 2: Run them**

Run: `python manage.py test api.test_helpdesk.SupportMetricsTests -v 2` → FAIL (`KeyError: 'feature_discovery'`)

- [ ] **Step 3: Implement**

Call `discovery_counts` over active seats; add the block to the response. Add one row per item to `METRIC_DEFINITIONS.md` under a new "Feature discovery" table with the definition, source columns, hand-reproducible query and test name — the format the file already uses.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test api.test_helpdesk -v 2` → PASS

- [ ] **Step 5: Commit**

```bash
git add KG_backend/api audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md
git commit -m "feat(metrics): feature discovery, defined and shared with the seat's checklist"
```

---

### Task 5: Frontend state helpers

**Files:**
- Create: `kg_frontend/src/lib/onboarding.js`
- Create: `kg_frontend/src/lib/__tests__/onboarding.test.mjs`
- Modify: `kg_frontend/src/utils/api.jsx`

**Interfaces:**
- Produces:
  - `shouldShowStrip(payload) -> boolean` — false when dismissed, when `total === 0`, or when every item is done.
  - `nextItem(payload) -> item | null` — the first entitled, not-done item, for the collapsed line.
  - `progressLabel(done, total) -> string` — Persian digits, e.g. `۲ از ۵ قدم`.
  - `onboardingApi = { get(), dismiss() }` in `utils/api.jsx`, following `kbApi`.

- [ ] **Step 1: Write the failing tests**

```js
test('the strip hides when every entitled item is done', ...)
test('the strip hides for a seat with no entitled items at all', ...)
test('the strip hides when dismissed even with items outstanding', ...)
test('nextItem skips done items and returns null when none remain', ...)
test('progressLabel uses Persian digits', ...)
```

- [ ] **Step 2: Run them**

Run: `node --test src/lib/__tests__/onboarding.test.mjs` → FAIL (cannot find module)

- [ ] **Step 3: Implement both files**

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test src/lib/__tests__/*.mjs` → all pass

- [ ] **Step 5: Commit**

```bash
git add kg_frontend/src/lib kg_frontend/src/utils/api.jsx
git commit -m "feat(onboarding): frontend state rules for the discovery strip"
```

---

### Task 6: The strip

**Testing note for Tasks 6 and 7:** this repository has no component-test
harness — frontend tests are `node --test` over pure modules in `src/lib/`.
The decisions worth pinning (when the strip shows, what it says) are therefore
in Task 5 as pure functions, and Tasks 6–7 are verified in a real browser
against a seeded backend. That boundary is deliberate, not an omission; adding
a component-test framework is a separate decision.

**Files:**
- Create: `kg_frontend/src/components/OnboardingStrip.jsx`
- Modify: `kg_frontend/src/app/browse/page.jsx` (mount), `kg_frontend/src/app/globals.css`
- Modify: `docs/07-frontend.md` (§7.8), `docs/CHANGELOG.md`

**Interfaces:**
- Consumes: `onboardingApi`, `shouldShowStrip`, `nextItem`, `progressLabel` (Task 5).

- [ ] **Step 1: Implement the component**

Collapsed: one line — `progressLabel` plus `nextItem().title` as a link. Expanded on click: the entitled items with done state and `why`. A dismiss control calling `onboardingApi.dismiss()`. Never a modal, never over content, no layout shift when absent. Tokens only in CSS (`--surface`, `--text-dim`, …), following the `.sup-*` blocks added for the support desk.

- [ ] **Step 2: Verify in the browser**

Serve the production build against a seeded backend as recorded in `audit-evidence/16-improvement-programme/evidence/ui/README.md` (`KG_DEV_API_PROXY`; the dev server's HMR socket is refused by the CSP and the page never hydrates). Confirm: a seat with items sees the strip; completing an item by *doing* it ticks the box after reload; dismissal survives a reload and a second session.

- [ ] **Step 3: Lint and build**

Run: `npx eslint src --max-warnings $(cat ../ops/deploy/lint_max_warnings)` and `npm run build`
Note: `npm run build` rewrites `src/lib/shield.js` in place (the `prebuild` obfuscation step). `git checkout -- src/lib/shield.js` before committing.

- [ ] **Step 4: Commit**

```bash
git add kg_frontend/src docs/07-frontend.md docs/CHANGELOG.md
git commit -m "feat(onboarding): a quiet discovery strip on /browse"
```

---

### Task 7: The friction nudges

**Files:**
- Modify: `kg_frontend/src/guidance/hintRules.js`, `kg_frontend/src/guidance/GuidanceProvider.jsx`
- Modify: `docs/13-guidance-system.md`

**Interfaces:**
- Consumes: the onboarding payload (Task 5), the existing `signals` mechanism in `GuidanceProvider`.

- [ ] **Step 1: Implement the three rules**

Each fires on friction, not elapsed time, at most once per surface per session, dismissible for good (existing `storage.dismissHint`):
1. a search that returned nothing **and** `ask_assistant` not done **and** entitled → point at the assistant;
2. ≥ 25 section views in the session **and** `ask_assistant` not done **and** entitled → ask instead of hunting;
3. viewing a car whose grant includes `parts` **and** `open_parts` not done → one pointer.

Hint dismissals stay in `localStorage` — the spec's stated boundary: the strip's state is progress, a hint dismissal is per-surface noise control.

- [ ] **Step 2: Verify in the browser**

Trigger each rule against the seeded backend; confirm it appears once, that dismissing it keeps it away across a reload, and that an unentitled seat never sees rules 1–2.

- [ ] **Step 3: Lint, build, commit**

```bash
git add kg_frontend/src/guidance docs/13-guidance-system.md
git commit -m "feat(onboarding): nudges that fire on friction rather than on a timer"
```

---

### Task 8: Whole-branch verification

- [ ] **Step 1: Full backend suite**

Run: `python manage.py test api`
Compare the failure set against `audit-evidence/16-improvement-programme/evidence/baseline-failures-9d214ef.txt`; it must be identical.

- [ ] **Step 2: Coverage floor and frontend gates**

Run: backend coverage ≥ `ops/deploy/coverage_min`; `node --test src/lib/__tests__/*.mjs`; eslint under the ratchet; `npm run build`.

- [ ] **Step 3: Record the evidence**

Append to `audit-evidence/16-improvement-programme/evidence/ui/README.md`: the discovery figures before the change (assistant 9, parts 6, search 0) and the payload a seeded seat receives, so the next measurement has a baseline to move.

- [ ] **Step 4: Commit and push**

```bash
git add audit-evidence
git commit -m "docs(evidence): discovery baseline before the onboarding change"
git push
```
