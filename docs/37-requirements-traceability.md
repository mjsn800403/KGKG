# 37 — Requirements-to-implementation traceability

Maps every requirement in [00-srs.md](00-srs.md) (FR-01…FR-30, NFR-01…NFR-14) to the code that implements it (routes, modules, models) and to the tests the SRS names as verification. The *verified by* column
is copied from the SRS and **checked by `ops/governance/check_srs_trace.py`**: every test file named there must exist, and every requirement ID in the SRS must appear in this table. The check proves
that the named tests exist, **not** that they pass or that they cover the requirement; pass/fail is the CI result of the release commit. Revision `origin/work` @ `07f3ab5` **[C]**. Persian version:
[fa/37-requirements-traceability.md](fa/37-requirements-traceability.md). Security/business rules `RQ-xx`: `audit-evidence/01-requirements-and-traceability/TRACEABILITY.md` (dated audit evidence).

Status vocabulary: **Implemented** = code and routes exist; **Implemented, config-gated** = exists but off unless a switch is set; **Partial** = implemented with a stated gap; **Manual** = verified by procedure, not a test.

## 37.1 Functional requirements

| ID | Requirement (short) | Implementation (routes → modules → models) | Verified by (SRS) | Status |
|---|---|---|---|---|
| FR-01 | Purchase request | `POST api/purchase-request/` → `views.purchase_request_view` → `PurchaseRequest` | `test_purchase_flow.py` | Implemented |
| FR-02 | Request → company, grants, first users | `api/admin/requests/…`, `api/admin/companies/…`, `api/admin/users/…` → `portal.admin_*` → `Company`, `CompanyCarAccess`, `PortalUser`, `UserCarAccess`, `InviteToken` | `test_purchase_flow.py`, RQ-11 | Implemented |
| FR-03 | Password + SMS OTP, SMS recovery | `api/auth/login|verify-otp|resend-otp|recover/*` → `portal.*`, `portal_auth.py`, `ratelimit.py` → `OtpChallenge`, `OtpEvent`, `KnownDevice`, `AuthToken` | `test_qa_auth.py`, `test_recover.py`, `test_sms_bodies.py`, `auth.spec.js`, RQ-04 | Implemented |
| FR-04 | One live session, server-side revocation | `api/auth/logout/`, `api/auth/me/` → `portal.*`, `portal_auth.py` → `AuthToken` (hashed) | `session.spec.js`, `test_security.py`, RQ-05 | Implemented |
| FR-05 | List only entitled vehicles/layers | `api/auth/fleet/`, `{brand}/{year}/{model}/` → `portal.fleet_view`, `views.car_view`, `access.py`, `listing.py` → `CompanyCarAccess`, `UserCarAccess` | `test_qa_access.py`, `test_vehiclefilter.py`, `tests.py`, RQ-01 | Implemented |
| FR-06 | Render manual tree/pages; entitled images only | `views.car_view`, `api/media-auth/` (nginx `auth_request`) → `cardb.py`, `cardb_pg.py`, `mediaauth.py` | `test_qa_catalog.py`, `test_qa_mediaauth_paths.py`, `media.spec.js`, RQ-03 | Implemented (content store engine per [23](23-data-layer.md)) |
| FR-07 | Persian/English search within one vehicle | `api/search/` → `views.search_view` → `rag/service.search`, `rag/retrieve.py` | `rag/test_fts.py`, `rag/test_retrieve.py`, `rag/test_service_paths.py` | Implemented |
| FR-08 | Grounded Persian answers, links resolvable and entitled | `POST /api/chat` (Next) → `api/assist/` → `rag/*`; `chatPrompt.js` | `rag/test_*.py`, `test_qa_content_guard.py`, `chatPrompt.test.mjs`, RQ-09 | Implemented; opt-in parts per [30](30-ai-assistant-deep-dive.md) §30.12 |
| FR-09 | Deterministic DTC/symptom engine first | `api/diagnose/` → `rag/diag.py`, `diag_build.py` | `test_qa_content_guard.py`, `rag/test_service_paths.py` | Implemented where sidecars exist **[U]** |
| FR-10 | Part numbers, special tools, labor times when bought | `parts.py`, `sst.py`, `labortimes.py`, `assist_lookup.py`; `api/admin/parts/` | `tests_parts.py`, `test_exports.py`, `test_qa_access.py` | Implemented |
| FR-11 | Org chart, invites/provisioning, delegation ≤ own access | `api/org/*`, `api/invite/<token>/` → `orggraph_api.py`, `orggraph.py`, `team.py` → `OrgGraph`, `OrgNode`, `NodePermission`, `NodeInvite` | `test_orggraph.py`, `test_qa_orggraph_authz.py`, `test_qa_orggraph_input.py`, `test_team.py`, RQ-01 | Implemented |
| FR-12 | Branch analytics and Persian PDF | `api/team/analytics|report|insights/` → `team.py`, `reporting.py`, `recommend.py` | `test_team.py`, `test_orgreach.py` | Implemented |
| FR-13 | Manager requests with live status | `api/company/requests/…`, `api/admin/company-requests/` → `requests_api.py`, `events.py` → `CompanyRequest`, `TicketMessage`, `TicketRead`, `Event` | `test_qa_requests.py`, `test_events.py` | Implemented |
| FR-14 | Recommendations only from openable vehicles | `api/recommendations/` → `recommend.py` | `test_recommend.py`, `rag/test_store_ro.py` | Implemented |
| FR-15 | Admin console | `api/admin/*` → `adminops.py`, `portal.py`, `monitoring.py` | `test_adminops.py`, `test_ops.py`, `test_admin_token_scope.py` | Implemented |
| FR-16 | Resumable ingestion without blocking serving | `api/admin/pipeline/`, `ops/hostjobs` → `pipeline.py`, `ingest.py`, `parse_worker.py`, `tis_crawler.py`, `partsouq_*.py` → `ZipPackage`, `ProcessingJob`, `PipelineSettings` | `test_pipeline.py`, `test_pipeline_ext.py`, `test_tisparse.py`, `test_partsouq_build.py` | Implemented |
| FR-17 | Log exchanges/activity, company-scoped | `api/auth/chat-log/`, `api/team/chat-logs/`, `api/admin/chat-logs/`, `api/activity/` → `chatlog.py` → `ChatLog`, `ActivityLog` | `test_chatlog.py`, `test_events.py` | Implemented |
| FR-18 | Feature flags incl. A/B | `api/auth/flags/`, `api/admin/flags/…` → `flags.py` → `FeatureFlag` | `test_flags.py` | Implemented |
| FR-19 | Structured vehicle specs | `api/admin/vehicle-specs/` → `adminops.py`, `frm.py` → `VehicleSpec` | `test_vehicleschema.py`, `test_adminops.py` | Implemented |
| FR-20 | SMS alerts without duplicates | `alert_rules.py`, `monitoring.py`, `ops/observability/watchdog.py` → `SystemAlert`, `NotificationLog` | `test_alert_probe.py`, `test_disk_guard_resolve.py`, `ops/observability/test_*.py`, watchdog `--selftest` | Implemented |
| FR-21 | Anonymous support chat | `api/support-chat/*` (status, threads, messages, contact, reopen, csat) → `support_chat/views_public.py`, `tokens.py`, `limits.py`, `throttle.py`, `lifecycle.py`, `config.py` → `SupportThread`, `SupportMessage`, `SupportRating` | `test_public_api.py`, `test_lifecycle.py`, `test_tokens.py`, `test_security_sweep.py`, `test_kill_switch.py`, `test_throttling.py`, `support-chat.spec.js` | Implemented, config-gated (`KG_SUPPORT_CHAT_ENABLED`); production state **[U]** |
| FR-22 | Staff inbox and support RBAC | `api/admin/support-chat/*` → `views_admin.py`, `views_admin_inbox.py`, `views_status.py`, `rbac.py`, `permissions.py` → `SupportPresence` (+ role storage after a later migration **[U]**) | `test_inbox_api.py`, `test_staff_actions.py`, `test_rbac.py`, `test_rbac_api.py`, `test_support_roles_command.py` | Implemented; RBAC off by default |
| FR-23 | Notification outbox | `notifications/service.py`, `worker.py`, `providers.py`, `config.py`; `manage.py process_outbox`; `ops/outbox/` → `NotificationOutbox` | `notifications/test_service.py`, `notifications/test_worker.py`, `notifications/test_providers.py`, `notifications/test_privacy_and_concurrency.py`, `notifications/test_command.py` | Implemented, config-gated (channels default `off`); delivery receipts not observed |
| FR-24 | Knowledge base | `api/kb/*`, `api/admin/kb/*`, `api/admin/company-requests/<id>/promote-to-article/` → `knowledge.py` → `KnowledgeArticle`, `KnowledgeRevision`, `KbSearchLog` | `test_knowledge.py`, `test_helpdesk_desk.py` | Implemented |
| FR-25 | Assistant allowance per plan | `api/auth/ai-usage/` → `quota.py` (`PLAN_AI`) → `ActivityLog` (`ask_assistant` rows), `Company.plan`; checked in `/api/chat` | `test_qa_access.py`, `pricing.test.mjs` | Implemented; **no dedicated test module** (only allowance paths inside access tests) |
| FR-26 | Helpdesk SLA targets and product feedback | `sla.py` (high 2 h/8 h, normal 8 h/48 h, low 24 h/120 h, calendar hours), `feedback.py` (`api/feedback/submit/`, `api/admin/feedback/`), `support_metrics.py` → `CompanyRequest`, `Feedback` | `test_helpdesk.py`, `test_helpdesk_desk.py` | Implemented |
| FR-27 | Feature-discovery checklist | `api/auth/onboarding/` → `onboarding.py`, `access.user_ai_eligible` → `ActivityLog` | `test_onboarding.py`, `onboarding.test.mjs` | Implemented |
| FR-28 | Content shield and read caps | `shield.py` (`api/shield/key/`, `KG_SHIELD`, `KG_SHIELD_SECRET`), `contentguard.py` | `test_shield.py`, `test_contentguard.py` | Implemented, config-gated (shield); caps always on |
| FR-29 | Admin tool gates | `grafanaauth.py` (`api/admin/grafana-ticket/`, `api/grafana-auth/`), `vncauth.py` (`api/vnc-auth/`), nginx `auth_request` | **(manual)** | Implemented; **no automated test found** |
| FR-30 | Assistant behaviour insights | `behavior.py`, `insights.py` (`api/admin/insights/*`, `api/auth/chat-feedback/`) → `ChatLog` | `test_routes_and_independence.py` (route coverage only) | Implemented; behaviour logic has no dedicated test **[U]** |

