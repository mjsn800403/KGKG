# 04 — Backend Reference (`KG_backend/api`)

One Django app holds everything. Modules, what they own, and what to know before editing.

## Serving & auth

### `views.py` — public catalog + gated manual content + RAG endpoints
- `brands_list_view` (GET `/`) — public brand list (sales page needs it), 60s cached.
- `car_view` — the content workhorse for `/brand/`, `/brand/year/`,
  `/brand/year/model/?seg=…`. Cases: brand→years, year→models, model→node tree walk.
  Year resolution is *tolerant* (exact → brand+name fallback) because legacy assistant links
  can carry `'unknown'`. Node paths are passed as repeated `?seg=` params (titles can
  contain `/`). Uses the `cardb` pool — **never close pooled connections**.
- `assist_view`, `diagnose_view`, `search_view` — RAG/diag/semantic search, all guarded by
  `_guard_car_content` (login + per-car gate + `allowed_cars` allow-list threading).
- `_guard_car_content` / `_resolve_car` / `_user_allowed_stems` — the content authorization
  helpers (doc 06 §6.4).
- `purchase_request_view` — public POST with validation + rate limit.
- Feedback: `feedback_rate_view` (👍/👎), `feedback_pin_view` (expert pins),
  `feedback_recent_view` (admin review feed), `assist_feedback_view` (click log),
  `eval_report_view` (offline eval harness results).
- `rewrite_image_urls`, `read_page_content`, `node_to_dict` — content HTML massage.

### `portal.py` — portal + admin auth, admin CRUD API
- `portal_user(request)` — session resolver: Bearer header **or** `kg_portal_token` cookie
  (SSR path); checks active/locked/expiry on user and company.
- `login_view` — username OR email; timing-equalized against user enumeration; emits
  login activity/event. `logout_view`, `me_view`, `fleet_view` (granted + on-disk cars),
  `activity_view` (the activity beacon sink; resolves category from segments).
- Admin: `admin_login_view` (PlatformAdmin + AdminAuthToken), `admin_overview_view`,
  `admin_packages_view`, `admin_requests_view` (+status), `admin_cars_view`,
  `admin_companies_view` (+detail: create/update companies), `admin_company_access_view` (purchase scope; prunes user grants on re-scope),
  `admin_users_view` (+detail +access), `admin_activity_view`, `admin_analytics_view`
  (cross-company analytics). Admin user-update runs `enforce_org_consistency`.
- `_user_dict` is THE user payload shape shared by login/me/team — grep it before changing.

### `admin_auth.py` / `portal_auth.py` — decorators
- `require_admin_token` — `KG_ADMIN_TOKEN` env value **or** an `AdminAuthToken` session
  (DEBUG mode is open when no token configured).
- `require_manager` / `require_analytics` — portal-token + capability gates.
- `user_can_view_company_stream` — company SSE audience rule (manage OR analytics).

### `access.py` — the RBAC spine (doc 06 covers semantics)
Roles/levels, packages, capability seeding, legacy rank/scope helpers (still used when a user has no seat), seat-based reach through `orggraph`,
`manageable_user_ids` / `subtree_user_ids` / `manager_can_target`,
`find_valid_supervisor` / `enforce_org_consistency`,
grant writers `apply_user_access` / `apply_managed_access` / `manager_grantable_cars`,
AI eligibility (`user_ai_eligible`), per-car docs resolution (`user_car_documents`),
content-category taxonomy + `resolve_category`.

### `team.py` — invite acceptance, team analytics, PDF report
The member/role CRUD that used to live here (`team_members_view`, `team_roles_view`, `team_org_view` ...) was **removed** when the org-graph canvas replaced it
(`orggraph_api.py`, `api/org/*`; see [06](06-permissions-rbac.md) section 6.6). What remains: invite acceptance (`invite_view`: GET validates, POST sets the
password, activates and auto-logs-in), company usage analytics (`build_team_analytics`, `team_analytics_view`) and the Persian PDF (`team_report_pdf_view`).
`_emit_team` (the old `team.*` live-sync emitter) is still defined but has no caller at this revision **[C]**. **Boundary rule:** form ids arrive
as strings; coerce with `_as_id` before comparing to int sets (the 2026-07-14 bug class).

