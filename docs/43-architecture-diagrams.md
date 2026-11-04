# 43 — Architecture and data-flow diagrams

One place for the diagrams, drawn from the implementation. Persian version: [fa/43-architecture-diagrams.md](fa/43-architecture-diagrams.md). Every diagram names the document and code it comes from; production state is as observed on 2026-11-04 ([38](38-implementation-status-matrix.md)). The full entity-relationship diagram of all 49 models is generated, so it cannot drift: [generated/schema.md](generated/schema.md). Diagrams that already live elsewhere are linked, not copied: system context and containers [33 §33.1–33.2](33-system-design.md), manual page request [33](33-system-design.md), support thread states [35](35-support-system.md), release pipeline [36](36-cicd-and-deployment.md).

## 43.1 System context (who talks to whom)

```mermaid
flowchart LR
  U[Customer user] -->|HTTPS| CF[Cloudflare]
  A[Platform admin] -->|HTTPS| CF
  CF --> NG[nginx on the host]
  NG --> FE[Next.js frontend]
  NG --> BE[Django backend]
  FE -->|SSR and chat route| BE
  FE -->|phrasing only| LLM[Metis LLM API]
  BE --> PG[(PostgreSQL kgkg - portal data)]
  BE --> PGV[(PostgreSQL kgkg_vec - manuals, RAG vectors, FTS)]
  BE --> SQ[(SQLite - parts catalogs, feedback, terms)]
  BE --> SMS[SMS provider]
  BE --> GT[GlitchTip]
  BE -.-> HJ[host-jobs daemon]
  PROM[Prometheus, Loki, Grafana] -.-> BE
```
Source: [33](33-system-design.md), [38 §38.3, 38.5](38-implementation-status-matrix.md) (production reads RAG vectors and FTS from `kgkg_vec`).

## 43.2 Backend component map

```mermaid
flowchart TB
  subgraph Edge
    MW[middleware: origin guard, shield, content guard, audit]
    AUTH[token auth: portal_auth, admin_auth]
  end
  subgraph Portal
    PORTAL[portal.py - login, OTP, fleet, me]
    TEAM[team.py, orggraph.py, orggraph_api.py]
    REQ[requests_api.py, sla.py - tickets]
    KB[knowledge.py, onboarding.py, recommend.py]
  end
  subgraph Content
    CARDB[cardb.py, cardb_pg.py - manual trees]
    PARTS[parts.py, frm.py, sst.py, labortimes.py]
    MEDIA[mediaauth.py - media auth_request]
  end
  subgraph AI
    RAG[rag/: retrieve, store, pgvec, pgfts, diag, feedback]
    ASSIST[assist_lookup.py, chatlog.py]
  end
  subgraph Support
    SC[support_chat/ - threads, staff API, RBAC]
    NOTIF[notifications/ - outbox, worker]
    NOTIFY[notify.py - login device SMS]
  end
  subgraph Ops
    ADMIN[admin.py, adminops.py, insights.py, audit.py]
    EV[events.py - SSE]
    MON[monitoring.py, alert_rules.py, metrics_exposition.py]
    PIPE[pipeline.py, hostjobs.py, dataquality.py]
  end
  MW --> AUTH --> Portal
  AUTH --> Content
  AUTH --> AI
  AUTH --> Support
  AUTH --> Ops
  Portal --> DB[(kgkg)]
  Content --> CV[(kgkg_vec, SQLite)]
  AI --> CV
  Support --> DB
  Ops --> DB
```
Source: module list `KG_backend/api/`, [04](04-backend-reference.md), [33](33-system-design.md).

## 43.3 Portal login with SMS second factor

```mermaid
sequenceDiagram
  participant B as Browser
  participant F as Next.js
  participant D as Django portal.py
  participant T as Cloudflare Turnstile
  participant S as SMS provider
  B->>F: open /login
  B->>D: POST /api/auth/login/ username, password, turnstile token
  D->>T: verify token
  T-->>D: ok
  alt phone on file and OTP enabled
    D->>S: send 6-digit code (stored as SHA-256, TTL 2 min, 5 attempts)
    D-->>B: otp_session
    B->>D: POST verify-otp with code
  end
  D->>D: issue session, delete the user's other tokens
  D->>D: log activity, emit live event, check login device
  D-->>B: Set-Cookie kg_portal_token + token body
  B->>B: store token, redirect to next
```
Source: [26 §26.2](26-auth-and-sessions.md), `utils/api.jsx`, `app/login/page.tsx`.

