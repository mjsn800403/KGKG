# Metric definitions (the BI semantic layer)

The evaluation's BI finding is not that the platform has no data — it has a
great deal — but that no number carried a definition, so no number could be
audited. This file is the fix: **one entry per metric, naming its calculation,
its source column and how to reproduce it by hand.** A dashboard may show only
metrics defined here. A metric whose definition is not written here does not
exist.

Rules that apply to every entry:

1. **An average of nothing is `null`, not `0`.** Zero is a measurement; absence
   is not. Every rate and average below returns `null` when its denominator is
   empty, and the API does the same.
2. **Windows are closed-open on `created_at`**: `created_at >= now - days`.
   `days` is clamped to 1–365.
3. **Backlog figures are current state, not windowed.** "What is open" is a
   fact about now; filtering it by a window would hide old tickets, which are
   exactly the ones that matter.
4. **Clock arithmetic is calendar time**, not business hours (see `api/sla.py`
   for why, stated rather than hidden).
5. Each entry names the test that pins it. A definition without a test is a
   claim.

Implementation: `KG_backend/api/support_metrics.py`,
`KG_backend/api/sla.py`, `KG_backend/api/knowledge.py` (`metrics`),
`KG_backend/api/feedback.py` (`summary`). Served by
`GET /api/admin/support/metrics/?days=30` (admin only).

---

## Support desk

| Key | Definition | Source | Reproduce by hand | Test |
|---|---|---|---|---|
| `totals.created` | Tickets whose `created_at` is in the window. | `CompanyRequest.created_at` | `CompanyRequest.objects.filter(created_at__gte=since).count()` | `test_counts_match_the_rows` |
| `totals.open` | Of those, `status` in `('pending','in_progress')`. | `CompanyRequest.status` | add `.filter(status__in=CompanyRequest.OPEN_STATUSES)` | `test_counts_match_the_rows` |
| `totals.closed` | Of those, `status` in `('completed','rejected')`. A rejected ticket is closed: it is decided, and excluding it would flatter the resolution figures. | `CompanyRequest.status` | add `.filter(status__in=CompanyRequest.CLOSED_STATUSES)` | `test_counts_match_the_rows` |
| `totals.reopened` | Tickets in the window with `reopen_count > 0`. Counts tickets, not reopenings. | `CompanyRequest.reopen_count` | `.filter(reopen_count__gt=0).count()` | `test_a_customer_message_on_a_closed_ticket_reopens_it` |
| `totals.escalated` | Tickets in the window with `escalated_at` set. | `CompanyRequest.escalated_at` | `.filter(escalated_at__isnull=False).count()` | `test_escalation_stamps_the_time_raises_priority_and_emits` |
| `first_response.measured` | Tickets in the window with `first_response_at` set. The companion `unmeasured` is `created − measured`, published so the average cannot be read as covering everything. | `CompanyRequest.first_response_at` | `.filter(first_response_at__isnull=False).count()` | `test_first_response_minutes_are_measured_from_the_stamps` |
| `first_response.avg_minutes` | Mean of `(first_response_at − created_at)` in minutes over the measured set. `first_response_at` is stamped by the **first public** admin message; an internal note is not a response. | both stamps | `(fr - created).total_seconds()/60`, averaged | `test_first_response_minutes_are_measured_from_the_stamps`, `test_an_internal_note_is_not_a_first_response` |
| `first_response.p90_minutes` | 90th percentile by **nearest rank**: sort ascending, take index `ceil(0.9·n) − 1`. Stated because "p90" is ambiguous between interpolation methods. | as above | sort and index | `test_first_response_minutes_are_measured_from_the_stamps` |
| `resolution.avg_hours` | Mean of `(resolved_at − created_at)` in hours. For a reopened ticket `resolved_at` is the **latest** closure, so the figure covers the whole life of the problem rather than the first attempt. | `CompanyRequest.resolved_at` | `(resolved - created).total_seconds()/3600`, averaged | `test_resolution_hours_are_measured_from_the_stamps` |
| `sla.policy_hours` | The targets themselves, echoed so a reader never has to guess which policy produced a compliance figure. high 2 h/8 h · normal 8 h/48 h · low 24 h/120 h. | `api/sla.POLICY` | read the module | `test_every_priority_has_a_policy` |
| `sla.response.{met,breached,pending,untracked}` | Per ticket in the window, `sla.state(sla_response_due_at, first_response_at, now)`: **met** responded at or before due; **breached** responded late, or unanswered and past due; **pending** unanswered and not yet due; **untracked** no due date (rows created before this release). | `sla_response_due_at`, `first_response_at` | apply the same three-line rule | `test_response_state_is_pending_met_or_breached`, `test_sla_compliance_counts_met_against_decided` |
| `sla.response.compliance` | `met / (met + breached)`, rounded to 4 dp. **Pending and untracked are excluded from the denominator** — a ticket whose target has not expired is not a success yet, and counting it as one is the classic way to inflate an SLA report. `null` when nothing is decided. | as above | divide the two counts | `test_sla_compliance_counts_met_against_decided` |
| `sla.resolution.*` | Same rule with `sla_resolve_due_at` and `resolved_at`. Reopening restamps `sla_resolve_due_at` from the reopen moment. | as above | as above | `test_reopening_restarts_the_resolution_clock` |
| `csat.responses` | Tickets in the window with `csat_score` set. One score per ticket, set once, by the person who filed it. | `CompanyRequest.csat_score` | `.filter(csat_score__isnull=False).count()` | `test_csat_aggregates_and_response_rate` |
| `csat.avg` | Mean score, 1–5. `null` with no responses. | as above | average the scores | `test_csat_aggregates_and_response_rate` |
| `csat.distribution` | Count per score 1–5, always all five keys present (a zero is informative). | as above | group by score | `test_csat_aggregates_and_response_rate` |
| `csat.response_rate` | `responses / closed`, where `closed` is `totals.closed`. Denominator is **tickets that closed in the window**, because only a closed ticket can be rated. | as above | divide | `test_csat_aggregates_and_response_rate` |
| `by_source` | Count per `source` for tickets in the window; only sources that occur appear. This is the number that answers the evaluation finding: the share of `phone` against `portal` over time is the measure of the shift to a digital channel. | `CompanyRequest.source` | group by source | `test_counts_match_the_rows`, `test_an_admin_can_log_a_telephone_call_as_a_ticket` |
| `by_kind` | Count per `kind` for tickets in the window. | `CompanyRequest.kind` | group by kind | `test_counts_match_the_rows` |
| `backlog.open` | Open tickets **now**, all time. | `CompanyRequest.status` | `.filter(status__in=OPEN_STATUSES).count()` | `test_backlog_reports_age_breaches_and_unassigned` |
| `backlog.unassigned` | Of those, `assignee` is null — the queue nobody owns. | `CompanyRequest.assignee` | add `.filter(assignee__isnull=True)` | `test_backlog_reports_age_breaches_and_unassigned` |
| `backlog.breaching_now` | Of those, `sla_resolve_due_at < now`. Already late, not "about to be". | `sla_resolve_due_at` | add `.filter(sla_resolve_due_at__lt=now)` | `test_backlog_reports_age_breaches_and_unassigned` |
| `backlog.oldest_days` | Age in days of the oldest open ticket. `null` when nothing is open. | `created_at` | `(now - min(created_at)).days` | `test_backlog_reports_age_breaches_and_unassigned` |

