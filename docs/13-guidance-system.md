# 13 — User Guidance System

A single, docs-driven guidance layer that gives every user role-appropriate
onboarding, always-available searchable help, and subtle contextual assistance —
built to stay in sync with this documentation. It lives entirely in the
frontend under `kg_frontend/src/guidance/` and mounts once in the app layout.

## 13.1 Goals it satisfies

| Requirement (from the product brief) | How it's met |
|---|---|
| Role-based onboarding / interactive tour per role & permissions | `TOURS` in `content.js`, one per audience; auto-starts once per role on the matching surface; spotlight `TourEngine` |
| Dedicated admin guide covering every capability | Admin-role articles, one per admin section (`SECTIONS` id), plus a setup-workflow index and a troubleshooting article |
| Always-available in-context help for admins (and everyone) | Floating `?` button + `?` keyboard shortcut → `HelpCenter` slide-over; never leaves the page |
| Docs ↔ guidance kept synchronized | Every tour/article carries a `docRef`; `scripts/check-guidance-sync.mjs` fails on a broken ref and warns on staleness; protocol in `docs/README.md` |
| Intelligent contextual assistance (detect mistakes / inefficiency → subtle guidance) | Rule-based `HintLayer` + `hintRules.js`, fed by lightweight signals; at most one calm, dismissible hint at a time |
| Clean, minimal, unobtrusive; the listed UX patterns | Progressive disclosure (master/detail help, collapsed categories), lightweight tooltips (tour tips), smart inline recs (hints), role-based onboarding, on-demand + searchable + keyboard-accessible help, non-intrusive indicators |

## 13.2 Architecture

```
kg_frontend/src/guidance/
├─ index.js            # public entry: default = GuidanceProvider; { reportSignal }
├─ GuidanceProvider.jsx# client root: resolves audience + surface, owns help/tour/hint state,
│                      #   keyboard shortcut, auto-start, restart hook; mounts the FAB + overlays
├─ content.js          # DOC-SYNCED registry: ROLES, resolveAudience, TOURS, ARTICLES, CATEGORIES,
│                      #   selectors (autoTourFor, articlesFor, contextualArticles). Every item has docRef.
├─ TourEngine.jsx      # spotlight walkthrough for one tour (skips missing targets, reduced-motion safe)
├─ HelpCenter.jsx      # searchable slide-over: contextual suggestions + categorized master/detail
├─ HintLayer.jsx       # renders at most one contextual hint; handles act/dismiss/cooldown
├─ hintRules.js        # behavioural rules (copy + condition), evaluated against a live context
├─ signals.js          # reportSignal(name,value) — decoupled channel components use to feed hints
└─ storage.js          # localStorage: tour-seen-per-role, hint dismissals/cooldowns, help-opened
```

Guidance CSS is appended to `src/app/globals.css` (namespaced `guide-*`, reusing the
app's design tokens so it themes light/dark automatically).

Mount point: `src/app/layout.tsx` renders `<Guidance />` once — it covers public,
portal and admin surfaces. It renders nothing on auth screens (`/login`,
`/admin/login`, `/invite/*`).

## 13.3 Audience resolution

`resolveAudience({ pathname, portalUser, isAdmin })` → `{ role, caps, isAdmin }`:

- `admin` — on `/admin*` or when an admin token is present.
- `visitor` — no portal user.
- `manager` — `can_manage_team`.
- `analyst` — `can_view_analytics` without manage.
- `user` — a plain seat.

Capabilities (`caps.manage/analytics/ai`) come straight from the cached portal user
(`getPortalUser()`), refreshed on the app's `kg:me` event and cross-tab `storage`
events. Visibility of an article/tour is `roles.includes(role)` **or** a satisfied
`cap` requirement (so analytics help reaches every analytics viewer regardless of
their headline role).

## 13.4 Tours (role-based onboarding)

`TOURS` entries: `{ id, roles, autoRoute(pathname), route, title, docRef, steps[] }`.
Each step is `{ sel, title, body }` where `sel` targets a stable anchor
(`[data-tour="…"]` reused from the legacy tour, or new `[data-guide="…"]`; steps
accept a comma-list so both work). Anchors currently placed:

- Landing: `login-btn`, `doc-layers`, `vin-box`, `support` (pre-existing `data-tour`).
- Portal sidebar: `nav-fleet`, `nav-assistant`, `nav-team`, `nav-requests`,
  `nav-analytics`, `nav-settings`; `model-filter`; `recs` (RecommendationsWidget).
- Team: `team-tabs`, `team-add`, `team-search` (TeamView).
- Admin: `admin-hub`, `admin-group-realtime/customers/insights/operations` (AdminHub);
  the FAB (`.guide-fab`).

Behaviour: the matching tour auto-starts once per role (1.3s after landing on its
surface) unless already seen (`storage.tourSeen`); finishing **or** skipping marks it
seen (never re-nags). Replayable any time from the help panel ("شروع راهنمای تصویری"
on an article) or Settings ("شروع دوبارهٔ راهنما" dispatches `kg:tour`). A tour
launched off its route navigates there first (`route`) then starts. Missing targets
are skipped so a tour degrades gracefully when a surface changes. Reduced-motion is
respected (spotlight transitions disabled). Keyboard: ←/→ step, Esc exit.

## 13.5 Help center (on-demand, searchable, keyboard)

`HelpCenter` is a slide-over (`?` button or `?` key; Esc closes). It shows:
- **"مرتبط با این صفحه"** — `contextualArticles(audience, {pathname, section})` ranks
  articles by surface specificity (matching admin section > exact path > path prefix),
  so the panel opens on the most relevant article automatically (context-sensitive
  help). Admin section is tracked via the hash **and** a `kg:guide-context` event the
  admin panel dispatches from `go()` (since `replaceState` fires no `hashchange`).
- **Search** — matches title, summary, keywords and body (Persian).
- **Categorized list** (progressive disclosure) → **article detail** (master/detail):
  summary, body paragraphs, optional step list, an optional "start visual tour"
  button, and a subtle `docRef` note.

`ARTICLES` fields: `{ id, category, roles, cap?, surfaces[], title, keywords[],
summary, body[], steps?, tourId?, docRef, reviewed }`. The admin set is the full
administrator guide — one article per section (dashboard, company-requests, requests,
companies, users, analytics/activity/overview, catalog, dataquality, pipeline,
system) plus an index (setup workflow) and troubleshooting.

## 13.6 Contextual hints (intelligent assistance)

`hintRules.js` defines behavioural rules; `HintLayer` shows **at most one** calm,
dismissible card at a time (bottom-inline-start, above the FAB — never modal). Each
rule: `{ id, roles, cap?, severity, test(ctx), title, body, action, cooldownMs,
maxShows }`. `pickHint` returns the first eligible, non-dismissed, under-cap rule
whose `test` passes.

Context: `{ audience, pathname, section, signals }`. `signals` is a plain map fed by
`reportSignal(name, value)` from around the app; a rule that needs a signal returns
false when it's absent, so an un-wired signal keeps its hint dormant (never a false
positive). Wired signals today:

