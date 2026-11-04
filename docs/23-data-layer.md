# 23 — Data layer: what is stored where

This is the authoritative map of storage. Docs 01, 02, 03 and ADR 0001 describe the original design
("one read-only SQLite per vehicle"); production has since moved most manual content to PostgreSQL.
ADR `0007` records that change. When this document and the older ones disagree, this one and the code win.

## 23.1 The four stores [C unless tagged]

| Store | Engine | What it holds | Configured by | Code |
|---|---|---|---|---|
| Portal DB `kgkg` | PostgreSQL 16 on the host (`KG_DB_ENGINE=postgres`; SQLite `db.sqlite3` in development) | accounts, companies, grants, sessions, logs, rollups, requests, support chat, KB, flags | `KG_PG_NAME/USER/PASSWORD/HOST/PORT`, `KG_PG_CONN_MAX_AGE` | `KG_backend/KG_backend/settings.py`, `api/models.py` |
| Car content, manual vehicles | PostgreSQL database `kgkg_vec`, one schema `car_<md5(file name)>` per car, registry table `public.car_dbs(filename, schema, nodes, loaded_at)` | the manual tree (`nodes`, HTML, hrefs, paths) with stored lowercase `_lc` twins for LIKE search | `KG_CARDB_PG` (`*` = every loaded car; or `|`-separated file names), `KG_CARDB_PG_DSN` (defaults to the RAG PG DSN) | `api/cardb_pg.py` (`PgCarConn` speaks the small sqlite3 surface the views use), `api/cardb.py` |
| Car content, parts-only vehicles | SQLite file per car under `Database_warehouse/_parts/` | the parts catalog tree | `KG_PARTS_*` paths in `api/parts.py` | `api/parts.py`, `api/partsingest.py` |
| RAG index | `_rag/index.rag.db` (SQLite + FTS5 + `sqlite-vec`) by default; vectors/FTS can be mirrored to `kgkg_vec` (`blob_vec` pgvector HNSW) | chunks, int8[1024] embeddings, graph, diagnostic rules | `RAG_VEC_BACKEND`, `RAG_FTS_BACKEND` (default `sqlite`), `RAG_PGVEC_DSN/DB`, `RAG_PGVEC_EF_SEARCH` | `api/rag/config.py`, `ops/rag/pgvec_load.py`, `ops/rag/pgfts_load.py` |

Other files: `terms.db` (terminology, doc 14), `feedback.db` (assistant feedback), static media under
`static_warehouse` served through nginx with an auth subrequest (`api/mediaauth.py`).

## 23.2 Production state on 2026-11-03 [D: session ea4f3d3e, read-only checks; re-verify before relying]

- 237 cars: **222 manual cars exist only in PostgreSQL `kgkg_vec`** (about 58 GB), **15 parts-only cars** have
  valid SQLite catalogs in `_parts`, **0 cars have both**.
- `cardb_pg.adopt()` loads a new car, re-counts nodes through the serving connection and then **deletes the SQLite
  file** (and `-wal`/`-shm`). The pipeline stage `pgcar` (`api/pipeline.py`) runs it. So for those cars there is
  no SQLite copy to fall back to.
- The deploy-time backup (`deploy.sh` `pg_backup`) dumps database `kgkg` only. `kgkg_vec` is not in it, not in
  the hourly off-host snapshot and not in `portal.dump` [D]. PostgreSQL `archive_mode` was off [D].
  See risk R1 in `27-open-risks-and-decisions.md`.
- Doc 11 section 11.6 calls the warehouse "derived (rebuildable from the source ZIPs)". That is only true if the ZIPs
  are present and the rebuild is feasible; how many of the 222 cars have their ZIP on disk is **[U]**
  (an earlier "26 of 222" figure came from loose name matching and is unreliable).

## 23.3 Behaviours that surprised people [C]

- `has_manual` / `has_parts` on the fleet card come from `cardb.ready_path` / `parts_db_ready`. Before PR #71 the
  parts check accepted the PostgreSQL registry by basename, so 222 of 237 cars showed a parts chip. Parts
  readiness and connections are now SQLite-file-only (`pg=False`); the chip shows only when `has_parts` and not
  `has_manual` (`kg_frontend/src/lib/vehicleContent.js`).
- A car can be served from PostgreSQL while a stale SQLite file with the same name exists: PostgreSQL wins when the
  file name is in `KG_CARDB_PG` or the car is in `public.car_dbs` (cached 60 s, `_LOADED_TTL_S`).
- SQL written for SQLite is translated on the fly (`?`→`%s`, `printf('%08d',x)`→`lpad`, `title|content|href|path LIKE ?`→
  the `_lc` twin, other `LIKE`→`ILIKE`). New queries in views must stay inside that translated subset or extend
  `cardb_pg.py` and its test (`test_cardb_pg.py`).
- Staging (`deploy.sh --staging`) clones only `kgkg`, but its backend uses the production environment, so it reads
  the same `kgkg_vec` and mounts the warehouse read-write [D 2026-11-03]. `smoke_fleet.py` now asserts the
  has_manual/has_parts flags against the endpoints. Treat staging as able to read production car data.

## 23.4 Tools [C]

| Tool | Purpose |
|---|---|
| `ops/cardb/pg_car_load.py "<car>.db"` | copy one SQLite car into its schema; does **not** delete the file |
| `ops/cardb/car_parity.py "<car>.db"` | byte-for-byte parity of `car_view` between SQLite and PostgreSQL in a rolled-back transaction |
| `manage.py copy_sqlite_to_postgres` | copy the portal DB into PostgreSQL (cut-over helper, `ops/deploy/cutover_postgres.sh`) |
| `ops/rag/pgvec_load.py`, `pgfts_load.py`, `pgvec_bench.py` | mirror/benchmark RAG vectors and FTS in PostgreSQL |

## 23.5 What to do before you touch this layer

1. Read `api/cardb.py` `connect()` and `ready_path()` and `api/cardb_pg.py` `PgCarConn`.
2. Run `test_cardb_pg.py`, `tests_parts.py` and `test_vehiclefilter.py`.
3. For anything that deletes, moves or reloads car data: stop and ask the owner. Backups of `kgkg_vec` are
   unverified (R1).
