# Findings (verified 2026-11-02, revised after review)

Method: read-only. Production PostgreSQL 16.15 was queried through the application's ORM inside `SET TRANSACTION READ ONLY` (counts, minima, maxima and set comparisons; no row text was read). Historical SQLite backups on the host were opened with `mode=ro&immutable=1`. No file or row was changed.

Two questions are kept apart throughout, because answering one does not answer the other:

1. **Provenance.** What is this record technically, and is there independent evidence that it existed? (reconstructed batch, back-filled from state, application write that existed in an older backup, application write with no independent source)
2. **Attribution.** Did a real person doing real work produce it, or was it a demo, test, QA, scripted or administrative event? **Nothing in this document establishes attribution as human for any row.**

## 1. Inventory

| Item | Value | Source |
|---|---|---|
| Rows in `api_activitylog` | 86,212 | production |
| Rows carrying the reconstruction marker | 83,486 (96.8%) | production |
| Marker-row ids / created_at | 12154-114201 / 2025-08-23 to 2026-08-12 | production |
| Marker rows by action | view_node 47,080; view_section 23,454; login 6,476; view_fleet 6,476 | production |
| Rows without the marker | 2,726 | production |
| Unmarked rows inside the marker id range | 0 | production |
| Rows inserted by the generator | 102,054 (ids 12148-114201, one `executemany`; manifest `rows` = after-count minus before-count) | `gen_manual_activity.py`, manifest |
| Earlier generator batch (v1) | 3,288 rows, ids 8849-12136; no longer present | `RECONSTRUCTED-ACTIVITY.md`, empty id range (inference; no backup of v1 was found) |

The generator and manifest are tracked in the repository (checksums in `CHECKSUMS.txt`). `RECONSTRUCTED-ACTIVITY.md` exists only as an untracked file on the production host; it states that the data is synthetic, gives the marker, and gives two SQL statements for removal or relabelling. It is preserved where it is.

## 2. The gap: 102,054 inserted vs 83,486 present

All 102,054 rows were intact in every backup from 2026-09-19 to 2026-09-27. 18,568 were later lost, in three steps, each coinciding with the deletion of one or more seats.

| Backup window | Marked rows lost | Seats removed (internal ids) |
|---|---:|---|
| 2026-09-27 to 2026-09-29 | 11,271 | 11, 53, 54 |
| 2026-09-29 to 2026-10-01 | 4,853 | 56 |
| 2026-10-01 to 2026-10-28 | 2,444 | 55 |
| **Total** | **18,568** | exactly the five seats above |

**Mechanism, verified.** `ActivityLog.user` is declared `on_delete=CASCADE` in the Django model. In production PostgreSQL the actual foreign-key constraint is **`NO ACTION`, deferrable, initially deferred** (`pg_constraint.confdeltype = 'a'`; the same for the car foreign key). So the cascade is performed by Django's deletion collector when a seat is deleted through the ORM (the Django admin or application code), **not by the database**. A raw SQL `DELETE` of a seat that still owns activity rows would fail at commit; the application path deletes the activity first. Which path was used for the five seats is not recorded.

Seat 11 also owned 25 pre-reconstruction rows, lost in the first step (457 rows in the 2026-08-05 backup, 432 of them still present). Seats 53-56 were created within about nine minutes on 2026-08-11, which looks like test or seeding accounts; seat 11 was created 2026-07-14. Row counts have been identical (83,486) in the 2026-10-28, 2026-10-29 and 2026-11-02 snapshots and in production now.

Excluded as causes: an insertion error (ids were contiguous at insert time and the count matched the manifest until 2026-09-27); a pruning or retention job (the loss maps one-to-one to five deleted seats); the PostgreSQL migration (counts are equal before and after the cutover snapshots).

