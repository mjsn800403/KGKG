# Test plan and acceptance criteria (revised after review)

Rule: these tests are written, and seen to fail for the right reason, **before** any implementation. They are a design here; none exists yet. Suggested homes: `KG_backend/api/test_activity_provenance.py` (behaviour), `ops/governance/` (static guards), `ops/deploy/` (migration safety).

Shared fixture: one company with several seats, one demo company, and rows of every kind: reconstructed (marker, registry range, `origin='reconstructed'`), back-filled (`account_created` with a back-dated timestamp), pre-batch application rows, unconfirmed application rows, administrative actions, and new rows with `origin='app'`. Both axes (provenance and attribution) are exercised.

## A. Exclusion by mode

| ID | Test | Expected |
|---|---|---|
| A1 | admin traffic, usage report and insights over a 365-day window, `operational` | equals the count of non-reconstructed, non-back-filled, non-`not_human` rows; adding any number of reconstructed rows changes nothing |
| A2 | contract test over every analytics endpoint: result with reconstructed rows added equals result without | identical, except the `provenance` object |
| A3 | recommendations when only reconstructed peer history exists | none seeded from it; documented fallback is used |
| A4 | team report | reconstructed rows never appear in member totals |
| A5 | onboarding `read_manual` for a seat whose only manual views are reconstructed | not discovered; the nudge fires |
| A6 | demo-company seat's rows and administrative actions | excluded from `operational` by rule |

## B. Conservative handling and the two axes

| ID | Test | Expected |
|---|---|---|
| B1 | row with `origin` NULL and no registry entry | provenance `app_unconfirmed`, attribution `unknown`; present in `operational`, absent from `strict` |
| B2 | row with `origin='app'` | provenance `app`, attribution still `unknown`; absent from `strict` |
| B3 | row matched in the pre-batch backup (`app_preexisting`) | attribution still `unknown`; absent from `strict` |
| B4 | `strict` on the unattested fixture | empty, and the endpoint says so instead of falling back |
| B5 | a cohort attestation meeting `ATTESTATION_POLICY.md` | only rows inside its seat set, id range and action set become `human_confirmed`; rows outside do not |
| B6 | attestation missing a required field (no approver, same analyst and approver, no evidence_ref, no review_by, unbounded scope such as "all rows") | rejected |
| B7 | withdrawing an attestation by a superseding entry | rows return to `unknown`; the old entry stays visible in the audit view |

## C. Registry correctness

| ID | Test | Expected |
|---|---|---|
| C1 | overlapping entries with different values and no `supersedes_id` | the insert is rejected by the trigger |
| C2 | resolution order | most specific scope wins; equal specificity with different values resolves to the less trusted value and the consistency check fails |
| C3 | superseded entries | ignored in resolution, visible in audit |
| C4 | downgrade versus upgrade | a downgrade needs one person; an upgrade to `human_confirmed` needs two different people |
| C5 | append-only | as the application database role, `UPDATE` and `DELETE` on both new tables fail; model-level guards are not relied on |
| C6 | `rows_recorded` | immutable; no stored surviving count exists; the diagnostic surviving count for the batch matches production's 83,486 against `rows_recorded` 102,054 on the production-shaped fixture |
| C7 | cross-process visibility | two separate processes: a registry entry written by one is read by the other on its next request; no process cache holds a stale entry |

## D. Preservation of historical data and migration safety

| ID | Test | Expected |
|---|---|---|
| D1 | run M1 and M2 on a database with the fixture | a checksum over the **named original columns only** (`id, user_id, action, detail, category, car_id, node_title, app_url, created_at`) and the ordered id list is identical before and after; every existing row has `origin IS NULL` |
| D2 | reverse M2 and M1 | schema returns to the old state; the original-column checksum is still identical |
| D3 | `ActivityLog.objects` | still returns every row, so audit and Django admin are unfiltered |
| D4 | old application code against the migrated schema | inserts and reads succeed (rollback safety) |
| D5 | generator guard | `--apply` without the explicit flag exits non-zero and writes nothing; with it, rows carry `origin='reconstructed'` and registry entries with `rows_recorded` are written in the same transaction |
| D6 | no table rewrite | `pg_class.relfilenode` of `api_activitylog` is unchanged after M1 |

## E. Time windows and presentation

| ID | Test | Expected |
|---|---|---|
| E1 | windows of 7, 30, 90, 180 and 365 days over fixture data that straddles the reconstruction end date | each reports `operational` rows; `provenance.excluded` equals the registered rows inside the window |
| E2 | a window wholly after the last reconstructed row | `provenance.excluded` is 0; the unverified label is still shown |
| E3 | a window reaching into the registered range | qualification fields present; the UI shows the banner |
| E4 | no response contains an unlabelled field called `genuine`; every aggregate carries its class composition | pass |
| E5 | evaluator export | `strict` only; "no verified data" when empty |
| E6 | determinism with a fixed `as_of` | with the same fixture and `as_of` set to a fixed timestamp, every window count is identical when the test runs at different wall-clock times and after further rows are inserted with later timestamps; the code never reads the current time when `as_of` is given |
| E7 | the bound formula | for fixtures with chosen `R`, `B`, `D`, `A` and `O`, the measured `operational` count equals `W - R - B - (D + A - O)` and lies between the two stated bounds |

