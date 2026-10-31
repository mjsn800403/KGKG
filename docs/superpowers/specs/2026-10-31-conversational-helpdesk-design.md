# A conversational help desk

**Date:** 2026-10-31
**Status:** approved in principle 2026-10-31; acceptance criteria below are the contract
**Owners:** mjsalimin, Ali Sartipi
**Priority:** first of four agreed pieces (this, then guidance tours, then reply SMS, then the notification-state fixes)

## Why

The 2026-10-30 evaluation found customer feedback arriving by telephone. The
root cause was a bug — `@require_manager` on the request endpoints meant a
specialist seat got a 403, so the telephone was the only channel open to most
of the company — and that is fixed and live as of `41aa0ea`.

Fixing the gate did not make the channel good. What exists now is a form and a
list: every ticket is an accordion row with its conversation hidden inside, the
only category is the request *type*, there is no search, and the knowledge base
is never offered before a question becomes a ticket. People will go back to the
telephone if the written channel is worse than talking.

This piece makes the written channel the better option.

## Scope

In: categorisation, a conversation-first interface on both sides, per-viewer
read state, search and filters, knowledge-base deflection at compose time, and
the metrics for all of it.

Out, by explicit decision: **attachments** (no upload path, no model, no
endpoint) and **email** (no `EMAIL_*` configuration exists; SMS on reply is the
third agreed piece and has its own spec).

## What must not break

Every one of these has tests today and must still pass unchanged:

* `MANAGER_ONLY_KINDS` — a specialist may file support and other; seats,
  vehicle access, AI assistant and documents stay manager-only.
* Visibility — a specialist sees only their own tickets; a manager sees the
  company's; another company sees none (404, writing nothing).
* SLA — policy per priority, response and resolution clocks, breach state,
  `admin_note` counting as a first response, reopen restarting the resolution
  clock.
* Status lifecycle, cancellation, reopen-on-customer-message, CSAT after
  closure, assignee, escalation, `source`, and the `awaiting_reply` signal
  shipped today.
* Internal notes are never serialised to a customer.

## Design

### 1. Categorisation

`kind` keeps its current job and its current values. It is not a taxonomy: it
decides who may file what, and overloading it with problem types would tie
permissions to vocabulary.

Two new optional fields carry the categorisation:

* `topic` — `CharField(max_length=24, blank=True, default='', db_default='',
  db_index=True)` with choices: `missing_document`, `content_wrong`,
  `access_problem`, `assistant_wrong`, `error_or_slow`, `billing`, `other`.
  Offered for `kind` in {`support`, `other`}; accepted but not required for
  the commercial kinds.
* `car` — `ForeignKey(Car, null=True, blank=True, on_delete=models.SET_NULL,
  related_name='requests', db_index=True)`. The vehicle the problem is about.

Both optional. Existing rows keep `topic=''` and `car=None` and render as
"uncategorised" rather than being back-filled with a guess.

A `car` the filer cannot access is rejected with 400 — the field must not
become a way to probe the catalogue. Reuse the existing access check
(`UserCarAccess` / `access` helpers), not a new one.

### 2. Per-viewer read state

One model, `TicketRead`:

```
request       FK CompanyRequest, on_delete=CASCADE, related_name='reads'
user          FK PortalUser,    null=True, on_delete=CASCADE
admin         FK PlatformAdmin, null=True, on_delete=CASCADE
last_read_at  DateTimeField
```

with `UniqueConstraint(fields=['request', 'user'], name=…)` and the same for
`admin`, plus a `CheckConstraint` that exactly one of `user` / `admin` is set.

`unread_count(request, viewer)` counts messages where `created_at >
last_read_at`, excluding the viewer's own messages, and excluding internal
notes for a customer. With no read mark, every message the viewer did not
write counts — so a ticket nobody has opened reads as fully unread, which is
true.

**Every badge in this feature is derived from these marks.** No notification
rows, no counters to decrement, nothing that can be left behind. A badge
cannot go stale because there is nothing stored to go stale: opening the
conversation writes `last_read_at`, and the count recomputes to zero. This is
the whole of requirement 5.

Marking read is an explicit action, `POST …/<id>/ {"action": "read"}` on both
the customer and admin detail endpoints, sent by the client when the
conversation pane shows the ticket. A GET never mutates.

### 3. Serialised state

