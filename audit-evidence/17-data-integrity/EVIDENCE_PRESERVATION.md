# Evidence preservation procedure

Status: **designed, not executed.** No backup, copy, checksum run or retention change has been made as part of this work. Every step below needs the product owner's explicit authorization first (gate G2 in `REMEDIATION_DESIGN.md`).

Revision note, 2026-11-02 (after review): the encryption step now names its input file and recipients (the earlier example had no input argument, so it would have read standard input), and the plaintext is no longer deleted until preservation has been verified (section 4, steps 7-9). Second revision: restore verification of the legacy backups is by checksum stream (no plaintext written), and the one decrypted copy that verification needs (the dump and its scratch database) lives only in an approved, access-restricted verification scratch location that is cleaned under step 7a.

Third revision, 2026-11-03 (after review): (1) the snapshot identifier and reference values are written by psql to files (`\g`) while the exporting transaction is still open, instead of being read from a redirected log that might not be flushed until the session ends; whether that works is a rehearsal item, not an assumption. (2) Every attempt has its own directory and its own record binding the snapshot identifier, the reference values and the dump's SHA-256; a retry never reuses or overwrites an earlier attempt's files, and later steps refuse a directory that fails the gate in step 3. (3) Restore verification now compares the decrypted dump's SHA-256 with the recorded plaintext hash (archive integrity) before it compares restored content, and section 4.2 assesses an optional full-row content checksum. (4) The scratch database must be UTF-8.

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
- **Temporary working directory.** A directory on the host used only for this operation, mode `0700`, owned by the operator, holding one subdirectory per attempt (step 1), with free space of at least the plaintext dump plus the ciphertexts of the dump and of the legacy backups (about 4.5 GB in total, since ciphertext is about the size of its input), plus about 60 MB for each further attempt allowed by section 4.1 (at most three). Plaintext is sensitive (display names, usernames) and must not sit in a world-readable location or in a shared temp directory.
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
- **Authorization.** Written approval in GitHub #64 naming the destination, the recipient fingerprints, the custodians, the retention period, the verification scratch location, and the result of the non-production rehearsal required by section 4.1 (every item in its list, with the tool versions and the outcome of each check; the rehearsal uses synthetic data and never a copy of production).

## 4. Procedure (when authorized)

Run by a person with host access, never by an unattended job. Commands are templates; fill in the approved paths. `<date>`, `<recipients-file>` and the destination are the approved inputs from section 3.

1. **Create the attempt directory, open the exporter session and take the reference state inside it.** The reference values and the dump must come from the **same** consistent snapshot, otherwise a row written between "count" and "dump" makes a correct restore look like a failure. One database session exports a snapshot and stays open; the reference queries run inside it and their results are written to files while it is open; the dump imports the snapshot (section 4.1 explains why, and the failure handling). Every file of one attempt lives in that attempt's own directory, so attempts cannot overwrite or be mixed with each other.
   ```
   umask 077
   set -o noclobber                 # '>' refuses to overwrite an existing file
   A=<tmpdir>/attempt-<NN>          # NN = 01, 02, 03 ...; a number is never reused
   mkdir "$A"                       # no -p: fails if the directory already exists
   mkfifo "$A/ctl"
   psql -X -At -v ON_ERROR_STOP=1 <approved connection> < "$A/ctl" > "$A/exporter.log" 2>&1 &
   EXPORTER_PID=$!
   exec 3> "$A/ctl"
   ```
   If `mkdir` fails, stop: the number is taken. Send these lines to the session through descriptor 3 (for example with `printf '%s\n' ... >&3`), in this order. `<A>` stands for the absolute path of the attempt directory, written into the line by the operator, because psql does not expand shell variables:
   ```
   SET idle_in_transaction_session_timeout = '15min';
   SET client_encoding = 'UTF8';
   SET TimeZone = 'UTC';
   BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
   SELECT pg_export_snapshot() \g <A>/snapshot.id
   SELECT count(*), min(id), max(id),
          count(*) FILTER (WHERE detail LIKE '%بازسازی%'),
          encode(sha256(convert_to(string_agg(id::text, ',' ORDER BY id), 'UTF8')), 'hex')
   FROM api_activitylog \g <A>/reference.txt
   ```
   (`\g <file>` sends the query and writes its output to the file instead of the terminal; the PostgreSQL 16 documentation says so, and says the file is written only if the query succeeds. It does **not** say when the file is closed or flushed, whether an existing file is overwritten, or how a relative name resolves, which is why the names are absolute and new, and why the rehearsal checks this.) If the content checksum of section 4.2 has been validated by the rehearsal, also send it with `\g <A>/content.txt`.

   **Wait until `snapshot.id` and `reference.txt` exist, are non-empty and complete, read by a separate process while the transaction is still open** (poll with `test -s` for up to about 60 seconds). If they are not readable in that time, the method does not work as designed: the attempt has failed (section 4.1), and the procedure is not to be executed until the rehearsal has shown a method that works. Ending the session to look at its output is not allowed, because that ends the snapshot.

   Then write the attempt's **record**, built by command and not typed, so values cannot be mistyped or mixed:
   ```
   {
     echo "attempt=<NN>"
     echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
     echo "tool_versions=$(psql --version); $(pg_dump --version); $(age --version)"
     echo "snapshot_id=$(cat "$A/snapshot.id")"
     echo "reference=$(cat "$A/reference.txt")"     # count|min id|max id|marker count|sha256 of ordered ids
   } > "$A/record.txt"
   ```
   On 2026-11-02 the first four reference values read 86,212 / 1 / 116,419 / 83,486; they will differ if the table has grown, which is fine; record what is found. The fifth is the SHA-256 of the ordered id list (a text of ids separated by commas, in ascending order). **Leave the transaction open** until step 2 has finished.
