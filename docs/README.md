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
| [CHANGELOG](CHANGELOG.md) | Dated log of shipped changes, newest first |

## Quick facts (verified 2026-07-15)

- **Production:** `http://103.75.197.155/` — single Ubuntu 24 host (16 cores / 31 GB / 290 GB).
- **Repo root on server:** `/opt/KGKG` (this is the deployed working copy AND the git repo).
- **Backend:** Django 5.2.15, gunicorn (3 gthread workers × 8 threads) on `:8000`.
- **Frontend:** Next.js 16.2.9 / React 19.2.4 (`npm run start`) on `:3000`, behind nginx 1.24.
- **Data:** 38 servable vehicles (21 GB warehouse + 9.8 GB static assets), one SQLite DB per
  vehicle; main relational DB `db.sqlite3` (WAL); unified RAG index `_rag/index.rag.db`.
- **Branch:** `rag-db-improvements` (ahead of `main`); remote `github.com/mjsn800403/KGKG`.

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

## Reading order for a new maintainer

1. `01-overview.md` then `02-architecture.md` — mental model.
2. `06-permissions-rbac.md` — nearly every bug/feature touches authorization.
3. The doc matching your task area.
4. `11-operations-deployment.md` **before touching the server** — deploys have sharp edges
   (SQLite WAL, detached pipeline worker, nginx SSE location, `*.md` gitignore).
