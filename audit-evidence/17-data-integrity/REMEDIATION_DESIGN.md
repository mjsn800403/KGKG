# Remediation design: provenance-aware activity analytics

Status: **proposal for review.** No code, migration or production change exists. Nothing here may be deployed or run against production without passing the gates in section 8.

## 1. Goals and non-goals

Goals: keep every row; make provenance explicit; make normal analytics, onboarding and recommendations use only trustworthy activity; keep full, unfiltered access for authorized audit; do it in one place, with tests that stop regression.

Non-goals: deleting, updating or anonymizing any existing `api_activitylog` row; changing the meaning of any existing column; deciding whether the reconstructed rows should eventually be removed (a separate decision, section 9).

## 2. Classification model

Every row has exactly one class.

| Class | Meaning | Counts today |
|---|---|---:|
| `synthetic` | generated or reconstructed; never user behaviour | 83,486 |
| `verified_genuine` | independently confirmed by a source older than, or independent of, the table | 432 (ids 1-470, matched in the 2026-08-05 backup) |
| `derived` | back-filled from account state, not contemporaneous behaviour | 21 (ids 115263-115288 that are `account_created`) |
| `unverified` | written by the application by every sign, but not independently confirmed | 2,273 (181 before the batch, 2,092 after) |

The default for any row that is not classified is `unverified`, never `verified_genuine`: an unknown is not good evidence.

**Promotion by attestation.** A range of `unverified` rows can be promoted to `verified_genuine` only by an explicit, signed registry entry stating the basis (for example "live application writes after 2026-08-12 15:42; 43 of 43 assistant rows match `ChatLog`; 12 of 19 logins match `AuditLog`") and who attests. This is a product-owner decision (gate G3). Without it, the 2,092 post-batch rows stay `unverified` and dashboards show them as a separate, labelled series.

## 3. Data model (all additive)

### 3.1 `api_activityprovenance` (new, append-only)

| Column | Notes |
|---|---|
| `id` | primary key |
| `classification` | `synthetic`, `verified_genuine`, `derived`, `unverified` |
| `reason` | short code, e.g. `reconstruction_batch_20260812`, `pre_batch_backup_match`, `backfilled_account_event`, `pm_attestation` |
| `id_min`, `id_max` | inclusive range of `api_activitylog.id`; check `id_min <= id_max` |
| `marker` | optional extra condition (substring of `detail`) for ranges that mix classes |
| `rows_recorded`, `rows_surviving` | informational counts (for the batch: 102,054 and 83,486) |
| `evidence_ref` | pointer to this directory or a checksum entry; never data |
| `recorded_by`, `recorded_at` | who and when |
| `supersedes_id` | a reclassification adds a new row pointing at the one it replaces; rows are never updated or deleted |

The newest non-superseded entry covering an id wins. The registry is the only place where history is classified, so a reclassification is itself auditable.

### 3.2 `api_activitylog.origin` (new, nullable)

`varchar(16) NULL`. New rows written by the application set `origin = 'app'` through the model default. Rows that exist today keep `NULL` (they are classified by the registry). The reconstruction generator must set `origin = 'reconstructed'` and write a registry entry (section 5). No existing row is updated.

### 3.3 Why a registry plus a column

A column alone would require updating 86,212 existing rows, which this proposal forbids. A registry alone makes every future filter a range lookup. The pair keeps history untouched and makes new rows cheap to classify.

## 4. Access layer: one definition

- `ActivityLog.objects`: unchanged, unfiltered. Used by Django admin, audit and the evidence tooling.
- `ActivityLog.genuine`: new manager. `genuine()` returns rows where `origin = 'app'`, or `origin` is NULL and the id falls in a `verified_genuine` range. `unverified()`, `synthetic()` and `derived()` return the other classes. Registry ranges are read once per process and cached for a short time (invalidated when a registry row is written).
- `ActivityLog.classified()`: annotates each row with its class, for diagnostics and the admin.
- Every analytics reader uses `genuine`; a metric that deliberately includes `unverified` must say so by name (`genuine(include_unverified=True)`), and the API response then carries which classes it included.
- A static guard test (section 6) fails the build if an analytics module uses `ActivityLog.objects` outside an explicit allow-list.

### Reader behaviour

