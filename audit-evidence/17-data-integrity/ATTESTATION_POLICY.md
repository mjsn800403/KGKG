# Attestation policy: when unverified activity may be treated as human activity

Status: proposal. No attestation has been made. Today no activity row is `human_confirmed`.

## 1. Principle

An attestation changes the **attribution** of a defined set of rows from `unknown` to `human_confirmed`. It is never granted for "all unmarked rows", for "rows after a date", or on the strength of aggregate counts or general application behaviour. Existence in an older backup (`app_preexisting`) and a technical origin (`origin='app'`) are provenance facts and are not evidence of attribution.

## 2. What can be attested, and the evidence each needs

| Scope | What it claims | Minimum evidence |
|---|---|---|
| **Event** | one specific row was produced by a real person doing real work | an independent record of the same event, matched by seat, action and time window, with the matching record's id cited (for example an `AuditLog` login, a `ChatLog` question, a delivery record from the SMS or OTP provider, a web-server access-log line). |
| **Seat cohort** (seat set x id range x action set) | all rows in that scope are by a named, real, working person | (a) written confirmation, by someone with authority over the seat (the company administrator or the product owner), that the seat belongs to a real person and is not demo, test, QA, scripted or administrative; (b) the exclusion checks below pass; (c) an independent sample match as below. |

A seat is never attested wholesale across the history of its account: the scope names an id range and an action set, so later use by someone else, or a role change, does not inherit the attestation.

## 3. Exclusion checks (all must pass for a cohort)

1. The seat's company is not flagged `is_demo`, and the seat is not recorded as `demo`, `test`, `qa` or `admin_ops` in the seat-kind registry.
2. The scope contains no administrative action (`account_created`, `team_add`, `role_*`, `password_reset`).
3. The seat's rows are not confined to a short window after its creation (the shape of a one-off check), and are not machine-regular (fixed intervals, bursts of identical actions).
4. The seat was not created in a bulk-creation burst, unless the person confirms it individually.
5. The seat does not appear in the scripted or QA activity of the QA stack (the E2E and smoke seats).

## 4. Independent sample match

For a cohort, draw a random sample of the scope's events with a recorded seed and match each against an independent source. Sample size: all events if the scope has 30 or fewer, otherwise at least 30 or 10%, whichever is larger. Required match rate: at least 90%, and **every unmatched event is listed with the reason** (no source covers the period is a reason that blocks attestation, not a pass).

Independent sources and the period each covers (confirm before use; this list is not a guarantee):

| Source | Covers | Notes |
|---|---|---|
| `ChatLog` | from 2026-09-27 | assistant questions only |
| `AuditLog` | from 2026-10-13 | logins, admin and API writes |
| `SearchLog` | none (0 rows) | |
| Web-server access logs | retention not confirmed (see #63) | would cover page views, if retained |
| SMS / OTP provider records | provider-dependent | |

No independent source is known for page views between 2026-08-12 and 2026-09-27. Rows from that period can be attested at seat level only if an access-log source is found; otherwise they stay `unknown`. This is an expected outcome, not a failure.

## 5. The record of an attestation

Each attestation is a new, append-only registry entry (never an edit) containing:

- **scope**: seat ids, id range, action set, time bounds;
- **classification change**: dimension, previous value, new value (the entry's `supersedes_id` links the old one);
- **evidence**: basis code, `evidence_ref` to the matched-record list and the sample seed, the exclusion-check results, and the match rate;
- **analyst** and **approver**, who must be different people, and the timestamp;
- **review_by**: a date after which the entry must be re-confirmed (default 180 days);
- the number of rows covered at the time (`rows_recorded`).

## 6. Reversal

An attestation is withdrawn by a new entry that supersedes it (for example back to `unknown`, or to `not_human`). A downgrade needs only one person and takes effect immediately; an upgrade needs both roles. A withdrawn attestation stays visible in the audit view.

## 7. What this means for the numbers

- The 432 pre-batch rows are `app_preexisting`, attribution `unknown`; 409 of them come from two top-manager seats, which is consistent with administrative or product-owner use. They are candidates for a seat-level attestation, not already confirmed.
- The 2,092 post-batch rows are `app_unconfirmed`, attribution `unknown`. 9 belong to demo-company seats and are `not_human` by rule; 75% come from five top-manager seats. They are attested, if at all, cohort by cohort. The fraction that ends up attested may be small, and `strict` metrics will say so.
- Until an attestation is approved, no figure may be described as "genuine usage"; the permitted wording is "unverified application activity, excluding reconstructed rows".