### Coverage statement

FR-21…FR-30 were added to the SRS on 2026-11-04 from the verified code (they existed before; the SRS had not named them). "Test file exists" in the *Verified by* column means the file is present and named for that behaviour; it does **not** mean
every rule of the requirement is asserted or that the test passes. Rows marked *no dedicated test* (FR-25, FR-30) or *(manual)* (FR-29) are the known verification gaps. The requirement-by-requirement pass/fail is the CI run on the release commit.

## 37.2 Quality requirements

| ID | Requirement (short) | Where it is realised | Verified by (SRS) | Status |
|---|---|---|---|---|
| NFR-01 | Tenant isolation and entitlement | `access.py`, `mediaauth.py`, retrieval `allowed_cars` | RQ-01/02/03/07 (TRACEABILITY.md) | Implemented |
| NFR-02 | Hostile input never 5xx | `nulguard.py`, view validation | `test_qa_*`, `test_adminops.py`, `qa/dast/` | Implemented; DAST result figure not in this repo **[U]** |
| NFR-03 | Admin token only from loopback; session expiry | `admin_auth.py` | `test_admin_token_scope.py`, `test_security.py` | Implemented |
| NFR-04 | No known high/critical vulnerability or secret ships | CI gates | `ci.yml` security + images, RQ-15 | Enforced by CI |
| NFR-05 | Performance thresholds | `qa/perf/k6-kgkg.js` | k6 thresholds, `audit-evidence/06-…/PERFORMANCE_REPORT.md` | Thresholds defined; latest run result **[U]** |
| NFR-06 | Detection, watchdog, zero-gap deploy, rollback | `alert_rules.py`, `watchdog.py`, `deploy.sh` | blackbox probes, watchdog selftest, ADR-0003 | Implemented; host timer state **[U]** |
| NFR-07 | Recoverability | backups ([34](34-data-model-reference.md) §34.7) | doc 11 §11.6 (manual restore drill) | **Not demonstrated** (R1) |
| NFR-08 | Accessibility (WCAG 2.1 A/AA) | frontend | `a11y.spec.js`, RQ-14 | Nightly QA only |
| NFR-09 | Persian/RTL/Jalali | frontend, `team.py` | `faTerms*.test.mjs`, `test_team.py` | Implemented |
| NFR-10 | Coverage never falls; authz mutation-tested | `coverage_min`, `qa/mutation/run.sh` | CI ratchet | Floor 59 %; mutation on demand |
| NFR-11 | Docs change with code; API spec matches routes | governance job, `docs/openapi.yaml` | `test_openapi_routes.py` | Enforced by CI |
| NFR-12 | Release control by a person | `kg-deploy-gate`, `kgkg-promote`, ADR-0004 | `test_gate_roles.sh`, `test_promote.sh` | Enforced by tests |
| NFR-13 | Non-production never writes production data | feedback DB redirection, sanitizer | `rag/test_feedback_isolation.py`, `test_qa_fixtures.py`, RQ-12 | **Partial**: staging read production `kgkg_vec` (R5) |
| NFR-14 | AI faithfulness | scope gates, link sanitiser | `qa/eval/`, `rag/test_service_paths.py` | Implemented; no automated CI quality gate ([32](32-testing-and-qa.md) §32.13) |

## 37.3 Using and maintaining the matrix

1. Change behaviour → change the SRS row, this row and the named tests in the same PR (docs protocol, [AGENTS.md](AGENTS.md) §5).
2. `python3 ops/governance/check_srs_trace.py` fails when a test named in the SRS does not exist or an SRS requirement ID is missing here.
3. A requirement is **met** only when its verification ran on the release commit (SRS §7); this matrix does not assert that.
