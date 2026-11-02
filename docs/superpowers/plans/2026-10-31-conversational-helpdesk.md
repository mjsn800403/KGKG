# Conversational Help Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the request channel into a support desk people choose over the telephone: categorised, conversational, searchable, with per-viewer read state and knowledge-base deflection before a question becomes a ticket.

**Architecture:** Two optional model fields carry categorisation (`topic`, `car`), leaving `kind` to its existing permission job. One `TicketRead` model carries per-viewer read marks, and every unread badge in the product is *derived* from it — there are no notification rows, so none can go stale. The customer view and the admin inbox become the same two-pane shape over the same filter vocabulary.

**Tech Stack:** Django 5.2 (`KG_backend/api/`), PostgreSQL in production, Next.js 16 / React 19 (`kg_frontend/`), `node:test` for frontend units, Playwright for E2E.

**Spec:** `docs/superpowers/specs/2026-10-31-conversational-helpdesk-design.md`

## Global Constraints

- Every added NOT NULL column carries `db_default`. `ops/deploy/check_migrations.py` inspects every migration added since the live commit and refuses the deploy otherwise — it blocked production on 2026-10-31.
- `api/test_helpdesk.py` (90 tests) must pass **with no edits**. Editing one to make it green means something broke; fix the code.
- Persian is the UI language. New user-visible strings are Persian; code, comments and commits are English.
- Rates and averages return `None`, never `0`, when the denominator is zero (existing convention in `api/support_metrics.py`).
- `source` is never taken from a portal client; only the admin endpoint may set it.
- Internal notes are filtered out of the queryset for a customer, never hidden by the client.
- No attachments, no upload path, no `EMAIL_*` anything. Out of scope by the owner's decision.
- New backend file budget: `api/` modules stay under ~400 lines; split rather than grow.
- Frontend: `npx eslint src` must stay at or below the ratchet in `ops/deploy/lint_max_warnings`.

## Review Focus

Five inputs the spec implies but no acceptance criterion names. Each has a test added to the task that owns the code.

