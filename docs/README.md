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
| [00 — Software requirements (SRS)](00-srs.md) · [fa](fa/00-srs.md) | What the system must do and how well: FR/NFR with the tests that verify each |
| [01 — System overview](01-overview.md) · [fa](fa/01-overview.md) | What the product is, who uses it, roles, top-level user flows, glossary |
| [02 — Architecture](02-architecture.md) · [fa](fa/02-architecture.md) | Runtime topology, stack, design principles, data flow, scale strategy |
| [03 — Data model](03-data-model.md) · [fa](fa/03-data-model.md) | Every Django model, the per-vehicle warehouse schema, the RAG index schema |
| [04 — Backend reference](04-backend-reference.md) · [fa](fa/04-backend-reference.md) | Module-by-module guide to `KG_backend/api`, management commands |
| [05 — API reference](05-api-reference.md) · [fa](fa/05-api-reference.md) | Every HTTP endpoint: auth, parameters, responses, errors, rate limits |
| [06 — Permissions & RBAC](06-permissions-rbac.md) · [fa](fa/06-permissions-rbac.md) | Auth systems, roles, capabilities, grants, org hierarchy, authorization spine |
| [07 — Frontend](07-frontend.md) · [fa](fa/07-frontend.md) | Next.js routes, components, session handling, UI conventions, validation |
| [08 — AI assistant & RAG](08-ai-assistant-rag.md) · [fa](fa/08-ai-assistant-rag.md) | Index build, retrieval, diagnostic engine, chat flow, Metis integration |
| [09 — Real-time events (SSE)](09-realtime-sse.md) · [fa](fa/09-realtime-sse.md) | Event backbone, emitters, stream endpoint, frontend consumers |
| [10 — Analytics, reports & recommendations](10-analytics-reporting.md) · [fa](fa/10-analytics-reporting.md) | Activity logging, team/platform analytics, PDF reports, recommendation engine |
| [11 — Operations & deployment](11-operations-deployment.md) · [fa](fa/11-operations-deployment.md) | Server layout, systemd, nginx, env vars, pipeline, monitoring, alerts, backups, deploy process |
| [12 — Security](12-security.md) · [fa](fa/12-security.md) | Auth details, enforced guarantees, hardening history, known limitations |
| [13 — User guidance system](13-guidance-system.md) · [fa](fa/13-guidance-system.md) | Role-based tours, help center, contextual hints — and how they stay in sync with these docs |
| [14 — Terminology & bilingual display](14-terminology.md) · [fa](fa/14-terminology.md) | terms.db store, bilingual chat display, QA-gated translation |
| [15 — Vehicle schema & ingestion pipeline](15-vehicle-schema.md) · [fa](fa/15-vehicle-schema.md) | download/parse pipeline stages, ZIP inbox, multi-year stems, schema.org vehicle specs |
| [16 — Parts catalog](16-parts-catalog.md) · [fa](fa/16-parts-catalog.md) | Parts-only vehicles, import pipeline, /parts UI |
| [17 — AI evaluation suite](17-evaluation.md) · [fa](fa/17-evaluation.md) | Gold sets, baselines, retrieval/diagnosis/answer metrics, expert-review tooling |
| [18 — Security hardening](18-security-hardening.md) · [fa](fa/18-security-hardening.md) | Secret/token rotation, nginx rate limiting, ModSecurity+CRS WAF, GlitchTip error monitoring |
| [19 — Engineer onboarding](19-onboarding.md) · [fa](fa/19-onboarding.md) | Day 1 / week 1 / month 1 path for a new engineer, with a check per step; how knowledge is handed over |
| [20 — Runbooks](20-runbooks.md) · [fa](fa/20-runbooks.md) | Site down, false alerts, slowness, failed deploy, AI provider outage, disk, restore, adding a vehicle, SMS paging, rebuild from nothing |
| [21 — CSRF-exempt views](21-csrf-exempt-views.md) · [fa](fa/21-csrf-exempt-views.md) | Every @csrf_exempt view, how it authenticates, why it is safe; registry + Origin guard |
| [AGENTS — start here (agents and new engineers)](AGENTS.md) | Evidence rules, task-to-doc map, rules that are easy to break, how docs are kept true |
| [22 — Support chat](22-support-chat.md) · [fa](fa/22-support-chat.md) | Visitor widget, staff inbox, tokens, throttling, RBAC rollout, kill switch |
| [23 — Data layer](23-data-layer.md) · [fa](fa/23-data-layer.md) | Where every kind of data lives: PostgreSQL `kgkg`, per-car schemas in `kgkg_vec`, parts SQLite, RAG index |
| [24 — Integrations](24-integrations.md) · [fa](fa/24-integrations.md) | Metis, SMS, Turnstile, Cloudflare, GlitchTip, observability: config names and failure behaviour |
| [25 — Operations inventory](25-ops-inventory.md) · [fa](fa/25-ops-inventory.md) | Observed host state: units, timers, containers, directories, with evidence tags |
| [26 — Authentication and sessions](26-auth-and-sessions.md) · [fa](fa/26-auth-and-sessions.md) | Token lifetimes, login/OTP flow, single-session rule, admin gate, content protection |
| [27 — Open risks and decisions](27-open-risks-and-decisions.md) · [fa](fa/27-open-risks-and-decisions.md) | Register of known risks (backups, shared staging data, ...) with evidence and tracking |
| [28 — Team workflow](28-team-workflow.md) · [fa](fa/28-team-workflow.md) | GitHub/Jira/Trello/Slack roles, labels, issue-closing rule, daily reconcile |
| [29 — Environment variable reference](29-environment-reference.md) · [fa](fa/29-environment-reference.md) | Operational and tuning variables: default, consumer, meaning (no values) |
| [30 — AI assistant deep dive](30-ai-assistant-deep-dive.md) · [fa](fa/30-ai-assistant-deep-dive.md) | Request lifecycle, retrieval, scoring, scope gates, prompts, Metis, fallbacks, feedback, evaluation, capability status |
| [31 — Ops files and units reference](31-ops-files-reference.md) · [fa](fa/31-ops-files-reference.md) | Observability stack, log rotation, Umami, systemd units, offline RAG tools, security baselines |
| [32 — Testing, QA and verification](32-testing-and-qa.md) · [fa](fa/32-testing-and-qa.md) | Every test and gate: purpose, commands, CI, QA stack, gaps |
| [33 — System design](33-system-design.md) · [fa](fa/33-system-design.md) | Context, runtime topology, middleware, auth layers, async work, caches, failure scenarios |
| [34 — Data model reference](34-data-model-reference.md) · [fa](fa/34-data-model-reference.md) | Entity groups, ER overview, lifecycles, constraints; generated field-level [schema](generated/schema.md) |
| [35 — Support system](35-support-system.md) · [fa](fa/35-support-system.md) | Visitor chat, staff inbox, tickets, RBAC, outbox, retention, capability status |
| [36 — CI/CD and deployment](36-cicd-and-deployment.md) · [fa](fa/36-cicd-and-deployment.md) | Branch protection, workflows, promotion pipeline, environments, rollback |
| [37 — Requirements traceability](37-requirements-traceability.md) · [fa](fa/37-requirements-traceability.md) | FR/NFR to routes, modules, models, tests; checked by CI |
| [38 — Implementation and operational status matrix](38-implementation-status-matrix.md) · [fa](fa/38-implementation-status-matrix.md) | Per capability: code / deployed / enabled / operating evidence / tests / observed on production (2026-11-04) |
| [39 — Evaluation evidence guide](39-evaluation-evidence-guide.md) · [fa](fa/39-evaluation-evidence-guide.md) | Per subsystem: demonstrable capability, limits and reporting-ready wording |
| [40 — Documentation access guide](40-documentation-access-guide.md) · [fa](fa/40-documentation-access-guide.md) | GitHub links, directory map by category, which document for which report, downloadable package |
| [41 — Documentation coverage and backlog](41-documentation-coverage-and-backlog.md) · [fa](fa/41-documentation-coverage-and-backlog.md) | Honest coverage assessment, gaps G1-G18, further documents worth writing, owner questions |
| [42 — Frontend architecture reference](42-frontend-architecture.md) · [fa](fa/42-frontend-architecture.md) | Layers, auth path, security, state, API integration, component catalogue, workflows |
| [43 — Architecture and data-flow diagrams](43-architecture-diagrams.md) · [fa](fa/43-architecture-diagrams.md) | 10 Mermaid diagrams from the implementation (context, components, login, assistant, retrieval, ingestion, access, chat, observability, ERD) |
| [44 — Data lifecycle](44-data-lifecycle.md) · [fa](fa/44-data-lifecycle.md) | Per data class: collection, storage, access, retention, deletion, backup; evidence-based backup status; undefined policies |
| [47 — Engineering follow-up register](47-engineering-followups.md) | Internal register of engineering/operations items (not documentation tasks), with status and evidence |
| [48 — Handoff](48-handoff.md) | Taking the project over cold: what a clone does not contain, what must be obtained from the owner, continuity gaps in order |
| [Persian user guide](manuals/fa/01-user-guide.md) · [Persian staff/admin guide](manuals/fa/02-staff-admin-guide.md) | Task-oriented manuals for company users and platform staff (Persian only) |
| [Persian index](fa/README.md) | Persian twins of the documents above and how they are kept in sync |
| [Generated inventory](generated/inventory.md) | Machine-generated list of modules, models, commands, env var names, routes, units; CI-checked |
| [ADR — Architecture decisions](adr/README.md) | Why the system is built this way: SQLite, local retrieval, containers, promotion, monitoring, docs-as-code |
| [CHANGELOG](CHANGELOG.md) | Dated log of shipped changes, newest first |

