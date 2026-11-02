# Findings (verified 2026-11-02)

Method: read-only. Production PostgreSQL was queried through the application's ORM inside `SET TRANSACTION READ ONLY` (counts, minima, maxima and set comparisons; no row text was read). Historical SQLite backups on the host were opened with `mode=ro&immutable=1`. No file or row was changed. Every number below can be reproduced by the queries described in the method notes.

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
| Earlier generator batch (v1) | 3,288 rows, ids 8849-12136; no longer present | `RECONSTRUCTED-ACTIVITY.md`, empty id range (inference, no backup of v1 was found) |

The generator and manifest are tracked in the repository (checksums in `CHECKSUMS.txt`). `RECONSTRUCTED-ACTIVITY.md` exists only as an untracked file on the production host; it states that the data is synthetic, gives the marker, and gives two SQL statements for removal or relabelling. It is preserved where it is.

## 2. The gap: 102,054 inserted vs 83,486 present

All 102,054 rows were intact in every backup from 2026-09-19 to 2026-09-27. 18,568 were later lost, in three steps, each coinciding with the deletion of one or more seats. `ActivityLog.user` is a foreign key with `ON DELETE CASCADE`, so deleting a seat deletes its activity.

| Backup window | Marked rows lost | Seats removed (internal ids) |
|---|---:|---|
| 2026-09-27 to 2026-09-29 | 11,271 | 11, 53, 54 |
| 2026-09-29 to 2026-10-01 | 4,853 | 56 |
| 2026-10-01 to 2026-10-28 | 2,444 | 55 |
| **Total** | **18,568** | exactly the five seats above |

Seat 11 also owned 25 pre-reconstruction rows, lost in the first step (457 rows in the 2026-08-05 backup, 432 of them still present). Seats 53-56 were created within about nine minutes on 2026-08-11, which looks like test or seeding accounts; seat 11 was created 2026-07-14. Row counts have been identical (83,486) in the 2026-10-28, 2026-10-29 and 2026-11-02 snapshots and in production now.

Excluded as causes: an insertion error (ids were contiguous at insert time and the count matched the manifest until 2026-09-27); a pruning or retention job (the loss maps one-to-one to five deleted seats); the PostgreSQL migration (counts are equal before and after the cutover snapshots).

**Earlier insertions, inferred.** The verified genuine rows occupy ids 1-470 (the 2026-08-05 backup's last id is 470). The next unmatched row is id 478, created 2026-08-06; the 181 unmatched unmarked rows are scattered between id 478 and 12147. That range holds 181 rows over about 11,670 ids, so roughly 11,500 ids were consumed by rows that no longer exist. This is consistent with the generator having run, and its output having been removed, before the batch of 2026-08-12 (the generator's own comment describes an earlier batch, and `RECONSTRUCTED-ACTIVITY.md` describes the 3,288-row v1). It is an inference from the id sequence; no backup of those earlier batches was found, and their size and content cannot be established.

**Cannot be established:** who deleted the five seats, when exactly, or why. `AuditLog` begins on 2026-10-13, after four of the five removals, and the activity rows that could have recorded the actions were deleted with the seats. The 2026-08-12 14:03 pre-insert backup named in `RECONSTRUCTED-ACTIVITY.md` (`db.sqlite3.bak_manualactivity_20260812_140324`) was searched for across the whole host filesystem and **was not found**. That is an evidence gap in the original procedure, not in the present analysis.

## 3. Reconciliation of figures

### 71,886 vs 70,534 + 1,354 = 71,888

The baseline of 2026-10-30 counted 71,886 manual views (`view_node` + `view_section`). Rows created before 2026-10-30: 71,886 = 70,534 marked + 1,352 unmarked. Two further unmarked rows were created on 2026-10-31 at 04:50 (ids 116412 and 116413). Today: 70,534 + 1,354 = 71,888. The figures agree; the difference is exactly the two later rows.

### 34 vs 36 seats

