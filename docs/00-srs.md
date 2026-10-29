# 00 — Software Requirements Specification (SRS)

**Product:** KGtechvault (KGKG) · **Version:** 1.0.0 (`VERSION`) · **Status:** baseline, 2026-10-29
**Structure:** ISO/IEC/IEEE 29148 (stakeholder → system requirements), quality attributes per ISO/IEC 25010.

This document states *what* the system must do and how well. *How* lives in docs 01–15;
*proof* lives in the tests named in each row and in `audit-evidence/`. A requirement without
a verifying test is marked **(manual)** and says how it is checked instead.

Identifiers:

* `FR-xx` — functional requirements.
* `NFR-xx` — quality requirements.
* `RQ-xx` — the security and business rules already traced in
  `audit-evidence/01-requirements-and-traceability/TRACEABILITY.md`; they are referenced here, not repeated.

Keep IDs stable: retire a requirement by striking it through, never by reusing its number.

---

## 1. Purpose and scope

KGtechvault sells company subscriptions to official Toyota/Lexus service documentation for
Iranian after-sales businesses. Subscribers get:

* a Persian, right-to-left web portal for the original English manuals;
* an AI assistant that answers repair and diagnostic-code questions in Persian, grounded
  only in the manuals the company bought;
* self-service team management.

The vendor operates the platform from an admin console. See doc 01 for the narrative.

**In scope:** the web portal, admin console, backend API, RAG and diagnostic engines, the
ingestion pipeline, and the operations tooling in `ops/` and `qa/`.

**Out of scope:**

* the language model itself (Metis, an external service used only as a Persian phraser);
* payment processing;
* native mobile apps.

## 2. Stakeholders and actors

| Actor | Goal | Doc |
|---|---|---|
| Visitor | Learn what is covered, check a VIN, ask to buy | 01 |
| Portal user (seat) | Find the right procedure, spec or part for a car, fast, in Persian | 01, 07 |
| Company manager | Staff seats, delegate access, see team usage, ask the vendor for more | 01, 06 |
| Platform admin (vendor) | Provision companies, keep content and the service healthy | 01, 11 |
| Evaluator / auditor | Verify quality and security claims | `audit-evidence/` |

## 3. Constraints and assumptions

* **C-01:** single production host (Ubuntu 24, 16 cores, 31 GB RAM). Staging and QA share it. (doc 02, 11)
* **C-02:** relational data in SQLite (WAL); manuals as one read-only SQLite file per vehicle.
  (ADR-0001)
* **C-03:** the embedding model runs locally and offline (`HF_HUB_OFFLINE=1`); no request data
  leaves the host except to Metis (phrasing) and the SMS provider. (doc 08, 12)
* **C-04:** the user interface is Persian and right-to-left; manual content stays English.
  (doc 07, 14)
* **C-05:** production changes only through `kgkg-promote`. (ADR-0004)

---

## 4. Functional requirements

| ID | The system shall… | Actor | Verified by |
|---|---|---|---|
| FR-01 | accept a purchase request (vehicles, layers, company identity, seat plan) from a visitor and show it to the admin | Visitor, Admin | `test_purchase_flow.py` |
| FR-02 | let the admin turn an approved purchase into a company, its grants and its first users, who can then sign in | Admin | `test_purchase_flow.py`, RQ-11 |
| FR-03 | authenticate users by username + password with an SMS OTP second step, and recover accounts by SMS | Seat | `test_qa_auth.py`, `test_recover.py`, `test_sms_bodies.py`, E2E `auth.spec.js`, RQ-04 |
| FR-04 | keep one live session per account and revoke it server-side on logout | Seat | E2E `session.spec.js`, `test_security.py`, RQ-05 |
| FR-05 | list only the vehicles and document layers the user may open, with brand/model/year filtering | Seat | `test_qa_access.py`, `test_vehiclefilter.py`, `tests.py`, RQ-01 |
| FR-06 | render a vehicle's manual tree and pages server-side, with images served only to entitled users | Seat | `test_qa_catalog.py`, `test_qa_mediaauth_paths.py`, E2E `media.spec.js`, RQ-03 |
| FR-07 | search a vehicle's manuals in Persian or English and return pages of that vehicle only | Seat | `rag/test_fts.py`, `rag/test_retrieve.py`, `rag/test_service_paths.py` |
| FR-08 | answer a repair question in Persian from the selected vehicle's manuals only, with links that resolve to pages the user may open | Seat (AI-eligible) | `rag/test_*.py`, `test_qa_content_guard.py`, frontend `chatPrompt.test.mjs`, RQ-09 |
| FR-09 | resolve diagnostic trouble codes and symptoms with a deterministic engine before falling back to retrieval | Seat (AI-eligible) | `test_qa_content_guard.py`, `rag/test_service_paths.py` (DiagnoseTests) |
| FR-10 | show part numbers, special tools and labor times for a vehicle when the company bought those layers | Seat | parts: `tests_parts.py`; labor times and SST CSV exports: `test_exports.py`; layer entitlement: `test_qa_access.py` |
| FR-11 | let a manager build the org chart, invite or provision employees, and delegate only access they hold themselves | Manager | `test_orggraph.py`, `test_qa_orggraph_authz.py`, `test_qa_orggraph_input.py`, `test_team.py`, RQ-01 |
| FR-12 | show a manager usage analytics for their own branch of the org chart, and a Persian PDF report | Manager | `test_team.py`, `test_orgreach.py` |
| FR-13 | let a manager file requests to the vendor and see status changes live | Manager, Admin | `test_qa_requests.py`, `test_events.py` |
| FR-14 | recommend sections to read from the user's own recent activity, never from vehicles they cannot open | Seat | `test_recommend.py`, `rag/test_store_ro.py` |
| FR-15 | give the admin a console for companies, users, grants, requests, analytics, data quality, pipeline and monitoring | Admin | `test_adminops.py`, `test_ops.py`, `test_admin_token_scope.py` |
| FR-16 | ingest new vehicles (ZIP inbox → parse → RAG index → diagnostic sidecar → audit) resumably, without blocking serving | Admin | `test_pipeline.py`, `test_pipeline_ext.py`, `test_tisparse.py`, `test_partsouq_build.py` |
| FR-17 | log assistant exchanges and activity for analytics and the admin, scoped by company | Admin, Manager | `test_chatlog.py`, `test_events.py` |
| FR-18 | switch features per company or user with flags, including A/B variants | Admin | `test_flags.py` |
| FR-19 | publish structured vehicle specifications (schema.org) built from the manuals | Seat, Admin | `test_vehicleschema.py`, `test_adminops.py` (VehicleSpecsTests) |
| FR-20 | alert the operator by SMS when security, AI, SMS-delivery or infrastructure rules fire, without duplicate pages | Admin | `test_alert_probe.py`, `test_disk_guard_resolve.py`, `ops/observability/test_*.py`, watchdog `--selftest` |

