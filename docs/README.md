# KGtechvault — Technical Documentation

**Project:** KGtechvault (KGKG) — Persian (fa/RTL) automotive technical-documentation platform
(Toyota / Lexus service manuals) with RAG-grounded AI assistance, company self-service team
management, real-time dashboards, and a full operations/observability stack.

**Company:** شرکت خدمات گستر سپهر گیتی (Khadamat Gostar Sepehr Giti)

This directory is the **primary source of truth** for how the system works and why. It is
*living documentation*: every feature change must update the affected section(s) in the same
commit (see [Maintenance protocol](#maintenance-protocol) below).

---

## Table of contents

| Doc | Covers |
|---|---|
| [00 — Software requirements (SRS)](00-srs.md) | What the system must do and how well: FR/NFR with the tests that verify each |
| [01 — System overview](01-overview.md) | What the product is, who uses it, roles, top-level user flows, glossary |
| [02 — Architecture](02-architecture.md) | Runtime topology, stack, design principles, data flow, scale strategy |
| [03 — Data model](03-data-model.md) | Every Django model, the per-vehicle warehouse schema, the RAG index schema |
| [04 — Backend reference](04-backend-reference.md) | Module-by-module guide to `KG_backend/api`, management commands |
| [05 — API reference](05-api-reference.md) | Every HTTP endpoint: auth, parameters, responses, errors, rate limits |
| [06 — Permissions & RBAC](06-permissions-rbac.md) | Auth systems, roles, capabilities, grants, org hierarchy, authorization spine |
| [07 — Frontend](07-frontend.md) | Next.js routes, components, session handling, UI conventions, validation |
| [08 — AI assistant & RAG](08-ai-assistant-rag.md) | Index build, retrieval, diagnostic engine, chat flow, Metis integration |
| [09 — Real-time events (SSE)](09-realtime-sse.md) | Event backbone, emitters, stream endpoint, frontend consumers |
| [10 — Analytics, reports & recommendations](10-analytics-reporting.md) | Activity logging, team/platform analytics, PDF reports, recommendation engine |
| [11 — Operations & deployment](11-operations-deployment.md) | Server layout, systemd, nginx, env vars, pipeline, monitoring, alerts, backups, deploy process |
| [12 — Security](12-security.md) | Auth details, enforced guarantees, hardening history, known limitations |
| [13 — User guidance system](13-guidance-system.md) | Role-based tours, help center, contextual hints — and how they stay in sync with these docs |
| [14 — Terminology & bilingual display](14-terminology.md) | terms.db store, bilingual chat display, QA-gated translation |
| [15 — Vehicle schema & ingestion pipeline](15-vehicle-schema.md) | download/parse pipeline stages, ZIP inbox, multi-year stems, schema.org vehicle specs |
| [16 — Parts catalog](16-parts-catalog.md) | Parts-only vehicles, import pipeline, /parts UI |
| [17 — AI evaluation suite](17-evaluation.md) | Gold sets, baselines, retrieval/diagnosis/answer metrics, expert-review tooling |
| [18 — Security hardening](18-security-hardening.md) | Secret/token rotation, nginx rate limiting, ModSecurity+CRS WAF, GlitchTip error monitoring |
| [19 — Engineer onboarding](19-onboarding.md) | Day 1 / week 1 / month 1 path for a new engineer, with a check per step; how knowledge is handed over |
| [20 — Runbooks](20-runbooks.md) | Site down, false alerts, slowness, failed deploy, AI provider outage, disk, restore, adding a vehicle, SMS paging |
| [21 — CSRF-exempt views](21-csrf-exempt-views.md) | Every @csrf_exempt view, how it authenticates, why it is safe; registry + Origin guard |
| [AGENTS — start here (agents and new engineers)](AGENTS.md) | Evidence rules, task-to-doc map, rules that are easy to break, how docs are kept true |
| [22 — Support chat](22-support-chat.md) | Visitor widget, staff inbox, tokens, throttling, RBAC rollout, kill switch |
| [23 — Data layer](23-data-layer.md) | Where every kind of data lives: PostgreSQL `kgkg`, per-car schemas in `kgkg_vec`, parts SQLite, RAG index |
| [24 — Integrations](24-integrations.md) | Metis, SMS, Turnstile, Cloudflare, GlitchTip, observability: config names and failure behaviour |
| [25 — Operations inventory](25-ops-inventory.md) | Observed host state: units, timers, containers, directories, with evidence tags |
| [26 — Authentication and sessions](26-auth-and-sessions.md) | Token lifetimes, login/OTP flow, single-session rule, admin gate, content protection |
| [27 — Open risks and decisions](27-open-risks-and-decisions.md) | Register of known risks (backups, shared staging data, ...) with evidence and tracking |
| [28 — Team workflow](28-team-workflow.md) | GitHub/Jira/Trello/Slack roles, labels, issue-closing rule, daily reconcile |
| [29 — Environment variable reference](29-environment-reference.md) · [fa](fa/29-environment-reference.md) | Operational and tuning variables: default, consumer, meaning (no values) |
| [30 — AI assistant deep dive](30-ai-assistant-deep-dive.md) · [fa](fa/30-ai-assistant-deep-dive.md) | Request lifecycle, retrieval, scoring, scope gates, prompts, Metis, fallbacks, feedback, evaluation, capability status |
| [31 — Ops files and units reference](31-ops-files-reference.md) · [fa](fa/31-ops-files-reference.md) | Observability stack, log rotation, Umami, systemd units, offline RAG tools, security baselines |
| [32 — Testing, QA and verification](32-testing-and-qa.md) · [fa](fa/32-testing-and-qa.md) | Every test and gate: purpose, commands, CI, QA stack, gaps |
| [Persian index](fa/README.md) | Persian twins of the documents above and how they are kept in sync |
| [Generated inventory](generated/inventory.md) | Machine-generated list of modules, models, commands, env var names, routes, units; CI-checked |
| [ADR — Architecture decisions](adr/README.md) | Why the system is built this way: SQLite, local retrieval, containers, promotion, monitoring, docs-as-code |
| [CHANGELOG](CHANGELOG.md) | Dated log of shipped changes, newest first |

## Quick facts (re-verified 2026-11-04 against `origin/work` `8a380f6`; production head matched)

- **Production:** `https://kgtechvault.com` — single Ubuntu 24 host `103.75.197.155` (16 cores / 31 GB / 290 GB, 75% used).
- **Repo root on server:** `/opt/KGKG` (this is the deployed working copy AND the git repo).
- **Backend:** Django 5.2.15, gunicorn (3 gthread workers × 8 threads) on `:8000`.
- **Frontend:** Next.js 16.2.9 / React 19.2.4 (`npm run start`) on `:3000`, behind nginx 1.24.
- **Data:** 237 cars on 2026-11-03: 222 manual cars in PostgreSQL `kgkg_vec` (one schema per car), 15 parts-only cars as SQLite; portal data in
  PostgreSQL `kgkg`; unified RAG index `_rag/index.rag.db`. Details and caveats: [23 — Data layer](23-data-layer.md).
- **Branches:** work on `work` (PRs target it); `main` is the GitHub default and receives merges from `work`. Remote `github.com/mjsn800403/KGKG`.
- **Start here if you are an AI agent or new engineer:** [AGENTS.md](AGENTS.md). Open risks: [27](27-open-risks-and-decisions.md).

## Maintenance protocol

These docs only stay valuable if they stay true. The rules:

1. **Docs ship with the change.** A PR/commit that alters behavior (endpoint, model,
   permission rule, UI flow, ops procedure) must edit the affected doc section(s) in the same
   commit. If you don't know which section: `grep -ri <feature-name> docs/`.
2. **CHANGELOG.md gets one dated line per shipped change** (newest first). This is the index
   future sessions use to catch up.
3. **The guidance system mirrors these docs.** User-facing help content lives in
   `kg_frontend/src/guidance/content.js`; every article carries a `docRef` pointing at the
   doc section it summarizes. When you edit a doc section, search `content.js` for its
   `docRef` and update the matching article(s). See [13 — Guidance system](13-guidance-system.md).
4. **State the *why*, not just the *what*.** Each section should let a future maintainer
   predict the blast radius of a change. When you make a non-obvious tradeoff, record it.
5. **`.gitignore` ignores `*.md` globally** (manual-content spillover protection) — docs are
   force-added: `git add -f docs/`.
6. **English for engineering docs, Persian for user-facing strings.** UI copy inside code and
   guidance content is Persian; these maintainer docs are English.
7. **Every document has named owners and a review date** in [`OWNERS.toml`](OWNERS.toml), and
   CI enforces it (`ops/governance/check_docs_freshness.py`): a document with no entry, no
   owner, or past `reviewed + review_days` fails the build. Reviewed a document and it is still
   correct? Move `reviewed` to today — that is the whole ritual, deliberately cheap enough to
   actually do. Changed one? Move it too; you have just confirmed it. The staleness rule is the
   same one the product applies to knowledge-base articles, so the repository and the product
   never disagree about what "stale" means. `owner` takes one name or several — both
   maintainers own every document today, and a stale notice names both, so neither can assume
   the other was asked. `docs/superpowers/specs/` is excluded: a dated design record cannot go
   stale.

## Reading order for a new maintainer

1. `01-overview.md` then `02-architecture.md` — mental model.
2. `06-permissions-rbac.md` — nearly every bug/feature touches authorization.
3. The doc matching your task area.
4. `11-operations-deployment.md` **before touching the server** — deploys have sharp edges
   (SQLite WAL, detached pipeline worker, nginx SSE location, `*.md` gitignore).
