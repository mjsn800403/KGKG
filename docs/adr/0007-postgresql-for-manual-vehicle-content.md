# ADR-0007 — Retrospective record: PostgreSQL stores in the data layer (amends ADR-0001)

**Status:** Proposed. This is a *retrospective* record of an implementation that already exists. It stays Proposed until the
maintainers ratify it. Ratifying it accepts the **description** below; it does **not** resolve the operational risks in section 6,
which are separate decisions. · **Amends:** [ADR-0001](0001-sqlite-and-per-vehicle-databases.md) in part · **Recorded:** 2026-11-04

How to read the tags: **[C]** verified in code at `origin/work` `8a380f6`; **[H]** historical statement found in the repository
(CHANGELOG, docs, git history) or in team discussion, not independently re-verified; **[S]** observed in production, with date;
**[U]** unknown / not established. Nothing here states a decision date, decision-maker, benchmark result or rationale that was
not found; where none was found, it says so.

## 1. Context

ADR-0001 (recorded 2026-10-29 for a decision in force since 2026-06) chose SQLite for application data and one read-only SQLite
file per vehicle. The codebase now contains PostgreSQL-backed storage in several places. This ADR records what exists.

## 2. Implementation facts [C]

| Responsibility | Store | Selected by | Code |
|---|---|---|---|
| **Application (portal) database**: accounts, companies, grants, sessions, logs, requests, support chat, knowledge base | PostgreSQL 16, database `kgkg` when `KG_DB_ENGINE=postgres`; SQLite file otherwise (development default) | `KG_DB_ENGINE`, `KG_PG_*` | `KG_backend/settings.py` |
| **Vehicle content, manual cars** | PostgreSQL database `kgkg_vec`: one schema `car_<md5 of file name>` per car; registry table `public.car_dbs` | a car is served from PostgreSQL if its file name is in `KG_CARDB_PG` (`*` = every loaded car) or in the registry; registry cached 60 s | `api/cardb.py` `connect()`, `api/cardb_pg.py` (`PgCarConn`, translated SQL subset) |
| **Vehicle content, parts-only cars** | one read-only SQLite file per car under `Database_warehouse/_parts/` | parts readiness is SQLite-file-only (`pg=False`) since PR #71 | `api/parts.py`, `api/cardb.py` |
| **RAG storage** | `_rag/index.rag.db` (SQLite, FTS5, `sqlite-vec`) is the default; vectors and FTS *can* be mirrored into `kgkg_vec` (pgvector HNSW) | `RAG_VEC_BACKEND`, `RAG_FTS_BACKEND` (both default `sqlite`) | `api/rag/config.py`, `ops/rag/pgvec_load.py`, `ops/rag/pgfts_load.py` |

Loading and lifecycle [C]: `ops/cardb/pg_car_load.py` copies a car's SQLite file into its schema and does not delete it;
`cardb_pg.adopt()` loads, re-counts nodes through the serving connection and then **deletes the SQLite file** (and `-wal`/`-shm`);
the pipeline stage `pgcar` (`api/pipeline.py`) runs it for new cars when `KG_CARDB_PG=*`. `ops/cardb/car_parity.py` compares
`car_view` output between the two engines in a rolled-back transaction.

What did not change [C]: retrieval is local and deterministic (ADR-0002); authorization (`allowed_cars`) is applied in the views and
inside retrieval; the `Car` rows and the file-name key still identify a vehicle.

## 3. Historical statements [H]

- The portal database moved to PostgreSQL on 2026-10-29 (`docs/01-overview.md`, `02-architecture.md`; `ops/deploy/cutover_postgres.sh`,
  `manage.py copy_sqlite_to_postgres`). `db.sqlite3` was kept frozen as the way back.
- The PostgreSQL car-content layer, the `pgcar` pipeline stage and the pgvector/FTS scripts exist in the repository, and benchmark
  scripts (`ops/rag/pgvec_bench.py`) are present. The commit and PR history would show when each arrived; **this ADR does not
  reconstruct it**.

## 4. Observed production state [S]

On 2026-11-03 (read-only checks recorded in a Claude session, not repeated by this documentation work): 237 cars; 222 manual cars
existed only in `kgkg_vec` (about 58 GB); 15 parts-only cars had valid SQLite catalogs in `_parts`; no car had both. Re-verify
before relying on these numbers.

## 5. Unresolved questions about the decision itself [U]

- When the move of vehicle content to PostgreSQL was decided, by whom, and when it took effect.
- The rationale and constraints that led to it. No decision text, benchmark summary or comparison was found in the repository.
- Whether the benchmark scripts' results justified it, and where those results are kept.

## 6. Operational decisions that this ADR does NOT settle

Each needs its own owner decision and, when taken, its own record (a new ADR or a runbook change). Accepting this ADR must not be read
as accepting or resolving any of them. Tracked in [27-open-risks-and-decisions.md](../27-open-risks-and-decisions.md).

| # | Open decision | Why it is open | Tracking |
|---|---|---|---|
| D1 | **Backup and recovery of `kgkg_vec`, `_parts` and static images** | Deploy-time `pg_dump` covers `kgkg` only; no backup of `kgkg_vec` was found in the hourly snapshot (observed 2026-11-03); SQLite files are deleted after loading; rebuild from source ZIPs is not demonstrated; PostgreSQL `archive_mode` was off | R1, GitHub #80, KGTEC-18 |
| D2 | **Staging isolation** | Staging clones only `kgkg` but its backend used the production environment, so it read the production `kgkg_vec`, with the warehouse mounted read-write (observed 2026-11-03) | R5 (no issue yet) |
| D3 | **Which engine serves which content in future** (for example whether parts catalogs or the RAG index move too) | not decided anywhere found | none |
| D4 | **Ratifying the original decision's date and rationale** | see section 5 | this ADR |

## 7. Consequences of the implementation (descriptive, not a judgement)

- ADR-0001's "no database server to run, back up or secure" and "a backup is a file copy" do not hold for vehicle content.
- SQL written for SQLite reaches PostgreSQL through a translator limited to a small subset (`cardb_pg.py`); new queries must stay within
  it or extend it and `test_cardb_pg.py`.
- Doc [23 — Data layer](../23-data-layer.md) is the working map of what lives where.
