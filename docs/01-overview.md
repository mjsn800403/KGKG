# 01 — System Overview

## What KGtechvault is

KGtechvault sells **access to official automotive service documentation** (Toyota / Lexus,
currently 38 vehicles) to Iranian legal entities (dealership networks, after-sales service
companies). Buyers get a Persian, RTL web portal where their technicians browse the original
English manual content, plus an **AI assistant** that answers repair questions and diagnostic
trouble codes (DTCs) in Persian, grounded *exclusively* in the purchased manuals.

The business model is per-company subscriptions: a company purchases specific vehicles and
specific **document layers** (packages) for them, receives seats for its staff, and manages
its own team self-service. A single **platform admin** (the vendor) provisions companies,
grants access, processes purchase/feature requests, and operates the data platform.

## Why it is built the way it is

- **Content is immutable and sharded per vehicle.** Manuals arrive as crawled HTML, parsed
  once into one self-contained SQLite DB per vehicle. Serving code opens them read-only.
  Adding vehicle #4,000 is a file copy + catalog sync — no migrations, no downtime.
- **Everything else lives in one relational DB** (`db.sqlite3`): companies, users, grants,
  analytics rollups, events, jobs. Engine-agnostic Django ORM — a future PostgreSQL move is a
  settings change.
- **AI must never hallucinate beyond the paid content.** Retrieval, ranking, and the
  diagnostic rule engine are local and deterministic; the external LLM (Metis) is used only
  as a Persian *phraser* over already-retrieved context, with a no-LLM fallback. Access
  control is enforced *inside* retrieval (per-user car allow-list), not just at the UI.
- **Dependency-light by policy.** No DRF, Redis, Celery, or external queue until a measured
  need exists. The hand-rolled pieces (rate limiter, metrics aggregator, SSE-over-SQLite,
  pipeline supervisor) each document their scale envelope.

## The four actors

| Actor | Where they work | What they can do |
|---|---|---|
| **Visitor** (public) | Landing `/`, `/login`, `/purchase` | Read marketing content, check VIN coverage, submit a purchase request (lead form) |
| **Portal user** (company seat) | `/browse`, content pages, `/assistant`, `/settings` | Browse manuals for granted cars/layers, semantic search, AI assistant (if eligible), log activity |
| **Company manager** (portal user with capabilities) | + `/team`, `/team/analytics`, `/requests` | Create/invite/deactivate employees, define org roles & hierarchy, delegate car grants, view team analytics + PDF reports, file requests to the platform admin |
| **Platform admin** (vendor) | `/admin` (separate login) | Everything: companies, users, grants, purchase & company requests, platform analytics, data quality, processing pipeline, system monitoring |

"Manager" is not a fixed role: any portal user whose `can_manage_team` /
`can_view_analytics` capability flags are on sees those areas. Capabilities are seeded from
the user's org-role but individually editable (see doc 06).

## Core user flows

### Buying (visitor → company)
1. Visitor fills `/purchase` (vehicle, document layers, company identity, seat plan per role,
   optional demo/AI add-ons) → `PurchaseRequest` row.
2. Platform admin reviews it in Admin → «درخواست‌های خرید», creates the `Company`, purchases
   (`CompanyCarAccess`), and the first user(s).
3. Employees receive credentials or an invite link and log in at `/login`.

### Browsing content (portal user)
1. Login → `/browse` shows the user's granted, on-disk vehicles (fleet tiles + model filter)
   plus a personalized recommendations widget.
2. Clicking a vehicle opens the manual tree at `/{brand}/{year}/{model}`; deeper nodes use
   repeated `?seg=` query params (a node title may contain `/`). Content pages are
   server-rendered; images come from `/kg-api/media/…` (nginx serves them from disk).
3. Every meaningful action (view, search, assistant open) is beaconed to `/api/activity/`
   with a resolved technical **category** (engine/brakes/…) — the fuel for analytics and
   recommendations.

### Asking the assistant (portal user, AI-eligible)
1. `/assistant` (general) or per-car assistant page. The Next.js `/api/chat` route validates
   the session and AI eligibility, then grounds the question:
   **diagnose first** (deterministic DTC/symptom engine), **assist** (RAG) as fallback.
2. Metis phrases the grounded context into Persian; a faithfulness gate keeps buttons/links
   exactly as retrieved; if Metis fails, a deterministic Persian fallback renders the same
   content. Every answer's links resolve to real in-app pages the user may open.

### Managing a team (manager)
1. `/team` — three tabs: **اعضا** (member cards + add/edit drawer), **چارت سازمانی**
   (interactive org chart, click-to-move reporting lines), **نقش‌ها** (role editor: create,
   rename, drag-to-re-rank, scope, capability defaults, access templates).
2. New employee: invite by email link (7-day single-use token) **or** direct
   username/password provisioning. Car/document grants are delegated "give only what you
   have" — clamped to the manager's own effective scope.
3. `/team/analytics` — usage by member/category/trend + downloadable Persian PDF report.
4. `/requests` — file requests to the vendor (more vehicles, seats, AI enablement…) and watch
   their status change live (SSE).

### Operating the platform (admin)
`/admin` (dedicated login) lands on a **hub** of section cards; each section is a tool:
live dashboard, catalog, purchase requests, company requests inbox, companies & access,
users, platform analytics, activity log, data quality, processing pipeline, system
monitoring. All admin capabilities are documented in doc 05 (endpoints) and the in-app admin
guide (doc 13).

## Vocabulary / glossary

| Term | Meaning |
|---|---|
| **Car / vehicle** | One catalog row = one warehouse DB file = one trim-level manual (e.g. "4Runner TRD Pro"). `car_stem` = the DB filename stem = `Car.car_name`. |
| **Document layer / package** | Sellable slice of a manual: `manual` (repair), `parts`, `standard_time`, `special_tools`, `full_spec`. |
| **Grant** | `CompanyCarAccess` (company bought car X with layers Y) or `UserCarAccess` (user may open car X with layers ⊆ company's). `admin_granted` rows bypass purchase clamps. |
| **Capability** | Per-user boolean: `can_manage_team`, `can_view_analytics`, `ai_assistant_enabled`. |
| **OrgRole** | Company-defined position with a numeric `rank` (1 = top) and a `manage_scope` (org / subtree / none). |
| **Blob / occurrence** | RAG index storage: identical page content across the fleet is stored once (blob); each (car, path) it appears at is an occurrence. |
| **Diag sidecar** | Per-car derived DB of DTC subtrees + symptom tables powering the deterministic diagnostic engine. |
| **Pipeline** | The admin-triggered/automatic chain: catalog sync → RAG ingest/embed/graph → diag build → audit refresh, run by a detached worker. |
| **Event** | Append-only `Event` row tailed by the SSE endpoint — the real-time backbone. |
| **Category** | Canonical technical area (engine, brakes, electrical, …) resolved from manual section titles; the analytics dimension. |

## Current production state (2026-07-15)

- 1 active company (شرکت خدمات گستر سپهر گیتی), 5 portal users (manager `gostar_te_01`,
  head `yar_mohammadi`, supervisor `Behnam_hosienpour`, specialists incl. custom role
  «کارشناس فنی»), 1 platform admin.
- 38 vehicles, all passing data-quality audit; RAG index covers the whole fleet
  (126k vectors); diag sidecars for all cars.
- Known content gap: **Land Cruiser Base has no static images** (assets never downloaded;
  needs a lemon-downloader re-crawl). 5 malformed partial crawls + 1 duplicate live in
  `Database_warehouse/_quarantine/`.
