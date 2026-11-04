# 41 — Documentation coverage assessment and remaining-work backlog

Persian version: [fa/41-documentation-coverage-and-backlog.md](fa/41-documentation-coverage-and-backlog.md). Assessed 2026-11-04 against `origin/work` after PR #91; **updated the same day after the priority documents 42-44, the Persian manuals and the engineering register [47](47-engineering-followups.md) were written** (rows below carry their new status). Production facts come from [38](38-implementation-status-matrix.md).

## 41.1 Honest summary

- The library has 41 reference documents with Persian twins, three generated references, 7 ADRs and machine checks (freshness, i18n stamps, SRS trace, inventory ratchet). **These checks prove names are mentioned, not that behaviour is explained.** The inventory ratchet is satisfied by a single mention of a model, command or env var.
- **Breadth is good; depth is uneven.** Backend structure, data model, support system, CI/CD, requirements trace and production status are covered at implementation level. The frontend, the pricing/plans flow, the admin observability screens, end-user and staff procedures, data lifecycle and diagrams are thin or absent.
- **Realistic completeness estimate (judgement, not a measurement):** before the priority documents roughly 70–75 %; after frontend (42), diagrams (43), data lifecycle (44) and the Persian manuals, roughly 80–85 % of what an external evaluator or a new engineer would want is present and defensible. The remainder is listed below. Nothing here supports a "100 % complete" claim.
- **Correction:** an earlier version of this document said no full ERD existed. That was wrong: the generated [schema](generated/schema.md) contains an entity-relationship diagram of every declared foreign key; the count of diagrams only covered hand-written documents.
- Method: the 2026-11-04 scan counted how often each backend module, management command, frontend file (≥120 lines), `ops/` file and key term appears in `docs/*.md`, then read the flagged items. A low count is a *lead*, not proof; each row below was checked against the source.

## 41.2 Coverage matrix (by area)

| Area | Where documented | Depth | Verdict |
|---|---|---|---|
| Requirements, SRS, traceability | [00](00-srs.md), [37](37-requirements-traceability.md) | machine-checked | Good |
| Architecture, system design | [02](02-architecture.md), [33](33-system-design.md) | 3 diagrams in 33 | Good; few sequence/data-flow diagrams |
| Backend modules, commands | [04](04-backend-reference.md), [33](33-system-design.md) | names + purpose | Partial: 10 modules and 7 commands have one-line coverage |
| Data model, schemas | [03](03-data-model.md), [34](34-data-model-reference.md), [generated/schema.md](generated/schema.md) | 49 models; one `erDiagram` | Good; no full ERD, no lifecycle/retention matrix |
| API | [05](05-api-reference.md), [generated/routes.md](generated/routes.md), [openapi.yaml](openapi.yaml) | routes + rate limits | Good; per-endpoint validation rules not enumerated |
| Auth, sessions, RBAC | [06](06-permissions-rbac.md), [26](26-auth-and-sessions.md), [21](21-csrf-exempt-views.md) | detailed | Good |
| AI assistant / RAG | [08](08-ai-assistant-rag.md), [30](30-ai-assistant-deep-dive.md), [17](17-evaluation.md) | detailed | Good; production backend facts only in 30/38 (see §41.4) |
| Support and communication | [22](22-support-chat.md), [35](35-support-system.md) | backend detailed | Partial: chat front end not described |
| Frontend | [07](07-frontend.md), [13](13-guidance-system.md) | routes + structure | **Thin** (§41.3 G2) |
| Pricing, plans, purchase | scattered mentions | — | **Undocumented** (G1) |
| Admin observability screens | [20](20-runbooks.md), `insights.py` mentions | — | **Thin** (G3) |
| Vehicle manuals, parts pipelines | [15](15-vehicle-schema.md), [16](16-parts-catalog.md), [23](23-data-layer.md) | good | Good; crawler operating procedure thin |
| Testing, QA | [32](32-testing-and-qa.md) | detailed | Good; nightly failures unexplained (engineering) |
| CI/CD, deployment, rollback | [36](36-cicd-and-deployment.md), [11](11-operations-deployment.md), [20](20-runbooks.md) | detailed | Good |
| Monitoring, alerts | [25](25-ops-inventory.md), [31](31-ops-files-reference.md) | inventory | Partial: dashboards and alert thresholds not described (G11) |
| Security, privacy, retention | [12](12-security.md), [18](18-security-hardening.md) | controls | Partial: no consolidated data-retention/privacy matrix (G7) |
| Production reality | [38](38-implementation-status-matrix.md), [39](39-evaluation-evidence-guide.md) | observed 2026-11-04 | Good, dated; ages quickly |
| End-user / staff manuals | — | — | **Absent** (G10) |

