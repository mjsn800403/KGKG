# Production compatibility and presentation

Question: if analytics stop reading reconstructed and unverified activity as before, what changes for users and operators, and how is uncertain data shown without passing it off as genuine?

All figures are read-only counts from production on 2026-11-02, by provenance class (see `FINDINGS.md`). Percentages are of rows.

## 1. Why `strict` cannot be the default

`strict` includes only attested rows. Today that set is empty. Making it the default for any reader would:

| Reader | Effect of `strict` as default |
|---|---|
| Admin traffic and usage, 7-day and 30-day windows | 82 and 670 rows drop to 0 (every row in those windows is unverified) |
| Recommendations | no history for any seat; empty or non-personalised output |
| Onboarding "has this seat done X" | every seat looks as if it has done nothing; every nudge fires |

That would trade a misleading chart for a broken product. `strict` is therefore for evaluator-facing and adoption-evidence reporting only, where "no verified data" is the correct answer.

## 2. What `operational` changes

`operational` excludes `reconstructed`, `backfilled` and rule-based `not_human` rows and includes `unknown` rows, labelled.

| Window | Rows today | Rows under `operational` | Change |
|---|---:|---:|---|
| 7 days | 82 | 82 | none |
| 30 days | 670 | 670 | none |
| 90 days | about 4,263 | about 2,300 | -46%; the 1,946 reconstructed and 17 back-filled rows leave |
| 180 days | 28,910 | 2,705 | -91% |
| 365 days | 73,949 | 2,705 | -96% |

(Demo-company and administrative rows are also excluded under `operational`; they are a few dozen and are not netted out of the table above.)

Consequences to plan for:

- **Wide-window charts fall off a cliff.** A 365-day engagement chart goes from tens of thousands of rows to a few thousand. Without annotation this reads as a collapse in usage. Each affected view needs a visible note: "N reconstructed rows are excluded; history before 2026-07-04 has no application data."
- **Feature discovery.** Seats with any manual view: 26 including reconstructed rows, 12 without. 14 seats would flip from "has read the manuals" to "has not", and their nudges would start to fire. That is the correct behaviour and it will look like a sudden change in onboarding traffic.
- **Recommendations.** Peer history shrinks from 71,888 to about 1,354 manual views from 12 seats. Seats with no recent history fall back to non-personalised suggestions; this fallback must be tested (it is part of `TEST_PLAN.md`).
- **Operators.** Reads only; no write path changes. A search of `ops/` found no alert, watchdog, exporter or dashboard that reads `api_activitylog`; the only references are the staging sanitizer and the restore verifier. Anything outside the repository was not searched. Disk, locks and migrations are unaffected (nullable column, no rewrite).
- **Concentrated use.** In the last 30 days five seats produced all activity and the top-manager role accounts for 302 of 670 rows. Dashboards built on such a small base will be volatile; the note on small samples belongs in the UI.

## 3. Presentation

Never one unlabelled number called "genuine".

| Element | Behaviour |
|---|---|
| Headline KPI | "n unverified application events (excluding m reconstructed)", with "verified: v" beside it, v being 0 until attestations exist |
| Charts | stacked series: verified, unverified; excluded classes shown as a separate, muted line or a footnote count, never summed in |
| Tables | a class column in the admin audit view; filter by class |
| API | additive `provenance` object: `mode`, `included` classes, `counts` per class, `excluded` per class; existing keys unchanged |
| Wide windows | banner when the window reaches back into a registered range |
| Evaluator exports | `strict` only; states the attested scope and "no verified data" when empty |
| Small samples | "based on n events from k seats" when k is under 10 |

## 4. Per-reader policy

| Reader | Mode | Notes |
|---|---|---|
| `adminops` traffic, today and recent feeds | operational | composition shown |
| `portal` usage report | operational | composition and wide-window banner |
| `insights` funnel | operational for activity; `dormant_accounts` unchanged (reads `last_login_at`) | do not back-fill `last_login_at` |
| `recommend` | operational, excluding administrative actions and demo seats | fallback when history is empty |
| `team` reports | operational | |
| `onboarding` `exists()` | operational | an `unknown` row counts as done; a reconstructed row never does |
| evaluator-facing adoption figures | strict | empty until attested |
| `quota`, writers, `behavior` | unchanged | different action or table |

## 5. Rollout

1. Implement behind a flag per reader (`KG_ACTIVITY_PROVENANCE_<READER>`), default off.
2. **Shadow mode** on staging against a sanitized copy: compute old and new values, log the difference, show nothing new.
3. Compare dashboards at 7, 30, 90 and 365 days against the table in section 2.
4. Enable readers one at a time; each with its annotation and its test.
5. Production promotion only by a person (`kgkg-promote <sha>`).
6. Rollback is the previous image tag plus turning the flag off; no data to restore.

## 6. What has not been assessed

User-visible impact on customers' own dashboards if any are exposed outside the admin and team roles; this must be checked reader by reader during step 2 of the rollout. The count of Grafana or other external dashboards reading the table directly is not known (none was found in the repository).
