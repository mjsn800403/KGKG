# 42 — Frontend architecture reference

Extends [07 — Frontend](07-frontend.md) (route map, admin hub, filter, desk) with the layer-by-layer design, state management, API integration, security layers, a catalogue of every component group and the implemented user workflows. Persian version: [fa/42-frontend-architecture.md](fa/42-frontend-architecture.md). All statements are **[C]** (read in `kg_frontend/src/`) unless tagged. Commercial plans/pricing screens are deliberately out of scope here.

## 42.1 Stack and rendering model

| Aspect | Fact |
|---|---|
| Framework | Next.js 16.4 (App Router) with React 19.2; TypeScript for newer pages (`*.tsx`), JavaScript (`*.jsx`) for the rest. `kg_frontend/package.json` |
| Libraries | `@xyflow/react` (org canvas), `motion` (animation), `@sentry/node` (server error reporting); Tailwind 4 and its PostCSS plugin are installed, but no stylesheet imports Tailwind and no Tailwind utility classes were found; styling is hand-written CSS (`globals.css`, `system.css`, `landing.css`, `plans.css`) |
| No global state library | No Redux/Zustand/Context store for data. State is component-local (`useState`/`useReducer`), plus browser storage and a few DOM events (§42.4) |
| Language / direction | `<html lang="fa" dir="rtl">`; all UI copy is Persian; Jalali dates via `JalaliDateTimeInput`; digits normalised by `utils/phone.js` |
| Rendering | Every page is dynamic (the root layout reads the per-request CSP nonce from `headers()`). Manual content pages are **server components** that fetch from Django during SSR; interactive surfaces are client components (`'use client'`) |
| Fonts / assets | Self-hosted fonts; icons are an inline-SVG set (`components/Icon.jsx`), no CDN |
| Analytics | Self-hosted Umami, manual page views from `components/Analytics.jsx` with URL redaction (`utils/analytics.js`); auto-track is off |
| Production process | `next start` in container `kgkg-frontend:<sha>` on loopback `:3000`; nginx in front ([33](33-system-design.md)) |

## 42.2 Request path and authentication

```
Browser ──► nginx ──► Next.js (proxy.ts) ──► page (server component) ──► Django /api/... (SSR, token from cookie)
   │                                         └► client component ──► /kg-api/... (nginx → Django), Bearer or cookie
   └─ POST /api/chat ──► Next route handler ──► Django (/api/auth/me, /ai-usage, /diagnose, /assist) and Metis
```

- **Two API bases** (`utils/api.jsx`): in the browser `NEXT_PUBLIC_API_BASE` (default `/kg-api`, same origin through nginx); during SSR `API_BASE_INTERNAL` (default `http://127.0.0.1:8000`). Media URLs always use the public base.
- **`src/proxy.ts`** runs on every non-asset request: (1) redirects a visitor without the `kg_portal_token` cookie to `/login?next=…` for `/browse`, `/assistant`, `/team`, `/settings`, `/requests`, `/admin-review` and brand routes (`/Toyota/2023/…`); (2) generates a per-request CSP **nonce** and sets the Content-Security-Policy (script-src `'self'` + nonce + Cloudflare Turnstile/Insights; frames only `'self'` and Turnstile; `frame-ancestors 'none'`; `object-src 'none'`). `/admin` is not in the list: its token lives in `sessionStorage`/`localStorage` and is checked client-side.
- **Portal token** — HttpOnly cookie set by the backend plus a copy in `localStorage` (`kg_portal_token`, cached `kg_portal_user`) mirrored to a same-site cookie by `setPortalSession` so server components can forward it (`utils/serverAuth.js`). **Admin token** — separate (`kg_admin_token`), sent as Bearer; `shareAdminToken`/`obtainAdminToken` share it across tabs.
- **401** on content → redirect to `/login`; **403 with body `{"error":"forbidden"}`** → "not in your subscription"; a 403 without that body is treated as a WAF block (`contentError`).

## 42.3 Security layers in the browser

