# Evidence preservation procedure

Status: **designed, not executed.** No backup, copy, checksum run or retention change has been made as part of this work. Every step below needs the product owner's explicit authorization first (gate G2 in `REMEDIATION_DESIGN.md`).

Revision note, 2026-11-02 (after review): the encryption step now names its input file and recipients (the earlier example had no input argument, so it would have read standard input), and the plaintext is no longer deleted until preservation has been verified (section 4, steps 7-9). Second revision: restore verification of the legacy backups is by checksum stream (no plaintext written), and the one decrypted copy that verification needs (the dump and its scratch database) lives only in an approved, access-restricted verification scratch location that is cleaned under step 7a.

Third revision, 2026-11-03 (after review): (1) the snapshot identifier and reference values are written by psql to files (`\g`) while the exporting transaction is still open, instead of being read from a redirected log that might not be flushed until the session ends; whether that works is a rehearsal item, not an assumption. (2) Every attempt has its own directory and its own record associating (by procedure) the snapshot identifier, the reference values and the dump's SHA-256; a retry never reuses or overwrites an earlier attempt's files, and later steps refuse a directory that fails the gate in step 3. (3) Restore verification now compares the decrypted dump's SHA-256 with the recorded plaintext hash (archive integrity) before it compares restored content, and section 4.2 assesses an optional full-row content checksum. (4) The scratch database must be UTF-8.

