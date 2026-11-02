# 05 — API Reference

All backend endpoints are served by Django on `:8000` and reached publicly under the
`/kg-api/` nginx prefix (e.g. `POST http://103.75.197.155/kg-api/api/auth/login/`).
Routing: `api/urls.py`. All bodies are JSON; all responses are JSON unless noted.

> **Complete list:** `docs/openapi.yaml` (OpenAPI 3.0.3) documents every routed endpoint with
> methods, auth and parameters, and is test-enforced (`api/test_openapi_routes.py` fails when a
> route is added or removed without updating it). The tables below are a curated overview.

**Auth kinds**

| Kind | How |
|---|---|
| *public* | none |
| *portal* | `Authorization: Bearer <AuthToken>` **or** `kg_portal_token` cookie (SSR) |
| *manager* | portal + `can_manage_team` (`@require_manager`) |
| *analytics* | portal + `can_view_analytics` or `can_manage_team` (`@require_analytics`) |
| *admin* | `X-Admin-Token`/Bearer = `KG_ADMIN_TOKEN` env value **or** an `AdminAuthToken` session token (`@require_admin_token`) |

**Rate limits** (fixed window, per IP, per worker process): login 15/60s,
admin_login 20/60s, activity 120/60s, assist 60/60s, diagnose 60/60s, search 90/60s,
click 120/60s, purchase ~5/60s. 429 body: `{error}`.

**Common errors:** 401 `{error:'unauthorized'}`; 403 `{error:'forbidden', detail}` (Persian
detail for content gates); 400 validation `{error:<fa message>}`; 405 `{error:'POST only'}`.

## 5.1 Health & public

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/health/` | GET | public | Liveness: `{ok, uptime_s, db, time}` — for uptime monitors |
| `/` | GET | public | Distinct brand list (array) — sales page |
| `/api/purchase-request/` | POST | public | Lead form. Body: brand, model, year, documents[], company, landline, mobile, reg_no, note?, employees_count?, seat_plan[] ({role, department, count, note} → validated by `parse_seat_plan`), wants_demo?, wants_ai_assistant?. → `{ok, id}` |

## 5.2 Portal auth & session

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/auth/login/` | POST | public | `{username, password}` — username **or email**; timing-equalized. → `{token, user}` (user = full `_user_dict` incl. capabilities, `ai_eligible`, `accesses[]` with per-car `ready` flag) |
| `/api/auth/logout/` | POST | portal | Deletes the presented token |
| `/api/auth/me/` | GET | portal | `{user}` — same shape as login |
| `/api/auth/fleet/` | GET | portal | `{items:[{brand_name, car_name, year}]}` — granted **and on-disk** cars (drives /browse tiles) |
| `/api/activity/` | POST | portal | Beacon: `{action, detail?, category?|segments?, car_id?|brand+model+year?, node_title?, app_url?}` → `{ok}`; resolves category server-side; emits company `activity` event |

## 5.3 Content (all gated per-car — doc 06 §6.4)

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/<brand>/` | GET | public* | Years for brand (catalog level only) |
| `/<brand>/<year>/` | GET | public* | Models for year. Junk year → `[]` (tolerant) |
| `/<brand>/<year>/<model>/` | GET | **portal + car grant** | Root nodes; walk deeper with repeated `?seg=<title>` params (in order). Returns node list or `{nodes, content}` for leaf pages; image URLs pre-rewritten |
| `/api/search/` | GET | portal + car gate | `q, brand, model, car?, limit?` — semantic cross-lingual per-car search; falls back to SQL LIKE if index missing |
| `/api/assist/` | GET/POST | portal + car gate | `{query, brand?, model?, car?}` → grounded excerpts with real in-app URLs + graph-related + cross-vehicle context (allow-list scoped) |
| `/api/diagnose/` | GET/POST | portal + car gate | `{query, brand?, model?, car?}` → deterministic DTC/symptom result: candidates, steps, repair + labor, cross-vehicle matches |

\* brand/year levels stay public for the sales flow; car content requires a grant.
`db_address` is never exposed in any response.

## 5.4 Assistant feedback / eval

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/assist/feedback/` | POST | portal | Click log `{query, blob_id, app_url}` (relevance signal), always `{ok}` |
| `/api/feedback/rate/` | POST | portal | 👍/👎 verdict on an answer (+reason/comment) |
| `/api/feedback/pin/` | POST | admin | Expert pin: query-pattern → known-good target |
| `/api/feedback/recent/` | GET | admin | Review feed (drives `/admin-review`) |
| `/api/eval/report/` | GET | admin (enforced since 2026-10-28; was reachable without credentials) | Latest offline eval run (read-only) |

