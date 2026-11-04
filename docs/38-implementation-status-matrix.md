# 38 — Implementation and operational status matrix (what is real today)

Purpose: one place that answers *"what does the system actually have, and what can we legitimately claim?"* for formal reports and external evaluation.
Every row separates **code**, **deployment**, **configuration**, **operating evidence**, **tests** and **direct production observation**.
Persian version: [fa/38-implementation-status-matrix.md](fa/38-implementation-status-matrix.md). Reporting-ready wording per subsystem: [39](39-evaluation-evidence-guide.md).

## 38.1 How this matrix was produced (read before quoting it)

| Source | What it is | Tag |
|---|---|---|
| Source code and tests at `origin/work` | read in the repository | **[C]** |
| **Direct production observation, 2026-11-04 ≈ 11:00–11:30 UTC** | a separate, strictly **read-only** session on the saved SSH connection `kgtechvault` ran the checks listed in §38.8. It changed nothing and printed no secret values (env variable **names** only, plus a short allow-list of non-secret on/off switches). Results are quoted as reported by that session | **[P]** |
| Public edge probes | `GET` of public URLs only (`/`, `/kg-api/api/health/`, `/kg-api/api/support-chat/status/`) | **[P]** |
| Earlier sessions, Slack, Jira | second-hand claims | **[D]** |
| Not observed | | **[U]** |

Production was running commit **`8a380f664570894c111605c0fa6277cc76609fae`** (`deploy-20261104-053524`; container image tags and the `kgkg.sha` labels agree [P]). `work` is now at or beyond `8d5ab4e`.
The only application files that differ between that production commit and `work` are `KG_backend/api/events.py` (SSE database-connection handling) and `KG_backend/api/alert_rules.py` [C, `git diff 8a380f6 origin/work`]; the rest of the difference is documentation, governance scripts and CI. A newer commit (`135aa78b7`) had passed the gate and smoke on staging but was **not promoted** [P].
This matrix therefore describes the **deployed** behaviour of commit `8a380f6` unless a row says otherwise.

**Status vocabulary** (one per row):

| Code | Meaning |
|---|---|
| **IC** | Implemented in code only (no evidence of deployment) |
| **DD** | Deployed but **disabled** or not configured |
| **DE** | Deployed and enabled (configuration observed), but no usage evidence |
| **OP** | Operational with supporting evidence (usage or runtime data observed) |
| **EX** | Experimental, partial or known-failing |
| **PL** | Planned, not implemented |
| **UV** | Unverified (insufficient evidence or access) |

"Tests" names what the automated tests actually assert, not whether a feature "has tests". CI pass/fail is a property of a commit, not of this matrix.

## 38.2 Platform and portal

