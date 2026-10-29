# ADR-0001 — SQLite (WAL) for application data; one read-only SQLite file per vehicle

**Status:** Accepted · **Since:** 2026-06 (project start) · **Recorded:** 2026-10-29

## Context
The product serves large, immutable manual content: 38 vehicles, 21 GB of warehouse data
and about 300k pages. It also keeps small, mutable application data: companies, users,
grants, events and analytics. The whole system runs on one host, run by a very small team.
The expected load is tens of concurrent users; the measured peak on 2026-10-27 was
0.22 req/s.

## Decision
* **Each vehicle manual is parsed once** into its own SQLite file, opened read-only by
  serving code (`mode=ro`).
* **Adding a vehicle is a file copy** plus a catalog sync. No schema migration, no downtime.
* **Everything else lives in one Django database**, `db.sqlite3`, in WAL mode, through the
  engine-agnostic ORM.
* **The RAG index is a separate SQLite file** with sqlite-vec (`_rag/index.rag.db`).

## Consequences
* **No database server to run, back up or secure.** A backup is a file copy (online-safe in
  WAL mode).
* **Writes are serialised.** That is acceptable at measured load, but a second writer process
  is a known risk: observation O-1 (`disk I/O error` under concurrent re-seeding) is
  unexplained.
* **Moving to PostgreSQL is a settings change for app data.** It is not for the per-vehicle
  files, which are content, not state.
* **A missing or moved file must fail loudly, not be silently created.** D-41: a read-only
  open created an empty index.

## Evidence
`docs/01-overview.md` ("Why it is built the way it is"), `docs/03-data-model.md`,
`KG_backend/ARCHITECTURE.md`, `api/rag/store.py`, `api/rag/test_store_ro.py`.