Fourth revision, 2026-11-03 (after review): (1) a custodian-side verification gate that uses only what is transferred (a sealed attempt record and manifest, in an encrypted evidence bundle) and hashes recorded independently of the host and of the transfer channel; the record and logs are preserved encrypted before any cleanup. (2) The snapshot/dump association is described as procedural, not as a property of the dump. (3) The files psql writes are format-validated before use, and validation, flushing, FIFO and shell behaviour are rehearsal items. (4) Every failed or abandoned attempt is marked, there is one defined failed-attempt action, and undesignated plaintext has a 7-day recorded disposition. (5) The content checksum's exact query is stored with its hash in the record; any change to it requires a new rehearsal.

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
- **Connection and secrets.** The approved connection uses a service file or `.pgpass` held outside the attempt directory; no password appears on a command line, in a log or in any file of the attempt.
- **Independent record of hashes.** The place where the seal hash and ciphertext hashes are recorded outside the host and outside the transfer channel (the G2 evidence entry in GitHub #64), and the second person who recomputes them on the host (step 4).
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

1. **Check earlier attempts, create the attempt directory, open the exporter session and take the reference state inside it.** The reference values and the dump must come from the **same** consistent snapshot, otherwise a row written between "count" and "dump" makes a correct restore look like a failure. One database session exports a snapshot and stays open; the reference queries run inside it and their results are written to files while it is open; the dump imports the snapshot (section 4.1 explains why, and the failure handling). Every file of one attempt lives in that attempt's own directory.

   *Earlier attempts first.* Before a number is used, every earlier attempt directory in `<tmpdir>` must be in one of two states: **SEALED** (step 4 finished) or **FAILED** (a `FAILED` marker file with the reason and the UTC time). Any other directory (in progress, abandoned after a lost session, a host restart or a crash) is marked FAILED, reason "abandoned", by the operator before the new attempt starts. Each attempt, its state and the designation of the evidence attempt are also appended to `<tmpdir>/attempts.log` (only ever appended to with `>>`).
   ```
   umask 077
   set -o noclobber                 # '>' refuses to overwrite an existing regular file
   A=<tmpdir>/attempt-<NN>          # NN = 01, 02, 03 ...; a number is never reused
   mkdir "$A"                       # no -p: fails if the directory already exists
   mkfifo "$A/ctl"
   psql -X -q -At -v ON_ERROR_STOP=1 <approved connection> < "$A/ctl" > "$A/exporter.log" 2>&1 &
   EXPORTER_PID=$!
   exec 3> "$A/ctl"
   echo "attempt-<NN> started $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> <tmpdir>/attempts.log
   ```
   If `mkdir` fails, stop: the number is taken, and that directory is classified as above. `-q` keeps command tags such as `BEGIN` and `COMMIT` out of the output, so the log holds only errors and notices; the success signal for the session is its exit status (step 2). The approved connection must not carry a password on the command line or in any file inside the attempt directory (use a service file or `.pgpass` outside it). Whether `noclobber` accepts the redirect onto a FIFO, how `exec 3>` and `wait` behave, and what a normal `exporter.log` looks like are **not assumed**; the rehearsal checks them in the same shell (`bash --version` is recorded).

   Send these lines to the session through descriptor 3 (for example with `printf '%s\n' ... >&3`), in this order. `<A>` stands for the absolute path of the attempt directory, written into the line by the operator, because psql does not expand shell variables:
   ```
   SET idle_in_transaction_session_timeout = '15min';
   SET client_encoding = 'UTF8';
   SET TimeZone = 'UTC';
   BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
   SELECT pg_export_snapshot() \g <A>/snapshot.id
   SELECT column_name || ':' || data_type FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'api_activitylog'
     ORDER BY ordinal_position \g <A>/columns.txt
   SELECT count(*), min(id), max(id),
          count(*) FILTER (WHERE detail LIKE '%بازسازی%'),
          encode(sha256(convert_to(string_agg(id::text, ',' ORDER BY id), 'UTF8')), 'hex')
   FROM api_activitylog \g <A>/reference.txt
   ```
   (`\g <file>` sends the query and writes its output to the file instead of the terminal; the PostgreSQL 16 documentation says so, and says the file is written only if the query succeeds. It does **not** say when the file is closed or flushed, whether an existing file is overwritten, how a relative name resolves, or whether anything besides the query output is written to the file, which is why the names are absolute and new, and why the format checks below and the rehearsal exist.)

   *Optional content checksum (section 4.2).* Only if `columns.txt` is identical to the column list recorded by the rehearsal, copy the rehearsed query text into `<A>/content-query.sql` and confirm its SHA-256 equals the hash recorded by the rehearsal; then send that text followed by `\g <A>/content.txt`. If the columns differ, or the hash differs, **do not change the query**: the content checksum is `NOT_USED` for this attempt (section 4.2).

   **Validate the files before they are used, while the transaction is still open**, with a separate process, after waiting for them to appear (poll with `test -s` for up to about 60 seconds):
   ```
   test "$(wc -l < "$A/snapshot.id")" -eq 1 && grep -Eq '^[0-9A-Fa-f]+(-[0-9A-Fa-f]+)*$' "$A/snapshot.id"
   test "$(wc -l < "$A/reference.txt")" -eq 1 && grep -Eq '^[0-9]+\|[0-9]+\|[0-9]+\|[0-9]+\|[0-9a-f]{64}$' "$A/reference.txt"
   test -s "$A/columns.txt" && ! grep -q '^$' "$A/columns.txt"          # one name:type line per column, no blank line; compared with the rehearsed list before the content query is used
   test "$(wc -l < "$A/content.txt")" -eq 1 && grep -Eq '^[0-9a-f]{64}$' "$A/content.txt"      # only if the content checksum is used
   ```
   That is: `snapshot.id` is exactly one line made only of hexadecimal digits and hyphens (the PostgreSQL documentation does not specify the identifier's format; the rehearsal records the observed shape and this pattern is tightened to it); `reference.txt` is exactly one line of five `|`-separated fields, the first four digits only and the fifth 64 hexadecimal characters; `content.txt`, if used, is one line of 64 hexadecimal characters. Any extra line (such as a status line), an empty file or a different shape fails the check. **If a file is not present and valid in that time, the attempt has failed** (apply the failed-attempt action in section 4.1), and the procedure is not to be executed until the rehearsal has shown a method that works. Ending the session to look at its output is not allowed, because that ends the snapshot.

   Then write the attempt's **record**, built by command and not typed, so values cannot be mistyped or mixed:
   ```
   {
     echo "attempt=<NN>"
     echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
     echo "bash_version=$BASH_VERSION"
     echo "tool_versions=$(psql --version); $(pg_dump --version); $(age --version)"
     echo "snapshot_id=$(cat "$A/snapshot.id")"
     echo "reference=$(cat "$A/reference.txt")"     # count|min id|max id|marker count|sha256 of ordered ids
     echo "content_query_sha256=<sha256 of content-query.sql, or NOT_USED>"
     echo "content_checksum=<content of content.txt, or NOT_USED>"
     echo "columns_not_covered=<columns in columns.txt that the content query does not hash, or none>"
   } > "$A/record.txt"
   ```
   On 2026-11-02 the first four reference values read 86,212 / 1 / 116,419 / 83,486; they will differ if the table has grown, which is fine; record what is found. The fifth is the SHA-256 of the ordered id list (a text of ids separated by commas, in ascending order). **Leave the transaction open** until step 2 has finished.
2. **Dump the one table from that same snapshot**, into the attempt directory:
   ```
   pg_dump --format=custom --table=public.api_activitylog --snapshot="$(cat "$A/snapshot.id")" --file="$A/activitylog-<date>-a<NN>.dump" <approved connection> 2> "$A/pg_dump.log"
   ```
   Do **not** add `--serializable-deferrable`: the PostgreSQL 16 documentation does not say whether it can be combined with `--snapshot`. When `pg_dump` has exited successfully, send `COMMIT;` and `\q` to the exporter session through descriptor 3, close the descriptor, run `wait "$EXPORTER_PID"`, and confirm that its exit status is 0 and that `exporter.log` has no line starting with `ERROR` or `FATAL` (what a normal log looks like is a rehearsal result). A session that was terminated before the `COMMIT` cannot exit with status 0 in this setup (`ON_ERROR_STOP`), which is what the exit status is relied on for; the rehearsal confirms it. Append `exporter_exit=<status>` to the record.
3. **Checksum the plaintext dump and close the host gate for this attempt.** Compute `sha256sum` of the dump and record its size, appending both to `record.txt` (`>>`), then make the dump read-only (`chmod 0400`). **What the record does and does not establish:** it associates, **by procedure and not by any property of the dump**, the snapshot identifier, the reference values, the dump file name, size and SHA-256 and the exporter's exit status. A custom-format archive carries no snapshot identifier that could be checked afterwards, so nothing in the file proves which snapshot it came from. The evidence that the dump matches the values is the restore comparison in step 7, not the record. **Host gate:** before steps 4, 6 and 9 the operator checks, in this attempt directory, that (a) no `FAILED` marker exists, (b) exactly one `*.dump` file exists and its name equals the one in the record, (c) a fresh `sha256sum` of it equals the recorded value, (d) the record shows `exporter_exit=0`, and (e) the format checks of step 1 still pass on the stored `snapshot.id`, `reference.txt` (and `content.txt`). A directory that fails any check is not used. The plaintext SHA-256 recorded here is the value that the decrypted dump is compared with in step 7.
4. **Encrypt, then seal the attempt, naming the input files explicitly.** `age` reads standard input when no input file is given, so the input must be an argument:
   ```
   age --encrypt -R <recipients-file> -o "$A/activitylog-<date>-a<NN>.dump.age" "$A/activitylog-<date>-a<NN>.dump"
   ```
   Then check that the ciphertext exists, is not empty, is close to the plaintext size, and append its `sha256sum` and size to the record (`ciphertext_sha256=`, `ciphertext_size=`). **Do not delete the plaintext.** The host cannot prove the ciphertext decrypts to the dump; only a custodian's restore (step 7) can.

   **Seal.** Square brackets in the commands below mean "include only if the content checksum is used". Run the host gate, then, in the attempt directory, list the small evidence files and make them read-only:
   ```
   sha256sum record.txt snapshot.id columns.txt reference.txt [content.txt content-query.sql] exporter.log pg_dump.log > manifest.sha256
   chmod 0400 record.txt snapshot.id columns.txt reference.txt [content.txt content-query.sql] exporter.log pg_dump.log manifest.sha256
   sha256sum manifest.sha256        # the SEAL HASH
   ```
   The manifest hashes every file that makes up the attempt's evidence (including the record, which holds the dump's SHA-256, the ciphertext SHA-256 and the exporter exit status). The **seal hash** is the SHA-256 of the manifest. Append `attempt-<NN> SEALED <UTC time>` to `attempts.log`.

   **Preserve the record and logs as evidence, without exposing them.** `exporter.log` and `pg_dump.log` can contain host names, role names, paths and error text, so they are treated as sensitive: they are never edited (an altered log is worse than a sensitive one), never put in git, GitHub or Jira, and kept only encrypted. Put the sealed files in one archive and encrypt it to the same two recipients:
   ```
   tar -C "$A" -cf "$A/evidence-a<NN>.tar" manifest.sha256 record.txt snapshot.id columns.txt reference.txt [content.txt content-query.sql] exporter.log pg_dump.log
   age --encrypt -R <recipients-file> -o "$A/evidence-a<NN>.tar.age" "$A/evidence-a<NN>.tar"
   sha256sum "$A/evidence-a<NN>.tar.age" "$A/activitylog-<date>-a<NN>.dump.age"
   ```
   Before sealing, the operator reads both logs once. A credential or token in either is a defect of the connection set-up: stop, treat the attempt as failed, rotate the credential, and start again. If a redacted copy is ever needed for sharing, it is made later from the preserved original, labelled as redacted, and never replaces it.

   **Independent record of the hashes.** The seal hash, the SHA-256 of `evidence-a<NN>.tar.age` and the SHA-256 of the dump's `.age` file are recorded **outside the host and outside the transfer channel**: written by the operator into the G2 evidence entry in GitHub #64 together with the attempt number, which that entry designates as the evidence attempt (provisionally: it is re-designated if verification fails and a later attempt is used), and confirmed there by a second person who recomputed them on the host independently (not by copying the operator's output). The custodian compares what they receive with this record in step 7.