2. **Dump the one table from that same snapshot**, into the attempt directory:
   ```
   pg_dump --format=custom --table=public.api_activitylog --snapshot="$(cat "$A/snapshot.id")" --file="$A/activitylog-<date>-a<NN>.dump" <approved connection> 2> "$A/pg_dump.log"
   ```
   Do **not** add `--serializable-deferrable`: the PostgreSQL 16 documentation does not say whether it can be combined with `--snapshot`. When `pg_dump` has exited successfully, send `COMMIT;` and `\q` to the exporter session through descriptor 3, close the descriptor, run `wait "$EXPORTER_PID"`, and confirm that its exit status is 0 and that `exporter.log` shows the commit was acknowledged and the session ended normally. Append `exporter_exit=<status>` to the record.
3. **Checksum the plaintext dump and close the gate for this attempt.** Compute `sha256sum` of the dump and record its size, appending both to `record.txt` (`>>`), then make the dump read-only (`chmod 0400`). The record now binds, for this attempt only: the snapshot identifier, the reference values, the dump file name, size and SHA-256. **Gate:** every later step that uses the dump (4, 6, 7, 9, 10) first checks, in this attempt directory, that (a) no `FAILED` marker exists, (b) exactly one `*.dump` file exists and its name equals the one in the record, (c) a fresh `sha256sum` of it equals the recorded value, and (d) the record shows `exporter_exit=0`. A directory that fails any check is not used. The plaintext SHA-256 recorded here is the value that the decrypted dump is compared with in step 7.
4. **Encrypt, naming the input file explicitly.** `age` reads standard input when no input file is given, so the input must be an argument:
   ```
   age --encrypt -R <recipients-file> -o "$A/activitylog-<date>-a<NN>.dump.age" "$A/activitylog-<date>-a<NN>.dump"
   ```
   Then check that the ciphertext exists, is not empty, is close to the plaintext size, and append its `sha256sum` and size to the record. **Do not delete the plaintext.** The host cannot prove the ciphertext decrypts to the dump; only a custodian's restore (step 7) can.
5. **Preserve the seven legacy SQLite backups and the 2026-08-05 pre-batch backups by encrypting at the source, never by copying plaintext.** For each original: record `sha256sum` and size in place (read-only), then encrypt it, naming the input file explicitly, into the temporary directory:
   ```
   age --encrypt -R <recipients-file> -o <name>.age <original-backup-file>
   ```
   The original's checksum and size, and each ciphertext's checksum and size, go into a separate `legacy-record.txt` (created with `>`, extended with `>>`, never rewritten; a repeated encryption adds a new line and keeps the old). The `.age` files are written into their own new directory, not into any attempt directory, and a file that already exists is not overwritten. Only the `.age` files are transferred. **No plaintext copy of any legacy backup is made on the production host, at the destination, or in any shared location**: these files contain personal data (usernames, display names, phone numbers, password hashes) and must not exist unencrypted outside their current location. The only permitted exception is a temporary, optional decrypted verification copy inside the verification scratch location, under the rules in section 3 and step 7; by default none is made, because step 7 verifies legacy backups by checksum stream. The originals stay exactly where they are.