## Product feedback

| Key | Definition | Source | Test |
|---|---|---|---|
| `feedback.submissions` | `Feedback` rows in the window. Distinct from tickets on purpose: an opinion is not a request, and mixing them would corrupt both the support load and the feedback volume. | `Feedback.created_at` | `test_the_metrics_endpoint_reports_the_feedback_channel` |
| `feedback.avg_rating` | Mean of `rating` over rows that carry one (a comment-only submission has `rating = null` and is excluded from the mean, not counted as zero). | `Feedback.rating` | `test_a_comment_alone_is_enough`, `test_the_admin_feed_lists_and_aggregates` |
| `feedback.with_comment` | Rows whose `comment` is not empty. | `Feedback.comment` | `test_the_admin_feed_lists_and_aggregates` |

## Knowledge base

| Key | Definition | Source | Test |
|---|---|---|---|
| `knowledge.articles` | All `KnowledgeArticle` rows, any status or audience. Current state, not windowed. | `KnowledgeArticle` | `test_the_knowledge_block_counts_articles_staleness_and_misses` |
| `knowledge.published` | `status = 'published'`. | `KnowledgeArticle.status` | same |
| `knowledge.stale` | Articles where `reviewed_at` is null, or `now − reviewed_at > review_interval_days` (default 180). **This is the number the knowledge-transfer finding asks for**: it makes decay visible without anyone reading the documents. | `reviewed_at`, `review_interval_days` | `KbStalenessTests` (3 tests) |
| `knowledge.unowned` | Articles with no `owner`. Should be zero; a non-zero value names knowledge nobody maintains. | `KnowledgeArticle.owner` | `test_the_knowledge_block_counts_articles_staleness_and_misses` |
| `knowledge.from_tickets` | Articles with `source_request` set — knowledge that came out of real support work rather than someone's spare afternoon. The rate of change of this number is the measure of whether the transfer loop is actually running. | `source_request` | `test_articles_promoted_from_tickets_are_counted` |
| `knowledge.searches` | `KbSearchLog` rows in the window. Only a `q=` query counts; opening the index is browsing, and counting it would dilute the rate below. | `KbSearchLog.created_at` | `test_every_search_is_logged_with_its_result_count`, `test_listing_without_a_query_is_not_logged_as_a_search` |
| `knowledge.zero_result_searches` | Of those, `results = 0`. | `KbSearchLog.results` | `test_the_knowledge_block_counts_articles_staleness_and_misses` |
| `knowledge.zero_result_rate` | `zero_result_searches / searches`, 4 dp, `null` with no searches. | as above | `test_the_knowledge_block_is_honest_when_nothing_was_searched` |
| `knowledge.top_misses` | The 20 most frequent zero-result queries, by count then alphabetically. **This is a work list**: each entry names an article that should exist. | `KbSearchLog.query_norm` | `test_the_knowledge_block_counts_articles_staleness_and_misses` |
| `knowledge.{views,helpful,unhelpful}` | Sums of the per-article counters. `helpful`/`unhelpful` are votes, one increment per click and not deduplicated per person — stated because it means they measure clicks, not readers. | `KnowledgeArticle` counters | `test_a_seat_can_mark_an_article_helpful_or_not` |

## Metrics deliberately NOT defined yet

Named so that their absence is explicit rather than an oversight. Each belongs
to a later phase in `ROADMAP.md`:

* **Delivery** — deployment frequency, lead time for change, change failure
  rate, MTTR. The data exists (deploy tags, CI run JSON, git history) but no
  collector reads it.
* **Quality trend** — coverage and defect counts per release. Measured today
  per audit, not as a series.
* **Task flow** — issue throughput, cycle time, ageing work in progress.
  Needs the GitHub milestones and board of phase 2.
* **Per-agent support load** — tickets handled per assignee. Possible now that
  `assignee` is a foreign key, but deliberately not published until there is
  more than one person on the desk; a productivity metric over a team of one
  is theatre.
