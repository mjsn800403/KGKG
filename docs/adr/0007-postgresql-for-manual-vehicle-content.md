# ADR-0007 — Manual vehicle content is served from PostgreSQL schemas; parts-only vehicles stay in SQLite

**Status:** Proposed (records a change already in force; needs the maintainers' confirmation of the decision and its date) · **Amends:** [ADR-0001](0001-sqlite-and-per-vehicle-databases.md) in part · **Recorded:** 2026-11-04

## Context
ADR-0001 chose one read-only SQLite file per vehicle manual and one SQLite file for application data, and noted
that moving application data to PostgreSQL is "a settings change". Since then:

* application data moved to PostgreSQL 16, database `kgkg` (`KG_DB_ENGINE=postgres`); [C `settings.py`, doc 02];
* manual content moved too: `api/cardb_pg.py` serves a car from its own schema in database `kgkg_vec` when
  the car is listed in `KG_CARDB_PG` (`*` = all loaded cars), and `cardb_pg.adopt()` deletes the SQLite file after
  loading and re-counting; [C];
* on 2026-11-03, 222 of 237 cars existed only in PostgreSQL (about 58 GB); the 15 parts-only cars remained SQLite;
  [D session ea4f3d3e; re-verify].

Who decided this, when, and on what measurements is **[U]**: it is visible in code and CHANGELOG fragments
(`ops/cardb/`, `ops/rag/pgvec_*`, `api/pipeline.py` stage `pgcar`) but no decision record or benchmark summary
is in the repository. The pgvec/FTS benchmark scripts (`ops/rag/pgvec_bench.py`, `pgfts_load.py`) suggest it was
measured, not guessed.

## Decision (as built)
* Manual vehicle content for loaded cars is read from PostgreSQL (`public.car_dbs` registry, schema per car).
* Parts-only catalogs remain one SQLite file per car under `_parts/`.
* Retrieval, authorization (`allowed_cars`) and the deterministic-retrieval rule of ADR-0002 are unchanged; the
  sqlite3-compatible surface (`PgCarConn`) keeps callers engine-agnostic.
* ADR-0001's "no database server to back up or secure" and "a backup is a file copy" **no longer hold** for car content.

## Consequences
* Backups must cover `kgkg_vec`. They did not on 2026-11-03 [D]: the deploy dump, the hourly snapshot and
  `portal.dump` cover `kgkg` only. This is risk R1 in `27-open-risks-and-decisions.md` and GitHub #80; it needs an
  owner decision, not a documentation fix.
* "The warehouse is derived and rebuildable" (doc 11 section 11.6) is only true while the source ZIPs are retained and a rebuild
  has been rehearsed. Neither is demonstrated.
* Staging reads the same `kgkg_vec` as production (shared connection settings); a staging bug can read, and a
  read-write warehouse mount could modify, production car data. [D]
* Query code must stay within the SQL subset `cardb_pg` translates, or extend the translator and its test.

## Open questions for acceptance
1. Confirm the decision date and rationale (measurements, constraints).
2. Decide the backup/restore design for `kgkg_vec` and `_parts` and record it here or in a successor ADR.
3. Decide whether staging gets its own copy or a read-only role.