### `orggraph_api.py` / `orggraph.py` — org-graph canvas
`api/org/graph|nodes|nodes/<id>|nodes/<id>/permission|nodes/<id>/create-user` (root-only writes via `require_root`; any company member may read) and
`api/admin/org/reassign-root/`. `orggraph.py` compiles a seat's `NodePermission` into the real enforcement state (`sync_node_to_user`), mirrors the canvas
parent edge onto `reports_to`, decides who sees the team page (`user_can_view_team`) and seeds graphs for new companies. Semantics: [06](06-permissions-rbac.md) section 6.6.

### `ratelimit.py` — sliding-window limiter with a shared store
`@rate_limited(name, limit, window)`; per-IP via `X-Real-IP`/last-XFF-hop when
`KG_TRUST_PROXY=1` (nginx sets it). Counters live in a SQLite file (`KG_RL_STORE`, default `/tmp/kg_ratelimit.sqlite3`) shared by all gunicorn workers of one
container, so the cap is not multiplied by the worker count; if the file cannot be used the limiter falls back to an in-process window (then ≈ workers × nominal) and
never blocks on its own fault. The file is container-local and ephemeral (reset by a deploy). The support chat's per-thread *poll* limiter is deliberately in-process
(see [35](35-support-system.md)); its other limits use this shared store. `KG_RL_DISABLE=1` for tests. Rules overridable via env `KG_RL_<NAME>`.

## Real-time & requests

### `events.py` — SSE backbone (doc 09)
`emit`/`emit_company`/`emit_user` (best-effort INSERT), `stream_view` (SSE; admin or portal
auth; audience scoping; Last-Event-ID resume; 1s tail/15s heartbeat/300s recycle),
`recent_view` (REST companion), `snapshot_pending`, `detect_and_emit` (fingerprint diff →
`data.detected`/`processing.pending`), amortized trim to ~20k rows.

### `requests_api.py` — CompanyRequest lifecycle
Manager list/create (`company_requests_view`), detail/cancel; admin inbox
(`admin_company_requests_view`) and actions (status transitions, note, priority) — every
transition emits to both audiences. `_sanitize_payload` whitelists the structured payload
per kind.

## Analytics & recommendations

### `recommend.py` (doc 10)
`recommend_for_user` — continue / related (RAG graph neighbours, gated to owned cars) /
focus_areas (category affinity) / popular_in_company / explore. `insights_for_manager` —
seat utilization, idle/top members, category coverage+gaps. Endpoints
`recommendations_view`, `manager_insights_view`.

### `reporting.py` — WeasyPrint fa/RTL PDF team report
Jalali date conversion (arithmetic), fa digits, donut/trend SVGs. **Font gotcha:** uses the
FULL official Vazirmatn Regular/Bold TTFs in `reporting_assets/fonts/` — subset/woff2-derived
fonts garble Latin and `ل`; don't replace. SVG `<text>` gets no bidi in WeasyPrint —
center labels are HTML overlays.

## Operations

### `monitoring.py` (doc 11)
`RequestMetricsMiddleware` (first in chain; in-memory agg → periodic batched flush to
TrafficStat/VisitorSeen; quiescent under the test runner), `system_snapshot`
(disk/mem/load/db/rag status), `evaluate_alerts` (disk/mem/db-liveness/5xx-rate/latency/DQ
alerts; dedup by key; auto-resolve; env-tunable `KG_ALERT_*`), `prune_old_data`.

### `dataquality.py` (doc 11)
Fleet audit: canonical-section completeness (normalizes `&`/`and` AND U+2044), powertrain-
aware requirements (EV/hybrid by stem), content fingerprint (strips the tree's OWN depth-0
root path — renamed "(1)" copies keep the original root inside), duplicate merge (grants +
activity repointed; files → `_quarantine/`, never deleted), backlog per vehicle.
`run_audit_to_db` / `run_audit_async` for the admin panel.