6. **Transfer** the ciphertexts over an authenticated, encrypted channel to the approved location. Confirm the destination checksum equals the ciphertext checksum in the record.
7. **Restore verification, by a custodian, off the production host, inside the approved verification scratch location (VSL, section 3).**
   - **Activity-log dump, archive integrity first.** Decrypt it as a stream into the hash, without writing plaintext, and compare with the plaintext SHA-256 in the attempt record (step 3): `age --decrypt -i <identity-file> activitylog-<date>-a<NN>.dump.age | sha256sum`. Equality shows that the ciphertext is intact, that the custodian's key decrypts it, and that the result is byte for byte the dump the host hashed in step 3. It says **nothing** about whether that dump holds the right table content. If it differs, stop: do not restore, and treat the verification as failed.
   - **Activity-log dump, restored content second.** Decrypt it into the VSL, hash the decrypted file again and compare with the same recorded value (a mismatch means the copy in the VSL is not the dump), then restore it with `pg_restore --no-owner --exit-on-error --section=pre-data --section=data -d <scratch-database>` (only the table definition and its rows: the documentation places indexes and constraints, including the foreign key to the seat table, in the post-data section, and says a table-only restore makes no attempt to restore what the table depends on, so constraints are deliberately not restored; the reference values do not depend on them), into a scratch database whose data lives inside the VSL (never production, and never a container on the production host: staging and production share that host, GitHub #25). **The scratch database must be UTF-8:** create it with `createdb --template=template0 --encoding=UTF8`, and before restoring confirm `SHOW server_encoding;` returns `UTF8` (the marker count and the content checksum assume it; a different encoding can fail the restore or change the text, and a result from such a database is not accepted). Run the **same reference query** as in step 1 on the restored table, in a session with `client_encoding` UTF8 and `TimeZone` UTC. All five values (row count, minimum id, maximum id, marker-row count, SHA-256 of the ordered id list) must equal the record's values exactly, and so must the content checksum if section 4.2 applies. They are comparable because step 1 took them inside the snapshot the dump was made from. Record `pg_restore --version`.
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

**Required before G2 execution: the non-production rehearsal.** It is **not executed**; nothing in this document claims it has been done, and until it has passed, every statement here that a method works is a design, not a result. It runs exactly these commands on a **non-production** PostgreSQL 16 database (never a copy of production) holding a table of the same shape filled with synthetic rows that include Persian text, NULLs, empty strings, quotes, backslashes and microsecond timestamps, with a throwaway `age` key pair (never a custodian's key). It records `psql --version`, `pg_dump --version` (major version at least the server's), `pg_restore --version`, `age --version`, and the outcome of each item:

1. **Readable while open.** `snapshot.id` and `reference.txt` (and `content.txt`) are complete and readable by another process while the exporter transaction is still open, and how long that takes. If not, the method is changed and this document corrected.
2. **Snapshot binding.** With the exporter open, another session inserts and updates rows; the dump and the reference values contain none of those changes.
3. **Lifetime.** `pg_dump --snapshot` succeeds while the exporter is open; the `COMMIT` is acknowledged and the exporter's exit status is 0; with a deliberately short idle timeout, a timed-out exporter is detected as a failed attempt.
4. **Attempt isolation.** A forced failure (kill `pg_dump`) leaves a `FAILED` marker and the gate refuses that directory; a second attempt uses a new directory and the first attempt's files are byte for byte unchanged; a dump copied into another attempt's directory is rejected by the gate.
5. **Round trip.** Encrypt, decrypt as a stream, and the SHA-256 equals the record; a copy of the ciphertext with one byte changed fails to decrypt or does not match.
6. **Restore.** Into a UTF-8 scratch database, `pg_restore --section=pre-data --section=data` succeeds and the five values equal the record; whether the `id` default restores without its sequence is observed (if not, the sequence is added as a second `--table` and the rehearsal repeated). A scratch database in another encoding is also tried, to show what the UTF-8 requirement prevents.
7. **Content checksum (section 4.2).** The same expression gives the same value twice on the source table and the same value on the restored table; after changing one column of one row in the restored copy (one character of `detail`, or one microsecond of `created_at`) the content checksum differs while the five reference values do not.

The G2 request attaches this record. A failed item is a finding, not something to work around silently.

**Transaction lifetime.** The exporter transaction exists from the `BEGIN` in step 1 to the `COMMIT` after `pg_dump` has exited, which for a table of this size is expected to be seconds to a few minutes. The 15-minute idle timeout is a ceiling, not a target. A longer life holds back vacuum cleanup on the whole database, so do not leave it open while waiting for a person.

**Failure handling.** Each attempt has its own numbered directory and record (step 1). The snapshot identifier, the five reference values and the dump of one attempt are used **only together**; values from one attempt are never paired with a dump from another, and a retry never writes into an earlier attempt's directory.

| Event | Action |
|---|---|
| the exporter session cannot start, `mkdir` of the attempt directory fails, or `pg_export_snapshot()` errors | stop; nothing was created that is evidence; fix and start a new attempt with a new number |
| `snapshot.id` or `reference.txt` is not readable and complete while the transaction is open | the attempt failed and the method is not working as rehearsed: send `ROLLBACK;` and follow the failed-attempt action below; do not proceed until the rehearsal is repeated |
| `pg_dump` exits non-zero, or reports an invalid or unimportable snapshot | the attempt failed: send `ROLLBACK;` to the exporter, write a `FAILED` marker (with the reason) into the attempt directory, delete that attempt's partial or complete dump (a failed attempt's dump is never kept, encrypted or reused), keep its record and logs, and start a new attempt in a **new** directory with a new snapshot; the failed attempt's reference values are never paired with another attempt's dump |
| the exporter session ended before `pg_dump` exited (timeout, connection loss), even if `pg_dump` reported success | treat the attempt as failed, because the snapshot's validity is not confirmed; same action as the row above |
| the exporter did not acknowledge `COMMIT` after `pg_dump` succeeded | treat as failed; do not use the dump |
| the gate in step 3 fails at any later step (marker present, extra or renamed dump, checksum differs from the record) | stop; treat the directory as failed and investigate before any new attempt; never copy a dump between attempt directories |
| the decrypted dump's SHA-256 differs from the recorded plaintext SHA-256 | verification failed; do not restore; keep everything; step 9 does not run |
| the restore in step 7 does not reproduce all five values (or the content checksum, where used) | do not delete anything; keep the ciphertext, the plaintext dump and the logs; investigate; this is a failed verification, and step 9 does not run |
| three attempts fail in a row | stop and escalate to the product owner; do not improvise a different method |
| a later attempt succeeds after an earlier one produced files | exactly one attempt is designated the evidence attempt in the final entry; every number in the entry comes from that attempt's own directory; other attempts' files stay until a recorded decision |

