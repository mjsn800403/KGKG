# 03 — Data Model

Three storage tiers: the **main relational DB** (`db.sqlite3`, Django ORM), the **per-vehicle
content warehouse** (immutable SQLite files), and the **derived RAG tier** (rebuildable).

## 3.1 Main DB — Django models (`api/models.py`)

### Catalog & sales

**`Car`** (table `main_db` — legacy name, do not rename casually)
`brand_name`, `car_name`, `year`, `db_address` (relative path of the warehouse DB).
One row per servable vehicle. `car_name` doubles as the RAG `car_stem`; the stem/name
equality is relied on by content authorization (`views._user_allowed_stems`).

**`PurchaseRequest`** — public lead form from `/purchase`: vehicle (brand/model/year),
requested `documents` (JSON list of package ids), legal-entity contact (company, landline,
mobile, reg_no), sizing (`employees_count`, `seats_count`, `seat_plan` JSON rows
`{role, department, count, note}`), extras (`wants_demo`, `wants_ai_assistant`), workflow
`status` (new/reviewing/approved/rejected) + `handled`.

### Access control (see doc 06 for semantics)

**`Company`** — legal entity: `name` (unique), `department_label` (customizes role labels),
contact fields, `seats_count`, `is_demo`, `ai_assistant_enabled` (company-level AI gate),
`active`, `note`.

**`CompanyCarAccess`** — what a company purchased: `(company, car)` unique + `documents`
(JSON subset of package ids; **empty list = all layers**).

**`OrgRole`** — company-defined position: `name` (unique per company), `rank`
(1 = top, smaller outranks), `manage_scope` (`org` | `subtree` | `none`), capability
defaults (`can_manage_team`, `can_view_analytics`, `ai_assistant_enabled`), `color`
(org-chart accent), `default_accesses` (JSON access template `[{car_id, documents}]`
auto-applied to new members). Four canonical roles are seeded per company
(`access.seed_default_org_roles`).

**`PortalUser`** — a company seat: `username` (unique), `email` (unique, alternate login
id), `phone`, `personnel_code`, `password_hash`, `display_name`, legacy `role` charfield
(kept in sync with `org_role` via `legacy_role_for_rank`), `org_role` FK, `reports_to`
self-FK (explicit org edge; invariant: supervisor strictly outranks report), capability
flags (`can_manage_team`, `can_view_analytics`, `ai_assistant_enabled`), `active`, `locked`,
invite lifecycle (`invite_status` active/invited/disabled, `password_set`, `invited_by`),
`access_expires_at`, `last_login_at`.

**`UserCarAccess`** — per-user grant: `(user, car)` unique, `documents` (subset of the
company scope), `admin_granted` (bypasses purchase clamps; survives company re-scopes).

### Auth tokens

**`AuthToken`** — opaque 64-hex bearer token per portal login (DB-backed session; multiple
tokens per user allowed). **`AdminAuthToken`** — same for platform admins.
**`PlatformAdmin`** — vendor superuser (separate namespace from portal users).
**`InviteToken`** — single-use, 7-day TTL, sha256-hashed at rest; `issue()` returns the raw
token exactly once (embedded in the invite URL); issuing invalidates prior unused invites.

### Telemetry & analytics

**`ActivityLog`** — one row per user action: `action` (login/view_car/view_node/search/
assist…), `detail`, `category` (canonical technical area), `car` FK, `node_title`,
`app_url` (deep-link for recommendations). Indexed by (user, created_at), (category,
created_at), (created_at).

**`TrafficStat`** — hourly per-endpoint-group rollups (requests, 4xx, 5xx, total/max
latency), written by the batched metrics flusher. **`VisitorSeen`** — (day, salted IP hash)
for exact daily uniques; pruned after ~90 days.

### Operations

**`DataQualityRun`** — one audit pass: status, `summary` (aggregate counters), `vehicles`
(per-vehicle detail), `actions` (fixes taken/recommended).

**`ProcessingJob`** — one pipeline run: status machine
(pending/scheduled/running/paused/stalled/done/failed/canceled), `trigger`
(manual/auto/schedule), worker identity (`pid`, `unit_name`), `attempts`, `stages` (JSON
per-stage state), `progress` (JSON: overall_pct/stage/eta_s/rate), `log_tail`, heartbeat.
Resumable states: paused/stalled/failed. Active (slot-occupying): pending/running.

**`PipelineSettings`** — singleton (id=1): `auto_enabled`, `load_threshold` (load1/cores
gate for auto-starts), `auto_resume`, observed throughput (`embed_rate_pps`,
`diag_secs_per_car`) used for honest ETA estimates.

**`SystemAlert`** — deduplicated operational alerts keyed by condition (`disk_high`,
`error_rate:assist`…), severity info/warning/critical, auto-resolve, first/last seen.

### Real-time & requests

**`Event`** — append-only event log; the SSE backbone. `type` (dotted, e.g.
`request.updated`), `audience` (admin/company/user/all), plain-int `company_id`/`user_id`
(events outlive the rows they describe), JSON `payload`. `id` is the resume cursor.
Trimmed to ~20k rows (amortized).

**`SystemState`** — tiny key→JSON store for cross-worker singletons (e.g. the pending-work
fingerprint the change detector diffs against).

