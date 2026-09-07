# 02 — Architecture

## Runtime topology (single host)

```
                         nginx :80  (103.75.197.155, HTTP only — no TLS yet)
        ┌───────────────────────────┼───────────────────────────────┐
        │ /kg-api/media/*           │ /kg-api/*                     │ /*
        │ alias → static_warehouse/ │ proxy → gunicorn :8000        │ proxy → Next.js :3000
        │ (30d immutable cache)     │ (+ dedicated SSE location:    │ (websocket upgrade kept
        │                           │  /kg-api/api/events/stream/   │  for HMR/dev parity)
        │                           │  proxy_buffering off, 3600s)  │
        ▼                           ▼                               ▼
   Disk (nginx)              Django 5.2 (KG_backend)          Next.js 16 (kg_frontend)
                             ├─ db.sqlite3 (WAL) ────────── users/RBAC/companies/rollups/events/jobs
                             ├─ Database_warehouse/*.db ─── one read-only SQLite per vehicle (38)
                             │    ├─ _rag/index.rag.db ──── unified deduplicated semantic index (~2.3GB)
                             │    ├─ _rag/diag/*.db ─────── per-vehicle diagnostic sidecars
                             │    ├─ _rag/feedback.db ───── ratings/pins/click log (assistant HITL)
                             │    └─ _quarantine/ ────────── corrupt/duplicate files (moved, never deleted)
                             └─ static_warehouse/<car>/ ─── manual images (SVG/PNG), served by nginx

   systemd: kgkg-backend, kgkg-frontend, nginx,
            kgkg-alerts.timer (5m), kgkg-pipeline.timer (5m), kgkg-detect.timer (30s),
            transient kgkg-pipeline-job<id>-a<n> units (detached pipeline workers)
```

The Next.js server is both the SSR frontend AND a thin API proxy for exactly one route:
`/api/chat` (it holds the Metis key server-side). Everything else the browser calls goes to
Django via `/kg-api/…` (the `NEXT_PUBLIC_API_BASE` env). SSR pages call Django directly on
`127.0.0.1:8000` (`BACKEND_URL`), forwarding the portal token from a same-site cookie.

## Stack

| Layer | Tech | Notes |
|---|---|---|
| Frontend | Next.js 16.2.9, React 19.2.4, `motion` 12 | App Router; JS + a few TS files; Tailwind v4 present but styling is hand-written `globals.css` (~1500 lines, CSS variables + `data-theme`) |
| Backend | Django 5.2.15, gunicorn gthread | No DRF — plain `JsonResponse` views, `@csrf_exempt` + token auth |
| DBs | SQLite everywhere | Main DB in WAL + IMMEDIATE transactions; per-car DBs read-only via `api/cardb.py` pool; RAG index via `sqlite-vec` |
| Embeddings | bge-m3 (sentence-transformers 5.6, torch 2.12 CPU) | Fully offline: HF cache at `/root/.cache/huggingface`, `HF_HUB_OFFLINE=1` |
| PDF | WeasyPrint 69 + bundled Vazirmatn TTFs | fa/RTL team reports |
| LLM | Metis (api.metisai.ir, paid, external) | Phrasing only; key lives in frontend server env |
| Proxy | nginx 1.24 | gzip, media alias, SSE passthrough |

## Design principles (the "why" behind the shape)

1. **One vehicle = one immutable content DB.** Content sharding by design: per-vehicle
   isolation, trivially parallelizable, no shared-schema migrations for content changes.
   Serving code (`api/cardb.py`) opens them strictly read-only with a per-thread LRU pool
   (mmap, 16MB page cache, busy timeout, auto-reopen on file replacement).
2. **Metadata in one relational DB.** All Django models are engine-agnostic; PostgreSQL is a
   `DATABASES` swap + dump/load when write contention is *measured*.
3. **Derived data is disposable.** Everything under `_rag/` (index, diag, feedback) and the
   audit reports can be rebuilt from the warehouse. Deleting `_rag/` degrades the site to
   manual browsing — it never breaks it.
4. **No new infrastructure until measured need.** The SSE bus is a SQLite table because the
   process set (3 gunicorn workers + detached pipeline worker) has exactly one shared,
   durable medium and no Redis. The rate limiter is per-process in-memory. Each such piece
   documents its envelope and its replacement path (see Scale path below).
5. **Authorization lives at the lowest layer that serves content.** Per-car access is checked
   in the Django views AND threaded into RAG retrieval as an allow-list (`allowed_cars`), so
   a cached or cross-vehicle result can never leak unpurchased content (see docs 06, 08).
