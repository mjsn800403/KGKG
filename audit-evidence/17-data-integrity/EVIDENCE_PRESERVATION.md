# Evidence preservation procedure

Status: **designed, not executed.** No backup, copy, checksum run or retention change has been made as part of this work. Every step below needs the product owner's explicit authorization first (gate G2 in `REMEDIATION_DESIGN.md`).

Revision note, 2026-11-02 (after review): the encryption step now names its input file and recipients (the earlier example had no input argument, so it would have read standard input), and the plaintext is no longer deleted until preservation has been verified (section 4, steps 7-9).

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
2. **Encrypted at rest and in transit**, with the decryption key held by named people other than the storage operator.
3. **Restricted access**, recorded; two named custodians at most for the decryption key, at least two for recoverability (section 3).
4. **Retention controls**: a stated minimum retention, a legal-hold marker, and deletion only by recorded decision.
5. **Restore verified**, not assumed: a copy that has never been restored is a guess.
6. **Nothing is deleted until preservation is verified.** The temporary plaintext is the only copy on the host that was made for this purpose; it is removed last, after the encrypted copy has been transferred, checksummed and restored successfully (section 4, step 9).
7. **Read-only on production.** Nothing here writes to the live database or modifies existing backup files.

## 3. Pre-checks and required inputs (before any copy is made)

Record the answers in the authorization request. A missing input blocks the procedure.

- **Destination.** A storage location with encryption, access control and versioning, chosen by the product owner. The existing off-host pull target is **not** assumed suitable until its retention is confirmed (GitHub #63).
- **Encryption inputs (all required).**
  1. The **recipient list**: the public keys the dump will be encrypted to, as a file outside the repository, with each key's fingerprint recorded in the authorization. At least **two** recipients so that losing one private key does not lose the evidence.
  2. The **decryption custodians**: the named people who hold the matching private keys, and where each private key is kept (location only; never on the production host, never in git).
  3. A **key-loss and rotation plan**: who can add a recipient and re-encrypt, and how often the keys are re-confirmed.
  4. The **tool and version** (`age`, with the version recorded), installed on the operator's side, not assumed present on the host.
- **Temporary working directory.** A directory on the host used only for this operation, mode `0700`, owned by the operator, with free space of at least the plaintext dump plus the ciphertexts of the dump and of the legacy backups (about 4.5 GB in total, since ciphertext is about the size of its input). Plaintext is sensitive (display names, usernames) and must not sit in a world-readable location or in a shared temp directory.
- **Capacity.** Production host `/` on 2026-11-02: 290 GB total, 219 GB used, 71 GB free. A table-level dump is about the size of the existing full dumps (about 25 MB); seven legacy backups are about 4.4 GB in total. Neither is a capacity risk, but free space must be re-read at execution time.
- **Operational impact.** A table-level `pg_dump` takes only an ACCESS SHARE lock, so it does not block reads or writes, but it does read the whole table; run off-peak (the 7-day traffic window is about 80 rows, so the system is lightly used). Checksumming the legacy backups reads about 4.4 GB once; run with `nice` and `ionice`.
- **Authorization.** Written approval in GitHub #64 naming the destination, the recipient fingerprints, the custodians, the retention period and the restore-test location.

## 4. Procedure (when authorized)

Run by a person with host access, never by an unattended job. Commands are templates; fill in the approved paths. `<date>`, `<recipients-file>` and the destination are the approved inputs from section 3.

1. **Freeze the reference state (read-only counts).** Record row count, id range and marker count of `api_activitylog` (expected on 2026-11-02: 86,212 / 1..116419 / 83,486; they will differ if the table has grown, which is fine; record what is found).
2. **Dump the one table** into the temporary directory, consistent snapshot:
   ```
   umask 077
   pg_dump --format=custom --table=api_activitylog --serializable-deferrable <approved connection> -f activitylog-<date>.dump
   ```
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
   Only the `.age` files are transferred. **No plaintext copy of any legacy backup is made, at the destination or anywhere else**: these files contain personal data (usernames, display names, phone numbers, password hashes) and must not exist unencrypted outside their current location. The originals stay exactly where they are.
6. **Transfer** the ciphertexts over an authenticated, encrypted channel to the approved location. Confirm the destination checksum equals the host's ciphertext checksum.
7. **Restore verification, by a custodian, off the production host**, in a scratch database that is not production (a staging container is acceptable): decrypt with the private key, restore, and compare total rows, marker count, id range, and a checksum of the ordered id list against step 1. Record pass or fail and the date. For **every** legacy backup, decrypt and confirm that its SHA-256 equals the checksum of the original recorded in step 5, and open at least one read-only and count its activity rows.
8. **Retention and custody.** Set the retention period and legal-hold flag at the destination; record custodians and key locations (locations only) outside GitHub.
9. **Clean up the temporary plaintext, only if all of these hold:**
   - the ciphertext at the destination has the same checksum as the host's ciphertext (step 6);
   - the restore verification passed and is recorded (step 7);
   - a second person confirms both in writing;
   - the metadata for `CHECKSUMS.txt` is prepared (step 10).

   Then delete the plaintext dump and the temporary ciphertext copies (including those of the legacy backups, which are duplicates of what is now at the destination) from the temporary directory and remove the directory. The original legacy backups and every original file are never touched. File deletion on journaling or copy-on-write filesystems does not guarantee the bytes are gone; the limit is recorded in the evidence entry, and is why the plaintext stays in a `0700` directory for as short a time as possible.

   **If any condition fails**, the plaintext stays in the restricted directory, and the operation is repeated or the problem is resolved first. The plaintext is never deleted on the strength of the host's own checks. The production table remains the source, and nothing here changes it.
10. **Publish only the metadata**: add a dated table of file names, sizes, SHA-256 (plaintext and ciphertext), row counts, the age version, recipient fingerprints and the restore-verification result to `CHECKSUMS.txt` via a normal reviewed PR.
11. **Protect the originals.** Only after steps 1-10 are verified and with separate approval: mark the legacy backups on the host read-only. Never delete them as part of this work.

## 5. Acceptance

- A dated entry exists with the destination, retention period, custodians, recipient fingerprints and a passed restore verification.
- The temporary plaintext was removed only after the checks in step 9, and the entry says so.
- `CHECKSUMS.txt` lists every preserved artifact with checksums.
- No dump, raw row, credential or key material is in git history.
- Production behaviour and data are unchanged.

## 6. Known limits

- The pre-insert backup of 2026-08-12 cannot be preserved because it is not on the host.
- Rows lost to the five seat deletions survive only in the legacy backups; this procedure is what keeps them.
- The off-host mirror's own retention is unverified; do not treat it as the evidence store until GitHub #63 is closed.
- The plaintext dump exists on the production host for the duration of steps 2-9. That exposure is the cost of verifying before deleting; the restricted directory and short duration limit it.