## 41.3 Gaps (each checked against source)

Legend — Class: **U** undocumented · **P** partial, needs depth · **O** outdated/contradictory · **V** implemented, production status unverified · **R** needs engineering, not documentation · **X** planned (write as proposal). Priority C/H/M/L; effort S/M/L; Dep = evidence needed beyond the repo.

| ID | Component (status) | Class | Existing coverage | Missing | Evidence (source) | Deliverable | Pri | Eff | Dep | Next action |
|---|---|---|---|---|---|---|---|---|---|---|
| G1 | Plans, pricing and quote engine | U — **deprioritised by the owner (2026-11-04)** | — | — | `kg_frontend/src/lib/pricing.js`, `app/purchase/PlansPage.tsx` | — | L | M | business owner | not scheduled |
| G2 | Frontend routes, components, state, workflows | P→**done** | [07](07-frontend.md) + new [42](42-frontend-architecture.md) | remaining: per-section detail of the 3,578-line `admin/page.jsx`, landing-page behaviour, guidance content registry | `kg_frontend/src/**` | — | L | M | none | optional |
| G3 | Admin observability screens: audit trail, AI cost, search insights, adoption funnel (implemented) | P | `audit.py`/`insights.py` named in [03](03-data-model.md), [20](20-runbooks.md); "AI cost" and "funnel" **0 mentions** | what each screen shows, metrics' definitions, retention of audit rows | `components/AdminInsights.jsx` (700 lines), `api/insights.py`, `api/audit.py` (340 lines) | new section in 10 or new doc "Admin analytics screens" | M | M | prod data only for sizes | do now |
| G4 | Support chat front end | P→**done** | [22](22-support-chat.md), [35](35-support-system.md), [42 §42.6](42-frontend-architecture.md), [43 §43.8](43-architecture-diagrams.md) | — | `kg_frontend/src/support-chat/**` | — | — | — | — | none |
| G5 | 10 thin backend modules (`audit`, `notify`, `reads`, `originguard`, `behavior`, `listing`, `signals`, `frm`, `safepath`, `apps`) | P | one-line rows in [04](04-backend-reference.md)/[33](33-system-design.md) | behaviour, inputs, failure modes | `KG_backend/api/<module>.py` | expand 04 | M | M | none | do now |
| G6 | 7 management commands with one mention each: `backfill_team`, `build_reranker_trainset`, `build_vehicle_schema`, `check_secret_age`, `optimize_index`, `seed_kb_faq`, `sync_org_reports` | P | [04](04-backend-reference.md) list | arguments, when to run, side effects, safety, which are cron-driven | `KG_backend/api/management/commands/` | "management command reference" section/doc | M | S | which run on the server [P] needs a read-only check | do now (repo part) |
| G7 | Data lifecycle, retention, privacy | P→**done for implemented behaviour** | new [44](44-data-lifecycle.md) (per data class: collection → deletion → backup, evidence-based) | owner policy decisions (retention periods, erasure, export) are **pending by design**, listed in 44 §44.9 | `api/models.py`, commands, `ops/observability/` | decisions, then code | H | — | **owner** | Q3 |
| G8 | Diagrams | P→**done** | new [43](43-architecture-diagrams.md): 10 diagrams (context, components, login, assistant, retrieval, ingestion, access, support chat, observability, domain ERD) + generated full ERD + existing 33/35/36 | per-endpoint sequence diagrams only if needed | — | — | L | S | none | optional |
| G9 | Documents contradicted by production observation | O | 23, 25 and 29 were **corrected in the same change as this document**; still to review for the same facts: [08](08-ai-assistant-rag.md), [11](11-operations-deployment.md), [32](32-testing-and-qa.md) (nightly QA currently failing; observed timers/databases) | finish the review of 08, 11, 32 | [38](38-implementation-status-matrix.md) §38.3–38.6 | corrections in place (EN+FA) | H | S | none | do next |
| G10 | End-user and staff procedures in Persian | U→**done (text)** | new Persian-only manuals: [user guide](manuals/fa/01-user-guide.md), [staff/admin guide](manuals/fa/02-staff-admin-guide.md) | screenshots; a quick-reference card; owner review of wording | UI + backend behaviour | — | M | M | owner review | review |
| G11 | Monitoring: four Grafana dashboards, alert rules, thresholds (observed running) | P | [25](25-ops-inventory.md), [20](20-runbooks.md) | panel/query list, each alert rule: condition, severity, action | `ops/observability/provisioning/dashboards/json/*.json` (0 mentions), `api/alert_rules.py`, `ops/observability/*` | new doc "Monitoring and alert reference" | M | M | Grafana view for rendered state [U] | do now (repo part) |
| G12 | Parts/crawler data pipelines: `tis_crawler`, `partsouq_crawler`, `partsouq_build`, `sst`, `labortimes` | P | [16](16-parts-catalog.md), [23](23-data-layer.md) (3–7 mentions each) | step-by-step ingestion runbook, data sources and licensing, outputs | `api/tis_crawler.py` (333), `sst.py` (326), `labortimes.py` (232), `partsouq_*.py` | runbook section in 16/20 | M | M | licensing = owner (Q5) | partly now |
| G13 | RAG internals at production: `pgvec.py`, `pgfts.py`, `evalreport.py` (2 mentions each); index counts | P | [30](30-ai-assistant-deep-dive.md) | pgvector schema, HNSW parameters, load procedure, hybrid SQL, how SQLite fallback triggers; blob/occurrence counts | `api/rag/pgvec.py`, `pgfts.py`, `ops/rag/*` | extend 30 | H | M | **prod read-only counts** [U] | repo part now; counts need prod |
| G14 | Test inventory → requirement/feature mapping beyond SRS-named files (113 backend, 21 frontend, 8 QA test files, plus `api/rag/`) | P | [32](32-testing-and-qa.md) | which test proves which behaviour; how to run each suite locally; known flaky/skipped | `KG_backend/api/test_*.py`, `api/rag/test_*.py`, `qa/**` | "test catalogue" appendix | M | L | none | later |
| G15 | Nightly E2E failures | R | moved to [47](47-engineering-followups.md) E1 | — | — | — | — | — | — | engineering |
| G16 | Backup scope, restore drill, `xrdp` | R | moved to [47](47-engineering-followups.md) E2–E4; evidence in [44 §44.8](44-data-lifecycle.md) | — | — | — | — | — | — | engineering / owner |
| G17 | Support chat privacy notice, delivery, outbox | V/X | [35](35-support-system.md); tracked as [47](47-engineering-followups.md) E9 | — | — | — | — | — | **owner** | decision |
| G18 | Staging isolation, off-host backup scope, `KG_PG_NAME`, SMTP status, Grafana rendering | V | stated as unverified in 38 | — (already correctly documented; **not** a documentation gap) | — | close by a read-only check when authorised | M | S | prod | optional |

