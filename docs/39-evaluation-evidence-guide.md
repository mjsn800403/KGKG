# 39 — Evaluation evidence guide (claims that are safe to make)

Companion to [38 — implementation and operational status matrix](38-implementation-status-matrix.md). Persian version: [fa/39-evaluation-evidence-guide.md](fa/39-evaluation-evidence-guide.md).
For each subsystem: what can be **demonstrated today**, the **evidence**, how to **demonstrate it to an evaluator**, the **limits**, and **reporting-ready wording**. Evidence tags as in doc 38 (**[C]** code, **[P]** observed on production 2026-11-04, **[D]** second-hand).

## 39.1 Rules for external statements

1. Say "implemented" only for code at a named commit; say "operating" only for what doc 38 marks OP; say "deployed but not enabled" for DD.
2. Quote counts with their date (2026-11-04) and the word "logged"; never turn a count into a quality claim.
3. Do not state anything tagged [D] or [U] as fact. Do not state accuracy, hallucination rate or uptime percentages: none is measured in this repository.
4. Describe production as commit `8a380f6`; later commits on `work` are not deployed until a person promotes them.

## 39.2 Subsystems

### A. Portal, accounts and access control
- **Verified capability:** SMS-OTP login, per-company users, entitlement grants, one active session per account, origin guard, content shield; 9 companies and 36 users registered; latest login on the day of the check [P].
- **Evidence:** [26](26-auth-and-sessions.md), [06](06-permissions-rbac.md); tests `test_qa_auth.py`, `test_qa_access.py`, `test_shield.py`, `auth.spec.js`.
- **Demonstrate:** log in with a test account, show that a user without a grant gets no manual (HTTP 403), show a second login ending the first session.
- **Limits:** SMS delivery end to end is unverified (#24); admin second factor not forced; the shield deters copying, it does not prevent it.
- **Wording:** "The platform provides role- and entitlement-based access with SMS one-time-code login and single active session per account. It is in production use by 9 registered companies (36 users) as of 2026-11-04."

### B. Vehicle knowledge (manuals, parts, diagnostics)
- **Verified capability:** 237 vehicle records, 222 vehicle content schemas in PostgreSQL, 222 diagnostic sidecars, a parts catalog for 15 parts-only cars; 86,250 activity records [P].
- **Evidence:** [23](23-data-layer.md), [34](34-data-model-reference.md), [generated/schema.md](generated/schema.md), ADR-0007.
- **Demonstrate:** open a car's manual, run a search, open a diagnostic procedure.
- **Limits:** correctness of manual content is not automatically verified; OEM data licensing is open ([16](16-parts-catalog.md)).
- **Wording:** "Manual, wiring and diagnostic content for 222 vehicle variants is served from the platform's PostgreSQL store with per-company authorization."

### C. Specialised AI assistant (RAG)
- **Verified capability:** hybrid retrieval (vector + keyword + glossary) over a 6.8 GB index with BGE-M3 embeddings, served from PostgreSQL (pgvector, PG full-text) in production; deterministic diagnostic engine; grounding gate; LLM phrasing through Metis with bot fallback, and a no-LLM fallback; Persian→English query translation enabled. 63 exchanges logged (47 in the last 30 days), of which 14 stored as grounded and 10 as degraded [P].
- **Evidence:** [30](30-ai-assistant-deep-dive.md), [08](08-ai-assistant-rag.md), [17](17-evaluation.md); tests under `KG_backend/rag/test_*`.
- **Demonstrate:** ask a question about a pinned car; show cited sources; ask about an absent topic and show the refusal; show the degraded no-LLM answer path (staging only).
- **Limits:** reranker and query adapter are **off**; feedback data is minimal (11 ratings, 0 clicks, 0 pins); no automated answer-quality gate; the last offline evaluation runs are from 2026-09-07; "grounded" is a stored flag, not a correctness measure.
- **Wording:** "The assistant answers from the platform's own manuals using hybrid retrieval, refuses when evidence is absent, and degrades to extractive answers if the language model is unavailable. Retrieval quality has been evaluated offline on internal gold sets; production usage is early (63 logged exchanges)."

### D. Support and communication
- **Verified capability:** a ticket desk (7 requests stored) in production use; visitor chat, staff inbox, notification outbox and role enforcement are **implemented and deployed but disabled** with zero data [P].
- **Evidence:** [35](35-support-system.md), [22](22-support-chat.md); CI job `support-chat-e2e` (21 browser tests on a throwaway stack).
- **Demonstrate:** ticket flow on production; chat flow on the CI stack or staging, not production.
- **Limits:** five nightly E2E failures concern ticket UI behaviour; the privacy notice for chat is a draft; no SMS/e-mail has been sent through the outbox.
- **Wording:** "A ticket-based support channel is operating. A live-chat and notification subsystem has been built and is deployed in a disabled state pending operational readiness; it has not been used with customers."

### E. Data platform, backup and recovery
- **Verified capability:** PostgreSQL 16 with a 134 MB portal database and a 58 GB vehicle database; pre-deploy dumps and an hourly off-host snapshot of the portal database [P].
- **Evidence:** [23](23-data-layer.md), [11](11-operations-deployment.md), [27](27-open-risks-and-decisions.md) R1.
- **Limits:** the vehicle database and parts files are not in any verified backup; no WAL archiving; no restore drill.
- **Wording:** "Portal data is backed up hourly off-host. Backup coverage of the vehicle-content database is an open, documented risk."

### F. Delivery pipeline, deployment and operations
- **Verified capability:** CI with required checks (backend on PostgreSQL, frontend, security scans, images, governance), staging with gate and smoke, person-only promotion, containerised zero-gap deploy with rollback state; monitoring (Prometheus, Grafana provisioning, GlitchTip, Loki) running; timers for alerts and watchdog healthy [P].
- **Evidence:** [36](36-cicd-and-deployment.md), [11](11-operations-deployment.md), [25](25-ops-inventory.md), [31](31-ops-files-reference.md).
- **Demonstrate:** a PR with its checks; the staged-not-promoted record for `135aa78b7`; the monitoring targets page.
- **Limits:** nightly QA currently fails (51 passed / 6 failed / 17 skipped); staging isolation from production vehicle data is unverified; `xrdp` active on the host.
- **Wording:** "Changes reach production only through a gated pipeline and a deliberate human promotion step; a staged build exists that has not been promoted."

### G. Security
- **Verified capability:** TLS at nginx, security headers, rate limits, key-only SSH, firewall, fail2ban, env files restricted [P]; CSRF exemption registry and tests, content-protection tests, DAST run with 0 failures and 5 warnings [P].
- **Evidence:** [12](12-security.md), [18](18-security-hardening.md), [21](21-csrf-exempt-views.md).
- **Limits:** no external penetration test; admin second factor not enforced; remote-desktop service active; rate-limiter counters are per host.
- **Wording:** "Layered controls are in place and tested in CI and nightly scans; no independent penetration test has been performed."

### H. Requirements and traceability
- **Verified capability:** SRS FR-01..FR-30 and NFR-01..14, each mapped to code and tests; CI fails if a named test disappears.
- **Evidence:** [00](00-srs.md), [37](37-requirements-traceability.md), `ops/governance/check_srs_trace.py`.
- **Wording:** "Every stated requirement is traced to implementing modules and automated tests; the trace is machine-checked on each change."

## 39.3 Consistency rule between documents

If a runtime observation (doc 38, [P]) contradicts a source-code default or an older document, the **observation wins for what is deployed**, the **code wins for what the next release will do**, and the document is corrected with the date. Unresolved contradictions stay listed in doc 38 §38.7 and doc 27.