Nothing in a failure path touches production data: the exporter is read-only, `pg_dump` only reads, and the originals are never modified.

### 4.2 Full-row content checksum: feasibility assessment

**Why consider it.** The five reference values cover the number of rows, the id range, the marker count and the ordered list of ids. A dump in which any other column was changed, truncated or mis-encoded would still reproduce all five. Two different things are being checked, and they must not be confused:

- **Archive integrity** is shown by the dump's SHA-256 (step 3) matching after decryption (step 7): the bytes were preserved. It proves nothing about what the bytes contain.
- **Restored content** is shown by recomputing values from the restored table and comparing them with values taken from the source snapshot. The five values do this for ids and the marker; a content checksum would extend it to the other columns.

**Assessment: feasible, proposed, not yet demonstrated.** The checksum can be computed in the exporter transaction, over the same snapshot, and for a table of this size should take seconds:

```
SELECT encode(sha256(convert_to(string_agg(
         encode(sha256(convert_to(
           quote_nullable(id) || ',' || quote_nullable(user_id) || ',' || quote_nullable(action) || ',' ||
           quote_nullable(detail) || ',' || quote_nullable(category) || ',' || quote_nullable(car_id) || ',' ||
           quote_nullable(node_title) || ',' || quote_nullable(app_url) || ',' ||
           quote_nullable(to_char(created_at, 'YYYY-MM-DD"T"HH24:MI:SS.US')), 'UTF8')), 'hex'),
         ',' ORDER BY id), 'UTF8')), 'hex')
FROM api_activitylog;
```