1. **A `car` that was deleted after the ticket was filed.** `SET_NULL` leaves `car_id` null; `_request_dict` must render the ticket, not raise. → Task 2.
2. **A `q` containing SQL wildcards or regex metacharacters** (`%`, `_`, `\`). Django parameterises, but `icontains` treats `%` and `_` literally only if not interpolated — a literal search for `100%` must return the row containing `100%` and not every row. → Task 4.
3. **A cursor from another company, or a forged/garbage cursor.** Must be a 400 or an empty page, never a leak and never a 500. → Task 4.
4. **Two tabs marking the same ticket read at once.** The unique constraint must not surface as a 500; the later write wins. → Task 3.
5. **A ticket with several hundred messages.** The conversation must not fetch and render all of them unbounded; the thread is capped and the cap is stated. → Task 4.

---

### Task 1: Topic and vehicle on a ticket

**Files:**
- Modify: `KG_backend/api/models.py` (`CompanyRequest`)
- Create: `KG_backend/api/migrations/0039_helpdesk_topic_car_read.py`
- Test: `KG_backend/api/test_helpdesk_desk.py` (new file; `api/test_helpdesk.py` stays untouched)

**Interfaces:**
- Consumes: nothing.
- Produces: `CompanyRequest.TOPIC_CHOICES` (list of `(value, label)`), `CompanyRequest.topic` (str, `''` when unset), `CompanyRequest.car` (FK `Car`, nullable). `VALID_TOPICS = {v for v, _ in TOPIC_CHOICES}` exported from `api/requests_api.py` in Task 2.

- [ ] **Step 1: Write the failing test**

```python
class TopicFieldTests(TestCase):
    def test_every_topic_choice_has_a_persian_label(self):
        for value, label in CompanyRequest.TOPIC_CHOICES:
            self.assertTrue(value.islower() and value.isascii(), value)
            self.assertNotEqual(value, label)

    def test_the_seven_agreed_topics_exist(self):
        self.assertEqual(
            [v for v, _ in CompanyRequest.TOPIC_CHOICES],
            ['missing_document', 'content_wrong', 'access_problem',
             'assistant_wrong', 'error_or_slow', 'billing', 'other'])

    def test_a_ticket_defaults_to_no_topic_and_no_car(self):
        co = Company.objects.create(name='T')
        r = CompanyRequest.objects.create(company=co, subject='s')
        self.assertEqual(r.topic, '')
        self.assertIsNone(r.car_id)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python manage.py test api.test_helpdesk_desk.TopicFieldTests -v2`
Expected: FAIL — `AttributeError: type object 'CompanyRequest' has no attribute 'TOPIC_CHOICES'`

- [ ] **Step 3: Add the fields**

In `CompanyRequest`: `TOPIC_CHOICES` with the seven values above and Persian labels; `topic = models.CharField(max_length=24, choices=TOPIC_CHOICES, blank=True, default='', db_default='', db_index=True)`; `car = models.ForeignKey('Car', null=True, blank=True, on_delete=models.SET_NULL, related_name='requests', db_index=True)`.

- [ ] **Step 4: Generate the migration and verify rollback safety**

Run: `python manage.py makemigrations api --name helpdesk_topic_car_read` then
`python ../ops/deploy/check_migrations.py $(git rev-parse origin/work)`
Expected: `ok` for the new migration. If it reports `NOT NULL without db_default`, fix the field, delete the migration and regenerate — never add a follow-up migration.

- [ ] **Step 5: Run the tests**

Run: `python manage.py test api.test_helpdesk_desk.TopicFieldTests api.test_helpdesk -v2`
Expected: PASS, and `test_helpdesk` still 90 tests passing.

- [ ] **Step 6: Commit**

```bash
git add KG_backend/api/models.py KG_backend/api/migrations/0039_*.py KG_backend/api/test_helpdesk_desk.py
git commit -m "feat(desk): a ticket can name its topic and its vehicle"
```

---

### Task 2: Accept and serialise topic and vehicle

**Files:**
- Modify: `KG_backend/api/requests_api.py` (`company_requests_view` POST, `_admin_create`, `_request_dict`)
- Test: `KG_backend/api/test_helpdesk_desk.py`

**Interfaces:**
- Consumes: Task 1's fields.
- Produces: `VALID_TOPICS` (set) in `api/requests_api.py`; `_request_dict` keys `topic`, `topic_label`, `car` (`{'id': int, 'name': str}` or `None`), where `name` is `f'{car.brand_name} {car.car_name} {car.year}'`.

- [ ] **Step 1: Write the failing tests** — acceptance criteria 1–6 and Review Focus 1

```python
class TopicAndCarApiTests(DeskBase):
    def test_a_ticket_round_trips_its_topic(self):
        t = self.create(topic='missing_document')
        self.assertEqual(t['topic'], 'missing_document')
        self.assertTrue(t['topic_label'])

    def test_an_unknown_topic_is_rejected(self):
        r = self.post(URL, {'kind': 'support', 'subject': 's', 'topic': 'nope'}, self.h_spec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(CompanyRequest.objects.count(), 0)

    def test_a_ticket_round_trips_a_car_the_filer_can_open(self):   # grant via UserCarAccess in setUp
        t = self.create(car_id=self.car.id)
        self.assertEqual(t['car']['id'], self.car.id)

    def test_a_car_the_filer_cannot_open_is_rejected_and_writes_nothing(self):
        r = self.post(URL, {'kind': 'support', 'subject': 's', 'car_id': self.forbidden_car.id}, self.h_spec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(CompanyRequest.objects.count(), 0)

    def test_a_ticket_without_either_is_uncategorised(self):
        t = self.create()
        self.assertEqual(t['topic'], '')
        self.assertIsNone(t['car'])

    def test_a_ticket_whose_car_was_deleted_still_serialises(self):
        t = self.create(car_id=self.car.id)
        self.car.delete()
        r = self.c.get(f'{URL}{t["id"]}/', **self.h_spec)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()['request']['car'])
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python manage.py test api.test_helpdesk_desk.TopicAndCarApiTests -v2`
Expected: FAIL — topic ignored, `KeyError: 'topic'`.

- [ ] **Step 3: Accept and validate**

In the POST branch of `company_requests_view` and in `_admin_create`: read `topic` (reject with 400 and the Persian message `نوع مشکل نامعتبر است.` when not in `VALID_TOPICS` and not empty); read `car_id` through `_int_or_none`, resolve the `Car`, and reject with 400 (`خودروی انتخاب‌شده در دسترس شما نیست.`) unless `access.user_can_open_car(user, car)`. The admin endpoint skips the access check — the desk may file about any vehicle — but still 400s an unknown id.

- [ ] **Step 4: Serialise**

Add `topic`, `topic_label`, `car` to `_request_dict` as in Interfaces. `select_related('car')` wherever requests are listed, so the list does not issue a query per row.

- [ ] **Step 5: Run the tests**

Run: `python manage.py test api.test_helpdesk_desk api.test_helpdesk -v2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(desk): accept, validate and serialise a ticket's topic and vehicle"
```

---

### Task 3: Per-viewer read state

**Files:**
- Modify: `KG_backend/api/models.py` (`TicketRead`), `KG_backend/api/migrations/0039_*.py` (same migration), `KG_backend/api/requests_api.py`
- Create: `KG_backend/api/reads.py`
- Test: `KG_backend/api/test_helpdesk_desk.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, in `api/reads.py`:
  - `mark_read(request_obj, *, user=None, admin=None) -> None`
  - `unread_count(request_obj, *, user=None, admin=None) -> int`
  - `unread_counts(request_ids, *, user=None, admin=None) -> dict[int, int]` — one query for a list page
  - `last_message(request_obj) -> dict | None` with keys `at` (ISO str) and `by` (`'customer' | 'platform'`)

- [ ] **Step 1: Write the failing tests** — acceptance criteria 7–15 and Review Focus 4

```python
class ReadStateTests(DeskBase):
    def test_an_unopened_ticket_counts_every_message_the_viewer_did_not_write(self): ...
    def test_marking_read_zeroes_the_count(self): ...
    def test_a_message_after_reading_is_unread_again(self): ...
    def test_your_own_message_is_never_unread(self): ...
    def test_an_internal_note_is_unread_for_an_admin_and_invisible_to_the_customer(self): ...
    def test_two_seats_in_one_company_have_independent_read_state(self): ...
    def test_an_admin_read_mark_does_not_touch_a_seat(self): ...
    def test_a_read_ticket_can_still_be_awaiting_our_reply(self): ...
    def test_a_get_does_not_mark_anything_read(self): ...
    def test_marking_read_twice_concurrently_does_not_error(self):
        # two mark_read calls for the same (request, user); the second updates
        for _ in range(2):
            reads.mark_read(r, user=self.spec)
        self.assertEqual(TicketRead.objects.filter(request=r, user=self.spec).count(), 1)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python manage.py test api.test_helpdesk_desk.ReadStateTests -v2`
Expected: FAIL — `ModuleNotFoundError: api.reads`.

- [ ] **Step 3: Add the model**

`TicketRead` in `api/models.py` exactly as the spec's §2 block, with `UniqueConstraint(fields=['request', 'user'])`, `UniqueConstraint(fields=['request', 'admin'])` and `CheckConstraint` that exactly one of `user_id`/`admin_id` is non-null. Add it to the **same** migration 0039 (regenerate it; do not stack a second migration).

- [ ] **Step 4: Implement `api/reads.py`**

`mark_read` uses `update_or_create` with `last_read_at=timezone.now()` — that is what makes Review Focus 4 a non-event. `unread_count` filters `request_obj.messages` on `created_at__gt=last_read_at`, excludes the viewer's own authorship (`author_user_id` for a seat, `author_admin_id` for an admin), and excludes `internal=True` for a seat. No mark means every message the viewer did not write.

- [ ] **Step 5: Wire the `read` action**

In `company_request_detail_view` and `admin_company_request_detail_view`, handle `{"action": "read"}` by calling `mark_read` and returning the request dict. Serialise `unread_count`, `last_message_at` and `last_message_by` in `_request_dict`, taking the viewer from a new keyword argument `viewer_user=` / `viewer_admin=`; when neither is given, `unread_count` is `None` (an event payload has no viewer).

- [ ] **Step 6: Run the tests**

Run: `python manage.py test api.test_helpdesk_desk api.test_helpdesk -v2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git commit -am "feat(desk): per-viewer read marks, with every badge derived from them"
```

---

### Task 4: Search, filters and cursor pagination

**Files:**
- Modify: `KG_backend/api/requests_api.py` (`company_requests_view` GET, `admin_company_requests_view`)
- Create: `KG_backend/api/listing.py`
- Test: `KG_backend/api/test_helpdesk_desk.py`

**Interfaces:**
- Consumes: Task 1's fields, Task 3's `unread_counts`.
- Produces, in `api/listing.py`:
  - `encode_cursor(created_at, row_id) -> str` and `decode_cursor(raw) -> tuple[datetime, int] | None` (returns `None` for anything malformed)
  - `apply_cursor(qs, cursor) -> QuerySet`
  - `LIMIT_DEFAULT = 30`, `LIMIT_MAX = 100`, `clamp_limit(raw) -> int`
  - Both list endpoints return `{'requests': [...], 'next_cursor': str | None, 'meta': {...}}`, where `meta` carries `open_count` (unchanged, for anything that still wants it) and **`unread_count`** — the viewer's total unread across every visible ticket, which is what the sidebar badge reads in Task 8.

- [ ] **Step 1: Write the failing tests** — acceptance criteria 16–23 and Review Focus 2, 3; cap the thread per Review Focus 5

```python
class SearchAndPaginationTests(DeskBase):
    def test_q_matches_a_word_in_the_subject(self): ...
    def test_q_matches_a_word_in_a_message_body_and_returns_the_ticket_once(self): ...
    def test_q_never_crosses_a_company_boundary(self): ...
    def test_topic_kind_status_and_car_filter_and_compose(self): ...
    def test_unread_returns_only_the_viewers_unread_tickets(self): ...
    def test_a_page_returns_a_cursor_that_yields_the_next_rows_exactly_once(self): ...
    def test_a_row_inserted_between_pages_neither_duplicates_nor_hides_a_row(self): ...
    def test_an_oversized_limit_is_clamped_not_an_error(self): ...
    def test_a_percent_sign_in_q_is_matched_literally(self):
        self.create(subject='coverage is 100% wrong')
        self.create(subject='unrelated')
        rows = self.c.get(f'{URL}?q=100%25', **self.h_spec).json()['requests']
        self.assertEqual(len(rows), 1)
    def test_a_garbage_cursor_is_a_400_not_a_500(self): ...
    def test_a_thread_is_capped_at_the_documented_maximum(self): ...
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python manage.py test api.test_helpdesk_desk.SearchAndPaginationTests -v2`
Expected: FAIL — `ModuleNotFoundError: api.listing`.

- [ ] **Step 3: Implement `api/listing.py`**

Cursor is `base64(f'{created_at.isoformat()}|{row_id}')`; `decode_cursor` returns `None` on any decode, split or parse failure — it is never trusted, and the endpoint answers 400. `apply_cursor` filters `Q(created_at__lt=ts) | Q(created_at=ts, id__lt=row_id)` against the `('-created_at', '-id')` ordering, which is what makes a row inserted between pages harmless.

- [ ] **Step 4: Wire both endpoints**

Shared filter vocabulary: `q`, `status`, `kind`, `topic`, `car_id`, `unread`; admin adds `source`, `company_id`, `awaiting`. `q` is `Q(subject__icontains=q) | Q(messages__body__icontains=q)` with `.distinct()`. Cap the serialised thread at `MAX_THREAD = 200` newest messages and report `messages_truncated: bool` — Review Focus 5.

- [ ] **Step 5: Run the tests**

Run: `python manage.py test api.test_helpdesk_desk api.test_helpdesk -v2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(desk): one filter vocabulary and cursor pagination on both sides"
```

---

### Task 5: Knowledge-base deflection at compose time

**Files:**
- Modify: `KG_backend/api/models.py` (`KbSearchLog`), `KG_backend/api/migrations/0039_*.py`, `KG_backend/api/knowledge.py`
- Test: `KG_backend/api/test_knowledge.py` (append a class; existing tests untouched)

**Interfaces:**
- Consumes: nothing.
- Produces: `KbSearchLog.context` (`''` or `'compose'`), `KbSearchLog.deflected_article` (FK, nullable); `POST /api/kb/<slug>/deflect/` body `{"query": str}` → `{'ok': True}`.

- [ ] **Step 1: Write the failing tests** — acceptance criteria 24–27

```python
class DeflectionTests(TestCase):
    def test_a_compose_search_is_logged_with_its_context(self): ...
    def test_this_answered_it_records_the_article_and_creates_no_ticket(self): ...
    def test_abandoning_the_form_records_no_deflection(self): ...
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python manage.py test api.test_knowledge.DeflectionTests -v2`
Expected: FAIL — unexpected keyword `context`.

- [ ] **Step 3: Add the fields and the endpoint**

`context = models.CharField(max_length=16, blank=True, default='', db_default='')` and `deflected_article = models.ForeignKey('KnowledgeArticle', null=True, blank=True, on_delete=models.SET_NULL, related_name='deflections')`, both in migration 0039. `kb_list_view` reads `?context=` and stores it. `deflect_view` finds the viewer's most recent `KbSearchLog` for that normalised query within the last hour and sets `deflected_article`; with no such row it creates one with `results=1`.

- [ ] **Step 4: Register the route**

`path('api/kb/<slug:slug>/deflect/', knowledge.deflect_view, name='kb_deflect')` in `api/urls.py`, and add it to `docs/openapi.yaml` — the OpenAPI gate fails CI otherwise.

- [ ] **Step 5: Run the tests**

Run: `python manage.py test api.test_knowledge api.test_helpdesk -v2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(kb): record a deflection only when someone says the article answered it"
```

---

### Task 6: Metrics by topic, vehicle and deflection

**Files:**
- Modify: `KG_backend/api/support_metrics.py`
- Test: `KG_backend/api/test_helpdesk_desk.py`

**Interfaces:**
- Consumes: Tasks 1, 5.
- Produces: response keys `by_topic` (`{topic: count}` with `'uncategorised'` for `''`), `by_vehicle` (list of `{car_id, name, count}`, newest-first by count, top 10), `deflections` (`{suggested, deflected, rate}`), `search` (`{compose_searches, zero_result_share}`).

- [ ] **Step 1: Write the failing tests** — acceptance criteria 28, 29, 27

```python
class DeskMetricsTests(DeskBase):
    def test_by_topic_counts_uncategorised_separately(self): ...
    def test_by_vehicle_counts_only_tickets_with_a_car(self): ...
    def test_the_deflection_rate_is_none_when_nothing_was_suggested(self): ...
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python manage.py test api.test_helpdesk_desk.DeskMetricsTests -v2`
Expected: FAIL — `KeyError: 'by_topic'`.

- [ ] **Step 3: Implement**, following the module's existing shape: aggregate with `values().annotate(Count)`, and return `None` for any rate whose denominator is zero.

- [ ] **Step 4: Run the tests**

Run: `python manage.py test api.test_helpdesk_desk api.test_helpdesk -v2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(metrics): tickets by topic and vehicle, and whether the KB deflected anything"
```

---

### Task 7: Desk helpers, as pure functions

**Files:**
- Modify: `kg_frontend/src/lib/support.js`
- Create: `kg_frontend/src/lib/__tests__/desk.test.mjs`

**Interfaces:**
- Consumes: the API shapes from Tasks 2–4.
- Produces, exported from `lib/support.js`:
  - `topicLabel(topic) -> string` (`'دسته‌بندی‌نشده'` for `''`)
  - `groupByDay(messages) -> [{ day: string, messages: [] }]`
  - `firstUnreadIndex(messages, unreadCount) -> number` (`-1` when nothing unread)
  - `activityState(req) -> 'unread' | 'awaiting_us' | 'awaiting_them' | 'closed'`
  - `rowSubtitle(req) -> string`

- [ ] **Step 1: Write the failing tests**

```js
test('firstUnreadIndex points at the first message the viewer has not seen', ...)
test('firstUnreadIndex is -1 when nothing is unread', ...)
test('groupByDay keeps order and splits on the day boundary', ...)
test('activityState prefers unread over awaiting', ...)
test('activityState of a closed ticket is closed even with unread messages', ...)
test('topicLabel names the uncategorised case', ...)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `node --test kg_frontend/src/lib/__tests__/desk.test.mjs`
Expected: FAIL — no such export.

- [ ] **Step 3: Implement the five functions.** Pure, no React, no fetch — that is what makes them testable here.

- [ ] **Step 4: Run the tests**

Run: `node --test kg_frontend/src/lib/__tests__/*.mjs`
Expected: PASS, 219+ tests.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(desk): pure helpers for grouping, unread position and activity state"
```

---

> **A note on Tasks 8 and 9.** These two do not open with a failing test, and
> that is a deliberate, stated exception rather than an oversight. This repo
> has no component test harness — the frontend suite is `node:test` over plain
> modules, with no jsdom and no React renderer — so there is no way to write a
> failing test for a React component here. The testable logic was therefore
> pulled *out* of the components into Task 7's pure functions, which are
> test-first, and the rendered behaviour is pinned by Task 10's E2E. If a unit
> of logic in Tasks 8 or 9 turns out to deserve a test, move it into
> `lib/support.js` and give it one; do not add a renderer as a side quest.

### Task 8: The customer's conversation

**Files:**
- Create: `kg_frontend/src/components/desk/DeskLayout.jsx`, `TicketList.jsx`, `Conversation.jsx`, `ComposeForm.jsx`
- Modify: `kg_frontend/src/components/RequestsView.jsx` (becomes the page shell), `kg_frontend/src/utils/api.jsx`, `kg_frontend/src/app/globals.css`
- Test: covered by Task 7's units and Task 10's E2E

**Interfaces:**
- Consumes: Task 7's helpers; `teamApi.requests(params)` extended to take an object of the Task 4 vocabulary; new `teamApi.markRead(id)`, `teamApi.kbSuggest(q, carId)`, `teamApi.kbDeflect(slug, q)`.
- Produces: `DeskLayout` owning selection and filters; `TicketList` presentational; `Conversation` owning the thread, the composer and the read mark.

- [ ] **Step 1: Extend the API client** — `requests(params)` serialises the filter vocabulary and returns `{requests, next_cursor, meta}`; `markRead(id)` posts `{action:'read'}`.

- [ ] **Step 2: Build `TicketList`** — row per spec §4: initials, subject, topic chip, vehicle chip, status pill, relative last-activity time, unread dot with count. Sorted by `last_message_at`, falling back to `created_at`.

- [ ] **Step 3: Build `Conversation`** — sticky header (subject, status, SLA, assignee, topic, vehicle), bubbles grouped by consecutive author via `groupByDay`, a "پیام‌های تازه" divider at `firstUnreadIndex`, scroll to that divider on open rather than to the bottom, `aria-live="polite"` on the message region. Calls `markRead` when the ticket renders. Reuses `TicketThread`'s bubble markup, `CsatPrompt` and the SLA row unchanged.

- [ ] **Step 4: Build `ComposeForm`** — kind, topic, vehicle, subject, body, priority. Debounced 400ms on a subject of ≥3 characters, queries `kbSuggest`, shows up to three articles, each with «همین پاسخ را می‌خواستم» which calls `kbDeflect` and closes the form.

- [ ] **Step 5: Wire `DeskLayout` into `RequestsView`** — two panes above 860px, stacked with a back control below it. Keep the existing cancel, reopen and rating paths calling the same `teamApi` methods.

- [ ] **Step 6: The toast stops duplicating** — fire it only when the arriving message's ticket is not the selected one (acceptance criterion 36).

- [ ] **Step 7: Sidebar badge follows unread** — `Sidebar.jsx` reads `meta.unread_count` instead of `meta.open_count` (criterion 35).

- [ ] **Step 8: Verify**

Run: `npx eslint src --max-warnings "$(cat ../ops/deploy/lint_max_warnings)"` then `npm run build`
Expected: both clean. `git checkout -- src/lib/shield.js` after the build — `prebuild` rewrites that tracked file.

- [ ] **Step 9: Commit**

```bash
git commit -am "feat(desk): the customer side is a conversation, not an accordion"
```

---

### Task 9: The admin inbox, same shape

**Files:**
- Modify: `kg_frontend/src/components/RequestsInbox.jsx`, `kg_frontend/src/utils/api.jsx`
- Reuse: `components/desk/*` from Task 8

**Interfaces:**
- Consumes: Task 8's components; `adminApi.companyRequests(params)` extended to the same vocabulary; new `adminApi.markRead(id)`.

- [ ] **Step 1: Extend `adminApi`** with the filter vocabulary and `markRead`.
- [ ] **Step 2: Render the inbox through `DeskLayout`**, keeping the admin-only controls — assignee, escalate, internal note, status, log-a-call — in the conversation header and composer.
- [ ] **Step 3: Add the filters** — the existing waiting-on-us and breached buttons, plus topic, vehicle and a search box.
- [ ] **Step 4: Verify** — eslint and build as Task 8 Step 8.
- [ ] **Step 5: Commit**

```bash
git commit -am "feat(desk): the admin inbox is the same conversation, with the desk's own controls"
```

---

### Task 10: Prove it end to end

**Files:**
- Create: `qa/e2e/tests/helpdesk.spec.js`
- Modify: `docs/openapi.yaml` (any route not already added), `audit-evidence/16-improvement-programme/` (metric definitions for the new numbers)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the E2E** — acceptance criteria 31–37: file a ticket with topic and vehicle, see a suggestion, send, reply as the platform, confirm the unread marker clears on open, find it later by search; at 360px confirm no horizontal scroll and a reachable composer.
- [ ] **Step 2: Run the whole backend suite and diff against the baseline**

Run: `python manage.py test api 2>&1 | tee /tmp/after.log` then compare the `FAIL:`/`ERROR:` set to the branch point.
Expected: **no new failures**. The 20 known environment-only failures (numpy/torch for `api.rag.*`, SSE, WeasyPrint) are the whole set.

- [ ] **Step 3: Confirm the preserved behaviour criterion**

Run: `git diff --stat origin/work -- KG_backend/api/test_helpdesk.py`
Expected: **empty**. Criterion 30 is that this file was never edited.

- [ ] **Step 4: Update the programme evidence** — metric definitions for `by_topic`, `by_vehicle`, `deflections`, `search`, stating what each counts and what it does not. Remember `docs/` is `*.md`-ignored: `git add -f`.
- [ ] **Step 5: Commit, open the PR against `work`** referencing the issue (the traceability gate refuses a PR with no issue reference).
