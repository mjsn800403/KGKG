# 07 — Frontend (`kg_frontend`)

Next.js 16 App Router, React 19, Persian/RTL (`<html lang="fa" dir="rtl">`), self-hosted
fonts, hand-written design system in `src/app/globals.css` (CSS variables, `data-theme`
light/dark), `motion` v12 for animation (always wrapped so `prefers-reduced-motion` is
respected via `MotionConfig`).

## 7.1 Route map (`src/app/`)

| Route | Access | What it is |
|---|---|---|
| `/` | public | Marketing landing: parallax hero, doc-layer cards, VIN coverage check, support strip |
| `/login` | public | Portal login (username or email) |
| `/purchase` | public | Purchase-request wizard (vehicle, layers, `SeatPlanBuilder`, contact) |
| `/invite/[token]` | public | Invite acceptance: validate → set password → auto-login |
| `/browse` | portal | Dashboard home: granted fleet tiles (`FleetView`), model filter chips, `RecommendationsWidget` |
| `/[brand]/[year]/[model]` (+`/[...path]`, `/page/[file]`, `/search`, `/assistant`) | portal + car grant (SSR-gated) | Manual browsing: node tree, leaf pages, per-car semantic search, per-car assistant |
| `/assistant` | portal (AI-eligible for answers) | General assistant chat (`AssistantChat`) |
| `/team` | manager | Team area: Members / Org chart / Roles tabs (`TeamView`, `OrgChart`, `RolesPanel`) |
| `/team/analytics` | analytics | `AnalyticsView`: category bars, member drill-down, trend, PDF download |
| `/requests` | manager | `RequestsView`: file/watch company requests (live) |
| `/settings` | portal | `SettingsView`: account, theme, notifications, security, tour restart |
| `/admin/login` | public | Dedicated platform-admin login |
| `/admin` | admin token | Admin hub + all sections (see 7.4) |
| `/admin-review` | admin | Assistant feedback review feed |
| `/api/chat` | route handler | Server-side assistant proxy (doc 08) |

## 7.2 Session & data layer (`src/utils/api.jsx` — the only fetch layer)

- **Token storage:** `localStorage` (`kg_portal_token` + cached `kg_portal_user`) mirrored
  into a same-site `kg_portal_token` **cookie** by `setPortalSession` so SSR pages can
  forward it (`utils/serverAuth.js` → `portalTokenCookie`). Admin token in
  `localStorage` (`kg_admin_token`).
- **`kg:me` event:** dispatched whenever the cached user changes; `Sidebar`, `SettingsView`
  etc. re-read capabilities on it. Any new component needing the user should follow this
  pattern (`getPortalUser()` + listen for `kg:me`).
- Content fetchers (`fetchNodes`, `fetchModels`, `searchNodes`, `resolveHref`,
  `fetchRawPage`) send the token (localStorage client-side, cookie value on SSR);
  content pages redirect to `/login` on 401 and render an access-denied state on 403.
- `logActivity(action, detail, extra)` — fire-and-forget beacon; content pages send
  `segments` + `brand/model/year` + `app_url` so the backend can attach category + car and
  recommendations can deep-link (`ActivityBeacon` on server-rendered pages).