36 is the number of seats: all 36 are active. 34 is the number of seats with at least one activity row (all 34 also have an unmarked row). The two seats without any activity row are internal ids 88 and 95, created 2026-09-29 and 2026-10-01, both with no recorded login. The documents that say "34 active seats" meant "34 seats with any logged activity". The spec's own wording ("34 seats with any activity") was correct; the changelog, metric definitions and evidence README shortened it.

### Seat-level counts (2026-11-02)

| Question | Including reconstructed rows | Unmarked rows only |
|---|---:|---:|
| Seats with a manual view | 26 | 12 |
| Seats with a `login` row | 31 | 17 |
| Seats with `last_login_at` null | 19 of 36 | of these 19, seats with an unmarked login row: **0** |

### The 21 unmarked rows with anomalous timestamps

Ids 115263-115288. Every one is an `account_created` event. Each row's `created_at` equals the `created_at` of the seat it belongs to, within five seconds (21 of 21), which is why the timestamps (2026-07-10 to 2026-08-11) are older than their neighbours' ids (inserted about 2026-09-22). Conclusion: back-filled account events derived from account state, not contemporaneous records and not behaviour. The application writes `account_created` with an automatic timestamp (`orggraph_api.py`), so these were not written by that code path. Who ran the back-fill is not recorded. Five other `account_created` rows (ids 115490-115600, 2026-09-28 to 2026-09-30) have ordinary timestamps. Classification: **derived**, excluded from behaviour analytics.

## 4. Classification of all 86,212 rows

| Class | Rows | Basis |
|---|---:|---|
| Known synthetic | 83,486 | marker in `detail` and inside the registered generator id range (12148-114201) |
| Verified genuine, pre-batch | 432 | match by (id, seat, action, timestamp) in the independent backup of 2026-08-05 21:30, taken before the batch (ids <= 12147, created up to 2026-08-05 13:57) |
| Derived (back-filled from state) | 21 | section 3 |
| Unverified, before the batch | 181 | ids <= 12147 created 2026-08-06 18:30 to 2026-08-12 15:16 (168 + 2 + 11); no independent backup covers them. Two rows have ids <= 8848 but timestamps of 2026-08-12 14:41, after the batch started: unexplained. |
| Unverified, after the batch | 2,092 | created 2026-08-12 15:42 to 2026-11-02; live application writes by every sign, partly corroborated (below) but not independently verified |
| **Total** | **86,212** | |

**Unmarked is not the same as genuine.** Only the 432 rows have independent confirmation from a source that predates the reconstruction. The rest are unverified, with the corroboration listed here:

- Assistant: 43 unmarked `ask_assistant` rows against 43 rows in `ChatLog` (2026-09-27 to 2026-10-27). Count-level only; rows were not matched one by one.
- Login: 19 unmarked `login` rows since 2026-10-13; 12 match an `auth.login` audit row for the same seat within 10 seconds, 7 do not (not investigated; possibly a login path the audit does not record).
- Search: `SearchLog` has 0 rows, consistent with "search used by 0".

Every unmarked row was written by seats belonging to real companies; whether any rows belong to demo or test seats has not been separated (the `is_demo` flag exists on `api_company`).

## 5. Which windows are affected today

| Window ending 2026-11-02 | Rows | Marked | Share |
|---|---:|---:|---:|
| 7 days | 82 | 0 | 0% |
| 30 days | 670 | 0 | 0% |
| 90 days | 4,267 | 1,946 | 46% |
| 180 days | 28,910 | 26,184 | 91% |
| 365 days | 73,949 | 71,223 | 96% |

Short windows are clean now because the last marked row is dated 2026-08-12; that will not remain true for any 90+ day view, and the time-based guard is accidental, not a control.

## 6. What this changes for issue #49

#49 states that 14 seats "demonstrably signed in" (login rows, latest 2026-08-12) while `last_login_at` is null. All 14 of those seats' login rows are marked; the latest date is the reconstruction batch's end date. No organic login evidence exists for them. `dormant_accounts` may therefore be correct. `last_login_at` must not be back-filled from `ActivityLog`.