## 5.5 Team management (manager)

The old `/api/team/members|org|roles` endpoints were removed on 2026-09-07 (commit `5aefebf`)
and replaced by the org-graph API `/api/org/*` (see `docs/openapi.yaml`).

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/invite/<token>/` | GET | public | Validate invite → `{user, company}` or 4xx |
| `/api/invite/<token>/` | POST | public | `{password}` → accept + auto-login `{token, user}` |

## 5.6 Analytics & recommendations

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/team/analytics/` | GET | analytics | `?range=N&member=<id>&category=<cid>` → totals, per-category bars, per-member drill-down, daily trend |
| `/api/team/report/` | GET | analytics | `?range=N` → **PDF** (WeasyPrint fa/RTL, attachment) |
| `/api/team/insights/` | GET | manager | Seat utilization, idle/top members, category coverage & gaps |
| `/api/recommendations/` | GET | portal | `?limit=N` → personalized: continue / related / focus_areas / popular_in_company / explore |

## 5.7 Support desk (any seat ↔ admin)

Was "company requests (manager ↔ admin)". Since 2026-10-30 **any signed-in seat**
may file a `support` or `other` request; the commercial kinds (`vehicle_access`,
`seats`, `ai_assistant`, `documents`) remain manager-only because they commit the
company to cost or scope. A seat sees the tickets it filed; a manager sees the
company's. Code: `api/requests_api.py`, `api/sla.py`. Rationale and root-cause
analysis: `audit-evidence/16-improvement-programme/`.

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/company/requests/` | GET/POST | portal | List (own, or the company's for a manager); create `{kind, subject, body?, payload?, priority?}` (payload whitelisted per kind). `source` is always `portal` — never taken from the client |
| `/api/company/requests/<id>/` | GET/POST | portal | Detail with the message thread (internal notes excluded). POST one of `{message}` (a reply; reopens a closed ticket and restarts the resolution clock), `{csat:{score 1..5, comment?}}` (once, after closure, by the filer), `{cancel:true}` |
| `/api/admin/company-requests/` | GET/POST | admin | Inbox (filter by `status`, `source`, `company_id`); POST `{company_id, subject, body?, kind?, priority?, source?}` logs a request that arrived by telephone, e-mail or in person |
| `/api/admin/company-requests/<id>/` | GET/POST | admin | GET the ticket with internal notes. POST `{status?, admin_note?, handled_by?, message?, internal?, assignee_id?, escalate?}`. The first thing the customer can read — a public message **or** a non-empty `admin_note` — stamps `first_response_at`; an internal note and a bare status change do not, and it is never overwritten. `escalate` is idempotent and raises priority to high |
| `/api/admin/company-requests/<id>/promote-to-article/` | POST | admin | `{slug, title?, category?, audience?}` — turns a closed ticket into a **draft** knowledge article seeded with the question, the public thread and the resolution |
| `/api/admin/support/metrics/` | GET | admin | `?days=30` — volumes, first-response and resolution times (mean and p90), SLA compliance, CSAT, `by_source`, `by_kind`, backlog ageing, feedback and knowledge blocks. Every field is defined in `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md` |

**SLA targets** (`api/sla.py`, calendar hours, not business hours): high 2 h first
response / 8 h resolution · normal 8 h / 48 h · low 24 h / 120 h. State per ticket is
`met` / `breached` / `pending`; `pending` is excluded from compliance.

## 5.7a Product feedback

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/feedback/submit/` | POST | portal | `{page?, rating? 1..5, comment?}` — either a rating or a comment is required. Rate-limited `feedback` 30/60s. Emits to the admin audience |
| `/api/admin/feedback/` | GET | admin | `?days=30` — feed plus totals and a per-page breakdown |

## 5.7b Knowledge base