### `pipeline.py` (doc 11)
`pending_work` (what needs processing), `start_job`/`resume_job`/`cancel_job` (atomic
single-flight claim + /proc scan against shell-launched builds), `launch_worker`
(systemd-run transient unit, Nice 15/CPUWeight 25/IO idle; falls back to plain detached
process), `tick` (watchdog: heartbeat+pid liveness → relaunch, bounded attempts; scheduler;
auto-start under load threshold), `job_dict` (panel payload).

### `adminops.py`
`health_view` (public liveness), `admin_data_quality_view` (GET report / POST refresh|fix →
background thread), `admin_system_view`, `admin_traffic_view`, `admin_pipeline_view`
(GET status / POST start|schedule|resume|cancel|settings), `admin_processing_snapshot_view`,
`admin_dashboard_view` (KPI aggregate for the live dashboard).

### `cardb.py`
Per-thread LRU pool (default 8/thread) of read-only car-DB connections; reopen on
mtime/size change; recursive-CTE `breadcrumbs`; TTL `ready_path` (30s) + cache
invalidation. **Views must never `.close()` pooled connections.**

## RAG subsystem (`api/rag/`, doc 08)

`config.py` (paths, registry, `car_meta` with catalog fallback), `ingest.py` (blob/occurrence
extraction), `embed.py` (bge-m3, windowed commits), `store.py` (index access, vec tables),
`graph.py` (semantic/crosslink/labor edges), `retrieve.py` (hybrid retrieval + scope gates +
app-URL building — `_enc(safe='')` everywhere), `scoring.py`, `glossary.py` (Book1.csv EN↔FA
parts expansion), `service.py` (TTL caches, embed lock, allowed_cars in cache keys),
`diag_build.py`/`diag.py` (sidecar build/query), `feedback.py` (ratings/pins/clicks),
`evalmetrics.py`/`evalreport.py` (offline eval harness).

## Management commands (`api/management/commands/`)

| Command | Purpose |
|---|---|
| `audit_vehicles [--fix] [--json]` | Data-quality audit (fix = remediate + quarantine) |
| `sync_car_catalog [--dry-run]` | Register new warehouse DBs as catalog rows |
| `build_rag [--add]` | Build/extend the RAG index (`--add` = only missing cars; no-op if none) |
| `build_diag` | Build per-car diagnostic sidecars |
| `optimize_index` | Index maintenance (FTS/vacuum) |
| `eval_rag` | Offline retrieval evaluation harness |
| `check_alerts` | Alert sweep + data retention (systemd timer, 5 min) |
| `process_outbox [--limit N]` | Send due outbox notifications (SMS/email) with retry; no-op while `KG_NOTIFY_*` is `off`. Unit and timer (every minute) are in `ops/outbox/`; whether they are installed and enabled on the host is **[U]** |
| `purge_support_chat [--apply]` | Reports support threads past the PROPOSED retention periods. Deletes nothing unless `KG_SUPPORT_RETENTION_ENABLED=1` and `--apply` (no policy is approved yet) |
| `pipeline_tick` | Pipeline watchdog/scheduler/autopilot pass (timer, 5 min) |
| `run_pipeline --job <id>` | Pipeline worker entry (spawned; not run manually) |
| `realtime_tick` | Change detector → events (kgkg-detect.timer, 30s) |
| `backfill_team` | One-time: promoted top-role user per company to manager (historical, from the rank-based model) |

## Tests

There are 112 test modules under `KG_backend/` at `origin/work` `07f3ab5` (`api/tests.py`, `api/test_*.py`, `api/rag/test_*.py`, `api/support_chat/test_*.py`,
`api/notifications/test_*.py`); the full map, commands, coverage floor and CI behaviour are in [32-testing-and-qa.md](32-testing-and-qa.md). (This section once
quoted "~193 tests green as of 2026-07-14"; that number is historical.) Quick run:

