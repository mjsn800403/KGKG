# 10 — Analytics, Reports & Recommendations

## 10.1 The signal: ActivityLog

Everything starts with the activity beacon (`POST /api/activity/` from `ActivityBeacon` and
key UI actions): `action`, `category` (canonical technical area resolved from the manual
path — `access.resolve_category`), `car`, `node_title`, `app_url`. Login is logged
server-side. The category taxonomy (engine / transmission / brakes / steering / suspension /
electrical / hvac / body / accessories / maintenance / other) is the analytics dimension
everywhere — extend it in `access.CONTENT_CATEGORIES` only (aliases map raw English section
titles).

## 10.2 Team analytics (manager/analytics viewers)

`team.build_team_analytics(viewer, days, member_id?, category?)` — scoped to
`manageable_user_ids(viewer)` (the same visibility rule as the team area, so an analytics
viewer can never see people they couldn't manage): totals, per-category distribution,
per-member drill-down, daily trend. Served by `/api/team/analytics/`, rendered by
`AnalyticsView` (bars, count-ups, area trend).

## 10.3 PDF team report (`api/reporting.py`)

`GET /api/team/report/?range=N` → WeasyPrint 69, fa/RTL, designed (cover, KPI band, donut +
category bars, trend SVG, member/vehicle tables). Implementation constraints that must
survive refactors:

- Fonts: bundled FULL official **Vazirmatn** Regular/Bold TTFs (`reporting_assets/fonts/`).
  Subset/woff2-derived fonts garble Latin glyphs and the letter «ل» — never "optimize" them.
- WeasyPrint applies no bidi inside SVG `<text>` — the donut's center labels are HTML
  overlays positioned over the SVG.
- Dates are Jalali via arithmetic conversion (no extra dependency); years render with
  `fa_int` (no thousands separators).

## 10.4 Platform analytics (admin)

`/api/admin/analytics/` — cross-company: usage by company, category, member; feeds the
«تحلیل کل پلتفرم» section. `/api/admin/activity/` is the raw filterable log. Traffic-level
analytics (requests/latency/errors/uniques) are separate — `monitoring.py` rollups via
`/api/admin/traffic/` (doc 11).

## 10.5 Recommendations (`api/recommend.py`)

`GET /api/recommendations/` → up to `limit` cards for the logged-in user, built from their
own ActivityLog + grants (never leaks other users' content):

| Kind | Logic |
|---|---|
| `continue` | Most recent viewed nodes with `app_url`, deduped — "ادامه بدهید" |
| `related` | RAG graph neighbours (semantic/crosslink edges) of recently viewed blobs, gated to granted cars |
| `focus_areas` | Category affinity from their history → top sections in those categories |
| `popular_in_company` | What colleagues with overlapping grants view (collaborative) |
| `explore` | Granted cars never opened |

Manager insights (`/api/team/insights/`): seat utilization, idle members (no activity in
window), top members, category coverage + gaps vs. the fleet's content.

Rendered by `RecommendationsWidget` on `/browse`. Deep links come from `ActivityLog.app_url`
— content pages must keep sending `app_url` in beacons or `continue`/`related` degrade.

## 10.6 Extending analytics

- New action type: pick a stable `action` string, beacon it, and it appears in reports
  automatically; add a Persian label in the UIs that enumerate actions.
- New dimension: add the column to `ActivityLog` (+migration, + index if filtered),
  populate in `activity_view`, surface in `build_team_analytics`/admin analytics.
- Keep beacons fire-and-forget — analytics must never break browsing.