Articles have a **named owner**, a review interval (`is_stale` = never reviewed or
past the interval), append-only revisions, and optional provenance from the ticket
they were promoted out of. Code: `api/knowledge.py`.

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/kb/` | GET | portal | `?q=&category=` — published, customer-facing articles. A `q=` search is logged with its result count (`KbSearchLog`); browsing the index is not |
| `/api/kb/<slug>/` | GET | portal | Article; counts a view |
| `/api/kb/<slug>/vote/` | POST | portal | `{helpful: bool}` |
| `/api/admin/kb/` | GET/POST | admin | GET everything (`?status=`, `?audience=`, `?stale=1`); POST `{title, slug, body, category?, audience?, status?, review_interval_days?}`. `slug` must match `^[a-zA-Z0-9][-a-zA-Z0-9_]*$` — what the reader's `<slug:slug>` route can match — so a published article is always reachable by its own URL |
| `/api/admin/kb/<id>/` | GET/POST | admin | GET with revision history. POST `{title?, body?, category?, status?, audience?, owner_id?, review_interval_days?, reviewed?, note?}` — a **text** change appends a revision and bumps the version; a review, a status change or a reassignment does not |

## 5.8 Real-time

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/events/stream/` | GET | portal or admin | **SSE.** Query `?admin=1` for the admin audience. `Last-Event-ID` header/`?after=` resume. Frames: `id`, `event:<type>`, `data:{id,type,ts,payload}`; 15s heartbeat comments; stream recycles after 300s (client auto-reconnects). nginx has a dedicated unbuffered location for this path |
| `/api/events/recent/` | GET | portal or admin | REST catch-up: `?after=<id>&limit=` |

Company-audience visibility requires `can_manage_team` or `can_view_analytics`; a plain user
receives only their own `user`-audience events.

## 5.9 Platform-admin API

All *admin* auth. The admin panel (`/admin`) is the only consumer.

| Endpoint | Method | Notes |
|---|---|---|
| `/api/admin/login/` | POST | `{username, password}` → `{token, admin}` (PlatformAdmin) |
| `/api/admin/overview/` | GET | Platform KPI summary |
| `/api/admin/dashboard/` | GET | Live-dashboard aggregate (KPIs, processing, requests, alerts, activity, traffic) |
| `/api/admin/processing-snapshot/` | GET | Pending-work snapshot (same source as pipeline panel) |
| `/api/admin/packages/` | GET | Package id/label list |
| `/api/admin/cars/` | GET | Catalog + per-car DB readiness + health indicators (`health`: status, completeness %, missing/empty sections, RAG/diag/asset indexing, pending processes — from the last DataQualityRun) + `has_spec`/`spec_fields`; `audited_at` on the envelope. Drives the admin catalogue filter (doc 07 §7.7) |
| `/api/admin/requests/` | GET | Purchase requests; `/<id>/status/` POST updates workflow status |
| `/api/admin/companies/` | GET/POST | List/create (create seeds default org roles) |
| `/api/admin/companies/<id>/` | GET/POST | Detail (deep: accesses+users) / update (field-length clamped) |
| `/api/admin/companies/<id>/access/` | PUT | Replace purchased scope; prunes now-out-of-scope user grants (admin_granted rows survive) |
| `/api/admin/users/` | GET/POST | Cross-company user admin; create issues credentials |
| `/api/admin/users/<id>/` | GET/POST | Update incl. role/company moves; runs org-consistency repair |
| `/api/admin/users/<id>/access/` | PUT | Replace grants via `apply_user_access(allow_admin_grants=True)` — may exceed purchase (admin_granted) |
| `/api/admin/activity/` | GET | Filterable activity report (company/user/action/category/date) |
| `/api/admin/analytics/` | GET | Cross-company usage analytics |
| `/api/admin/data-quality/` | GET/POST | GET latest audit report; POST `{refresh:true}` or `{fix:true}` → async run |
| `/api/admin/pipeline/` | GET/POST | GET full status (job, pending work, load, recommendation, settings, history); POST `{action:'start'|'schedule'|'resume'|'cancel'|'settings', …}` |
| `/api/admin/system/` | GET | `system_snapshot`: disk/mem/load/uptime, DB+RAG status, alerts |
| `/api/admin/traffic/` | GET | Traffic series, per-endpoint latency/error table, feature usage, daily uniques |

## 5.10 Frontend-internal API (Next.js server)

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/chat` | POST | portal token (validated against backend `/api/auth/me/` + `ai_eligible`) | The assistant conversation route. Grounds via backend diagnose→assist, then Metis-phrases with a strict context-only prompt + link-faithfulness gate; deterministic no-LLM fallback. Per-IP rate limited (uses `x-real-ip`/last XFF hop). Metis credentials never reach the browser |

## 5.11 Conventions for new endpoints

- Parse bodies with the hardened helpers (`portal._body` / `views._post_body` /
  `adminops._json_body`) — they coerce non-dict JSON to `{}` (a `"string"` body must not 500).
- Return Persian, user-displayable `error` strings for expected failures; keep machine
  fields (`ok`, ids) stable.
- Rate-limit anything unauthenticated or expensive (`@rate_limited`).
- Emit events for state changes other dashboards should see (doc 09 §emitters).
- Add the endpoint to this table and to `docs/CHANGELOG.md` in the same commit.
