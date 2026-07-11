# KGtechvault — Architecture & Scale Strategy

Persian (RTL) technical-documentation platform for automotive service teams
(Toyota / Lexus manuals), with RAG-grounded AI assistance.

```
                       nginx :80
        ┌────────────────┴───────────────────┐
        │ /kg-api/*  → gunicorn :8000        │  /* → Next.js :3000
        │ /kg-api/media/* served from disk   │
        ▼                                    ▼
   Django 5.2 (KG_backend)             Next.js 16 (kg_frontend)
   ├─ db.sqlite3 (WAL)  ── users/RBAC/companies/analytics rollups
   ├─ Database_warehouse/*.db ── one read-only SQLite per vehicle
   │    └─ _rag/index.rag.db ── unified deduplicated semantic index
   │    └─ _rag/diag/*.db    ── per-vehicle diagnostic sidecars
   │    └─ _quarantine/      ── corrupt/duplicate files (moved, never deleted)
   └─ static_warehouse/<car>/ ── manual images (SVG/PNG)
```

## Design principles

* **One vehicle = one immutable content DB.** The warehouse is a flat set of
  self-contained SQLite files, opened strictly read-only by serving code
  (`api/cardb.py`). Adding vehicle #4,000 is `scp` + `sync_car_catalog` —
  no migration, no shared-schema change, no downtime. This is deliberate
  content sharding: per-vehicle isolation, trivially parallelizable, and
  files can move to any number of hosts later.
* **Metadata lives in one relational DB** (`db.sqlite3`, WAL mode). All
  models are plain Django ORM — the code is engine-agnostic; moving to
  PostgreSQL is a `DATABASES` settings change + `dumpdata/loaddata` when
  concurrency demands it (see Scale path).
* **Derived data is disposable.** The RAG index, diag sidecars, feedback DB
  and audit reports can all be rebuilt from the warehouse. Nothing under
  `_rag/` is a source of truth.
* **Dependency-light by policy.** No DRF, no Redis, no Celery until a
  measured need exists. Every hand-rolled piece states its scale envelope in
  its docstring (rate limiter, metrics aggregator, audit runner).

## Serving-path performance

* `api/cardb.py` — per-thread LRU pool of read-only connections (mmap,
  16MB page cache, busy-timeout). Bounded FDs regardless of fleet size.
  Reopens automatically when a file is replaced (mtime/size signature).
* Breadcrumb chains use one recursive CTE instead of N per-row queries.
* Catalog/brand listings: 60s in-process cache; per-file existence checks
  TTL-cached (`cardb.ready_path`) so listings don't stat() the fleet per
  request.
* Main DB: WAL + IMMEDIATE transactions + busy timeout — readers never block,
  concurrent gunicorn workers don't see `database is locked`.
* gunicorn `gthread` workers: SQLite reads and media are I/O-bound; threads
  multiply concurrency without multiplying the ~2.3GB embedding model
  (which loads once per *process*).
* nginx serves `/kg-api/media/*` directly from `static_warehouse/` (long
  cache), taking image bytes off Python entirely; gzip on JSON.

## Data quality (api/dataquality.py)

`python manage.py audit_vehicles [--fix]`, also admin panel → «سلامت داده‌ها».

* **Duplicates**: content fingerprint (SHA1 over the manual tree with the
  car-specific root stripped) + name analysis. `"X (1)"` matching `"X"`
  byte-for-byte = same vehicle uploaded twice → merged (grants + activity
  repointed to the original, files quarantined). Identical content across
  *different* trims is normal (Toyota ships one manual per trim family) and
  reported as info only.
* **Completeness**: every vehicle is measured against the canonical section
  schema with normalized titles; powertrain-aware requirements (EVs aren't
  penalized for lacking "Engine Mechanical", non-hybrids for lacking
  "Hybrid/Electric Powertrain").
* **Process backlog**: per vehicle — catalog row, static assets, RAG
  coverage, diag sidecar, integrity. The report lists exactly which command
  is still pending per vehicle.