## Quick facts (re-verified 2026-11-04 against `origin/work` `8a380f6`; production head matched)

- **Production:** `https://kgtechvault.com` — single Ubuntu 24 host `103.75.197.155` (16 cores / 31 GB / 290 GB, 75% used).
- **Repo root on server:** `/opt/KGKG` (the production checkout; the applications run as containers built from it, [36](36-cicd-and-deployment.md)).
- **Backend:** Django 5.2.17, gunicorn 26 (3 gthread workers × 8 threads by default) on `:8000`, in a container.
- **Frontend:** Next.js 16.4.3 / React 19.2.4 (`next start`) on `:3000`, in a container, behind nginx 1.24.
- **Data:** 237 cars on 2026-11-03: 222 manual cars in PostgreSQL `kgkg_vec` (one schema per car), 15 parts-only cars as SQLite; portal data in
  PostgreSQL `kgkg`; unified RAG index `_rag/index.rag.db`. Details and caveats: [23 — Data layer](23-data-layer.md).
- **Branches:** work on `work` (PRs target it); `main` is the GitHub default and receives merges from `work`. Remote `github.com/mjsn800403/KGKG`.
- **Languages:** every reference document 00–37 has a Persian twin in [fa/](fa/README.md), kept in sync by `ops/governance/check_i18n.py`.
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