| Layer | Files | Purpose |
|---|---|---|
| CSP + nonce | `proxy.ts`, `app/layout.tsx` | blocks injected scripts; theme boot script carries the nonce |
| HTML sanitiser | `lib/sanitizeHtml.js` | allow-list sanitising of warehouse HTML before `dangerouslySetInnerHTML` (`ContentRenderer`, `StackedContent`) |
| Safe URLs | `lib/safeUrl.js` | assistant-cited links may only point inside the app |
| Content shield | `lib/shield.js`, `utils/shieldServer.js`, `lib/useUnsealed.jsx`, `lib/shieldBase.js` | request signing (`shieldFetch`) with rotating per-session keys from `/api/shield/key/`; SSR props sealed so the HTML/RSC payload carries ciphertext; `useUnsealed` opens them in the browser. Obfuscated at build time (`javascript-obfuscator`). Backend half: `api/shield.py`; a deterrent, not DRM ([26](26-auth-and-sessions.md)) |
| Content guard | `components/ContentGuard.jsx` | discourages copying, watermarks; real limits are server-side (`api/contentguard.py`) |
| Turnstile | login, recover, admin login, support chat | Cloudflare challenge token passed to the backend |

## 42.4 State management and browser storage

| State | Where | Notes |
|---|---|---|
| Signed-in user | `getPortalUser()` over `localStorage` `kg_portal_user`; `portalRefreshMe()` refreshes; DOM event **`kg:me`** tells `Sidebar`, `SettingsView` etc. to re-read | any new component that needs capabilities follows this pattern |
| Theme | `localStorage` `kg-theme` + attribute `data-theme`; event `kg:theme` keeps toggles in sync; boot script prevents flash | `ThemeToggle`, `SettingsView` |
| Tour state | `kg-tour-done`; guidance state under the `kg-guide:` prefix (`guidance/storage.js`) | every read/write is try/catch-guarded |
| Assistant | `kg_assistant_uid` (anonymous per-browser id for the chat), chat history in component state | history is sent to the route, sanitised server-side |
| Support chat widget | `localStorage kg_sc_v1` (thread id, token, intent), `sessionStorage kg_sc_q_v1` (unsent messages, 24 h cap) | pure reducer `support-chat/state.js`; token generated in the browser (32 random bytes, only the SHA-256 stored server-side) |
| Live events | `utils/sharedEventStream.js` — **one SSE connection per audience per tab**, shared by `useEventStream` subscribers; cursor resume with `Last-Event-ID`; fetch-based so the Bearer header can travel (`utils/eventStreamConnector.js`) | admin dashboard falls back to a 60 s re-sync |
| Modal | window event **`kg:modal`** `{title, body, icon}` handled by the global `Modal` | any component may open it |
| Hints | `reportSignal()` (`guidance/signals.js`) decouples components from the guidance provider; `SignalReporter` lets server components report | |
| URL state | brand/year/model/path segments (with `⁄` NAV_SLASH for slashes in segment names), `?cfg=` for parts configuration, `#section` hashes in the admin | `utils/api.jsx` |

## 42.5 API integration (`utils/api.jsx`, the only fetch layer)