* Fix mode never deletes: corrupt/duplicate files move to `_quarantine/`.

## Observability (api/monitoring.py)

* Request metrics middleware: in-memory aggregation, periodic batched flush
  to hourly rollups (`TrafficStat`) + exact daily uniques (`VisitorSeen`,
  salted irreversible IP hashes). Zero per-request DB writes; tables grow
  with hours, not traffic.
* `/api/health/` — public liveness probe (uptime monitors / LB checks).
* Admin panel → «پایش سیستم»: disk/memory/load/uptime, DB + RAG index
  status, traffic series, per-endpoint latency & error rates, feature usage.
* Alerting: `python manage.py check_alerts` (systemd timer, 5min) evaluates
  disk / memory / DB liveness / 5xx rate / latency / data-quality
  regressions into deduplicated `SystemAlert` rows with auto-resolve.
  Thresholds are env-tunable (`KG_ALERT_*`).

## Data-processing pipeline (api/pipeline.py)

Admin panel → «پردازش داده‌ها»: one button runs every pending server-side
process (catalog sync → RAG ingest/embed/graph → per-car diagnostics →
audit refresh) with live per-stage progress, rate and ETA. Designed so a
non-technical admin can operate it and nothing can half-break:

* The worker is a DETACHED process in its own systemd transient unit
  (`systemd-run`, Nice 15 / CPUWeight 25 / IO-idle) — closing the browser,
  restarting the backend, or deploying never interrupts it, and serving
  traffic always outranks it on CPU/IO.
* Every stage is incremental and kill-safe: embedding commits per window
  (`vec_blobs` is always a contiguous prefix), diag sidecars are per-car
  files, catalog sync is idempotent. A `graph_synced_vectors` marker makes
  the embed→graph handoff resumable too (after a resumed embed the graph is
  rebuilt from the persisted int8 vectors — the transient float table is
  dropped because it would only cover newer blobs).
* `pipeline_tick` (systemd timer, 5 min) is watchdog + scheduler + autopilot:
  detects dead workers via heartbeat + pid liveness and relaunches them
  (bounded attempts), starts jobs whose scheduled time arrived, and — when
  auto mode is on — starts processing of newly landed vehicle data by itself
  once server load per core is under the configured threshold.
* Single-flight everywhere: an atomic DB claim (pending→running exactly
  once), plus a /proc scan refusing to start on top of a shell-launched
  build_rag/build_diag.
* Progress is computed from the artifacts themselves (vector counts, sidecar
  files), so the panel shows the truth even right after a crash; duration
  estimates come from this server's observed throughput, persisted in
  `PipelineSettings`.

## Scale path (measured triggers, not speculation)

| Pressure signal | Move |
|---|---|
| write contention on db.sqlite3 (locked errors in logs) | PostgreSQL via `DATABASES` swap; models already engine-agnostic |
| >1 app host needed | warehouse + media to shared/object storage; rate-limit + cache to Redis; sessions are already DB-backed (shared) |
| media bandwidth | object storage/CDN for `static_warehouse` (URLs already relative) |
| embedding rebuild time | `build_rag --add` is incremental & content-deduplicated; shard by car across hosts if ever needed |
| in-memory rate limiter / caches per-worker drift | swap to Redis-backed implementations (interfaces are already isolated in `ratelimit.py` / Django cache) |

Vertical headroom today: 16 cores / 31GB serve read-mostly SQLite with mmap;
the practical ceiling is disk (fleet growth) and embedding rebuilds, both
detached from request serving.

## Operational commands

```
python manage.py audit_vehicles [--fix] [--json]   # data-quality audit
python manage.py sync_car_catalog [--dry-run]      # register new warehouse DBs
python manage.py build_rag --add                   # index cars missing from RAG
python manage.py build_diag                        # diagnostic sidecars
python manage.py check_alerts                      # alert sweep + retention
python manage.py pipeline_tick                     # pipeline watchdog/scheduler pass
python manage.py run_pipeline --job <id>           # pipeline worker (spawned, not manual)
```
