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

**This table is a reference reading, not an acceptance limit.** The counts were read from production on 2026-11-02 between about 16:05 and 16:27 UTC. Each window was a trailing window measured from the moment of its own query (`now()` minus N days), so the figures moved while they were being collected (the 90-day total read 4,267 in one query and 4,263 in a later one) and they will move again with every new row and every day that passes. A later snapshot, or a moving window, can legitimately fall outside these ranges through normal activity. They illustrate the **shape** of the change (nothing in the short windows, a drop of about 91% to 96% in the long ones); they must not be used as pass or fail limits. The acceptance criterion uses fixed boundaries and is defined in "Fixed boundaries for acceptance" below.

The table nets out **all** three exclusions. Two of them are exact; the third (demo-company and administrative rows) is bounded rather than exact, because its distribution across windows was not read and no production access was made for this revision.

| Window (trailing, at the reading) | Rows at the reading | Reconstructed and back-filled removed (exact) | Left before demo/administrative rule | `operational` after that rule (range) |
|---|---:|---:|---:|---:|
| 7 days | 82 | 0 | 82 | 55 to 82 |
| 30 days | 670 | 0 | 670 | 643 to 670 |
| 90 days | about 4,263 | 1,963 (1,946 + 17) | about 2,300 | 2,273 to 2,300 |
| 180 days | 28,910 | 26,205 (26,184 + 21) | 2,705 | 2,678 to 2,687 |
| 365 days | 73,949 | 71,244 (71,223 + 21) | 2,705 | 2,678 to 2,687 |

How the last column is bounded. Among the 2,705 unmarked, non-back-filled rows, the rule-based `not_human` exclusions are the 9 rows of seats in demo companies and the 18 administrative rows (`account_created`, `team_add`, `role_add`, `role_apply`, `role_delete`, `password_reset`, not counting the 21 back-filled rows already removed). They can overlap, so between 18 and 27 rows are excluded in total (all-time, hence the 180 and 365-day ranges of 2,678 to 2,687). In a shorter window an unknown number of them, between 0 and 27 but never more than the window's rows, falls inside, which gives the wider lower bound. The 90-day base of about 2,300 is 27 pre-batch rows plus 181 plus 2,092; it drifts by a few rows with the clock.

Change at the reading: 7 and 30 days, 0 to 27 rows (up to about 33% and 4%); 90 days, about -46% to -47%; 180 days, about -91%; 365 days, about -96%.

### Fixed boundaries for acceptance

Acceptance is evaluated on one **staging snapshot**, with the snapshot and the windows fixed in advance, so that normal activity cannot move the result.

1. **One fixed cutoff `T`** (a UTC timestamp recorded with the sanitized staging copy when it is made). Every count uses the explicit window `created_at >= T - N days AND created_at <= T`, for N in 7, 30, 90, 180 and 365. No query in the shadow comparison uses `now()`.
2. **Both code paths are evaluated at `T`.** The old behaviour and the new `operational` behaviour are run with the analytics code's `as_of` input set to `T` (the design adds an `as_of` parameter, default the current time, so the comparison is reproducible).
3. **The bounds are recomputed from that snapshot**, not copied from this document. For each window, from the staging copy: `W` all rows, `R` reconstructed, `B` back-filled, `D` rows of demo-company seats and `A` administrative rows, each counted only if not already in `R` or `B`, and `O` rows in both `D` and `A`.
4. **Bounds:** `W - R - B - (D + A) <= operational <= W - R - B - max(D, A)`. Once `O` is read the value is exact: `operational = W - R - B - (D + A - O)`.
5. **Pass criterion:** for every window, the measured `operational` count equals `W - R - B - (D + A - O)` computed by a separate query from the same snapshot (exact equality), and lies inside the bounds in step 4. The recorded `T`, the six counts per window and the measured values go into the evidence entry. Nothing is compared with the 2026-11-02 reference table.
6. **If the staging copy is refreshed**, `T` and every figure are recomputed; the previous result is not reused.

Consequences to plan for:

- **Wide-window charts fall off a cliff.** On the 2026-11-02 reading, a 365-day engagement chart goes from 73,949 rows to between 2,678 and 2,687. Without annotation this reads as a collapse in usage. Each affected view needs a visible note: "N reconstructed rows are excluded; history before 2026-07-04 has no application data."
- **Feature discovery.** Seats with any manual view: 26 including reconstructed rows, 12 without. 14 seats would flip from "has read the manuals" to "has not", and their nudges would start to fire. That is the correct behaviour and it will look like a sudden change in onboarding traffic.
- **Recommendations.** Peer history shrinks from 71,888 to at most 1,354 manual views from 12 seats (fewer by any made by demo-company seats). Seats with no recent history fall back to non-personalised suggestions; this fallback must be tested (it is part of `TEST_PLAN.md`).
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