`_request_dict` gains, per viewer:

* `unread_count` — integer, as above.
* `last_message_at` — ISO of the newest visible message, or `null`.
* `last_message_by` — `"customer" | "platform" | null`.
* `awaiting_reply` — unchanged; the platform owes an answer.
* `topic`, `topic_label`, `car` (`{id, name}` or `null`).

The three states the interface distinguishes, and they are distinct:

| state | means | shown as |
|---|---|---|
| unread | messages the viewer has not seen | dot + count on the row, "new messages" divider in the conversation |
| awaiting us | open, and the last public word was the customer's | the glowing tile and the inbox's first filter (admin side) |
| awaiting them | open, and the last public word was ours | a quiet marker; never a nag |

A ticket can be read and still awaiting us — somebody looked and did not
answer. That distinction is the point.

### 4. The interface

Two panes: ticket list, and the selected ticket's conversation with the
composer pinned at its foot. Not an accordion.

**Ticket list row**: author initials, subject, topic chip, vehicle chip,
status pill, relative time of the last message, unread dot with count.
Sorted by last activity, not creation — which needs a denormalised
`last_activity_at` column, because the cursor in §5 paginates over the
ordering column and an ordering computed per row in Python cannot be
paginated. Set on insert, moved by every public message, and never by an
internal note.

**Conversation**: sticky header with subject, status, SLA state, assignee,
topic and vehicle. Messages as bubbles grouped by consecutive author, with day
dividers, and a **"new messages" divider at the first unread** — on open the
pane scrolls to that divider rather than to the bottom, so you resume where
you stopped. An ARIA live region announces an arriving message.

**Composer**: Enter sends, Shift+Enter is a newline, send is optimistic and
rolls back visibly on failure. Closed ticket: the composer states that sending
reopens it, which is existing behaviour.

**Responsive**: below 860px the panes stack — list, then conversation, with a
back control; the composer sits above the keyboard; touch targets ≥44px; no
horizontal scroll at 360px. Keyboard: ↑/↓ moves through the list, Enter opens,
Esc returns to the list on narrow screens.

**States**: loading, empty ("no tickets yet" with the compose action), error
with a retry, and "no results" for a filtered view that matches nothing —
distinct from empty, because telling someone they have no tickets when they
have forty and a bad filter is how a tool loses trust.

`RequestsView.jsx` (341 lines doing list, detail, compose and toast) splits
into `DeskLayout`, `TicketList` and `Conversation`. `TicketThread`,
`CsatPrompt` and the SLA row are reused as they are — that reuse is what keeps
cancel, reopen and rating from regressing.

The admin inbox gets the same two-pane treatment and the same filters, so the
two sides are one mental model.

**No duplicate signal.** Two things could announce the same message: the
sidebar badge and the toast.

* The sidebar badge becomes unread-driven rather than open-driven. Today it
  shows `meta.open_count`, which cannot clear while a ticket is legitimately
  open, so it reads as a notification that never goes away. It shows unread
  instead; the open count stays in `meta` for anything that wants it.
* The toast fires only for a ticket that is **not** the one on screen. If the
  conversation is open, the message simply arrives in the thread and is marked
  read — announcing it as well would be the duplicate requirement 5 forbids.

### 5. Search and filters