6. **Heavy work never blocks serving.** Embedding/diag builds run in a detached systemd
   transient unit at low CPU/IO priority; progress is derived from artifacts (vector counts,
   sidecar files) so a crash never lies to the admin panel.

## Request-path performance

- Catalog/brand listings: 60s in-process cache; per-file existence checks TTL-cached
  (`cardb.ready_path`) so listings don't `stat()` the whole fleet per request.
- Breadcrumbs: one recursive CTE per page, not N queries.
- Main DB: WAL + `IMMEDIATE` + 20s busy timeout — readers never block on the metrics flush
  or activity writes.
- gunicorn `gthread` (3×8): SQLite reads and media are I/O-bound; threads multiply
  concurrency without multiplying the ~2.3GB embedding model (loaded once per process).
- nginx serves manual images directly from disk with 30-day immutable cache and gzips JSON.
- Metrics middleware aggregates in memory and flushes batched rollups — zero per-request DB
  writes.

## Data flow summaries

**Content ingestion (offline → served):** crawler (`kgtv-downloader/`) fetches manual HTML →
`htmlparser_logical.py` / `parser_gui.py` parse into `<car>.db` (nodes tree) + image files →
files land in `Database_warehouse/` / `static_warehouse/` → `sync_car_catalog` registers the
catalog row → pipeline embeds/graphs/diag-builds → data-quality audit verifies.

**A browse request:** Next SSR page → Django `car_view` (token from cookie, per-car gate) →
per-car DB via pool → HTML content with image URLs rewritten to `/kg-api/media/<car>/…` →
rendered; client beacons activity.

**An assistant question:** browser → Next `/api/chat` → validate `/api/auth/me/` +
`ai_eligible` → Django `/api/diagnose/` (rule engine; car context) → if empty, `/api/assist/`
(RAG) → grounded context → Metis phrase (strict context-only prompt) → faithfulness gate →
answer with real in-app links; fallback renders without LLM.

**A real-time update:** any process emits an `Event` row → SSE endpoint tails the table
(1s poll, 15s heartbeat, 300s recycle, `Last-Event-ID` resume) → nginx streams it unbuffered
→ `useEventStream` hook dispatches to dashboard components.

## Scale path (measured triggers, not speculation)

| Pressure signal | Move |
|---|---|
| `database is locked` in logs (write contention) | PostgreSQL via `DATABASES` swap |
| >1 app host needed | Warehouse + media → shared/object storage; rate limit + cache → Redis; sessions are already DB-backed |
| Media bandwidth | Object storage/CDN for `static_warehouse` (URLs already relative) |
| Embedding rebuild time | `build_rag --add` is incremental + content-deduplicated; shard by car across hosts |
| SSE fan-out beyond ~hundreds of clients | Move Event tailing to Redis pub/sub or a real broker; the client protocol (SSE + Last-Event-ID) stays identical |

Vertical headroom today: 185 GB of 290 GB disk used; CPU/RAM are far from limits at current
traffic. The practical ceiling is disk (fleet growth) and embedding rebuild time, both
detached from request serving.

## Repository layout

```
/opt/KGKG
├─ KG_backend/               Django project
│  ├─ KG_backend/            settings.py, urls.py (includes api.urls), wsgi
│  ├─ api/                   ALL application code (see doc 04)
│  ├─ Database_warehouse/    per-car DBs + _rag/ + _quarantine/  (NOT in git)
│  ├─ static_warehouse/      per-car images                       (NOT in git)
│  ├─ db.sqlite3             main DB                              (untracked 2026-07-10; old copies exist in git history)
│  ├─ ARCHITECTURE.md        original scale-strategy note (kept; superseded by docs/)
│  └─ requirements.txt
├─ kg_frontend/              Next.js app (src/app routes, src/components, src/utils, src/guidance)
├─ docs/                     ← THIS documentation suite
├─ htmlparser_logical.py     manual HTML → per-car SQLite parser
├─ parser_gui.py             tk GUI wrapper for the parser
├─ kgtv-downloader/         source-data crawler
├─ run_rag_build.sh / run_diag_build.sh / run_eval.sh / run_server.sh   convenience scripts
└─ Book1.csv                 EN↔FA parts glossary feeding RAG query expansion
```

**Git notes:** branch `rag-db-improvements` is the live branch (main is stale).
`.gitignore` ignores `*.md` globally (crawled-content protection) — docs must be
`git add -f`. `db.sqlite3` and the warehouses are intentionally untracked.