```bash
cd /opt/KGKG/KG_backend
set -a; . ./.env.prod; set +a           # needs DJANGO_SECRET_KEY
KG_RL_DISABLE=1 .venv/bin/python manage.py test api
```

Known flake: one rate-limit test is test-order-sensitive (shared in-process bucket);
`TeamManagementTests.setUp` clears `ratelimit._HITS` for this reason — new test classes that
hit rate-limited endpoints should do the same.

## 4.x Modules and commands added after this reference was written (2026-11-04)

One line each, taken from the module and command docstrings; the code is the authority. The full, generated list of
every module, model, command and env var is `docs/generated/inventory.md`.

### Modules (`KG_backend/api/`)

| Module | Role |
|---|---|
| `cardb_pg.py` | serves a car from its own PostgreSQL schema through a sqlite3-compatible connection; see [23](23-data-layer.md) |
| `assist_lookup.py` | structured lookups beside RAG: part numbers (parts catalog) and "which special tool for job X" answered from tables, not prose |
| `contentguard.py` | per-user hourly caps on page and media reads to stop bulk copying; thresholds `KG_CG_PAGE_WARN/BLOCK`, `KG_CG_MEDIA_WARN/BLOCK`; see [26](26-auth-and-sessions.md) |
| `shield.py` | encrypted document payloads and signed single-use requests (`KG_SHIELD=1` + `KG_SHIELD_SECRET`); see [26](26-auth-and-sessions.md) |
| `vncauth.py` | admin-only cookie ticket gating the TIS browser screen at `/kg-vnc/` (nginx `auth_request`) |
| `nulguard.py` | rejects request text containing NUL with 400, because PostgreSQL text cannot store U+0000 (SQLite did) |
| `safepath.py` | `safe_join` (the only way request-derived names become paths) and `split_year_suffix`; closes CodeQL path-injection/ReDoS classes |
| `frm.py` | flat-rate manual data sets (`Database_warehouse/_frm/<slug>.json`): labour-hour tables per model family |
| `labortimes.py`, `sst.py` | per-vehicle CSV export of Labor Times and Special Service Tools tables |
| `orggraph.py` | compiles a seat's root-assigned permissions into the enforcement primitives; break-glass root reassignment; seeding from the legacy org roles |
| `partsouq_crawler.py`, `partsouq_build.py` | admin start/stop/status of the Partsouq VIN crawl (shares the server Chrome with the TIS crawler on CDP 127.0.0.1:9222) and building a parts DB from a finished crawl |
| `support_metrics.py` | support-desk metrics; each number has a definition in `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md` and a test |
| `support_chat/`, `notifications/` | see [22](22-support-chat.md) |

### Management commands (`manage.py <name>`)

| Command | Role |
|---|---|
| `backfill_last_login` | fill null `PortalUser.last_login_at` from the newest `login` activity row (`--dry-run` counts only) |
| `check_coverage` | audit diagnostic-engine and retrieval coverage per vehicle against a stored baseline and alert on regression; run by `kgkg-coverage.timer` (not test coverage) |
| `check_secret_age` | alert when server secrets are overdue for rotation (`--max-age-days`, default 90); never rotates by itself |
| `copy_sqlite_to_postgres` | one-time portal data copy from the old SQLite file into PostgreSQL (`--verify-only`) |
| `seed_kb_faq` | publish the support desk FAQ articles into the knowledge base (`--dry-run`) |
| `seed_qa_fixtures` | deterministic accounts for E2E/load/DAST; runs only inside the isolated QA stack |
| `sync_org_reports` | backfill `PortalUser.reports_to` from the org-graph canvas |
| `build_reranker_trainset`, `train_kg_reranker`, `train_query_adapter` | offline training of the domain-adapted cross-encoder and the bge-m3 query-side adapter (doc 17); need torch and the model |