## F. Prevention of regression to unfiltered queries

| ID | Test | Expected |
|---|---|---|
| F1 | static scan of `KG_backend/api/` | any use of `ActivityLog.objects` outside an allow-list (writers, admin, audit, migrations, tests) fails the build and names the file and line |
| F2 | allow-list review | adding a file needs a comment naming why unfiltered access is correct |
| F3 | registry-manifest consistency | `rows_recorded` for the 2026-08-12 batch equals `reconstructed_activity_manifest.json` (102,054) |

## G. Onboarding and recommendation behaviour

| ID | Test | Expected |
|---|---|---|
| G1 | the existing onboarding suite | passes unchanged on ordinary fixtures |
| G2 | seat with reconstructed `view_node` and no other manual view | nudge fires; `read_manual` incomplete |
| G3 | `recommend` own-history and peer queries | built from `operational` rows only; administrative actions and demo seats excluded |
| G4 | 14-seat flip scenario | seats whose only manual evidence was reconstructed become "not discovered" and are counted in a logged shadow-comparison difference |

## H. Regressions for the problems actually found

| ID | Problem found | Test |
|---|---|---|
| H1 | reconstructed rows read as activity | A and F above, plus a production-shaped fixture (96.8% reconstructed) giving the expected `operational` totals |
| H2 | GitHub #49: login rows used as proof of sign-in | `dormant_accounts` never reads `ActivityLog`; a seat with only reconstructed login rows and a null `last_login_at` is counted as dormant |
| H3 | #49: every real login path must set `last_login_at` | one test per path: password, OTP verify, invite acceptance, recovery reset |
| H4 | 71,886 vs 71,888 and 34 vs 36 | a test that each metric definition states its denominator and the classes it includes, and that component counts sum to the total |
| H5 | back-filled `account_created` with older timestamps | classified `backfilled`, excluded from behaviour |
| H6 | the back-fill temptation | no code path writes `last_login_at` from `ActivityLog` |
| H7 | "assistant asked by 9" (9 opened, 3 asked) | a test that the discovery metric for the assistant counts `ask_assistant` seats, and that opens and asks are reported separately |
| H8 | the seat-to-activity cascade | a characterization test: deleting a seat through the ORM deletes its activity rows; the database foreign key is `NO ACTION`. It documents current behaviour; it does not change it (see `REMEDIATION_DESIGN.md` 7.6) |

## I. Migration and query performance

| ID | Test | Expected |
|---|---|---|
| I1 | migration on a production-shaped copy | seconds, brief locks only |
| I2 | dashboard queries on 1,000,000 generated rows | plan uses the existing indexes for bounded windows; time under an agreed budget |

## Acceptance criteria for the implementation PR

0. **Prerequisite:** the staging-equivalence verification in `COMPATIBILITY_ASSESSMENT.md` section 2 (built by the named Method B, not the unmodified deploy path, and fingerprinted with the approved query files; it needs its own production-read authorization, not yet requested or granted) has passed for the staging copy used: every activity, seat and company fingerprint equals its same-instant source fingerprint. Without it no shadow-comparison result counts.
1. All tests above exist, were red before the change and are green after it.
2. The backend coverage floor and lint ratchet do not drop.
3. No `api_activitylog` row differs before and after migration on the original columns (D1).
4. Staging shadow comparison on one fixed snapshot, as defined in `COMPATIBILITY_ASSESSMENT.md` ("Fixed boundaries for acceptance"): a single recorded cutoff `T` (the `transaction_timestamp()` of the exporter transaction the staging copy was made from, as defined in `COMPATIBILITY_ASSESSMENT.md`; a window boundary, not the snapshot instant), windows `[T - N days, T]` for N in 7, 30, 90, 180 and 365, both code paths evaluated with `as_of = T` and no `now()` anywhere in the comparison. For every window the measured `operational` count equals `W - R - B - (D + A - O)` computed by a separate query on the same snapshot, and lies inside the bounds `W - R - B - (D + A)` to `W - R - B - max(D, A)`. `T`, the six counts per window and the measured values are recorded in the evidence entry. The 2026-11-02 reference table is informative only and is never an acceptance limit.
5. `CHANGELOG` and `METRIC_DEFINITIONS.md` updated in the same commit; each metric states its denominator, the mode and the classes it includes.
6. An independent reader reproduces the `FINDINGS.md` queries after promotion and the numbers match the registry.