| Capability | Status | Code / deployed / enabled | Operating evidence | Tests (what they assert) | Limits |
|---|---|---|---|---|---|
| Public site, brand/year listings, purchase-request form | **DE** | [C] views and pages exist; [P] `https://kgtechvault.com/` returns HTTP 200 with CSP, HSTS, X-Frame-Options, referrer and permissions policies | edge probe only; the number of stored purchase requests was not counted [U] | `test_purchase_flow.py` (form → admin visibility) | submission end-to-end on production was not exercised |
| Login, SMS OTP, SMS recovery | **OP** | [C] `portal.py`; [P] latest portal login 2026-11-04 05:24 UTC; `ADMIN_REQUIRE_2FA` unset (admin second factor not forced) | live logins | `test_qa_auth.py`, `test_recover.py`, `auth.spec.js` (flows, throttles) | SMS delivery path never verified end to end (GitHub #24) [D]; admin has no password-change/recovery route |
| One active session per account, origin guard, content shield, read caps | **DE** | [P] `KG_SHIELD=1` in backend and frontend env; `KG_SINGLE_SESSION`, `KG_ORIGIN_GUARD` not set → code defaults apply (on) [C] | none beyond configuration | `test_shield.py`, `test_contentguard.py`, `SingleSessionTests` | shield is obfuscation, not DRM ([26](26-auth-and-sessions.md)) |
| Companies, users, grants (entitlements) | **OP** | [P] 9 companies, 36 portal users | tables populated | `test_qa_access.py`, `test_qa_orggraph_*`, `test_team.py` | org-graph row counts not taken [U] |
| Org-graph team canvas | **DE** | [C]; [P] code deployed (`8a380f6`) | not counted [U] | `test_orggraph.py` | guidance tours for the team page point at removed anchors (F1) |
| Manual browsing for 237 cars | **OP** | [P] `main_db` 237 rows, 2 brands; 222 schemas in `kgkg_vec`; 16 files in `_parts/` (15 catalogs + report) | 86,250 activity-log rows, latest 07:00 UTC | `test_qa_catalog.py`, `test_cardb_pg.py`, `media.spec.js` | content correctness is not tested end to end |
| Parts catalog | **DE** | [C] `parts.py`; [P] `_parts/` present | usage not counted [U] | `tests_parts.py` | licensing of OEM data unresolved ([16](16-parts-catalog.md)) |
| Team analytics, PDF report, recommendations | **DE** | [C]; deployed | activity data present; PDF generation not exercised [U] | `test_team.py`, `test_recommend.py` | |
| Knowledge base | **OP** | [P] 23 published articles | content exists | `test_knowledge.py` | usage/search logs not counted [U] |
| Ticket desk (`CompanyRequest`) | **EX** | [P] 7 requests stored | in use | `test_helpdesk.py` | **5 of 6 failing nightly E2E tests are in `support.spec.js`** (ticket filing, SLA state, feedback widget, category/vehicle, unread marker) [P]; reasons not examined |
| Feature flags | **OP** | [P] exactly one flag, `mq_translate`, enabled | | `test_flags.py` | |
| Real-time events (SSE) | **DE** | [C]; nginx location verified identical to repo [P] | no direct stream observation [U] | `ops/governance/test_nginx_sse.py`, `test_events.py` | newer SSE connection fix is on `work`, **not in production** |

## 38.3 Specialised AI assistant

| Capability | Status | Code / deployed / enabled | Operating evidence | Tests | Limits |
|---|---|---|---|---|---|
| Retrieval over the manuals (hybrid vector + keyword + glossary) | **OP** | [P] `RAG_VEC_BACKEND=pgvector`, `RAG_FTS_BACKEND=pg` (so **retrieval storage is PostgreSQL in production**, not the SQLite default); `index.rag.db` 6.77 GB present, `embed_model=BAAI/bge-m3`, `graph_synced_vectors=305875`; model cache present | 63 assistant exchanges logged, 47 in the last 30 days | `rag/test_retrieve.py`, `test_scoring.py`, `test_service*.py` | exact production retrieval path (pgvector vs SQLite fallback per request) not traced [U] |
| Grounding gate, vehicle-scope refusal, near-miss guard | **DE** | [C] defaults on; [P] `RAG_ABSENT_REFUSES`, `RAG_GROUND_SIM_FLOOR` unset in env → defaults (on, 0.60) | none | `rag/test_retrieve.py`, `test_service_paths.py` | effect on real questions not measured on production |
| Authorization inside retrieval (`allowed_cars`) | **DE** | [C]; deployed | n/a | `test_qa_content_guard.py`, `rag/test_*` | |
| Deterministic diagnostic engine | **OP** | [P] 222 diagnostic sidecars | used by the chat route when a car is pinned | `rag/test_diag_engine.py` | |
| LLM phrasing (Metis) with bot fallback chain and no-LLM fallback | **OP** | [P] `METIS_API_KEY`, `METIS_BOT_ID`, `METIS_FALLBACK_BOT_IDS` all set (frontend) | of 63 logged exchanges, **14 `grounded`, 10 `degraded`** (all-time counts of the stored flags) | `chatPrompt.test.mjs`, `rag/test_service_paths.py` | the stored `grounded` flag is not a quality score; the fallback has been used (10 degraded) |
| Persian→English query translation | **DE** | [P] frontend `RAG_MQ_TRANSLATE=1` and feature flag `mq_translate` enabled | | `test_flags.py` | benefit measured only on hand-made paraphrases [H] |
| Cross-encoder reranker | **DD** | [P] `RAG_RERANK=0`; model cached | | `rag/test_rerank_fuse.py` | do not describe reranking as active |
| Query adapter | **DD** | [P] `RAG_QUERY_ADAPTER` unset; adapter files cached | | `train_query_adapter` (offline) | disabled after it pushed queries below the grounding floor [D] |
| Human feedback loop (ratings, clicks, expert pins) | **EX** | [P] `feedback.db`: 582 logged queries, **11 ratings, 0 clicks, 0 pins** | very little learning signal | `rag/test_feedback*.py` | boosts exist but have almost no data |
| Offline evaluation suite | **EX** | [C] gold sets + metrics; [P] last runs 2026-09-07 | | `rag/test_evalmetrics.py` | no published results file in the repo; runs are two months old |
| Answer-quality gate in CI | **PL** | not present | | | do not claim automated hallucination testing |

## 38.4 Support and communication

| Capability | Status | Evidence | Limits |
|---|---|---|---|
| Visitor support chat + staff inbox | **DD** | [P] migration `0041_support_chat_core` applied; public status endpoint answers `enabled=false, mode=async`; no `KG_SUPPORT_*` switch in either env file; **0 threads, 0 messages** | deployed code, never switched on, never used; the privacy notice is an unpublished draft |
| Support RBAC (off/audit/enforce) | **DD** | [P] `KG_SUPPORT_RBAC`/`KG_SUPPORT_OWNERS` unset → mode `off` | enforcement exists only in code and tests |
| Notification outbox (SMS/e-mail) | **DD** | [P] table `api_notificationoutbox` exists with **0 rows**; `KG_NOTIFY_*` unset (off); the `kgkg-outbox.timer` unit **is not installed** | no customer notification has been sent through it |
| Support-chat E2E in CI | **OP (CI)** | passes on PR heads [C CI] | tests run on a throwaway stack, not production |

## 38.5 Data, storage and recovery

| Capability | Status | Evidence | Limits |
|---|---|---|---|
| Portal DB `kgkg` (PostgreSQL 16) | **OP** | [P] 134 MB; 59 recorded migrations, latest `api.0041_support_chat_core` | |
| Vehicle content `kgkg_vec` | **OP** | [P] 58 GB; 222 `car_*` schemas = 222 rows in `public.car_dbs` | **not in any backup path found** [P] |
| Other databases on the server | **UV** | [P] `kgkg_kb`, `kgkg_qa`, `kgkg_staging`, `kgkg_trial`, `kgkg_gate`, `kgkg_bench`, `partsouq` exist; none is referenced by a name-only env variable scan except via `KG_PG_NAME` (value not printed) | purpose of `kgkg_kb`, `kgkg_trial`, `kgkg_bench` is not documented |
| Backups | **EX** | [P] (a) pre-deploy `pg_dump` of `kgkg` (newest 3 kept, ≈ 25 MB each, readable by `pg_restore --list`); (b) hourly snapshot `/root/backup_snapshot/` (script `/root/kgkg_snapshot.py`, stamp and `portal.dump` refreshed 2026-11-04; includes `kgkg` dump, nginx configs, code mirror; excludes `kgkg_vec`, `_parts`, `_rag`, env files); (c) the owner states that the company's internal backup server and the hosting provider also back up the server — **(c) is not visible from the host**: the hourly pull by the company server is inferred from the refreshed stamp; the repository documents a monthly provider backup on the 5th; `archive_mode=off` | arrangement exists; **coverage of `kgkg_vec` and `_parts` by the company-server or provider backups is unverified**; `verify_restore.py` exists but no run log was found, so recoverability is demonstrated for neither mechanism ([44 §44.8](44-data-lifecycle.md), [47](47-engineering-followups.md) E2–E3) |
| Staging isolation | **UV** | [P] no staging container was running at the check; a staging run for `135aa78b7` had just passed; `kgkg_staging` database exists | whether staging reads production `kgkg_vec` could not be re-checked live (risk R5 stays open) |

## 38.6 Operations, monitoring, delivery

| Capability | Status | Evidence | Limits |
|---|---|---|---|
| Container deployment, zero-gap swap, rollback | **OP** | [P] containers `kgkg-backend/frontend-20261104-053524` healthy; `state.env` records `CURRENT` and `PREVIOUS`; deploy logs present | rollback not exercised during the check |
| Promotion only by a person | **OP** | [P] CI key role has no `deploy` verb (configuration in repo); `promote-overrides.log` absent | |
| nginx / TLS / rate zones / media gate | **OP** | [P] deployed file identical to `ops/nginx/kgkg.conf`; `auth_request /_kg_media_auth` present | WAF behaviour not tested live |
| Monitoring stack | **OP** | [P] Prometheus targets all up (kgkg_app, node, cadvisor, probes); 0 active alerts; four dashboard files provisioned; GlitchTip, Loki, Alloy, Umami running | dashboard contents not viewed |
| Alert sweep, watchdog, pipeline, detect, coverage, bizsnap, token-prune timers | **OP** | [P] all enabled; last runs `Result=success` | unit files for several are not in the repository (F4) |
| Nightly QA | **EX** | [P] timer enabled, service **failed**; e2e 51 passed / 6 failed / 17 skipped (sha `cedcb79b3`, older than live); DAST 0 failures, 5 warnings; p95 page 16.7 ms, API 29.9 ms, assistant 1030 ms | the six failures are listed in §38.7 |
| Legacy systemd units `kgkg-backend/frontend.service` | **retired** | [P] disabled, inactive | docs formerly implied they run |
| Host hardening | **OP** | [P] key-only SSH, ufw (22 open; 80/443 Cloudflare ranges only; 8081 docker network), fail2ban active, env files mode 600 root | **`xrdp` is active** on the production host |

## 38.7 Known failing or unproven items an evaluator could find

1. Nightly E2E: six failures on 2026-11-04 01:35 UTC (`session.spec.js:60` UI logout; `support.spec.js:30, 44, 109, 175, 193`). Reasons not analysed.
2. Support chat, outbox, RBAC: present but off; zero use.
3. Reranker and query adapter: off.
4. Feedback loop: 11 ratings, 0 clicks, 0 expert pins.
5. `kgkg_vec` (58 GB) has no verified backup; no WAL archiving.
6. 63 assistant exchanges logged in total; 14 stored as `grounded`.
7. Production runs `8a380f6`; `work` has a newer SSE fix and alert-rule change not yet promoted.

## 38.8 Checks performed on the server (all read-only)

Versions and tags; container list and labels; systemd units, timers and failed units; nginx listener/location summary and byte comparison with the repository file; PostgreSQL database list and sizes, migration table tail, **row counts only** for the listed tables, `archive_mode`; SQLite sizes and `meta` keys; non-secret environment switches (names, plus values of an allow-list); Hugging Face cache directory names; error-log line **count**; Prometheus target and alert summaries; backup directory listings; firewall and sshd effective settings; deploy-state files; public HTTP probes. Not performed: any write, restart, deploy, promote, migration, secret read, row-level data read, or staging container inspection (none existed).
Not checkable by that session: which database `KG_PG_NAME` names, mounts of staging containers, relationship of the live commit to `8d5ab4e` (object absent locally; no fetch was made).

## 38.9 Maintenance

Update a row only with a new observation, and move the date in §38.1. A change that flips a switch or promotes a commit must update this file in the same change set. Row sources are re-derivable with the commands in §38.8.