| Reader | New behaviour |
|---|---|
| `adminops` traffic, today and recent feeds | `genuine`; response includes `provenance: {synthetic_in_window, unverified_in_window}` so the UI can qualify wide windows |
| `portal` usage report | same; windows reaching back into a registered range show the qualification |
| `insights` funnel, views, retention | `genuine`; `dormant_accounts` stays based on `last_login_at` and is not backfilled |
| `recommend` | `genuine` only, for own and peer logs (synthetic must never seed recommendations) |
| `team` reports | `genuine` |
| `onboarding` `exists()` probes | `genuine`; a seat whose only manual views are reconstructed is treated as not having read a manual |
| `quota`, writers, `behavior` | unchanged (different action, or different table) |
| Django admin | unfiltered, with a class column |

## 5. Generator guard

`gen_manual_activity.py --apply` must refuse to run unless an explicit flag is passed, must set `origin='reconstructed'` on every row, and must write the registry entry in the same transaction. A test asserts this. The script already prints a preview by default; this makes the dangerous path impossible to take by accident.

## 6. Tests

Defined in `TEST_PLAN.md`; they are written before the implementation.

## 7. Migration and rollback

### Migrations (additive only, per repository policy)

| Step | Change | Row impact |
|---|---|---|
| M1 | create `api_activityprovenance`; add nullable `origin` to `api_activitylog` | none; on PostgreSQL 11+ a nullable column with no default is a metadata change and does not rewrite the table (confirm the production version first) |
| M2 | idempotent data migration inserting registry entries: the generator batch (synthetic, ids 12148-114201, marker), ids 1-470 (verified, `pre_batch_backup_match`), ids 115263-115288 where `action = 'account_created'` (derived), everything else unclassified | none to `api_activitylog` |
| M3 | later, separately: a partial index for `origin = 'app'` if measurement shows a need (built `CONCURRENTLY`, outside a transaction) | none |

### Pre-flight and verification

Before M2: take the evidence backup (`EVIDENCE_PRESERVATION.md`), record row count, id range, marker count and a checksum of the ordered id list. After M1 and M2: the same four values must be identical. The migration test suite proves no `api_activitylog` row changes (checksum before and after).

### Rollback

- **Code:** redeploy the previous image tag (promotion stays a person's action). The previous code ignores the new column (it is nullable and has no constraint) and never reads the registry, so it runs unchanged against the migrated schema. This is the reason the migrations are additive.
- **Schema:** reversing M2 deletes registry entries only; reversing M1 drops the new table and the nullable column. Neither touches activity data. Reversal is optional, not required, to roll back behaviour.
- **Data:** none to restore, because no activity row is modified.

### Performance and compatibility

Registry ranges are few (single digits), so the added predicate is a handful of `id BETWEEN` terms on the primary key plus the existing `created_at` indexes; at 86,212 rows the cost is negligible. A test records the query plan for the dashboard queries on a table of 1,000,000 synthetic test rows and fails if the plan degrades to a full scan for a bounded window. Existing endpoints keep their response shape; `provenance` is an added key. A feature flag (`KG_ACTIVITY_PROVENANCE`) lets the filtered readers be enabled one at a time on staging.

## 8. Approval gates

| Gate | Who | Needed before |
|---|---|---|
| G0 | product owner | decision on #64 recorded (done for direction; keep-or-remove remains open) |
| G1 | reviewer | merge of the documentation-only correction PR |
| G2 | product owner | any backup, checksum run or copy on the production host: destination, custodians, retention, capacity re-check |
| G3 | product owner | approval of this design, and of any attestation promoting `unverified` ranges |
| G4 | second reviewer | merge of the implementation PR (code, tests, migrations) |
| G5 | engineer | green staging run on a sanitized copy; dashboards compared at 7, 30, 90 and 365 days |
| G6 | a person, via `kgkg-promote <sha>` | any production change; never automated |
| G7 | independent reader | re-run of the section-1 queries of `FINDINGS.md` and the metric contract tests on production |
| G8 | product owner | closing #64, only after G7 |

## 9. Deferred decision

Whether the reconstructed rows stay (disclosed and excluded) or are removed later. If removed, it is a separate change with its own gate, uses the manifest's statements after a verified, restore-tested backup, and records before/after counts in the registry first.

## 10. Risks

- Unverified rows excluded by default will make some dashboards look quiet until the post-batch range is attested (G3). That is intended; the response says why.
- The 181 rows before the batch and the 2 rows with ids <= 8848 but a timestamp after the batch started stay `unverified`.
- If the registry and `origin` ever disagree, `synthetic` wins.
- Seat deletion still cascades activity; this design does not change that. A decision on soft-deleting seats is out of scope here but is the mechanism that destroyed 18,568 rows of evidence.