| Group | Exports (examples) | Backend area |
|---|---|---|
| Catalogue and manuals | `fetchAllBrands`, `fetchBrands`, `fetchYearData`, `fetchNodes`, `fetchNav`, `fetchSubtree`, `fetchModels`, `resolveHref`, `fetchRawPage`, `searchNodes`, `fetchVehicleSpec` | `car_view`, `api/views.py`, `cardb*` |
| Parts and tables | `fetchPartsRoot`, `fetchPartsNodes`, `fetchPartsSearch`, `fetchFrm`, `laborTimesCsvUrl`, `sstCsvUrl`, `fetchSstAvailable` | `api/parts.py`, `api/frm.py`, `labortimes`, `sst` |
| Session | `portalLogin`, `verifyOtp`, `resendOtp`, `recoverStart`, `recoverReset`, `portalRefreshMe`, `portalLogout`, `updateBrowseMode`, `updateNotifyPrefs`, `updateOtpEnabled`, `fetchGrantedFleet` | `api/portal.py` |
| Team | `teamApi.*` (analytics, chat logs), `orgGraph`, `orgCreateNode`, `orgUpdateNode`, `orgDeleteNode`, `orgSetPermission`, `orgCreateUser`, `validateInvite`, `acceptInvite`, `downloadTeamReport` | `api/team.py`, `orggraph_api.py` |
| Support desk | `feedbackApi.*`, `kbApi.*`, `onboardingApi.*`, `fetchRecommendations` | `requests_api.py`, `knowledge.py`, `onboarding.py`, `recommend.py` |
| Admin | `adminLogin`, `adminVerifyOtp`, `adminApi.*` (≈ all admin sections) | `api/admin.py`, `adminops.py`, `insights.py`, `audit.py`, `pipeline.py` |
| Assistant feedback | `chatFeedback`, `rateAnswer`, `pinFeedback`, `fetchRecentFeedback` | `rag/feedback.py` |
| Live | `openEventStream` | `api/events.py` (SSE) |
| Support chat (visitor) | `support-chat/client.js` (never throws, returns `{ok, kind, …}`) | `api/support_chat/` |
| Support chat (staff) | `utils/supportChatApi.js` (admin token) | same |
| Activity | `logActivity` (fire-and-forget), `ActivityBeacon` for server pages | `ActivityLog` |

The assistant does **not** go through `api.jsx`: `app/api/chat/route.js` is a server-side route handler that holds the Metis API key and implements the lifecycle in [30 §30.3](30-ai-assistant-deep-dive.md); helper modules `lib/chatPrompt.js`, `lib/contextualize.js`, `lib/faTerms.js`, `lib/safeUrl.js` are unit-tested.

## 42.6 Component catalogue

**Shell and navigation** — `DashboardShell` (sidebar + main), `Sidebar` (groups: documents, team, account; items gated by the user payload; `data-tour` anchors), `Breadcrumb` (collapses deep manual paths), `UserChip` (renders nothing; identity lives in the sidebar), `ThemeToggle`, `Modal`, `BackgroundFX`, `Skeleton`, `Icon`, `Switch`.
**Manuals** — `CarBrowser` (tree sidebar + content pane), `CarNav` (lazy tree, highlights trail), `NodeList`/`NodeItem`/`SectionList`/`CardGrid`, `ContentRenderer` (rewrites the legacy `pages/<id>.html` cross-links), `StackedContent` (flattened subtree, anchors `node-<id>`), `SearchBox` (autocomplete, up to 5 suggestions, English input), `VehicleCover` (facts from `VehicleSpec`, actions, capacities), `FleetView`, `VehicleFilter`/`VehicleCardGrid`/`VehicleGroupList` (one filter and grouping for every vehicle list).
**Parts and flat-rate** — `PartsConfigPicker`, `PartsNav`, `PartsViewer` (exploded diagram with pan/zoom + table), `FrmShell`, `FrmTable` (LTS table, ~5,000 rows, filters, paged).
**Assistant** — `AssistantChat` (markdown links and `[BUTTON]` form, streaming, suggested questions), `EvidencePanel` (why the answer: exact-code / keyword / semantic match, same car, expert-confirmed, diagnostic engine; useful/not-useful), `FeedbackBar` (👍/👎 with reason), `app/assistant/page.jsx` (pick a car first).
**Team** — `OrgGraphCanvas` (canvas + list view; root seat edits), `AnalyticsView` (7/30/90 days, per-employee drill-down, PDF), `ChatLogsView` (shared with the admin panel), `RecommendationsWidget`, `OnboardingStrip`, `SettingsView` (tabs: account, notifications, security & access; theme, browse mode, restart tour).
**Support desk** — `RequestsView` (customer), `RequestsInbox` (agent), `TicketThread`, `CsatPrompt`, `FeedbackWidget` (page feedback), `components/desk/*` (`DeskLayout` two panes ≥860 px, `TicketList`, `DeskFilters`, `KbSuggestions` — "this answered it" is the only thing that records a deflection), `SupportAdmin` (support KPIs, product feedback, knowledge-base desk).
**Admin** — `app/admin/page.jsx` (24 sections, §42.7), `AdminDashboard` (live KPIs via SSE), `AdminInsights` (audit trail, AI cost, search insights, adoption funnel), `JalaliDateTimeInput`.
**Guidance** — `GuidanceProvider` (single root; resolves audience, surface, tours, hints), `TourEngine`, `HintLayer` (at most one hint, never modal), `HelpCenter` (built-in `content.js` articles + knowledge base), `hintRules.js`, `SiteTour`. Known drift: team-page tours target removed anchors ([07 §7.3](07-frontend.md)).
**Support chat (visitor widget, disabled in production)** — `SupportChat.jsx`, `Parts.jsx`, `useSupportChat.js`, pure modules `client`, `state`, `schedule` (poll back-off; visitors poll, they do not hold SSE threads), `storage`, `token`, `turnstile` (loaded on first send), `copy.fa.js` (all copy is a proposal until approved); staff side `admin/SupportDesk.jsx` (tab beside tickets), `SupportChatInbox.jsx`, `logic.js`.