## 43.4 Assistant request lifecycle

```mermaid
sequenceDiagram
  participant B as Browser
  participant R as Next route /api/chat
  participant D as Django
  participant L as Metis
  B->>R: POST message, history, car context
  R->>D: GET /api/auth/me (reject if no session)
  R->>D: GET /api/auth/ai-usage (quota, fail closed)
  R->>R: sanitise history, contextualise follow-up
  alt car pinned and not a lookup
    R->>D: POST /api/diagnose (deterministic engine)
  end
  opt no usable diagnosis
    R->>D: POST /api/assist (hybrid retrieval, allowed_cars gate)
  end
  R->>R: drop hits outside selected car, build grounded prompt
  R->>L: session call, bot chain with fallbacks, streamed
  L-->>R: text (or failure)
  alt LLM failure
    R->>R: extractive fallback reply from sources
  end
  R->>R: keep only links present in retrieved set
  R->>D: POST chat-log (best effort)
  R-->>B: SSE deltas and final payload with sources, mode, grounded
```
Source: [30 §30.3, 30.7–30.8](30-ai-assistant-deep-dive.md), `app/api/chat/route.js`.

## 43.5 Retrieval pipeline (inside `/api/assist`)

```mermaid
flowchart LR
  Q[Query] --> G[Glossary expansion FA to EN]
  G --> C[Classify: code or natural language]
  C --> SG{Car has indexed content?}
  SG -->|no| NS[No-scope result]
  SG -->|yes| V[Dense kNN]
  SG --> K[BM25 keyword]
  SG --> CV[Car-scoped dense pass]
  V --> F[Weighted RRF fusion]
  K --> F
  CV --> F
  F --> AZ[Authorisation: keep blobs with an allowed occurrence]
  AZ --> SC[Occurrence choice, boosts, penalties, calibration]
  SC --> RR{Rerank on?}
  RR -->|off in production| OUT[Hits and evidence]
  RR -->|on| RK[Cross-encoder] --> OUT
  OUT --> GR{Grounding gate}
  GR --> ANS[Grounded, clarify or refuse]
```
Source: [30 §30.5](30-ai-assistant-deep-dive.md). Production storage: pgvector and PostgreSQL full-text search; reranker off ([38](38-implementation-status-matrix.md)).

## 43.6 Content ingestion and processing flow

```mermaid
flowchart LR
  SRC[Source ZIPs of manuals] --> SCAN[scan_zips, parse_worker]
  SCAN --> CAT[sync_car_catalog - Car rows]
  SCAN --> CARDB[(per-vehicle store)]
  CARDB -->|manual cars| PGCAR[pgcar adopt into kgkg_vec schema, delete SQLite file]
  CARDB -->|parts-only cars| PARTSDB[(SQLite in _parts)]
  PGCAR --> RAGB[build_rag: ingest blobs, embed bge-m3, graph]
  RAGB --> IDX[(RAG index: pgvector, PG FTS; SQLite file kept)]
  PGCAR --> DIAG[build_diag: per-car diagnostic sidecars]
  RAGB --> AUD[dataquality audit refresh]
  CAT --> AUD
```
Source: [11 §11.6](11-operations-deployment.md), [23 §23.2](23-data-layer.md), [30 §30.4](30-ai-assistant-deep-dive.md), `api/pipeline.py`, `management/commands/run_pipeline.py`. Stages are incremental and resumable; a stage failure does not stop later safe stages.

## 43.7 Access resolution (who can open which vehicle)