**`CompanyRequest`** — manager-filed request to the vendor: `kind` (vehicle_access / seats /
ai_assistant / documents / support / other), `subject`, `body`, structured `payload`,
`status` (pending/in_progress/completed/rejected), `priority`, `admin_note`, `handled_by`.
Every transition emits events to both company and admin audiences.

## 3.2 Migration history

| # | What it added |
|---|---|
| 0001–0004 | Car catalog, PurchaseRequest, Company, employees/seats sizing |
| 0005 | RBAC packages + PlatformAdmin/AdminAuthToken |
| 0006 | `seat_plan` on PurchaseRequest |
| 0007 | Team management: PortalUser email/phone/capabilities/invites, InviteToken, ActivityLog category/car/node_title |
| 0008 | DataQualityRun, SystemAlert, TrafficStat, VisitorSeen |
| 0009 | PipelineSettings, ProcessingJob |
| 0010 | OrgRole (+ seeding) |
| 0011 | CompanyRequest, Event, SystemState |
| 0012 | ActivityLog.app_url |

## 3.3 Per-vehicle warehouse DB (`Database_warehouse/<car_stem>.db`)

Produced by `htmlparser_logical.py`; opened read-only by serving code. Schema:

```sql
CREATE TABLE nodes (
  id          TEXT PRIMARY KEY,   -- sha1(path)
  parent_id   TEXT,               -- sha1(parent path); NULL at root
  path        TEXT NOT NULL,      -- absolute breadcrumb logical path
                                  -- NOTE: literal '/' inside a TITLE is encoded as U+2044 (⁄)
  title       TEXT NOT NULL,
  node_type   TEXT,               -- 'root' | 'folder' | 'leaf'
  file_type   TEXT,               -- 'root_path' | 'intermediate_path' | 'end_path'
  href        TEXT,               -- original link target, if any
  source_file TEXT,               -- html file this row was parsed from
  sort_order  INTEGER DEFAULT 0,
  depth       INTEGER DEFAULT 0,
  root_order  INTEGER,            -- ordering among root nodes
  content     TEXT,               -- raw div.main inner HTML for end_path rows
  updated_at  TEXT
);
CREATE TABLE crawl_state (k TEXT PRIMARY KEY, v TEXT);  -- 'snapshot' | 'status' JSON
```

Key facts:
- Manual sections live under the depth-0 root **"Repair and Diagnosis"**; depth-2 titles are
  the technical areas mapped onto canonical categories (`access.CONTENT_CATEGORIES`).
- Content HTML references images as relative `images/...` or `/api/Image/SVGImage/...`;
  `views.rewrite_image_urls` rewrites them to `/kg-api/media/<car>/…`.
- **U+2044 gotcha:** the `path` column encodes `/` inside titles as `⁄`. Anything comparing
  paths across systems must normalize it (data quality and RAG code do).
- Trim families often ship byte-identical manuals (e.g. 4Runner TRD Pro ≡ Trailhunter) —
  legitimate, deduplicated for free at the RAG blob layer.

## 3.4 RAG index (`Database_warehouse/_rag/index.rag.db`)

Content-addressed & deduplicated (see `api/rag/config.py` docstring):

| Table | Purpose |
|---|---|
| `blobs` | One row per unique cleaned page text (sha-keyed); fleet-wide dedup (~72% of leaves are exact duplicates) |
| `occurrences` | Every (car_stem, title_path, year, app-url metadata) where a blob appears — the *servable-car source of truth*; `occurrences.car_stem == Car.car_name` |
| `chunks` / `vec_blobs*` | sqlite-vec int8 embedding storage (bge-m3, 1024-dim); `vec_blobs_rowids` is the countable table (the vec0 extension isn't loaded on plain connections — count rowids, not `vec_blobs`) |
| `blobs_fts*` | FTS5 lexical index (hybrid retrieval) |
| `edges` | Blob-level relationship graph: `semantic` (kNN), `crosslink` (manual's own hrefs), `labor_time` (procedure ↔ labor-times page) |
| `cars`, `meta` | Car registry snapshot + build metadata (`graph_synced_vectors` marks the embed→graph handoff for resume) |

Diag sidecars: `_rag/diag/<car_stem>.diag.db` — DTC subtrees, symptom tables, labor rows,
pre-built app URLs. Feedback: `_rag/feedback.db` — 👍/👎 ratings, expert pins, click log.

**Rebuild rules:** everything under `_rag/` is disposable. `build_rag --add` only ingests
*missing cars* — resuming a half-embedded index means calling `embed.embed_index` directly,
then `store.drop_build_vec` **before** `graph.build_all` (a stale partial float table would
silently lose edges). The pipeline encodes this correctly; don't hand-roll it.

## 3.5 Data invariants worth protecting

1. `Car.car_name` ⇔ warehouse filename stem ⇔ `occurrences.car_stem`. Renaming any leg
   breaks content auth and assistant links.
2. `UserCarAccess.documents ⊆ CompanyCarAccess.documents` unless `admin_granted`.
   Enforced by `access.apply_user_access` / `apply_managed_access` — never write grants
   around them.
3. Org edge invariant: `rank(reports_to) < rank(user)` — enforced at every write and
   auto-repaired by `access.enforce_org_consistency`.
4. Empty `documents` on a **company** grant means "all layers", but user grants are always
   stored explicit (never empty) to avoid accidental ceiling lifts.
5. `Event.id` ordering is the SSE resume contract — never reuse/renumber ids.
