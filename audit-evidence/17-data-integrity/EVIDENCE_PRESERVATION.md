# Evidence preservation procedure

Status: **designed, not executed.** No backup, copy, checksum run or retention change has been made as part of this work. Every step below needs the product owner's explicit authorization first (gate G2 in `REMEDIATION_DESIGN.md`).

## 1. What must be preserved, and where it is today

| Evidence | Why it matters | Where it is | Risk |
|---|---|---|---|
| The unaltered `api_activitylog` table, including the 83,486 reconstructed rows | the primary evidence of what is in production | production PostgreSQL | live data; changes with normal use and any future cleanup |
| Seven SQLite backups holding all 102,054 inserted rows (2026-09-19 to 2026-09-27: `pre-recover`, `pre-dropdl`, `pre-codelete-20260926`, `pre-qa10open`, `pre-qa10slim`, `pre-qa10cleanup`, `pre-qa11`) | the only complete record of rows since lost to seat deletion (18,568) | prod host, `/root/db.sqlite3.pre-*`, about 630 MB each | manual files outside the automated retention; one cleanup away from loss |
| Backups before the batch (`sec_hardening_bak_1785964985*`, 2026-08-05) | the independent basis for the 432 verified rows | prod host, `/root` | same |
| Backups of 2026-10-28 and 2026-10-29 and the hourly snapshot | state at the PostgreSQL cutover | `/opt/KGKG_release/db-backups/`, off-host pull | the off-host retention window is itself unconfirmed (GitHub #63) |
| `gen_manual_activity.py`, `audit_after.py`, `panel_check.py`, `reconstructed_activity_manifest.json` | method and declared purpose | this repository (checksums in `CHECKSUMS.txt`) | low |
| `RECONSTRUCTED-ACTIVITY.md` | the generator's own statement that the data is synthetic | untracked file on the prod host, 6,173 bytes | not versioned; left in place |
| The pre-insert backup `db.sqlite3.bak_manualactivity_20260812_140324` named in that file | would have been the best "before" evidence | **not found** on the host | gap; cannot be recreated |

## 2. Principles

1. **Sensitive evidence never goes to GitHub.** Database dumps, raw rows, usernames, display names (they appear in `account_created` details), phone numbers, hashes and keys stay in secure backup storage. The repository holds only this documentation, checksums and counts.
2. **Encrypted at rest and in transit**, with the decryption key held by named people other than the storage operator.
3. **Restricted access**, recorded; two named custodians at most.
4. **Retention controls**: a stated minimum retention, a legal-hold marker, and deletion only by recorded decision.
5. **Restore verified**, not assumed: a copy that has never been restored is a guess.
6. **Read-only on production.** Nothing here writes to the live database or modifies existing backup files.

## 3. Pre-checks (before any copy is made)

Record the answers in the authorization request:

- **Destination.** A storage location with encryption, access control and versioning, chosen by the product owner. The existing off-host pull target is **not** assumed suitable until its retention is confirmed (GitHub #63).
- **Capacity.** Production host `/` on 2026-11-02: 290 GB total, 219 GB used, 71 GB free. A table-level dump is about the size of the existing full dumps (about 25 MB); seven legacy backups are about 4.4 GB in total. Neither is a capacity risk, but free space must be re-read at execution time.
- **Operational impact.** A table-level `pg_dump` takes only an ACCESS SHARE lock, so it does not block reads or writes, but it does read the whole table; run off-peak (the 7-day traffic window is about 80 rows, so the system is lightly used). Checksumming the legacy backups reads about 4.4 GB once; run with `nice` and `ionice`.
- **Authorization.** Written approval in GitHub #64 naming the destination, the key custodians and the retention period.

## 4. Procedure (when authorized)

Run by a person with host access, never by an unattended job. Commands are templates; fill in the approved paths.

1. **Freeze the reference state (read-only counts).** Record row count, id range and marker count of `api_activitylog` (expected on 2026-11-02: 86,212 / 1..116419 / 83,486; they will differ if the table has grown, which is fine; record what is found).
2. **Dump the one table**, consistent snapshot:
   ```
   pg_dump --format=custom --table=api_activitylog --serializable-deferrable <approved connection> > activitylog-<date>.dump
   ```
3. **Checksum** the plaintext dump: `sha256sum activitylog-<date>.dump`.
4. **Encrypt** with the approved recipient keys (for example `age -r <recipient> -o activitylog-<date>.dump.age`), checksum the ciphertext, and delete the plaintext from the host.
5. **Copy the seven legacy SQLite backups and the 2026-08-05 pre-batch backups** unchanged to the same destination (read-only source, `rsync --checksum` or `cp --reflink=never` then compare), checksum each, encrypt in the same way.
6. **Transfer** to the approved location over an authenticated, encrypted channel.
7. **Restore verification**, in a scratch database that is not production (a staging container is acceptable): decrypt, restore, and compare: total rows, marker count, id range, and a checksum of the ordered id list, against step 1. Record pass or fail and the date.
8. **Retention and custody.** Set the retention period and legal-hold flag at the destination; record custodians and key location (location only) outside GitHub.
9. **Publish only the metadata**: add a dated table of file names, sizes, SHA-256 (plaintext and ciphertext), row counts and the restore-verification result to `CHECKSUMS.txt` via a normal reviewed PR.
10. **Protect the originals.** Only after steps 1-9 are verified and with separate approval: mark the legacy backups on the host read-only. Never delete them as part of this work.

## 5. Acceptance

- A dated entry exists with the destination, retention period, custodians and a passed restore verification.
- `CHECKSUMS.txt` lists every preserved artifact with checksums.
- No dump, raw row or credential is in git history.
- Production behaviour and data are unchanged.

## 6. Known limits

- The pre-insert backup of 2026-08-12 cannot be preserved because it is not on the host.
- Rows lost to the five seat deletions survive only in the legacy backups; this procedure is what keeps them.
- The off-host mirror's own retention is unverified; do not treat it as the evidence store until GitHub #63 is closed.