| Signal | Emitted by | Enables hint |
|---|---|---|
| `team.memberCount` | TeamView (on load) | `team-empty` — "add your first employee" |
| `team.drawer='invite-no-email'` | TeamView member drawer | `team-invite-no-email` — suggest credentials mode (no SMTP configured) |
| `admin.pendingWork` | AdminDashboard | `admin-new-data` — "run data processing" |
| *(none — data-driven)* | portal user eligibility | `ai-not-eligible` — why the assistant is off + how to fix |
| *(none — route/once)* | route | `assistant-precision` — mention the vehicle + exact DTC |

Dismissals persist (`storage`); some hints return after a cooldown, capped by
`maxShows`, so they inform without nagging. Adding a new hint is editing
`hintRules.js` (+ a `reportSignal` call if it needs new data) — no engine changes.

## 13.7 Keeping docs and guidance in sync

This is the "living documentation" contract:

1. Every tour/article/hint carries a `docRef` → the doc section it summarizes.
2. When you change a doc section, `grep` this directory for its `docRef` and update
   the matching guidance copy in the **same commit**; bump `REVIEWED` in `content.js`.
3. `node kg_frontend/scripts/check-guidance-sync.mjs` **fails** if any `docRef`
   points at a missing docs file and **warns** if a referenced doc file was modified
   after the last review date — run it in the pre-deploy checklist (doc 11 §11.3).
4. Guidance content is user-facing and shipped to the browser: never put
   maintainer-only material (server internals, security limitations, tokens) in
   `content.js` — that stays in `docs/`.

What is intentionally **not** automated: there is no runtime markdown parser turning
`docs/*.md` into help. The docs are engineering-facing and include content that must
never reach end users; the guidance is a curated Persian mirror. The `docRef` linkage
+ the checker + the protocol are the synchronization mechanism — honest and
maintainable, without a fragile generator.

## 13.8 Extending it

- **New page/feature:** add anchor attributes (`data-guide="…"`), add a tour and/or
  article in `content.js` with a `docRef`, and (if it can be misused) a rule in
  `hintRules.js`. Update the relevant `docs/` section and this file.
- **New role/capability:** extend `ROLES` + `resolveAudience`, then tag content with
  the new role or a `cap`.
- **New contextual hint:** add a rule; wire a `reportSignal` only if it needs data the
  engine can't already see (route, section, audience capabilities).

## 13.9 Backward-compatibility notes

- Replaces the old `components/SiteTour.jsx` (removed). The legacy `kg:tour` event
  (dispatched by Settings) still works — the provider listens for it. The legacy
  `kg-tour-done` localStorage flag is honoured once so upgraders aren't re-toured.
- Reuses proven CSS patterns from the old tour (ring + tip), re-namespaced `guide-*`.