## 42.7 Admin panel sections (24, from `SECTIONS`)

Online: `dashboard`, `company-requests` (support desk). Support and knowledge: `support-metrics`, `product-feedback`, `knowledge`. Customers: `requests` (purchase), `companies`, `users`. Reporting: `overview`, `analytics`, `activity`, `chats`, `funnel`, `search-insights`, `assistant-behavior`, `ai-cost`, `experiments` (A/B), `audit`, `logs` (Grafana dashboards). Data and operations: `catalog`, `dataquality`, `pipeline`, `vehicle-specs`, `system`. Doc 07 §7.4 lists an older subset; this is the current registry.

## 42.8 Implemented workflows (browser side)

1. **Sign-in:** username + password + Turnstile → (if the account has a phone and OTP on) 6-digit SMS code with a 2-minute timer and resend → session cookie/token → `next` redirect. Recovery: identifier → SMS code → new password (≥ 8 characters).
2. **Browse a manual:** `/browse` fleet → vehicle → server-rendered tree → leaf page; per-car search with autocomplete; breadcrumbs; each view logs an activity beacon.
3. **Parts:** vehicle → configuration (EPC frame) picker → group tree → exploded diagram + table.
4. **Ask the assistant:** pick a car → type a Persian symptom, DTC or procedure question → streamed answer with sources, evidence panel, rating.
5. **File and follow a ticket:** `/requests` → new request (type, category, optional vehicle, subject, description, priority) → knowledge suggestions → thread, SLA state, reopen by replying, satisfaction question after closure.
6. **Team management (root seat):** `/team` canvas → add seat → pick/create user (credentials sent by SMS) → set permissions; read-only for others; analytics and assistant logs within reach.
7. **Admin:** `/admin/login` (+OTP) → hub → sections above; live events keep the dashboard current.
8. **Support chat (when enabled):** floating widget → first message creates a thread with a client-generated token → polling → staff replies in the inbox tab.

## 42.9 Tests and build

Unit tests (`node --test`, 21 files under `src/**/__tests__/`): chat prompt, contextualiser, Persian terms (incl. the generated artifact), friendly errors, manual content, onboarding, packages/pricing, safe URLs, sanitiser, support rules, vehicle content, support-chat client/state/schedule/token/storage/turnstile/logic, event-stream connector and sharing. Browser E2E (`qa/e2e/tests`): a11y, auth, authz, media, public, session, support and support-chat specs ([32](32-testing-and-qa.md)); the nightly run currently fails 6 of them ([38](38-implementation-status-matrix.md), [47](47-engineering-followups.md)). Build quirks and obfuscation: [07 §7.6](07-frontend.md).