```mermaid
flowchart TB
  REQ[Request for a vehicle] --> TOK{Valid session token?}
  TOK -->|no| R401[401 to login]
  TOK -->|yes| UR{UserCarAccess row for this car?}
  UR -->|no row| F403[403 forbidden - a company purchase alone grants nothing]
  UR -->|yes| ADM{admin_granted?}
  ADM -->|yes| D1[Documents = own list of the row, empty = all layers]
  ADM -->|no| CS{Inside the company ceiling CompanyCarAccess?}
  CS -->|no| F403
  CS -->|yes| D2[Documents = user list intersect company scope, empty user list inherits company scope]
  D1 --> LAY
  D2 --> LAY{Requested layer in documents? manual, parts, standard_time, special_tools, full_spec}
  LAY -->|no| F403
  LAY -->|yes| OK[Serve content, media via auth_request]
```
Source: [06 §6.2–6.3](06-permissions-rbac.md), `access.user_car_documents`; seat permissions from the org graph feed these rows ([06 §6.6](06-permissions-rbac.md)). The assistant applies the same grants as `allowed_cars` inside retrieval.

## 43.8 Support chat message path (feature deployed, disabled in production)

```mermaid
sequenceDiagram
  participant V as Visitor widget
  participant API as Django support_chat
  participant S as Staff inbox
  participant O as Notification outbox
  V->>V: generate token (32 random bytes)
  V->>API: first message with Turnstile token (creates thread, stores SHA-256 of token)
  API-->>V: thread id
  loop poll with back-off
    V->>API: messages since cursor
  end
  S->>API: staff list and reply (admin token, RBAC off/audit/enforce)
  API-->>S: events via SSE
  API->>O: optional SMS or e-mail notification
  Note over V,O: In production: disabled, 0 threads, outbox timer not installed
```
Source: [22](22-support-chat.md), [35](35-support-system.md), `src/support-chat/*`. Thread states: [35](35-support-system.md).

## 43.9 Observability and alerting flow

```mermaid
flowchart LR
  APP[Django and Next.js] -->|metrics :8081| PROM[Prometheus]
  HOST[node exporter, cAdvisor, probes] --> PROM
  APP -->|logs| LOKI[Loki via Alloy]
  APP -->|errors| GT[GlitchTip]
  APP -->|page views| UM[Umami]
  PROM --> GRAF[Grafana: 4 provisioned dashboards]
  LOKI --> GRAF
  TIMER[systemd timers: alerts, watchdog, pipeline, qa-nightly] --> RULES[alert_rules.py sweep]
  RULES --> SA[(SystemAlert rows)]
  SA --> SSE[Admin dashboard via SSE]
```
Source: [25](25-ops-inventory.md), [31](31-ops-files-reference.md), `api/monitoring.py`, `api/alert_rules.py`. Dashboard contents were not inspected ([38](38-implementation-status-matrix.md)).

## 43.10 Domain data model (core subset; full diagram in the generated schema)

```mermaid
erDiagram
  Company ||--o{ PortalUser : employs
  Company ||--o{ CompanyCarAccess : bought
  Car ||--o{ CompanyCarAccess : "sold as"
  PortalUser ||--o{ UserCarAccess : granted
  Car ||--o{ UserCarAccess : "opened by"
  PortalUser ||--o{ AuthToken : sessions
  PortalUser ||--o{ ActivityLog : generates
  PortalUser ||--o{ ChatLog : asks
  Company ||--|| OrgGraph : has
  OrgGraph ||--o{ OrgNode : seats
  OrgNode ||--o| PortalUser : occupant
  OrgNode ||--|| NodePermission : permissions
  Company ||--o{ CompanyRequest : files
  CompanyRequest ||--o{ TicketMessage : thread
  SupportThread ||--o{ SupportMessage : messages
  SupportThread }o--o| CompanyRequest : promoted_to
  Car ||--|| VehicleSpec : describes
```
Source: [34](34-data-model-reference.md), [generated/schema.md](generated/schema.md) (authoritative for every foreign key).

## 43.11 Release and deployment flow

See the pipeline flowchart in [36](36-cicd-and-deployment.md) (PR → CI → stage by CI key → smoke → **person promotes with `kgkg-promote`** → zero-gap swap with automatic rollback) and the container/host diagram in [33](33-system-design.md). Promotion is never automated.
