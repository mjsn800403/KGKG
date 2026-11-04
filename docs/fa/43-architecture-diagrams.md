<!-- i18n-source: 43-architecture-diagrams.md sha256:8fe49e396f2c -->
<div dir="rtl" lang="fa">

# ۴۳ — نمودارهای معماری و جریان داده

یک مرجع واحد برای نمودارها که از پیاده‌سازی استخراج شده‌اند. نسخهٔ انگلیسی: [../43-architecture-diagrams.md](../43-architecture-diagrams.md). هر نمودار سند و کدی را که از آن آمده نام می‌برد؛ وضعیت تولید مطابق مشاهدهٔ ۲۰۲۶-۱۱-۰۴ است ([۳۸](38-implementation-status-matrix.md)). نمودار کامل موجودیت-رابطهٔ ۴۹ مدل تولیدشده است و نمی‌تواند از کد جدا شود: [generated/schema.md](../generated/schema.md). نمودارهایی که جای دیگری هستند کپی نشده‌اند: بافتار سیستم و کانتینرها [۳۳](33-system-design.md)، درخواست صفحهٔ دفترچه [۳۳](33-system-design.md)، حالت‌های رشتهٔ پشتیبانی [۳۵](35-support-system.md)، خط انتشار [۳۶](36-cicd-and-deployment.md). برچسب‌های داخل نمودارها عمداً انگلیسی‌اند (نام ماژول‌ها و جدول‌ها).

## ۴۳٫۱ بافتار سیستم (چه کسی با چه کسی)

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
منبع: [۳۳](33-system-design.md)، [۳۸ بخش‌های ۳۸٫۳ و ۳۸٫۵](38-implementation-status-matrix.md) (تولید بردارها و FTS را از `kgkg_vec` می‌خواند).

## ۴۳٫۲ نقشهٔ مؤلفه‌های بک‌اند

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
منبع: فهرست ماژول‌های `KG_backend/api/`، [۰۴](04-backend-reference.md)، [۳۳](33-system-design.md).

## ۴۳٫۳ ورود به پورتال با عامل دوم پیامکی

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
منبع: [۲۶ بخش ۲۶٫۲](26-auth-and-sessions.md)، `utils/api.jsx`، `app/login/page.tsx`.

## ۴۳٫۴ چرخهٔ درخواست دستیار

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
منبع: [۳۰ بخش‌های ۳۰٫۳ و ۳۰٫۷ تا ۳۰٫۸](30-ai-assistant-deep-dive.md)، `app/api/chat/route.js`.

## ۴۳٫۵ خط بازیابی (درون `/api/assist`)

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
منبع: [۳۰ بخش ۳۰٫۵](30-ai-assistant-deep-dive.md). ذخیرهٔ تولید: pgvector و جست‌وجوی متنی PostgreSQL؛ بازرتبه‌بند خاموش ([۳۸](38-implementation-status-matrix.md)).

## ۴۳٫۶ جریان دریافت و پردازش محتوا

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
منبع: [۱۱ بخش ۱۱٫۶](11-operations-deployment.md)، [۲۳ بخش ۲۳٫۲](23-data-layer.md)، [۳۰ بخش ۳۰٫۴](30-ai-assistant-deep-dive.md)، `api/pipeline.py`، `management/commands/run_pipeline.py`. مراحل افزایشی و ازسرگیری‌پذیرند؛ شکست یک مرحله مراحل امنِ بعدی را متوقف نمی‌کند.

## ۴۳٫۷ تعیین دسترسی (چه کسی کدام خودرو را باز می‌کند)

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
منبع: [۰۶ بخش‌های ۶٫۲ تا ۶٫۳](06-permissions-rbac.md)، `access.user_car_documents`؛ دسترسی جایگاه‌ها در org-graph این ردیف‌ها را تغذیه می‌کند ([۰۶ بخش ۶٫۶](06-permissions-rbac.md)).

## ۴۳٫۸ مسیر پیام چت پشتیبانی (قابلیت مستقر، در تولید غیرفعال)

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
منبع: [۲۲](22-support-chat.md)، [۳۵](35-support-system.md)، `src/support-chat/*`. حالت‌های رشته: [۳۵](35-support-system.md).

## ۴۳٫۹ جریان پایش و هشدار

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
منبع: [۲۵](25-ops-inventory.md)، [۳۱](31-ops-files-reference.md)، `api/monitoring.py`، `api/alert_rules.py`. محتوای داشبوردها بازرسی نشد ([۳۸](38-implementation-status-matrix.md)).

## ۴۳٫۱۰ مدل داده دامنه (زیرمجموعهٔ اصلی؛ نمودار کامل در schema تولیدشده)

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
منبع: [۳۴](34-data-model-reference.md)، [generated/schema.md](../generated/schema.md) (مرجع قطعی هر کلید خارجی).

## ۴۳٫۱۱ جریان انتشار و استقرار

نمودار خط لوله را در [۳۶](36-cicd-and-deployment.md) ببینید (PR ← CI ← stage با کلید CI ← smoke ← **انسان با `kgkg-promote` ارتقا می‌دهد** ← جایگزینی بدون وقفه با بازگشت خودکار) و نمودار کانتینر/میزبان را در [۳۳](33-system-design.md). ارتقا هرگز خودکار نیست.

</div>