Query parameters on both list endpoints: `q` (subject and message bodies),
`status`, `kind`, `topic`, `car_id`, `unread` (viewer's own unread only), and
on the admin side the existing `source` and `company_id` plus `awaiting`.

Pagination: cursor on `(created_at, id)` descending, `limit` default 30,
maximum 100, with `next_cursor` in the response. The current endpoint caps at
300 rows with no way past it, which is a silent data loss.

`q` uses `icontains` over subject and `messages__body`, distinct. Deliberately
**no trigram or FTS index**: at nine companies and five tickets lifetime an
index would be ornament, and the honest note belongs here rather than a claim
that this scales. Revisit when a company passes a few thousand tickets.

### 6. The knowledge base before the ticket

While composing, debounced at 400ms on a subject of three characters or more,
query `/api/kb/?q=` (filtered by `car` when chosen) and show up to three
articles above the composer.

Each has an explicit **"this answered it"**. That closes the form and records a
deflection. Explicit, because "opened an article and did not file" is an
inference, and inventing a deflection metric from it is exactly the kind of
evidence the evaluation told us not to manufacture.

`KbSearchLog` gains `context` (`CharField(max_length=16, blank=True,
default='', db_default='')` — `'compose'` here) and `deflected_article`
(`FK KnowledgeArticle, null=True, on_delete=SET_NULL`). No new model.

### 7. Metrics

`/api/admin/support/metrics/` gains:

* `by_topic` — counts per topic, `uncategorised` for `''`.
* `by_vehicle` — top vehicles by ticket count.
* `deflections` — `{suggested, deflected, rate}`; `rate` is `None` when
  `suggested` is 0, matching the existing convention.
* `search` — compose-context KB searches and their zero-result share.

### 8. Migration

One migration: `topic`, `car`, `TicketRead`, and the two `KbSearchLog` fields.
Every added NOT NULL column carries `db_default`, or
`ops/deploy/check_migrations.py` refuses the deploy and rollback is unsafe —
that gate blocked production this morning and the rule is not optional.

## Acceptance criteria

Each is a test.

**Categorisation**
1. A support ticket may be filed with a `topic`, and it round-trips.
2. An unknown `topic` is a 400.
3. A ticket may be filed with a `car` the filer can access; it round-trips.
4. A `car` the filer cannot access is a 400 and nothing is written.
5. A ticket filed without either is accepted and reads as uncategorised.
6. Existing rows (no topic, no car) serialise without error.

**Read state**
7. A ticket nobody opened reports `unread_count` equal to the number of
   messages the viewer did not write.
8. `{"action":"read"}` sets the mark; `unread_count` is then 0.
9. A new message after reading makes `unread_count` 1.
10. A viewer's own message never counts as unread.
11. An internal note never counts toward a customer's `unread_count`, and does
    count for an admin.
12. Two seats in one company have independent read state.
13. An admin's read state is independent of every seat's.
14. A ticket can be `unread_count == 0` and `awaiting_reply == true`
    simultaneously.
15. A GET of a ticket does not change its read state.

**Search, filters, pagination**
16. `q` matches a word in the subject.
17. `q` matches a word in a message body, and returns the ticket once.
18. `q` never returns another company's ticket.
19. `topic`, `kind`, `status`, `car_id` each filter, and they compose.
20. `unread=1` returns only the viewer's unread tickets.
21. The first page returns `limit` rows and a `next_cursor`; the cursor
    returns the next rows with no duplicate and no gap.
22. A ticket inserted between two page fetches does not duplicate or hide a
    row already returned.
23. `limit` above the maximum is clamped, not an error.

**Deflection**
24. A compose-context search writes a `KbSearchLog` with `context='compose'`.
25. "This answered it" records `deflected_article` and creates no ticket.
26. Abandoning the form records no deflection.
27. Metrics report `deflections.rate` as `None` when nothing was suggested.

**Metrics**
28. `by_topic` counts uncategorised separately.
29. `by_vehicle` counts only tickets with a car.

**Preserved behaviour** (existing tests, unchanged)
30. The whole of `api/test_helpdesk.py` passes untouched — 90 tests covering
    permissions, visibility, thread, SLA, assignment, reopen, CSAT, source,
    the filer events and `awaiting_reply`.

**Interface**
31. The conversation opens scrolled to the first unread, not the bottom.
32. At 360px there is no horizontal scroll and the composer is reachable.
33. The list, the conversation and the composer are keyboard operable.
34. A filtered view with no matches says so, distinctly from having no
    tickets.
35. The sidebar badge shows unread, not open: a ticket that is open and read
    contributes nothing to it.
36. A message arriving for the ticket already on screen raises no toast; one
    arriving for another ticket does.
37. E2E: file a ticket with a topic and a vehicle, see a suggestion, send it,
    reply as the platform, see the unread marker clear on open, find the
    ticket later by search.

## Risks

* **The rewrite could regress SLA, cancel, reopen or CSAT.** Mitigated by
  reusing those components rather than reimplementing them, and by criterion
  30 — the existing suite must pass with no edits.
* **`icontains` is a sequential scan.** Stated, accepted at this data volume,
  with the revisit condition written down.
* **Read marks grow one row per (ticket, viewer).** At this volume, trivial;
  `CASCADE` on the ticket keeps it bounded.
* **Two-pane on mobile can trap a user in the conversation.** The back control
  and Esc are acceptance criteria, not polish.