## 5. Quality (non-functional) requirements

| ID | ISO 25010 | Requirement | Target | Verified by |
|---|---|---|---|---|
| NFR-01 | Security: confidentiality | Tenant isolation and entitlement rules | RQ-01, RQ-02, RQ-03, RQ-07 | see TRACEABILITY.md |
| NFR-02 | Security: integrity | Hostile input never yields a 5xx or query manipulation | RQ-08; ZAP API scan 0 high | `test_qa_*`, `test_adminops.py`, `qa/dast/` |
| NFR-03 | Security: authenticity | Static admin token only from direct loopback; admin sessions expire | 12 h idle / 7 d absolute | `test_admin_token_scope.py`, `test_security.py` |
| NFR-04 | Security: supply chain | No known high/critical vulnerability or secret ships | CI gates green | `ci.yml` security + images jobs, RQ-15 |
| NFR-05 | Performance | Page p95 < 1.5 s, API p95 < 0.5 s, assistant p95 < 4 s, errors < 1 % at 10 concurrent users | k6 thresholds | `qa/perf/k6-kgkg.js`, `audit-evidence/06-…/PERFORMANCE_REPORT.md` |
| NFR-06 | Reliability: availability | Outages are detected and paged; the alerting engine is itself watched; deploys have no downtime; failed deploys roll back | blackbox uptime probes; watchdog pages within 10 min of the alert sweep dying; zero-gap swap; auto-rollback | `ops/observability/` (`test_watchdog.py`), `ops/deploy/deploy.sh`, ADR-0003 |
| NFR-07 | Reliability: recoverability | Data restorable after host loss | off-host backup + restore check | doc 11 §11.6 **(manual: restore drill)** |
| NFR-08 | Usability: accessibility | Public pages have no serious/critical WCAG 2.1 A/AA violations | axe-core | E2E `a11y.spec.js`, RQ-14 |
| NFR-09 | Usability: localisation | Persian UI, RTL layout, Persian digits and Jalali dates in reports | — | frontend `faTerms*.test.mjs`, `test_team.py` (Jalali) |
| NFR-10 | Maintainability: testability | Backend coverage never falls; authz logic mutation-tested | floor in `ops/deploy/coverage_min`; mutation score recorded | CI ratchet, `qa/mutation/run.sh` |
| NFR-11 | Maintainability: modifiability | Docs change with the code; API spec matches routes | — | `test_openapi_routes.py`, `docs/README.md` protocol |
| NFR-12 | Operability: release control | Only a person promotes; staging and E2E evidence required or the override is logged | — | `test_gate_roles.sh`, `test_promote.sh`, ADR-0004 |
| NFR-13 | Data integrity: isolation of non-production | Staging/QA never write production data | — | `rag/test_feedback_isolation.py`, `test_qa_fixtures.py`, RQ-12 |
| NFR-14 | AI faithfulness | Answers cite only retrieved pages of the selected vehicle; out-of-domain queries return nothing | gold-set evaluation | `qa/eval/`, `04-integration-testing/`, `rag/test_service_paths.py` |

## 6. Interfaces

| Interface | Specification |
|---|---|
| HTTP API (90 routes) | `docs/openapi.yaml`, enforced by `test_openapi_routes.py`; narrative in doc 05 |
| Real-time events | Server-Sent Events, doc 09 |
| Metis LLM | outbound HTTPS, phrasing only, with a deterministic fallback (doc 08) |
| SMS provider | outbound HTTPS, OTP and alerts; never called from tests (`alert_rules.deliver`) |
| Metrics | Prometheus exposition `/api/metrics/` (loopback/docker network only), `test_metrics_exposition.py` |

## 7. Verification summary

Every FR and NFR above names its verification. A requirement is **met** only when that
verification ran on the release commit:

* CI for the unit and integration suites;
* `qa/run_e2e.sh` (recorded and enforced by `kgkg-promote`) for E2E;
* `qa/perf` and `qa/dast` for MINOR and MAJOR releases (`audit-evidence/10-release-management/RELEASE_POLICY.md`).

Results per release: `audit-evidence/15-final-audit-report/TEST_SUMMARY_REPORT.md`.

## 8. Change control

Change this file in the same commit as the behaviour it describes (docs protocol,
`docs/README.md`). A new feature adds an `FR-`; a new rule found by a defect adds an `RQ-` in
TRACEABILITY.md. Design decisions behind requirements are recorded as ADRs in `docs/adr/`.
