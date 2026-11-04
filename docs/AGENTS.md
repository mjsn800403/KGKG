# Agent and engineer entry point

Read this file first, then only the documents your task needs. It is written for AI coding agents
and new engineers who must become useful without re-reading the repository, the server and the
chat history. It is a map and a set of rules, not a second copy of the docs.

**Verified against:** `origin/work` @ `8a380f6` (2026-11-04). Anything marked **[U]** is unverified.

## 1. Evidence rules (how to read every document here)

| Tag | Meaning | Trust it for |
|---|---|---|
| **[C]** | Read from code or config in this repository | Behaviour. Re-check the file if you are about to change it |
| **[S]** | Observed on the production host, read-only, on the date given | The state of production on that date only |
| **[D]** | Taken from Slack, Jira, GitHub or a session transcript | A claim somebody made; verify before acting |
| **[U]** | Not verified | Nothing. Treat as a question |

Order of authority when sources disagree: **code and config > `docs/generated/inventory.md` >
reference docs (00-27) > ADRs (the decision, not today's state) > `CHANGELOG.md` > `docs/superpowers/`
(dated design records) > Slack, Jira, memory files.** A document's `reviewed` date in `OWNERS.toml`
says someone looked at it, not that it is right; the drift check (section 5) is what keeps facts honest.

## 2. What this system is (ten lines)

- KGtechvault: Persian (fa, RTL) portal selling per-company subscriptions to Toyota/Lexus service
  manuals, with an assistant that answers only from the manuals a company bought. [C] `01-overview.md`
- Backend: Django 5.2 in `KG_backend/api/` (one app). Frontend: Next.js 16 / React 19 in `kg_frontend/`.
- Metadata DB: PostgreSQL 16 `kgkg` in production; per-vehicle manual content: PostgreSQL schemas in
  database `kgkg_vec` for 222 cars plus SQLite files for parts-only cars. **This contradicts older
  statements of "one read-only SQLite per vehicle"; see `23-data-layer.md`.** [S 2026-11-03, C]
- Retrieval, ranking and diagnostics are deterministic and local; the LLM (Metis) only phrases the
  answer, with a no-LLM fallback. [C] ADR 0002, `08-ai-assistant-rag.md`
- One physical host runs production, staging, QA and observability. [D] GitHub #25
- Production is changed only by a person running `kgkg-promote <sha>`. Never automate or run it. [C] ADR 0004

## 3. Task to document map

| If you are about to... | Read first | Then verify in code |
|---|---|---|
| Understand the whole system | `01-overview.md`, `02-architecture.md`, this file | `docs/generated/inventory.md` |
| Touch car content, search, `has_manual`/`has_parts`, anything reading `Database_warehouse` | `23-data-layer.md`, ADR 0001 + 0007 | `api/cardb.py`, `api/cardb_pg.py` |
| Change the assistant, retrieval, prompts, grounding | `08-ai-assistant-rag.md`, `17-evaluation.md`, `24-integrations.md` | `api/rag/`, `kg_frontend/src/app/api/chat/route.js` |
| Change login, sessions, OTP, admin gate, roles | `06-permissions-rbac.md`, `26-auth-and-sessions.md`, `12-security.md` | `api/portal.py`, `api/admin_auth.py`, `api/access.py` |
| Add or change an endpoint | `05-api-reference.md`, `21-csrf-exempt-views.md` | `api/urls.py`; `docs/openapi.yaml` is test-enforced |
| Touch the support chat (visitor widget, staff inbox) | `22-support-chat.md`, the specs under `docs/superpowers/specs/2026-11-0*` | `api/support_chat/` |
| Change a model or write a migration | `03-data-model.md` | `api/models.py`, `ops/deploy/check_migrations.py` (additive only) |
| Deploy, stage, roll back, or debug production | `11-operations-deployment.md`, `20-runbooks.md`, `25-ops-inventory.md` | `ops/deploy/*.sh`, `.github/workflows/ci.yml` |
| Add an alert or touch monitoring | `11-operations-deployment.md` (alerts), `25-ops-inventory.md` | `api/alert_rules.py`, `ops/observability/` |
| Backups, restore, data loss questions | `27-open-risks-and-decisions.md` first, then `11` section 11.6 | do not assume a backup exists; see risk R1 |
| Work with Jira, Slack, Trello, issue closing | `28-team-workflow.md` | `.github/pull_request_template.md` |
| Look up any environment variable (meaning, default, consumer) | `29-environment-reference.md` | the `os.environ`/`_env_*` line it cites |
| Understand or change the assistant end to end (retrieval, scoring, prompts, Metis, fallbacks, evaluation) | `30-ai-assistant-deep-dive.md`, then `08`, `17` | `api/rag/retrieve.py`, `api/rag/service.py`, `kg_frontend/src/app/api/chat/route.js` |
| Touch observability, log rotation, Umami, systemd units, offline RAG tools, security baselines | `31-ops-files-reference.md` | the file it cites under `ops/` |
| Decide how to verify a change; understand CI, QA stack, E2E, load, mutation tests | `32-testing-and-qa.md` | `.github/workflows/ci.yml`, `qa/` |
| Understand the overall design, runtime topology, middleware, failure scenarios | `33-system-design.md` | `ops/nginx/kgkg.conf`, `KG_backend/KG_backend/settings.py` |
| Read or change models, constraints, relationships | `34-data-model-reference.md`, then generated `schema.md` | `api/models.py`; regenerate with `gen_schema.py` |
| Work on support chat, RBAC, outbox, retention (deep) | `35-support-system.md`, `22-support-chat.md` | `api/support_chat/`, `api/notifications/` |
| Understand CI jobs, branch protection, promotion, rollback | `36-cicd-and-deployment.md`, `11`, `20` | `.github/workflows/ci.yml`, `ops/deploy/` |
| Find which code/tests implement a requirement | `37-requirements-traceability.md`, `00-srs.md` | `ops/governance/check_srs_trace.py` |
| Know what is really implemented / enabled in production (before any external claim) | `38-implementation-status-matrix.md`, `39-evaluation-evidence-guide.md` | evidence tags [P] dated 2026-11-04 |
| Find a document by category, or get the downloadable package | `40-documentation-access-guide.md` | `ops/governance/build_docs_package.py` |
| Know what is still undocumented / what to write next | `41-documentation-coverage-and-backlog.md` | gap IDs G1-G18 |
| Add an env var, command, model, module, ops file | `docs/generated/inventory.md` rules in section 5 | run `python3 ops/governance/gen_inventory.py` |

## 4. Rules that are easy to break

1. Branch from `origin/work`, open the PR to `work`. `main` is the GitHub default branch but is behind
   `work` in content and only receives a merge from it. [S 2026-11-04] Both are protected.
2. A PR title/body must reference an issue (`ops/governance/check_traceability.py`). A bare `#123` in a
   code fence does not count. PRs to `work` do not auto-close issues even with `fixes #N` (only the
   default branch does); close them by hand. [D]
3. Docs ship in the same commit as the behaviour change, plus one dated line at the top of `CHANGELOG.md`.
   `*.md` is globally gitignored: use `git add -f`.
4. Migrations are additive only. Authorization (`allowed_cars`) is enforced inside retrieval and cache keys.
5. Never read, print, copy or commit `.env.prod`, `khadamat.pem`, tokens or keys. Record variable
   **names**, never values.
6. Do not deploy, restart services, edit `/opt/KGKG`, or run data-changing commands on the host without
   the owner's explicit go-ahead for that action. Reading is allowed when the task needs it.
7. Do not trust a green deploy or an HTTP 200 as proof of health: check container health, GlitchTip and metrics.

## 5. Keeping the docs true (change-triggered, not date-triggered)

- `docs/generated/inventory.md` is produced from the source (`ops/governance/gen_inventory.py`): backend modules, models, management commands,
  env var names, frontend routes, systemd units, `ops/` files, migrations, CI jobs. CI (job `governance`) fails when it is stale.
- `docs/generated/doc-debt.json` records items that are still undocumented. It must match the code, but **what binds is the copy on the target
  branch**: on a pull request CI fails for any undocumented item that is not already in the base branch's file, even if you regenerated yours.
  The way through is to describe the item in the matching reference doc, then run `python3 ops/governance/gen_inventory.py`. The only exception
  route is an entry with a reason in `docs/generated/doc-debt-exceptions.json` (CODEOWNERS: the repository owner).
- `ops/governance/check_docs_freshness.py` still requires an owner and a review date per document. Moving a
  date is not a verification. Move it only after the document's facts were re-checked against the code.
- When you change behaviour, update (a) the reference doc named in section 3, (b) the CHANGELOG line, and
  (c) any `[S]`/`[D]` claim your change makes false. If you cannot verify a claim, write **[U]**, do not delete the doubt.
- **Persian twins.** Documents listed in `docs/i18n.toml` have a Persian twin in `docs/fa/` whose first line stamps the English revision it matches. Change the English file and CI fails until you update the twin and run `python3 ops/governance/check_i18n.py --stamp <file>`. Do not stamp without actually updating the Persian text.
- At the end of any session that made a decision, write it down in the PR (ADR if it sets a standing
  rule). Chat history and memory files are not a place of record.

## 6. Quick re-verification commands (read-only)

```bash
git fetch && git log origin/work -5 --oneline          # what is current
gh pr list -R mjsn800403/KGKG; gh issue list -R mjsn800403/KGKG
python3 ops/governance/gen_inventory.py --check --base-ref origin/work --require-base   # docs vs code drift (env KG_DOC_BASE_REF sets the default base ref)
python3 ops/governance/check_docs_freshness.py --docs docs
python3 ops/governance/check_i18n.py               # Persian twins vs English sources (list: docs/i18n.toml)
python3 ops/governance/gen_schema.py --check       # generated model schema is current
python3 ops/governance/gen_routes.py --check       # generated route table (from openapi.yaml + decorators) is current
python3 ops/governance/check_srs_trace.py          # SRS tests exist, every FR/NFR is in doc 37
```

Production checks go through the saved `kgtechvault` SSH connection (host in `11-operations-deployment.md`):
`git rev-parse --short HEAD`, `git status --porcelain`, `docker ps` in `/opt/KGKG`.