**Earlier insertions, inferred.** The rows that existed in the 2026-08-05 backup occupy ids 1-470. The next unmarked row is id 478, created 2026-08-06; the 181 other unmarked rows with ids <= 12147 are scattered between id 478 and 12147. That range holds 181 rows over about 11,670 ids, so roughly 11,500 ids were consumed by rows that no longer exist. This is consistent with the generator having run, and its output having been removed, before the batch of 2026-08-12 (the generator's own comment describes an earlier batch, and `RECONSTRUCTED-ACTIVITY.md` describes the 3,288-row v1). It is an inference from the id sequence; no backup of those earlier batches was found, and their size and content cannot be established.

**Cannot be established:** who deleted the five seats, when exactly, or why. `AuditLog` begins on 2026-10-13, after four of the five removals, and the activity rows that could have recorded the actions were deleted with the seats. The 2026-08-12 14:03 pre-insert backup named in `RECONSTRUCTED-ACTIVITY.md` (`db.sqlite3.bak_manualactivity_20260812_140324`) was searched for across the whole host filesystem and **was not found**. That is an evidence gap in the original procedure, not in the present analysis.

## 3. Reconciliation of figures

### 71,886 vs 70,534 + 1,354 = 71,888

The baseline of 2026-10-30 counted 71,886 manual views (`view_node` + `view_section`). Rows created before 2026-10-30: 71,886 = 70,534 marked + 1,352 unmarked. Two further unmarked rows were created on 2026-10-31 at 04:50 (ids 116412 and 116413). Today: 70,534 + 1,354 = 71,888. The figures agree; the difference is exactly the two later rows.

### 34 vs 36 seats

36 is the number of seats: all 36 are active. 34 is the number of seats with at least one activity row. The two seats without any activity row are internal ids 88 and 95, created 2026-09-29 and 2026-10-01, both with no recorded login. The documents that say "34 active seats" meant "34 seats with any logged activity". The spec's own wording ("34 seats with any activity") was correct; the changelog, metric definitions and evidence README shortened it.

### Seat-level counts (2026-11-02)

| Question | Including reconstructed rows | Unmarked rows only (unverified) |
|---|---:|---:|
| Seats with a manual view | 26 | 12 |
| Seats with a `login` row | 31 | 17 |
| Seats with `last_login_at` null | 19 of 36 | of these 19, seats with an unmarked login row: **0** |

### The 21 unmarked rows with anomalous timestamps

Ids 115263-115288. Every one is an `account_created` event. Each row's `created_at` equals the `created_at` of the seat it belongs to, within five seconds (21 of 21), which is why the timestamps (2026-07-10 to 2026-08-11) are older than their neighbours' ids (inserted about 2026-09-22, inferred from the neighbouring ids). Conclusion: back-filled account events derived from account state, not contemporaneous records and not behaviour. The application writes `account_created` with an automatic timestamp (`orggraph_api.py`), so these were not written by that code path. Who ran the back-fill is not recorded. Five other `account_created` rows (ids 115490-115600, 2026-09-28 to 2026-09-30) have ordinary timestamps.

### The assistant figure is wrong independently of the reconstruction

The 2026-10-30 baseline says the assistant was "asked by 9". Nine seats **opened** the assistant (62 `open_assistant` rows); **3 seats asked** it (43 `ask_assistant` rows, matching the 43 rows in `ChatLog`, also from 3 seats). `METRIC_DEFINITIONS.md` itself defines the discovery metric on `ask_assistant`, so its baseline is 3 seats, not 9, and the "~50 %" discovery rate in the spec does not follow. No reconstructed row has either action; this error is separate from #64 and was found while reviewing the corrections.

## 4. What is established about the unmarked rows

**Provenance (technical, objective):**

| Provenance | Rows | Basis |
|---|---:|---|
| Reconstructed | 83,486 | marker in `detail` and inside the registered generator id range (12148-114201) |
| Application write, **existed in an independent backup older than the batch** | 432 | match by (id, seat, action, timestamp) in the backup of 2026-08-05 21:30 (ids 1-470, created up to 2026-08-05 13:57) |
| Back-filled from account state | 21 | section 3 |
| Application write, **no independent source**, before the batch | 181 | ids <= 12147 created 2026-08-06 18:30 to 2026-08-12 15:16 (168 + 2 + 11). Two rows have ids <= 8848 but timestamps of 2026-08-12 14:41, after the batch started: unexplained. |
| Application write, **no independent source**, after the batch | 2,092 | created 2026-08-12 15:42 to 2026-11-02 |
| **Total** | **86,212** | |

Existence in an older backup shows only that the row was in the database on 2026-08-05. It does not show that a field user did something.

**Attribution (behavioural): not established for any row.** What the data shows about who produced the unmarked rows:

- **Demo accounts.** The system has 3 demo companies (`is_demo`), one seat each. 9 of the 2,092 post-batch rows belong to those seats. An earlier draft of this document said every unmarked row came from real companies; that was unsupported and is withdrawn.
- **Concentration in top-manager seats.** 409 of the 432 pre-batch rows (95%) come from two seats with the role `مدیر ارشد` (top manager); 1,571 of the 2,092 post-batch rows (75%) come from five seats of that role. That pattern is what product-owner, administrator or testing use would look like, and it is also what a real top manager's use would look like. The data cannot tell them apart.
- **Bulk-created seats.** 16 seats (ids 37-52) were created on 2026-08-11 between 11:49 and 17:13, 15 of them within ten minutes; their non-synthetic rows total 101. Two seats have all their non-synthetic rows within 30 minutes of the seat's creation, which is the shape of a scripted or one-off check.
- **Administrative events.** 39 unmarked rows are administrative operations rather than use of the product: `account_created` 26, `team_add` 7, `role_add` 2, `role_apply` 1, `role_delete` 1, `password_reset` 2.
- **Test-like names.** 1 of 36 seat usernames matches a test-like pattern (`test`, `qa`, `demo`, `smoke`, `e2e`, `seed`).
- **Recent use is narrow.** In the last 30 days only 5 seats (all in non-demo companies) produced any activity; the top-manager role accounts for 302 of those 670 rows.

**Corroboration that exists (independent sources, partial):**

- Assistant: 43 `ask_assistant` rows against 43 `ChatLog` rows, same 3 seats (count level; rows were not matched one by one).
- Login: 19 unmarked `login` rows since 2026-10-13; 12 match an `auth.login` audit row for the same seat within 10 seconds, 7 do not (not investigated; possibly a login path the audit does not record).
- Search: `SearchLog` has 0 rows, consistent with "search used by 0".

None of this separates demo, test or administrative use from field use.

## 5. Which windows are affected today

Rows by window ending 2026-11-02 (counts drift slightly with the clock):

| Window | Reconstructed | Back-filled | Existed pre-batch | Unverified, no independent source | Total |
|---|---:|---:|---:|---:|---:|
| 7 days | 0 | 0 | 0 | 82 | 82 |
| 30 days | 0 | 0 | 0 | 670 | 670 |
| 90 days | 1,946 | 17 | 27 | 2,273 | about 4,263 |
| 180 days | 26,184 | 21 | 432 | 2,273 | 28,910 |
| 365 days | 71,223 | 21 | 432 | 2,273 | 73,949 |

The 7- and 30-day windows contain no reconstructed rows because the last one is dated 2026-08-12. That is accidental, not a control, and it does **not** make those windows verified: every row in them is unverified.

## 6. What this changes for issue #49

#49 states that 14 seats "demonstrably signed in" (login rows, latest 2026-08-12) while `last_login_at` is null. All 14 of those seats' login rows are marked; the latest date is the reconstruction batch's end date. No organic login evidence exists for them. `dormant_accounts` may therefore be correct. `last_login_at` must not be back-filled from `ActivityLog`.