- `teamApi.*`, `adminApi.*` — namespaced clients for team/admin surfaces.
- `openEventStream({admin, onEvent, onStatus})` — fetch-based SSE reader with Bearer header,
  auto-reconnect + Last-Event-ID cursor (native EventSource can't send headers). Used via
  the `useEventStream` hook.
- `downloadTeamReport(rangeDays)` — authenticated blob download of the PDF.

## 7.3 Portal UI composition

- `DashboardShell` = `Sidebar` + content column; every authed portal page renders inside it.
- `Sidebar` links are capability-gated: Team + Requests need `can_manage_team`, Analytics
  needs `can_view_analytics` (or manage). Nav items carry `data-tour` attributes — the
  guidance system anchors on these (doc 13).
- `TeamView` drawer (add/edit member) — invite-vs-credentials toggle, org-role select
  (supervisor dropdown filtered to ranks above the chosen position), access delegation
  limited to `meta.cars` (the manager's grantable set with layer ceilings), copyable
  invite-link / credentials success panels. **Ids from `<select>`s are strings — `Number()`
  them before sending** (bug class fixed 2026-07-14).
- `OrgChart` — rank-layered chart, click-to-move (validated server-side), role menu (quick
  role change), legend, empty-position ghost cards («افزودن عضو» opens the drawer
  preselected via `initialRoleId`).
- `RolesPanel` — motion `Reorder` drag-to-re-rank, scope picker, color swatches, access
  template editor, apply-to-members, per-role member chips (+ transfer select). Rows at or
  above the viewer's own rank are locked («جایگاه شما» tags).
- `TeamView` subscribes to `team.*` SSE events → debounced reload → tabs and other open
  sessions stay in sync without manual refresh.
- Content rendering: `NodeList`/`NodeItem` (tree), `ContentRenderer` (leaf HTML),
  `Breadcrumb`, `SearchBox`, `EvidencePanel` + `FeedbackBar` (assistant citations + 👍/👎),
  `AssistantChat` (chat UI with car context, suggested actions, link buttons).
- `RecommendationsWidget` — «ادامه بدهید», related, focus areas etc. on `/browse`.
- `RequestsView`/`RequestsInbox` — the two sides of company requests, both live.

## 7.4 Admin panel (`app/admin/page.jsx`, ~1900 lines)

Single client page, hash-routed sections (`#dashboard`, `#users`, …), guarded by the admin
token (`guard` wrapper redirects to `/admin/login` on 401). Landing state is the **hub** —
grouped section cards with quick stats; entering a section reveals the sidebar. Sections:

`dashboard` (live KPIs, processing progress, requests, alerts, activity, traffic, event
ticker — SSE-driven), `overview`, `catalog`, `requests` (purchase), `company-requests`
(inbox), `companies` (+access editor), `users` (+access editor), `analytics`, `activity`,
`dataquality` (audit report + refresh/fix), `pipeline` (start/schedule/resume/cancel +
settings + honest ETA), `system` (resources, traffic, alerts).

The `SECTIONS` array is the canonical section registry — the guidance system keys admin
help articles to these ids (doc 13).

## 7.5 UI conventions & validation

- **Design language:** dark-first glassmorphism, CSS variables (`--bg`, `--card`,
  `--accent`, …), `data-theme` on `<html>` (boot script applies stored theme pre-paint to
  avoid flash), gradient accents, `Icon.jsx` sprite set. New UI must reuse the variables —
  no hardcoded colors.
- **RTL:** everything is RTL by default; wrap Latin/numeric spans with `.ltr` where needed.
  Persian digits via `toLocaleString('fa-IR')`.
- **Motion:** entrance reveals + micro-interactions via `motion`; always respect
  reduced-motion.
- **Validation:** forms validate client-side for UX (required fields, seat-plan counts
  1–1000, password length on invite ≥ 8) but the backend re-validates everything with
  Persian error strings the UI displays verbatim.
- **Errors:** fetchers throw with the backend's `error` message; views toast or inline it.
- **Mobile:** responsive to ~360px. Verification trick from a fixed-width machine: inject a
  375px same-origin iframe and inspect (window resize is clamped — see ops notes).

## 7.6 Build & deploy quirks

- `NEXT_PUBLIC_API_BASE` is baked at **build time** — rebuilding on the server with the
  right `.env.production` matters (`http://103.75.197.155/kg-api`).
- `npm run build` ~90s on the server; `systemctl restart kgkg-frontend` afterwards.
- Staging copies must hardlink `node_modules` (`cp -al`) — Turbopack rejects out-of-root
  symlinks.
- `/api/chat` holds secrets (Metis) — it must stay a server route, never client-fetchable
  config.