5. **Preserve the seven legacy SQLite backups and the 2026-08-05 pre-batch backups by encrypting at the source, never by copying plaintext.** For each original: record `sha256sum` and size in place (read-only), then encrypt it, naming the input file explicitly, into the temporary directory:
   ```
   age --encrypt -R <recipients-file> -o <name>.age <original-backup-file>
   ```
   The original's checksum and size, and each ciphertext's checksum and size, go into a separate `legacy-record.txt` (created with `>`, extended with `>>`, never rewritten; a repeated encryption adds a new line and keeps the old). The `.age` files are written into their own new directory, not into any attempt directory, and a file that already exists is not overwritten. Only the `.age` files are transferred. **No plaintext copy of any legacy backup is made on the production host, at the destination, or in any shared location**: these files contain personal data (usernames, display names, phone numbers, password hashes) and must not exist unencrypted outside their current location. The only permitted exception is a temporary, optional decrypted verification copy inside the verification scratch location, under the rules in section 3 and step 7; by default none is made, because step 7 verifies legacy backups by checksum stream. The originals stay exactly where they are.
6. **Transfer** the ciphertexts (the dump's `.age`, the evidence bundle `evidence-a<NN>.tar.age`, and the legacy `.age` files) over an authenticated, encrypted channel to the approved location. Confirm each destination checksum equals the host's ciphertext checksum **and** the independently recorded value (step 4). The unencrypted record and logs are not transferred.
7. **Verification, by a custodian, off the production host, inside the approved verification scratch location (VSL, section 3).**
   - **Custodian-side gate, before anything is restored.** The custodian has only what was transferred and the independent record of hashes, so the gate uses only those:
     1. Check the received `.age` files' SHA-256 against the independently recorded values (step 4). A mismatch stops the verification.
     2. Decrypt the evidence bundle into the VSL (it is small and contains no dump) and compute the SHA-256 of `manifest.sha256`: it must equal the independently recorded **seal hash**.
     3. Run `sha256sum -c manifest.sha256` in the VSL: every listed file must match.
     4. Re-run the format checks of step 1 on `snapshot.id`, `reference.txt` (and `content.txt`), and check the record: `attempt` equals the attempt number designated in the evidence entry, `exporter_exit=0`, the dump file name equals the received `.age` name without its suffix, `ciphertext_sha256` equals the received dump `.age` hash, and `dump_sha256` is present. If `content_checksum` is not `NOT_USED`, `content_query_sha256` must equal the hash recorded by the rehearsal.
     5. Any failure: stop, record it, the verification has failed, nothing is deleted anywhere and step 9 does not run.

     The gate shows that the received record and logs are the sealed ones and that the files belong together as recorded. It does **not** show that the operator told the truth when producing them; the independent second-person check in step 4 is what limits that.
   - **Activity-log dump, archive integrity first.** Decrypt it as a stream into the hash, without writing plaintext, and compare with `dump_sha256` in the verified record: `age --decrypt -i <identity-file> activitylog-<date>-a<NN>.dump.age | sha256sum`. Equality shows that the ciphertext is intact, that the custodian's key decrypts it, and that the result is byte for byte the dump the host hashed in step 3. It says **nothing** about whether that dump holds the right table content. If it differs, stop: do not restore, and treat the verification as failed.
   - **Activity-log dump, restored content second.** Decrypt it into the VSL, hash the decrypted file again and compare with the same recorded value (a mismatch means the copy in the VSL is not the dump), then restore it with `pg_restore --no-owner --exit-on-error --section=pre-data --section=data -d <scratch-database>` (only the table definition and its rows: the documentation places indexes and constraints, including the foreign key to the seat table, in the post-data section, and says a table-only restore makes no attempt to restore what the table depends on, so constraints are deliberately not restored; the reference values do not depend on them), into a scratch database whose data lives inside the VSL (never production, and never a container on the production host: staging and production share that host, GitHub #25). **The scratch database must be UTF-8:** create it with `createdb --template=template0 --encoding=UTF8`, and before restoring confirm `SHOW server_encoding;` returns `UTF8` (the marker count and the content checksum assume it; a different encoding can fail the restore or change the text, and a result from such a database is not accepted). Run the **same reference query** as in step 1 on the restored table, in a session with `client_encoding` UTF8 and `TimeZone` UTC. All five values (row count, minimum id, maximum id, marker-row count, SHA-256 of the ordered id list) must equal the record's values exactly. If the content checksum was used, run the **byte-identical** query text (its hash equals `content_query_sha256`) and the result must equal `content_checksum` too. They are comparable because step 1 took them inside the snapshot the dump was made from. Record `pg_restore --version`.
   - **Legacy backups: by checksum stream, with no plaintext written.** For **every** legacy backup, decrypt as a stream straight into the hash and compare it with the checksum of the original recorded in step 5:
     ```
     age --decrypt -i <identity-file> <name>.age | sha256sum
     ```
     Equality proves the ciphertext decrypts to the original byte for byte, which is the property that matters. Nothing is materialized, so nothing needs cleanup. Opening a legacy backup and counting its rows is **optional**, adds nothing the checksum does not prove, and if a custodian nonetheless chooses to do it, the decrypted file lives only in the VSL, is opened read-only, and is deleted immediately.
   - Record pass or fail, the date, the custodian, and the hash comparison results.
7a. **Clean up the verification scratch location, immediately after step 7 whatever its result** (a failed verification is repeated from the ciphertext; it is not a reason to keep decrypted copies): delete every decrypted file and intermediate, drop the scratch database and remove its data directory, empty the VSL, and confirm that nothing remains in the trash, in snapshots or shadow copies, in backup jobs, in search indexes or in any sync client. A second person confirms in writing, and the cleanup is recorded in the evidence entry with the limit that deletion on journaling and copy-on-write filesystems does not guarantee the bytes are gone (which is why the VSL is encrypted storage).
8. **Retention and custody.** Set the retention period and legal-hold flag at the destination; record custodians and key locations (locations only) outside GitHub.
9. **Clean up the temporary plaintext, only if all of these hold:**
   - the ciphertexts at the destination, **including the evidence bundle**, have the same checksums as the host's and as the independently recorded values (step 6);
   - the custodian-side gate and the restore verification passed and are recorded (step 7), so the record and logs are preserved and verified at the destination;
   - the verification scratch location has been cleaned and confirmed (step 7a);
   - a second person confirms these in writing;
   - the metadata for `CHECKSUMS.txt` is prepared (step 10).

   Then delete, from the attempt directory, the plaintext dump, the plaintext archive `evidence-a<NN>.tar`, and the **unencrypted copies of the record, manifest, logs, `snapshot.id`, `columns.txt`, `reference.txt` and content files** (their encrypted copy is the bundle at the destination), together with the temporary ciphertext copies (including those of the legacy backups, which are duplicates of what is now at the destination), and remove the directory. `attempts.log` is kept. The original legacy backups and every original file are never touched. File deletion on journaling or copy-on-write filesystems does not guarantee the bytes are gone; the limit is recorded in the evidence entry, and is why the plaintext stays in a `0700` directory for as short a time as possible.

   **If any condition fails**, the plaintext stays in the restricted directory, and the operation is repeated or the problem is resolved first. The plaintext is never deleted on the strength of the host's own checks. The production table remains the source, and nothing here changes it.

   **Attempts that are not the designated evidence attempt** (failed ones, and completed ones that were superseded, for example after a failed verification) are not left as plaintext. Each gets a recorded disposition within **7 days of the designation of the evidence attempt**, or within 7 days of the last attempt if none is designated, whichever is first: (i) its plaintext dump and plaintext archive are deleted; (ii) its ciphertexts and bundle, if it has any, are either transferred and retained at the destination under the same retention and labelled "undesignated", or deleted by a recorded decision of the product owner; (iii) the entry records the attempt number, the reason, what was kept and what was deleted, the date and the person, and a second person confirms in writing. If the 7 days pass without a disposition, the plaintext is deleted anyway once its ciphertext exists (the ciphertext is the retained form) and the lapse is escalated to the product owner. The production table is the source, so deleting an undesignated plaintext loses no original data.
10. **Publish only the metadata**: add a dated table of file names, sizes, SHA-256 (plaintext and ciphertext), row counts, the attempt number, the snapshot identifier, the seal hash, the content-query hash (or `NOT_USED`), the age version, recipient fingerprints and the restore-verification result to `CHECKSUMS.txt` via a normal reviewed PR.
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

**Required before G2 execution: the non-production rehearsal.** It is **not executed**; nothing in this document claims it has been done, and until it has passed, every statement here that a method works is a design, not a result. In particular, **psql's file output and flushing, the FIFO and descriptor handling, `noclobber`, `wait`, and the exit status of a terminated session are unverified until rehearsed.** The rehearsal runs exactly these commands, in the same kind of shell (bash, on an Ubuntu 24 host like production; `bash --version` and the OS are recorded), on a **non-production** PostgreSQL 16 database (never a copy of production) holding a table of the same shape and column types, built from the repository's migrations and filled with synthetic rows that include Persian text, NULLs, empty strings, quotes, backslashes and microsecond timestamps, with a throwaway `age` key pair (never a custodian's key). It records `psql --version`, `pg_dump --version` (major version at least the server's), `pg_restore --version`, `age --version`, and the outcome of each item:

1. **Readable and well-formed while open.** `snapshot.id`, `columns.txt`, `reference.txt` (and `content.txt`) are complete and readable by another process while the exporter transaction is still open, and how long that takes. The exact content of each is inspected: whether psql wrote anything besides the query output, the observed shape of the snapshot identifier (to tighten the pattern in step 1), and that the format checks of step 1 **pass** on the real files. Negative controls: a file with an extra line, an empty file and a file with a wrong field count each **fail** the checks. If the method does not work, it is changed and this document corrected.
2. **Snapshot binding.** With the exporter open, another session inserts and updates rows; the dump and the reference values contain none of those changes.
3. **Lifetime and exit status.** `pg_dump --snapshot` succeeds while the exporter is open; with `-q`, what `exporter.log` contains on success is recorded; the exporter's exit status is 0 after `COMMIT`/`\q`; with a deliberately short idle timeout, a timed-out exporter yields a non-zero exit status (or another recorded signal) and is detected as a failed attempt; a lost shell session is also tried.
4. **Shell mechanics.** `set -o noclobber` with the FIFO redirect, `exec 3>`, `$!`, `wait`, and what a write to descriptor 3 does when the exporter has died.
5. **Attempt isolation and marking.** A forced failure (kill `pg_dump`) leaves a `FAILED` marker, an `attempts.log` line, and the host gate refuses that directory; a startup failure and an abandoned directory are marked FAILED before the next attempt; a second attempt uses a new directory and the first attempt's files are byte for byte unchanged; a dump copied into another attempt's directory is rejected.
6. **Seal, bundle and custodian gate.** The manifest and seal hash are produced; the encrypted bundle decrypts; the custodian-side gate **passes** on the untouched bundle and **fails** when a byte of the record, a log, the manifest, the dump `.age` or the seal hash is changed, and when the record names a different attempt number.
7. **Round trip.** Encrypt, decrypt as a stream, and the SHA-256 equals `dump_sha256`; a copy of the ciphertext with one byte changed fails to decrypt or does not match.
8. **Restore.** Into a UTF-8 scratch database, `pg_restore --section=pre-data --section=data` succeeds and the five values equal the record; whether the `id` default restores without its sequence is observed (if not, the sequence is added as a second `--table` and the rehearsal repeated). A scratch database in another encoding is also tried, to show what the UTF-8 requirement prevents.
9. **Content checksum (section 4.2).** The exact query text is saved as `content-query.sql` and its SHA-256 is recorded. The same file gives the same value twice on the source table and the same value on the restored table; after changing one column of one row in the restored copy (one character of `detail`, or one microsecond of `created_at`) the value differs while the five reference values do not. **Any change to the query text, however small, or a different column list or type in `columns.txt`, changes the hash and requires this item (and item 1) to be repeated before the changed query may be used.**

The G2 request attaches this record, including the recorded `content-query.sql` hash and column list. A failed item is a finding, not something to work around silently.

**Transaction lifetime.** The exporter transaction exists from the `BEGIN` in step 1 to the `COMMIT` after `pg_dump` has exited, which for a table of this size is expected to be seconds to a few minutes. The 15-minute idle timeout is a ceiling, not a target. A longer life holds back vacuum cleanup on the whole database, so do not leave it open while waiting for a person.

**Failure handling.** Each attempt has its own numbered directory and record (step 1). The snapshot identifier, the reference values and the dump of one attempt are used **only together**, by procedure (step 3); values from one attempt are never paired with a dump from another, and a retry never writes into an earlier attempt's directory.

**Failed-attempt action** (every row below that says "failed" means exactly this, in this order): (1) if the exporter session is alive, send `ROLLBACK;` and `\q`, and confirm the session has ended (otherwise confirm its process is gone); (2) write a `FAILED` marker into the attempt directory with the reason and the UTC time, **even if the directory holds almost nothing**; (3) delete any dump in it, partial or complete (a failed attempt's dump is never kept, encrypted or reused); (4) append `attempt-<NN> FAILED <reason> <UTC time>` to `attempts.log`; (5) keep the small files and logs as they are (they are never used for any other attempt); (6) start the next attempt in a **new** directory with a new snapshot.

| Event | Action |
|---|---|
| `mkdir` of the attempt directory fails | stop; that number is taken; classify the existing directory (SEALED or FAILED, else mark it FAILED "abandoned") and use the next number |
| the exporter session cannot start, `pg_export_snapshot()` errors, or any query before the dump errors | failed-attempt action |
| a file in step 1 is missing, empty, or fails its format check while the transaction is open | failed-attempt action; the method is not working as rehearsed, and the procedure is not repeated until the rehearsal has been repeated |
| the operator's session is lost, the host restarts, or the operator walks away with an attempt open | the exporter dies with its connection; the directory is marked FAILED "abandoned" by the next person who touches it, before any new attempt |
| `pg_dump` exits non-zero, or reports an invalid or unimportable snapshot | failed-attempt action |
| the exporter session ended before `pg_dump` exited (timeout, connection loss), even if `pg_dump` reported success | failed-attempt action, because the snapshot's validity is not confirmed |
| the exporter's exit status after `COMMIT` is not 0, or `exporter.log` has an `ERROR`/`FATAL` line | failed-attempt action; do not use the dump |
| the host gate fails at step 4, 6 or 9 (marker present, extra or renamed dump, hash differs from the record, format check fails) | stop; mark the directory FAILED and investigate before any new attempt; never copy a dump between attempt directories |
| a credential or token is found in a log | failed-attempt action; rotate the credential; the logs stay encrypted and are not published |
| the custodian-side gate fails (hash or seal-hash mismatch, record does not match, wrong attempt number) | the verification failed; nothing is deleted; step 9 does not run; the attempt is investigated, not repaired in place |
| the decrypted dump's SHA-256 differs from `dump_sha256` | verification failed; do not restore; keep everything; step 9 does not run |
| the restore does not reproduce all five values (or the content checksum, where used) | verification failed; keep the ciphertext, the plaintext dump and the logs; investigate; step 9 does not run |
| three attempts fail in a row | stop and escalate to the product owner; do not improvise a different method |
| a later attempt succeeds after earlier ones produced files | exactly one attempt is designated the evidence attempt in the entry and in `attempts.log`; every number in the entry comes from that attempt's own directory; the others get the recorded disposition in step 9 within 7 days |

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
- **Time.** `created_at` is rendered after `SET TimeZone = 'UTC'` with a fixed format that keeps microseconds. The actual column names and types are written to `columns.txt` inside the exporter transaction (step 1) and compared with the list the rehearsal used; if they differ, the query is **not** adjusted on the spot (see "Exact expression").
- **Coverage.** Only the listed columns are covered (the nine original columns, as in `TEST_PLAN.md` D1). Before the attempt the table's actual column list is read from the catalog; any column in `columns.txt` that the expression does not hash is **named in the record as not covered** (`columns_not_covered`). Constraints, indexes, the sequence, ownership and privileges are never covered.
- **Same value, same text.** A value that restores with a different text form than it had (a float, an interval, an out-of-range timestamp) would give a false difference. The listed columns are text, integers and a timestamp, but the rehearsal must show equality on a restored table; it is not argued here.

**Exact expression.** The text above is the proposal. What is used is a file, `content-query.sql`, saved byte for byte by the rehearsal, whose SHA-256 is recorded in the rehearsal result and in each attempt's record (`content_query_sha256`), and run unchanged on the source snapshot and on the restored table. Any change to the text, even whitespace, gives a different hash and requires the rehearsal items on the content checksum (and on file format) to be repeated before use; a changed column list or type in `columns.txt` likewise. At execution time there is no third choice between "the rehearsed query on the rehearsed columns" and `content_checksum=NOT_USED`, with the uncovered columns named.

**Status and rule.** The five reference values stay the mandatory base. The content checksum becomes a mandatory sixth value only after rehearsal item 9 passes (same hash of the query file, same value twice on the source table, same value on the restored table, different value after a one-column change). If the rehearsal does not establish it, it is not used, and the evidence entry states that restored verification covered ids, row count and marker count only. Even when it passes, it shows that the restored table matches the snapshot on the covered columns; it does not show that the snapshot reflects what users did.

## 5. Acceptance

- A dated entry exists with the destination, retention period, custodians, recipient fingerprints and a passed restore verification.
- The reference values were taken inside the same exported snapshot as the dump, each attempt has its own directory and record, the designated attempt's record associates, by procedure, the snapshot identifier, the five values and the dump's SHA-256, failed attempts are recorded, the decrypted dump's SHA-256 equalled the recorded plaintext SHA-256, and the restore into a UTF-8 scratch database reproduced all five values exactly (and the content checksum, if it was validated).
- The rehearsal of section 4.1 was done, with its record attached to the G2 request.
- The seal hash and ciphertext hashes were recorded independently of the host and the transfer, confirmed by a second person, and the custodian-side gate passed; the encrypted evidence bundle (record, manifest, logs) is preserved at the destination, and no unencrypted log or record was left on the host or published.
- Every attempt is marked SEALED or FAILED in `attempts.log`, exactly one is designated, and every other attempt has a recorded disposition within 7 days.
- The temporary plaintext was removed only after the checks in step 9, and the entry says so.
- The verification scratch location was named and approved beforehand, used only by the named custodian, and cleaned and confirmed under step 7a; the entry records this.
- Every legacy backup was verified by checksum stream against the original's recorded SHA-256.
- `CHECKSUMS.txt` lists every preserved artifact with checksums.
- No dump, raw row, credential or key material is in git history.
- Production behaviour and data are unchanged.

## 6. Known limits

- The record is a procedural association, not a property of the dump: no archive field proves which snapshot it came from. The seal hash protects the record against later alteration and mix-ups, not against an operator who writes a false record; the second person's independent recomputation limits that, and the restore comparison is what shows the dump matches the values.
- Logs may contain operational detail (hosts, roles, paths). They are preserved encrypted and never edited or published; only hashes appear in git.
- psql file output and flushing, FIFO, `noclobber`, `wait` and exit status of a terminated session are unverified until rehearsed.

- The rehearsal has not been performed. The file-output method, the attempt gate, the restore of a table-only archive and the content checksum are designs until it has.
- Without a validated content checksum, restore verification covers row count, id range, the marker count and the id list, not the other columns. With it, only the listed columns.
- Matching hashes show the preserved dump equals what was dumped from the snapshot; they do not show the data is correct or genuine.

- The pre-insert backup of 2026-08-12 cannot be preserved because it is not on the host.
- Rows lost to the five seat deletions survive only in the legacy backups; this procedure is what keeps them.
- The off-host mirror's own retention is unverified; do not treat it as the evidence store until GitHub #63 is closed.
- Decrypted evidence also exists briefly in the verification scratch location during step 7. Its protection depends on the custodian's device or volume meeting section 3, which this document can require but cannot verify.
- The plaintext dump exists on the production host for the duration of steps 2-9. That exposure is the cost of verifying before deleting; the restricted directory and short duration limit it.
