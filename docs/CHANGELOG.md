# Changelog

Living log of shipped changes, newest first. One dated block per deploy/commit; keep lines
short and point at the doc section that was updated.

## 2026-07-18
- **Bilingual terminology store shipped** (`_rag/terms.db`, `api/rag/terms.py`,
  `manage.py build_terms`): Book1.csv + translation.sql unified and cleaned (1,602 part
  pairs + 107 curated service terms); `Book1.csv` and the new `terms_en_fa.json` display
  dictionary are now GENERATED artifacts (hot-reload, atomic, dated backups). (doc 14)
- **Professional bilingual chat display**: chat source titles/buttons render
  «فارسی (English)» via `src/lib/faTerms.js` (token-index matcher, 1,644 entries,
  60s hot-reload, built-in fallback); Metis prompt gains a mandatory TERMINOLOGY block.
  (doc 08 §8.5)
- **Conversational assistant**: client sends recent thread; deterministic follow-up
  contextualizer (`src/lib/contextualize.js`, no LLM cost) joins anaphoric follow-ups
  for retrieval; HISTORY block in the prompt; 2-4 follow-up suggestion chips per answer;
  clarify mode (one Persian clarifying question + system chips) for ambiguous
  low-confidence queries; hardened history validation. (doc 08 §8.5)
- **QA-gated machine translation** (`manage.py translate_terms`): 2-sample
  self-consistency + bge-m3 back-translation gate, budget caps, lockfile, pipeline
  yielding, review CSV workflow; mining/report/fa-gap commands in `build_terms`. (doc 14)
- Backend tests 221 green (28 new); frontend node tests 4 suites green; sandbox E2E
  batteries (phase 1: bilingual display; phase 2: multi-turn/clarify/chips) all pass.

## 2026-07-15
- **Documentation suite created** (`docs/01…13`, this changelog). Source of truth going
  forward; maintenance protocol in `docs/README.md`.
- **User guidance system shipped** (`kg_frontend/src/guidance/`): role-based onboarding
  tours (visitor / user / manager / admin), searchable on-demand help center (`?` button +
  `Shift+?`), admin guide covering every admin section, contextual smart hints
  (rule-based, frequency-capped). Replaces the old two-page `SiteTour`. See doc 13.

## 2026-07-14
- Org-chart consistency overhaul deployed: strict supervisor-outranks invariant +
  auto-repair (`enforce_org_consistency`), string-id coercion fix at API boundary, SSE
  team sync, empty-position assign UX, «شما» labels. Tests 193 green. (docs 06, 07)
- Assistant link integrity: `_enc(safe='')`, tolerant year resolution, catalog fallback in
  `config.car_meta`, `NX 250 FWD (1)` purged from index, occurrences.year backfilled
  (1.52M rows), 414k diag URLs rewritten; 1.66M+181k URLs verified zero-fail. (doc 08)
- Dummy/test companies purged from prod (companies 2 & 6); prod = 1 real company.
- All prior uncommitted work committed as 2da813d + 347d6e3.

## 2026-07-11
- Real-time platform deployed: Event/SSE backbone, company requests, live admin/manager
  dashboards, recommendations engine, `ActivityLog.app_url` (migrations 0011–0012);
  4 security/robustness fixes (allow-list threading B-01, body clamps, grant clamp B-03,
  JSON hardening G12); gunicorn threads 8/timeout 300; nginx SSE location; detect timer.
  (docs 03, 05, 09, 10, 12)
- Flexible org hierarchy (OrgRole, migration 0010), PDF team reports (WeasyPrint),
  admin hub + `/admin/login`. (docs 03, 06, 10)

## 2026-07-10
- Data-quality engine + monitoring/alerting/traffic stack + cardb pool + admin ops panels
  (migration 0008, commit 2c949d1); processing pipeline with detached workers + watchdog
  timer (0009, commit 318f255). Fleet remediated: 38/38 complete, duplicates quarantined.
  `db.sqlite3` untracked from git. (docs 04, 11)

## 2026-07-09
- Backend content paywall enforced (per-car gates, SSR cookie, chat gating, per-IP rate
  limits). Company self-service team management + invites + analytics (migration 0007).
  (docs 05, 06, 12)

## 2026-07-08
- PlatformAdmin password rotated (was admin/admin); all admin sessions invalidated.
  RAG scope-leak gate (`car_not_indexed`). (docs 08, 12)

## Earlier (June 2026)
- Initial platform: parser + warehouse, Django content serving, Next.js portal, purchase
  flow, RBAC packages + platform admin (migrations 0001–0006), RAG index + diagnostic
  engine + Metis-phrased assistant, eval harness.
