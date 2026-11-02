# Evidence preservation procedure

Status: **designed, not executed.** No backup, copy, checksum run or retention change has been made as part of this work. Every step below needs the product owner's explicit authorization first (gate G2 in `REMEDIATION_DESIGN.md`).

Revision note, 2026-11-02 (after review): the encryption step now names its input file and recipients (the earlier example had no input argument, so it would have read standard input), and the plaintext is no longer deleted until preservation has been verified (section 4, steps 7-9). Second revision: restore verification of the legacy backups is by checksum stream (no plaintext written), and the one decrypted copy that verification needs (the dump and its scratch database) lives only in an approved, access-restricted verification scratch location that is cleaned under step 7a.

## 1. What must be preserved, and where it is today

| Evidence | Why it matters | Where it is | Risk |
|---|---|---|---|
| The unaltered `api_activitylog` table, including the 83,486 reconstructed rows | the primary evidence of what is in production | production PostgreSQL | live data; changes with normal use and any future cleanup |
| Seven SQLite backups holding all 102,054 inserted rows (2026-09-19 to 2026-09-27: `pre-recover`, `pre-dropdl`, `pre-codelete-20260926`, `pre-qa10open`, `pre-qa10slim`, `pre-qa10cleanup`, `pre-qa11`) | the only complete record of rows since lost to seat deletion (18,568) | prod host, `/root/db.sqlite3.pre-*`, about 630 MB each | manual files outside the automated retention; one cleanup away from loss |
| Backups before the batch (`sec_hardening_bak_1785964985*`, 2026-08-05) | the independent basis for the 432 rows known to have existed before the batch (existence only, not attribution) | prod host, `/root` | same |
| Backups of 2026-10-28 and 2026-10-29 and the hourly snapshot | state at the PostgreSQL cutover | `/opt/KGKG_release/db-backups/`, off-host pull | the off-host retention window is itself unconfirmed (GitHub #63) |
| `gen_manual_activity.py`, `audit_after.py`, `panel_check.py`, `reconstructed_activity_manifest.json` | method and declared purpose | this repository (checksums in `CHECKSUMS.txt`) | low |
| `RECONSTRUCTED-ACTIVITY.md` | the generator's own statement that the data is synthetic | untracked file on the prod host, 6,173 bytes | not versioned; left in place |
| The pre-insert backup `db.sqlite3.bak_manualactivity_20260812_140324` named in that file | would have been the best "before" evidence | **not found** on the host | gap; cannot be recreated |

## 2. Principles

1. **Sensitive evidence never goes to GitHub.** Database dumps, raw rows, usernames, display names (they appear in `account_created` details), phone numbers, hashes and keys stay in secure backup storage. The repository holds only this documentation, checksums and counts. **No key material of any kind is committed**, including public keys and recipient lists; they are referenced by fingerprint in the authorization record only.
2. **Encrypted at rest and in transit**, with the decryption key held by named people other than the storage operator. The only exceptions are the temporary plaintext dump on the production host (steps 2 to 9) and the temporary decrypted verification copies in the approved verification scratch location (steps 7 to 7a); both are time-boxed, access-restricted and removed under the stated conditions.
3. **Restricted access**, recorded. There are **exactly two** named decryption custodians, one for each of the two required recipient keys, so that either can decrypt alone and the loss of one key does not lose the evidence. A third custodian or recipient is added only by a recorded product-owner decision (section 3).
4. **Retention controls**: a stated minimum retention, a legal-hold marker, and deletion only by recorded decision.
5. **Restore verified**, not assumed: a copy that has never been restored is a guess.
6. **Nothing is deleted until preservation is verified.** The temporary plaintext is the only copy on the host that was made for this purpose; it is removed last, after the encrypted copy has been transferred, checksummed and restored successfully (section 4, step 9).
7. **Read-only on production.** Nothing here writes to the live database or modifies existing backup files.

## 3. Pre-checks and required inputs (before any copy is made)

Record the answers in the authorization request. A missing input blocks the procedure.

- **Destination.** A storage location with encryption, access control and versioning, chosen by the product owner. The existing off-host pull target is **not** assumed suitable until its retention is confirmed (GitHub #63).
- **Encryption inputs (all required).**
  1. The **recipient list**: the public keys the dump will be encrypted to, as a file outside the repository, with each key's fingerprint recorded in the authorization. **Exactly two** recipients, so that losing one private key does not lose the evidence (a third only by recorded decision).
  2. The **decryption custodians**: exactly two named people, each holding the private key matching one recipient, and where each private key is kept (location only; never on the production host, never in git).
  3. A **key-loss and rotation plan**: who can add a recipient and re-encrypt, and how often the keys are re-confirmed.
  4. The **tool and version** (`age`, with the version recorded), installed on the operator's side, not assumed present on the host.
- **Temporary working directory.** A directory on the host used only for this operation, mode `0700`, owned by the operator, with free space of at least the plaintext dump plus the ciphertexts of the dump and of the legacy backups (about 4.5 GB in total, since ciphertext is about the size of its input). Plaintext is sensitive (display names, usernames) and must not sit in a world-readable location or in a shared temp directory.
- **Capacity.** Production host `/` on 2026-11-02: 290 GB total, 219 GB used, 71 GB free. A table-level dump is about the size of the existing full dumps (about 25 MB); seven legacy backups are about 4.4 GB in total. Neither is a capacity risk, but free space must be re-read at execution time.
- **Operational impact.** A table-level `pg_dump` takes only an ACCESS SHARE lock, so it does not block reads or writes, but it does read the whole table; run off-peak (the 7-day traffic window is about 80 rows, so the system is lightly used). Checksumming the legacy backups reads about 4.4 GB once; run with `nice` and `ionice`.
- **Verification scratch location (VSL), required.** The restore test needs the dump decrypted and a scratch database. That is the **one** place where decrypted evidence may exist outside the production host, and it is only acceptable if it is named and approved in advance and meets all of these:
  1. **Not the production host, and not shared infrastructure.** The production host also runs staging, QA and observability (GitHub #25), so a staging container on it does not qualify. Not a CI runner, not a shared server, not a cloud workspace others can open.
  2. **Access-restricted to the named custodian only**: a single-user account, directory mode `0700`, no group or other access, no remote mounts.
  3. **Encrypted storage**: full-disk encryption or an encrypted volume (or a RAM-backed filesystem sized for the work), so that deleted bytes are not recoverable from the device.
  4. **Excluded from everything that copies data**: cloud sync, backup agents, volume snapshots and shadow copies, search indexing and antivirus uploads.
  5. **Capacity**, re-read at execution time. Baseline for the default procedure: the decrypted dump plus a scratch database plus working space (the dump is about 25 MB; allow 1 GB). Legacy backups are verified by checksum stream and need no space. **If a custodian chooses the optional read-only open of a legacy backup (step 7), that decrypted file also lives here:** add its size (about 630 MB per file) plus working space, so allow about 2 GB, and open only one backup at a time, deleting it before the next.
  6. **Time-boxed**: decrypted material exists only while step 7 runs and is removed under step 7a.
  7. **Recorded**: the location's identity (not its path secrets), the custodian, and the dates are written into the evidence entry.
- **Authorization.** Written approval in GitHub #64 naming the destination, the recipient fingerprints, the custodians, the retention period, the verification scratch location, and the result of the non-production rehearsal required by section 4.1.

## 4. Procedure (when authorized)

Run by a person with host access, never by an unattended job. Commands are templates; fill in the approved paths. `<date>`, `<recipients-file>` and the destination are the approved inputs from section 3.

1. **Open the exporter session and take the reference state inside it.** The reference values and the dump must come from the **same** consistent snapshot, otherwise a row written between "count" and "dump" makes a correct restore look like a failure. One database session exports a snapshot and stays open; the reference queries run inside it; the dump imports it (section 4.1 explains why, and the failure handling).
   ```
   umask 077
   mkfifo <tmpdir>/ctl
   psql -X -At -v ON_ERROR_STOP=1 <approved connection> < <tmpdir>/ctl > <tmpdir>/exporter.out 2>&1 &
   exec 3> <tmpdir>/ctl
   ```
   Send these to the session through descriptor 3 (for example with `printf '%s\n' ... >&3`), in this order, and read the outputs from `exporter.out`:
   ```
   SET idle_in_transaction_session_timeout = '15min';
   SET client_encoding = 'UTF8';
   BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
   SELECT pg_export_snapshot();
   SELECT count(*), min(id), max(id),
          count(*) FILTER (WHERE detail LIKE '%بازسازی%'),
          encode(sha256(convert_to(string_agg(id::text, ',' ORDER BY id), 'UTF8')), 'hex')
   FROM api_activitylog;
   ```
   Record the snapshot identifier and the five reference values: row count, minimum id, maximum id, marker-row count, and the SHA-256 of the ordered id list (a text of ids separated by commas, in ascending order). On 2026-11-02 the first four read 86,212 / 1 / 116,419 / 83,486; they will differ if the table has grown, which is fine; record what is found. **Leave the transaction open** until step 2 has finished.
2. **Dump the one table from that same snapshot**, into the temporary directory:
   ```
   pg_dump --format=custom --table=public.api_activitylog --snapshot=<snapshot-id> --file=activitylog-<date>.dump <approved connection>
   ```
   Do **not** add `--serializable-deferrable`: the PostgreSQL 16 documentation does not say whether it can be combined with `--snapshot`. When `pg_dump` has exited successfully, send `COMMIT;` and `\q` to the exporter session through descriptor 3, close the descriptor, and confirm in `exporter.out` that the commit was acknowledged and the session ended normally.
3. **Checksum** the plaintext dump: `sha256sum activitylog-<date>.dump`, and record its size.
4. **Encrypt, naming the input file explicitly.** `age` reads standard input when no input file is given, so the input must be an argument:
   ```
   age --encrypt -R <recipients-file> -o activitylog-<date>.dump.age activitylog-<date>.dump
   ```
   Then check that the ciphertext exists, is not empty, is close to the plaintext size, and record `sha256sum activitylog-<date>.dump.age`. **Do not delete the plaintext.** The host cannot prove the ciphertext decrypts to the dump; only a custodian's restore (step 7) can.
5. **Preserve the seven legacy SQLite backups and the 2026-08-05 pre-batch backups by encrypting at the source, never by copying plaintext.** For each original: record `sha256sum` and size in place (read-only), then encrypt it, naming the input file explicitly, into the temporary directory:
   ```
   age --encrypt -R <recipients-file> -o <name>.age <original-backup-file>
   ```
   Only the `.age` files are transferred. **No plaintext copy of any legacy backup is made on the production host, at the destination, or in any shared location**: these files contain personal data (usernames, display names, phone numbers, password hashes) and must not exist unencrypted outside their current location. The only permitted exception is a temporary, optional decrypted verification copy inside the verification scratch location, under the rules in section 3 and step 7; by default none is made, because step 7 verifies legacy backups by checksum stream. The originals stay exactly where they are.
6. **Transfer** the ciphertexts over an authenticated, encrypted channel to the approved location. Confirm the destination checksum equals the host's ciphertext checksum.
7. **Restore verification, by a custodian, off the production host, inside the approved verification scratch location (VSL, section 3).**
   - **Activity-log dump.** Decrypt it into the VSL, restore it with `pg_restore --no-owner --exit-on-error --section=pre-data --section=data -d <scratch-database>` (only the table definition and its rows: the documentation places indexes and constraints, including the foreign key to the seat table, in the post-data section, and says a table-only restore makes no attempt to restore what the table depends on, so constraints are deliberately not restored; the reference values do not depend on them), into a scratch database whose data lives inside the VSL (never production, and never a container on the production host: staging and production share that host, GitHub #25), and run the **same reference query** as in step 1 on the restored table (with `client_encoding` set to UTF8). All five values (row count, minimum id, maximum id, marker-row count, SHA-256 of the ordered id list) must equal the step 1 values exactly. They are comparable because step 1 took them inside the snapshot the dump was made from.
   - **Legacy backups: by checksum stream, with no plaintext written.** For **every** legacy backup, decrypt as a stream straight into the hash and compare it with the checksum of the original recorded in step 5:
     ```
     age --decrypt -i <identity-file> <name>.age | sha256sum
     ```
     Equality proves the ciphertext decrypts to the original byte for byte, which is the property that matters. Nothing is materialized, so nothing needs cleanup. Opening a legacy backup and counting its rows is **optional**, adds nothing the checksum does not prove, and if a custodian nonetheless chooses to do it, the decrypted file lives only in the VSL, is opened read-only, and is deleted immediately.
   - Record pass or fail, the date, the custodian, and the hash comparison results.
7a. **Clean up the verification scratch location, immediately after step 7 whatever its result** (a failed verification is repeated from the ciphertext; it is not a reason to keep decrypted copies): delete every decrypted file and intermediate, drop the scratch database and remove its data directory, empty the VSL, and confirm that nothing remains in the trash, in snapshots or shadow copies, in backup jobs, in search indexes or in any sync client. A second person confirms in writing, and the cleanup is recorded in the evidence entry with the limit that deletion on journaling and copy-on-write filesystems does not guarantee the bytes are gone (which is why the VSL is encrypted storage).
8. **Retention and custody.** Set the retention period and legal-hold flag at the destination; record custodians and key locations (locations only) outside GitHub.
9. **Clean up the temporary plaintext, only if all of these hold:**
   - the ciphertext at the destination has the same checksum as the host's ciphertext (step 6);
   - the restore verification passed and is recorded (step 7);
   - the verification scratch location has been cleaned and confirmed (step 7a);
   - a second person confirms these in writing;
   - the metadata for `CHECKSUMS.txt` is prepared (step 10).

   Then delete the plaintext dump and the temporary ciphertext copies (including those of the legacy backups, which are duplicates of what is now at the destination) from the temporary directory and remove the directory. The original legacy backups and every original file are never touched. File deletion on journaling or copy-on-write filesystems does not guarantee the bytes are gone; the limit is recorded in the evidence entry, and is why the plaintext stays in a `0700` directory for as short a time as possible.

   **If any condition fails**, the plaintext stays in the restricted directory, and the operation is repeated or the problem is resolved first. The plaintext is never deleted on the strength of the host's own checks. The production table remains the source, and nothing here changes it.
10. **Publish only the metadata**: add a dated table of file names, sizes, SHA-256 (plaintext and ciphertext), row counts, the age version, recipient fingerprints and the restore-verification result to `CHECKSUMS.txt` via a normal reviewed PR.
11. **Protect the originals.** Only after steps 1-10 are verified and with separate approval: mark the legacy backups on the host read-only. Never delete them as part of this work.

### 4.1 Snapshot mechanics, transaction lifetime and failure handling

**Checked against the PostgreSQL 16 documentation** (the production server read as 16.15 on 2026-11-02). Established by the documentation:

- `pg_export_snapshot()` returns a snapshot identifier, and the snapshot "is available for import only until the end of the transaction that exported it". In `REPEATABLE READ` and higher isolation levels a transaction uses one snapshot throughout its lifetime, so the reference queries in the exporting transaction see exactly the data the exported snapshot shows.
- `SET TRANSACTION SNAPSHOT` imports a snapshot only at the start of a transaction, in `REPEATABLE READ` or `SERIALIZABLE`; if the importer is `SERIALIZABLE` the exporter must be too. The exporter here is `REPEATABLE READ`, and `pg_dump` is run without `--serializable-deferrable`, so there is no isolation mismatch to trigger.
- `pg_dump --snapshot=<name>` "use[s] the specified synchronized snapshot when making a dump of the database". `--table` / `-t` dumps only the named table and no dependent objects (the table definition is in the archive; nothing else is). `--file` writes the archive. `pg_dump` refuses to dump a server with a newer major version than its own.
- `sha256(bytea)`, `convert_to(text, name)`, `encode(bytea, 'hex')` and the aggregate `string_agg` exist in the documented functions, which is why the id-list checksum is computed in SQL.
- `idle_in_transaction_session_timeout` terminates a session that stays idle in an open transaction longer than the set time (default 0, disabled); an open transaction also holds back cleanup of recently dead rows, which is why the exporter must not stay open long.
- `psql`'s `\!` runs a shell command with **no** variable interpolation of its argument (the remainder of the line is passed literally to the shell). That is why the snapshot identifier is not passed to `pg_dump` from inside one psql script, and why the exporter is a held session fed through a pipe. The documentation does not say whether `\setenv` interpolates, and does not describe an open transaction while `\!` runs, so neither is relied on.

- `pg_restore --section` accepts `pre-data`, `data` and `post-data`; "post-data items consist of definitions of indexes, triggers, rules and constraints"; `--no-owner` skips ownership commands; `--exit-on-error` stops at the first SQL error; `-d` restores directly into a database; and "there is no guarantee that a specific-table restore into a clean database will succeed" because dependencies are not restored.

**Not stated by the documentation, therefore not assumed:** which isolation level `pg_dump` uses by default; whether `--snapshot` combines with `--serializable-deferrable`; whether an importing `pg_dump` needs the exporter to stay open after it has imported (the procedure keeps the exporter open until `pg_dump` has exited, which covers it); and whether a table-only archive of `api_activitylog` restores its `id` default without the owning sequence (the rehearsal must show the pre-data restore succeeds; if it does not, the sequence is added to the dump as a second `--table` and the rehearsal is repeated, and this document is corrected).

**Required before G2 execution:** a rehearsal of exactly these commands on a **non-production** PostgreSQL 16 database with a table of similar shape, by the operator, recording `psql --version`, `pg_dump --version` (its major version must be at least the server's), the outcome, and that the restore reproduces all five reference values. This is a precondition, not something this document claims has been done.

**Transaction lifetime.** The exporter transaction exists from the `BEGIN` in step 1 to the `COMMIT` after `pg_dump` has exited, which for a table of this size is expected to be seconds to a few minutes. The 15-minute idle timeout is a ceiling, not a target. A longer life holds back vacuum cleanup on the whole database, so do not leave it open while waiting for a person.

**Failure handling.** Each attempt is numbered and logged. The five reference values and the dump of one attempt are used **only together**; values from one attempt are never paired with a dump from another.

| Event | Action |
|---|---|
| the exporter session cannot start, or `pg_export_snapshot()` errors | stop; nothing was created; fix and start a new attempt |
| `pg_dump` exits non-zero, or reports an invalid or unimportable snapshot | the attempt failed: send `ROLLBACK;` to the exporter, delete the partial output (it is not the preserved evidence), discard that attempt's reference values, record the failure and the message, and start a new attempt with a new snapshot |
| the exporter session ended before `pg_dump` exited (timeout, connection loss), even if `pg_dump` reported success | treat the attempt as failed, because the snapshot's validity is not confirmed; same action as the row above |
| the exporter did not acknowledge `COMMIT` after `pg_dump` succeeded | treat as failed; do not use the dump |
| the restore in step 7 does not reproduce all five values | do not delete anything; keep the ciphertext, the plaintext dump and the logs; investigate; this is a failed verification, and step 9 does not run |
| three attempts fail in a row | stop and escalate to the product owner; do not improvise a different method |

Nothing in a failure path touches production data: the exporter is read-only, `pg_dump` only reads, and the originals are never modified.

## 5. Acceptance

- A dated entry exists with the destination, retention period, custodians, recipient fingerprints and a passed restore verification.
- The reference values were taken inside the same exported snapshot as the dump, the attempt numbers and any failed attempts are recorded, and the restore reproduced all five values exactly.
- The temporary plaintext was removed only after the checks in step 9, and the entry says so.
- The verification scratch location was named and approved beforehand, used only by the named custodian, and cleaned and confirmed under step 7a; the entry records this.
- Every legacy backup was verified by checksum stream against the original's recorded SHA-256.
- `CHECKSUMS.txt` lists every preserved artifact with checksums.
- No dump, raw row, credential or key material is in git history.
- Production behaviour and data are unchanged.

## 6. Known limits

- The pre-insert backup of 2026-08-12 cannot be preserved because it is not on the host.
- Rows lost to the five seat deletions survive only in the legacy backups; this procedure is what keeps them.
- The off-host mirror's own retention is unverified; do not treat it as the evidence store until GitHub #63 is closed.
- Decrypted evidence also exists briefly in the verification scratch location during step 7. Its protection depends on the custodian's device or volume meeting section 3, which this document can require but cannot verify.
- The plaintext dump exists on the production host for the duration of steps 2-9. That exposure is the cost of verifying before deleting; the restricted directory and short duration limit it.
