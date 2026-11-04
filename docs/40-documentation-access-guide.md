# 40 — Documentation access guide

Persian version: [fa/40-documentation-access-guide.md](fa/40-documentation-access-guide.md). GitHub is the single source of truth; the downloadable package is a reproducible snapshot of it.
Base URL: `https://github.com/mjsn800403/KGKG/blob/work/` (branch `work`). Replace `blob/work` with `blob/<sha>` for a frozen view.

## 40.1 Entry points

| Purpose | Link |
|---|---|
| English index | [docs/README.md](https://github.com/mjsn800403/KGKG/blob/work/docs/README.md) |
| Persian index | [docs/fa/README.md](https://github.com/mjsn800403/KGKG/blob/work/docs/fa/README.md) |
| Agent / new-engineer entry point | [docs/AGENTS.md](https://github.com/mjsn800403/KGKG/blob/work/docs/AGENTS.md) |
| Status matrix (what is real today) | [docs/38-implementation-status-matrix.md](https://github.com/mjsn800403/KGKG/blob/work/docs/38-implementation-status-matrix.md) |
| Safe external claims | [docs/39-evaluation-evidence-guide.md](https://github.com/mjsn800403/KGKG/blob/work/docs/39-evaluation-evidence-guide.md) |
| Frontend architecture | [docs/42-frontend-architecture.md](https://github.com/mjsn800403/KGKG/blob/work/docs/42-frontend-architecture.md) |
| Architecture diagrams | [docs/43-architecture-diagrams.md](https://github.com/mjsn800403/KGKG/blob/work/docs/43-architecture-diagrams.md) |
| Data lifecycle and backup status | [docs/44-data-lifecycle.md](https://github.com/mjsn800403/KGKG/blob/work/docs/44-data-lifecycle.md) |
| Persian user guide | [docs/manuals/fa/01-user-guide.md](https://github.com/mjsn800403/KGKG/blob/work/docs/manuals/fa/01-user-guide.md) |
| Persian staff/admin guide | [docs/manuals/fa/02-staff-admin-guide.md](https://github.com/mjsn800403/KGKG/blob/work/docs/manuals/fa/02-staff-admin-guide.md) |
| Documentation coverage and gaps | [docs/41-documentation-coverage-and-backlog.md](https://github.com/mjsn800403/KGKG/blob/work/docs/41-documentation-coverage-and-backlog.md) |
| Engineering follow-up register | [docs/47-engineering-followups.md](https://github.com/mjsn800403/KGKG/blob/work/docs/47-engineering-followups.md) |

## 40.2 Directory map by category

| Category | English | Persian twin |
|---|---|---|
| SRS and requirements | [00-srs](https://github.com/mjsn800403/KGKG/blob/work/docs/00-srs.md), [37-requirements-traceability](https://github.com/mjsn800403/KGKG/blob/work/docs/37-requirements-traceability.md) | `docs/fa/00-srs.md`, `docs/fa/37-…` |
| Architecture and design | [43-architecture-diagrams](https://github.com/mjsn800403/KGKG/blob/work/docs/43-architecture-diagrams.md), [42-frontend-architecture](https://github.com/mjsn800403/KGKG/blob/work/docs/42-frontend-architecture.md), [02-architecture](https://github.com/mjsn800403/KGKG/blob/work/docs/02-architecture.md), [33-system-design](https://github.com/mjsn800403/KGKG/blob/work/docs/33-system-design.md), [01-overview](https://github.com/mjsn800403/KGKG/blob/work/docs/01-overview.md), [04-backend-reference](https://github.com/mjsn800403/KGKG/blob/work/docs/04-backend-reference.md), [07-frontend](https://github.com/mjsn800403/KGKG/blob/work/docs/07-frontend.md), [09-realtime-sse](https://github.com/mjsn800403/KGKG/blob/work/docs/09-realtime-sse.md) | same file name under `docs/fa/` |
| AI assistant and RAG | [30-ai-assistant-deep-dive](https://github.com/mjsn800403/KGKG/blob/work/docs/30-ai-assistant-deep-dive.md), [08-ai-assistant-rag](https://github.com/mjsn800403/KGKG/blob/work/docs/08-ai-assistant-rag.md), [17-evaluation](https://github.com/mjsn800403/KGKG/blob/work/docs/17-evaluation.md) | same |
| Support and communication | [35-support-system](https://github.com/mjsn800403/KGKG/blob/work/docs/35-support-system.md), [22-support-chat](https://github.com/mjsn800403/KGKG/blob/work/docs/22-support-chat.md) | same |
| Databases and schemas | [44-data-lifecycle](https://github.com/mjsn800403/KGKG/blob/work/docs/44-data-lifecycle.md), [34-data-model-reference](https://github.com/mjsn800403/KGKG/blob/work/docs/34-data-model-reference.md), [23-data-layer](https://github.com/mjsn800403/KGKG/blob/work/docs/23-data-layer.md), [03-data-model](https://github.com/mjsn800403/KGKG/blob/work/docs/03-data-model.md), [15-vehicle-schema](https://github.com/mjsn800403/KGKG/blob/work/docs/15-vehicle-schema.md), generated [schema](https://github.com/mjsn800403/KGKG/blob/work/docs/generated/schema.md) | same (generated files are English only) |
| API | [05-api-reference](https://github.com/mjsn800403/KGKG/blob/work/docs/05-api-reference.md), generated [routes](https://github.com/mjsn800403/KGKG/blob/work/docs/generated/routes.md), [openapi.yaml](https://github.com/mjsn800403/KGKG/blob/work/docs/openapi.yaml) | `docs/fa/05-…` |
| Testing, QA, E2E, performance | [32-testing-and-qa](https://github.com/mjsn800403/KGKG/blob/work/docs/32-testing-and-qa.md), [17-evaluation](https://github.com/mjsn800403/KGKG/blob/work/docs/17-evaluation.md) | same |
| Security | [12-security](https://github.com/mjsn800403/KGKG/blob/work/docs/12-security.md), [18-security-hardening](https://github.com/mjsn800403/KGKG/blob/work/docs/18-security-hardening.md), [21-csrf-exempt-views](https://github.com/mjsn800403/KGKG/blob/work/docs/21-csrf-exempt-views.md), [26-auth-and-sessions](https://github.com/mjsn800403/KGKG/blob/work/docs/26-auth-and-sessions.md), [06-permissions-rbac](https://github.com/mjsn800403/KGKG/blob/work/docs/06-permissions-rbac.md) | same |
| CI/CD and DevOps | [36-cicd-and-deployment](https://github.com/mjsn800403/KGKG/blob/work/docs/36-cicd-and-deployment.md), [11-operations-deployment](https://github.com/mjsn800403/KGKG/blob/work/docs/11-operations-deployment.md), [28-team-workflow](https://github.com/mjsn800403/KGKG/blob/work/docs/28-team-workflow.md) | same |
| Infrastructure, monitoring, operations | [25-ops-inventory](https://github.com/mjsn800403/KGKG/blob/work/docs/25-ops-inventory.md), [31-ops-files-reference](https://github.com/mjsn800403/KGKG/blob/work/docs/31-ops-files-reference.md), [20-runbooks](https://github.com/mjsn800403/KGKG/blob/work/docs/20-runbooks.md), [29-environment-reference](https://github.com/mjsn800403/KGKG/blob/work/docs/29-environment-reference.md) | same |
| Risks, decisions, evidence | [27-open-risks-and-decisions](https://github.com/mjsn800403/KGKG/blob/work/docs/27-open-risks-and-decisions.md), [adr/](https://github.com/mjsn800403/KGKG/tree/work/docs/adr), [38](https://github.com/mjsn800403/KGKG/blob/work/docs/38-implementation-status-matrix.md), [39](https://github.com/mjsn800403/KGKG/blob/work/docs/39-evaluation-evidence-guide.md), [CHANGELOG](https://github.com/mjsn800403/KGKG/blob/work/docs/CHANGELOG.md) | 38, 39 have twins |
| Generated references | [generated/](https://github.com/mjsn800403/KGKG/tree/work/docs/generated): `inventory.md`, `schema.md`, `routes.md` | — |
| Persian documents | [docs/fa/](https://github.com/mjsn800403/KGKG/tree/work/docs/fa) | — |

## 40.3 Which document for which report

| Reporting need | Use |
|---|---|
| "What does the system do and is it live?" | 38, then 39 |
| Formal requirements and proof they are implemented | 00, 37 |
| Technical architecture for reviewers | 02, 33, 34 |
| AI quality, limits, evaluation method | 30, 17, 39 §C |
| Security posture | 12, 18, 39 §G |
| Delivery process and controls | 36, 11 |
| Honest list of gaps and risks | 38 §38.7, 27 |
| Onboarding a new engineer | `docs/AGENTS.md`, 19 |

## 40.4 Downloadable package

`ops/governance/build_docs_package.py` builds `kgkg-docs-<commit-date>-<sha7>.zip` from git (all English and Persian documents, both indexes, generated references, ADRs, `openapi.yaml`, `OWNERS.toml`, `i18n.toml`, root `AGENTS.md`, `MANIFEST.json` with a SHA-256 per file, and `README-PACKAGE.txt`). The same commit always produces the same bytes. CI job `governance` builds it and uploads it as the workflow artifact `kgkg-docs-package` (retained 90 days); the build refuses to run if a secret-like pattern appears. It contains no database content, credentials or customer data.
Rebuild locally: `python3 ops/governance/build_docs_package.py --commit <sha>`.