What it relies on, and what is not assumed:

- **Stable ordering.** `ORDER BY id` is a total order only if `id` is unique (it is the primary key per the model; the rehearsal confirms it on the actual definition). It is an integer, so it does not depend on collation.
- **Unambiguous serialization.** `quote_nullable` separates NULL from the empty string and escapes quotes and backslashes, so field boundaries cannot be forged by the data. Each row is hashed first, so the aggregate stays small and a changed row changes the result.
- **Encoding.** `convert_to(..., 'UTF8')` assumes a UTF-8 database (hence the UTF-8 requirement on the scratch database) and a session `client_encoding` of UTF8.
- **Time.** `created_at` is rendered after `SET TimeZone = 'UTC'` with a fixed format that keeps microseconds. The actual column types are read from the catalog (read-only) at the start of the attempt, and the expression is adjusted and recorded if they differ from these assumptions.
- **Coverage.** Only the listed columns are covered (the nine original columns, as in `TEST_PLAN.md` D1). Before the attempt the table's actual column list is read from the catalog; any column not in the expression is **named in the record as not covered**. Constraints, indexes, the sequence, ownership and privileges are never covered.
- **Same value, same text.** A value that restores with a different text form than it had (a float, an interval, an out-of-range timestamp) would give a false difference. The listed columns are text, integers and a timestamp, but the rehearsal must show equality on a restored table; it is not argued here.

**Status and rule.** The five reference values stay the mandatory base. The content checksum becomes a mandatory sixth value only after rehearsal item 7 passes (same value twice on the source table, same value on the restored table, different value after a one-column change). If the rehearsal does not establish it, it is not used, and the evidence entry states that restored verification covered ids, row count and marker count only. Even when it passes, it shows that the restored table matches the snapshot on the covered columns; it does not show that the snapshot reflects what users did.

## 5. Acceptance

- A dated entry exists with the destination, retention period, custodians, recipient fingerprints and a passed restore verification.
- The reference values were taken inside the same exported snapshot as the dump, each attempt has its own directory and record, the designated attempt's record binds the snapshot identifier, the five values and the dump's SHA-256, failed attempts are recorded, the decrypted dump's SHA-256 equalled the recorded plaintext SHA-256, and the restore into a UTF-8 scratch database reproduced all five values exactly (and the content checksum, if it was validated).
- The rehearsal of section 4.1 was done, with its record attached to the G2 request.
- The temporary plaintext was removed only after the checks in step 9, and the entry says so.
- The verification scratch location was named and approved beforehand, used only by the named custodian, and cleaned and confirmed under step 7a; the entry records this.
- Every legacy backup was verified by checksum stream against the original's recorded SHA-256.
- `CHECKSUMS.txt` lists every preserved artifact with checksums.
- No dump, raw row, credential or key material is in git history.
- Production behaviour and data are unchanged.

## 6. Known limits

- The rehearsal has not been performed. The file-output method, the attempt gate, the restore of a table-only archive and the content checksum are designs until it has.
- Without a validated content checksum, restore verification covers row count, id range, the marker count and the id list, not the other columns. With it, only the listed columns.
- Matching hashes show the preserved dump equals what was dumped from the snapshot; they do not show the data is correct or genuine.

- The pre-insert backup of 2026-08-12 cannot be preserved because it is not on the host.
- Rows lost to the five seat deletions survive only in the legacy backups; this procedure is what keeps them.
- The off-host mirror's own retention is unverified; do not treat it as the evidence store until GitHub #63 is closed.
- Decrypted evidence also exists briefly in the verification scratch location during step 7. Its protection depends on the custodian's device or volume meeting section 3, which this document can require but cannot verify.
- The plaintext dump exists on the production host for the duration of steps 2-9. That exposure is the cost of verifying before deleting; the restricted directory and short duration limit it.