## 41.4 What is correctly documented and must not be reopened

Production unknowns already recorded as unknown in doc 38 (§38.7–38.8) are not documentation gaps. The org-graph, support RBAC, CI/CD, environment variables, schema, routes and SRS trace are documented to implementation level and machine-checked.

## 41.5 Additional documents worth producing

| # | Document | Why / who | Content and evidence | Needs | Produce now? | Home |
|---|---|---|---|---|---|---|
| D1 | Data lifecycle and privacy matrix (G7) | external evaluators, management, DPO-type reviewers | per data class: store, retention, purge job, backup, access role; from `models.py`, commands, [38](38-implementation-status-matrix.md) | owner decisions on retention targets | repo part yes | new doc 42 |
| D2 | Plans, pricing and entitlements (G1) | management, sales, finance | `pricing.js` rules, request flow, grants | price list, intent | after Q1 | new doc |
| D3 | ERD + key sequence diagrams (G8) | engineers, evaluators | from `schema.md` and flows in 26/30/35 | none | yes | inside 34, 26, 30, 35 |
| D4 | Monitoring and alert reference (G11) | on-call, evaluators | dashboards JSON, `alert_rules.py` | Grafana rendering check (optional) | yes | new doc |
| D5 | Management command and job reference (G6) | operators, agents | commands + timers observed in [38](38-implementation-status-matrix.md) | none for repo part | yes | section in 04 |
| D6 | Frontend route/component/state reference (G2, G4) | new engineers | `kg_frontend/src/**` | none | yes | extend 07/22 |
| D7 | Test catalogue and local run guide (G14) | QA, agents | all test files, commands | none | yes (large) | appendix to 32 |
| D8 | Persian end-user and staff manuals (G10) | customers, support staff | task flows, screenshots | audience decision; screenshots | after Q4 | separate (not engineering set) |
| D9 | Evaluation evidence pack: sample run outputs of gold-set evaluation and E2E reports | external evaluators | `qa/eval`, `api/evalsuite` outputs | permission to run on staging, or read-only copies of existing runs [U] | blocked | next to 38 |
| D10 | Integration specifications (Metis, SMS, e-mail, Cloudflare, GlitchTip) | engineers | [24](24-integrations.md) exists; add request/response contracts | provider contract details | partly | extend 24 |

