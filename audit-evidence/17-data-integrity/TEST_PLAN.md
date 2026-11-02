# Test plan and acceptance criteria

Rule: these tests are written, and seen to fail for the right reason, **before** any implementation. They are a design here; none exists yet. Suggested homes: `KG_backend/api/test_activity_provenance.py` (behaviour), `ops/governance/` (static guards), `ops/deploy/` (migration safety).

Shared fixture: a company with several seats and four kinds of rows: genuine (`origin='app'`), reconstructed (marker plus registry range, `origin='reconstructed'`), derived (`account_created` with a back-dated timestamp), and unverified (unclassified, `origin` NULL).

## A. Exclusion of synthetic records from genuine-user metrics

| ID | Test | Expected |
|---|---|---|
| A1 | admin traffic, usage report and insights funnel over a 365-day window | counts equal those computed from genuine rows alone; adding any number of synthetic rows changes nothing |
| A2 | contract test over every analytics endpoint: response with synthetic rows added equals response without them | identical, except the `provenance` key |
| A3 | recommendations for a seat when only synthetic peers exist | no recommendation is seeded from them |
| A4 | team report | synthetic rows never appear in member totals |
| A5 | feature-discovery `read_manual` for a seat whose only manual views are reconstructed | not discovered; the nudge still fires |

## B. Conservative handling of unverified records

| ID | Test | Expected |
|---|---|---|
| B1 | unclassified row with `origin` NULL | class `unverified`, excluded from `genuine()` |
| B2 | `genuine(include_unverified=True)` | includes them, and the response names the classes included |
| B3 | promotion by a signed registry attestation | the range becomes `verified_genuine`; the superseded entry is retained; the change is visible in `classified()` |
| B4 | registry and `origin` disagree | `synthetic` wins |
| B5 | derived `account_created` rows | excluded from behaviour metrics, still listed in the audit view |

## C. Preservation of historical data

| ID | Test | Expected |
|---|---|---|
| C1 | migration M1 and M2 on a database with the fixture rows | checksum of `api_activitylog` (ordered id list plus all columns) identical before and after |
| C2 | reverse M2 and M1 | schema returns to the old state; the activity checksum is still identical |
| C3 | registry is append-only | update and delete through the model raise; a reclassification adds a row with `supersedes_id` |
| C4 | `ActivityLog.objects` | still returns every row, so audit and Django admin are unfiltered |
| C5 | old application code against the migrated schema | inserts and reads succeed (rollback safety) |
| C6 | generator guard | `--apply` without the explicit flag exits non-zero and writes nothing; with it, rows carry `origin='reconstructed'` and the registry entry is written in the same transaction |

## D. Time windows

| ID | Test | Expected |
|---|---|---|
| D1 | windows of 7, 30, 90, 180 and 365 days over fixture data that straddles the reconstruction end date | each window reports genuine rows only; `provenance.synthetic_in_window` equals the registered rows inside the window |
| D2 | a window wholly after the last synthetic row | `provenance.synthetic_in_window` is 0 and the UI shows no qualification |
| D3 | a window reaching into the registered range | the response carries the qualification fields; the dashboard shows them |

## E. Prevention of regression to unfiltered queries

| ID | Test | Expected |
|---|---|---|
| E1 | static scan of `KG_backend/api/` | any use of `ActivityLog.objects` outside an allow-list (writers, admin, audit, migrations, tests) fails the build and names the file and line |
| E2 | allow-list review | adding a file to the allow-list requires a comment naming why unfiltered access is correct |
| E3 | registry-manifest consistency | the registry's recorded counts for the 2026-08-12 batch equal `reconstructed_activity_manifest.json` (102,054 inserted) |

## F. Onboarding and recommendation behaviour

| ID | Test | Expected |
|---|---|---|
| F1 | the existing onboarding suite | passes unchanged on genuine fixtures |
| F2 | seat with reconstructed `view_node` and no genuine view | nudge fires; `read_manual` incomplete |
| F3 | `recommend` own-history and peer queries | built from `genuine` only |

## G. Regressions for the problems actually found

| ID | Problem found | Test |
|---|---|---|
| G1 | 83,486 reconstructed rows read as genuine activity | the A and E tests above, plus a test that the production-shaped fixture (96.8% synthetic) gives genuine-only totals |
| G2 | GitHub #49: login rows used as proof of sign-in | `dormant_accounts` never reads `ActivityLog`; a seat with only reconstructed login rows and a null `last_login_at` is counted as dormant |
| G3 | #49: every real login path must set `last_login_at` | one test per path: password, OTP verify, invite acceptance, recovery reset; each moves the column |
| G4 | 18,568 rows lost to seat deletion by cascade | a test that deleting a seat is blocked or soft-deletes when the seat owns activity (design decision pending), and that the registry's `rows_surviving` can be recomputed |
| G5 | 71,886 vs 71,888 and 34 vs 36 | a test that metric definitions state their denominators, and that the manual-view figure equals genuine plus synthetic plus unverified components |
| G6 | back-filled `account_created` with older timestamps | classified `derived`, not counted as behaviour |
| G7 | the `last_login_at` backfill temptation | a test that no code path writes `last_login_at` from `ActivityLog` |

## H. Migration safety and performance

| ID | Test | Expected |
|---|---|---|
| H1 | migration on a production-shaped copy | runs in seconds, takes no table rewrite (check `pg_class` relfilenode unchanged for `api_activitylog`), takes only brief locks |
| H2 | dashboard queries on 1,000,000 generated rows | plan uses the existing indexes for bounded windows; time under an agreed budget |
| H3 | registry cache | a written registry row is visible within the cache window; a restart is not required |

## Acceptance criteria for the implementation PR

1. All tests above exist, were red before the change and are green after it.
2. The backend coverage floor and lint ratchet do not drop.
3. No `api_activitylog` row differs before and after migration (C1).
4. Staging comparison (G5 in `REMEDIATION_DESIGN.md`): every analytics endpoint equals its genuine-only recomputation at 7, 30, 90 and 365 days.
5. `CHANGELOG` and `METRIC_DEFINITIONS.md` updated in the same commit; each metric states its denominator and the classes it includes.
6. An independent reader reproduces the `FINDINGS.md` queries after promotion, and the numbers match the registry.