Not recommended: more per-module "reference" pages that restate code without new facts; extra translations of generated files.

## 41.6 Prioritised backlog

**Done:** G2, G4, G7 (implemented behaviour), G8, G10 (text), G9 for docs 23/25/29.
**Immediately actionable (no new evidence):** finish G9 for 08/11/32 → G6/G5 command and module reference → G3 admin analytics screens → G11 monitoring reference → G13 repo part → G14 test catalogue.
**Blocked on an owner answer:** G12 licensing (Q5), G17 (Q2), retention decisions in 44 §44.9 (Q3), wording review of the manuals (Q4). G1 is deprioritised.
**Blocked on production evidence (needs authorised read-only access):** G13 counts, company-server and provider backup scope (E2), G18 items.
**Engineering, not documentation:** everything in [47](47-engineering-followups.md).

## 41.7 Questions for the owner (they change what can be claimed)

1. **Pricing (G1):** is the plans/pricing page live and are the prices in `pricing.js` current? Is payment still offline? *Why:* a report must not describe commercial terms from stale code.
2. **Support chat and notifications (G17):** is activation planned, and who owns the privacy notice and SMS/e-mail providers? *Why:* decides whether to describe them as a roadmap item or as shelved.
3. **Retention (G7):** what retention periods apply to chat logs, activity logs, audit rows, tickets and assistant queries? *Why:* the code does not state policy; inventing it would be wrong.
4. **Manuals (G10):** do you want Persian end-user/staff manuals, and for which audience first? *Why:* effort is large and screenshots are needed.
5. **Parts data (G12):** may external reports state the sources and licensing of OEM parts data? *Why:* doc 16 lists licensing as unresolved.
6. **Evaluation evidence (D9):** may an evaluation run be executed on staging, or are earlier results available? *Why:* current evidence is only the 2026-09-07 offline runs.
7. **Backups (E2/E3):** please give read-only access to, or a summary from, (a) the company backup server's job definitions for this host and (b) the hosting-provider panel: what is backed up (is `kgkg_vec` included?), how often, how long kept, last success. *Why:* until then the strongest honest statement is that the arrangements exist but their coverage of the vehicle-content database is unverified.
8. **Remote desktop (E4):** is `xrdp` intentionally enabled on the production host? *Why:* decides whether it is a risk to disclose or a deliberate tool.
