# Phase 3: integration plan and SSE investigation (findings)

**Date:** 2026-11-03. Labels: *verified* (observed this session), *hypothesis*, *proposed*. Nothing here changes code.

## 1. Integration strategy, re-evaluated against the live Git state

**Verified state (fetched 2026-11-03):** `origin/work` = `c78c67d` (unchanged since the last check); Phase 2 = `origin/feat/customer-communication-core` `9a72d19`, still in no other branch, 14 ahead / 5 behind `work`; Phase 3 = `origin/feat/support-chat-phase3` `b8c51da`, pushed 2026-11-03 for CI only (3 commits on top of Phase 2). Open PRs: #59 (CodeQL fixes), #65 (data-integrity errata), both to `work`; neither touches support code or migrations. `work` requires the CI jobs `backend, frontend, security, images, governance`, 0 approving reviews; the repo allows merge, squash and rebase merges and **deletes the head branch on merge**.

**Conflicts (trial `git merge-tree`, nothing changed):** merging `work` into Phase 2 and into Phase 3 each conflict in exactly one file, `docs/CHANGELOG.md` (both sides add to "Unreleased"). Mechanical: keep both blocks, newest first. No conflicts in migrations, models, `urls.py`, `audit.py`, `openapi.yaml`, docs 04/05/11 or any frontend file, because `work` has only changed CI config, Dependabot and `qa/e2e/tests/support.spec.js`.

**Re-evaluation of the earlier recommendation ("Phase 2 PR and merge, then update Phase 3, then Phase 3 PR"):** the order stays right; two refinements from the actual settings:

1. **Never squash or rebase-merge Phase 2.** Phase 3's three commits sit on Phase 2's SHAs. A squash creates a new commit with no ancestry link, so Phase 3 would then conflict with an identical copy of its own base and need a rebase, which is forbidden. Use a normal **merge commit** (the repo's history already uses "Merge pull request #n" commits).
2. **Stack the PRs to avoid waiting:** open the Phase 3 PR with base = the Phase 2 branch so its diff shows only the three Phase 3 commits; because the repo deletes head branches on merge, GitHub then retargets that PR to `work` after Phase 2 merges. Either way Phase 3 needs one normal merge of `work` (CHANGELOG only) before its merge.

**Proposed sequence (each step needs your separate approval):**
1. PR A: `feat/customer-communication-core` to `work`. Title/body must reference an issue (`ops/governance/check_traceability.py`; #61 is referenced in every commit; references inside code fences do not count). Verification: the five required jobs green; PostgreSQL jobs passed on 9a72d19 earlier (CI run 41490509088).
2. Merge PR A with a merge commit. Resolve CHANGELOG at merge time (keep both).
3. `git fetch`; merge `origin/work` into `feat/support-chat-phase3` with a normal merge (no rebase, no force). Run the full backend/frontend suites and the support-chat E2E.
4. PR B: `feat/support-chat-phase3` to `work`, merge commit, after green CI. Migrations A/B come only after this, in their own branch and PR once numbering is confirmed.
No step may run `stage` before merging to `work`; the `stage` job only runs for pushes to `work` and stages (never promotes). Production promotion remains a person's `kgkg-promote <sha>`.

**What a PR needs (prepared, not opened):** PR A: Phase 1+2 summary (outbox, support-chat tables, migrations `0040`/`0041`, no public activation, all flags off), verification evidence, rollback note (additive tables; `deploy.sh --rollback` safe). PR B: M0/M1 summary, "no migration", flags `KG_SUPPORT_CHAT_ENABLED` and `KG_PRIVACY_DRAFT_PAGE` default off, evidence from CI and the local E2E, the known limitations list.

## 2. SSE investigation

**Question:** why did the staff inbox not receive live events locally, and does it affect QA or production?

### 2.1 Findings

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | **Local cause is a crash in `runserver`, not the proxy.** `events.stream_view` sets `Connection: keep-alive`, a hop-by-hop header that Python's `wsgiref` rejects (`AssertionError: Hop-by-hop header, 'Connection: keep-alive', not allowed`). Every `GET /api/events/stream/` under `runserver` is therefore a 500 ("A server error occurred."). | **Confirmed defect, dev-server only** | Direct request to Django (no proxy): status 500, traceback in the server log naming that line (`KG_backend/api/events.py:219`). |
| 2 | My earlier explanation ("the dev proxy buffers SSE") was **wrong**. | Retracted | With the header dropped by a scratch-only settings shim (not in the repo), the same stream works directly *and* through `next start` rewrites: first frames at 0.04-0.07 s, a new thread's event arrives 1.0 s after creation, identical with and without `Accept-Encoding: identity`. No buffering, no compression artifact. |
| 3 | The inbox is correct once the stream works. | Confirmed | Browser run: a visitor thread created via the API appeared in the staff inbox **271 ms later with no manual refresh**; the page received `support_chat.message` and refreshed. |
| 4 | Production/QA are probably unaffected by finding 1. | **Hypothesis (not verified)** | Production uses gunicorn behind nginx (docs 11), and the stream already feeds the ticket desk; gunicorn does not abort on this header the way `wsgiref` does. I did not touch QA or production and cannot confirm which server QA uses. A one-request check of the QA stream by an authorized person would settle it. |
| 5 | **Existing issue: opening or reconnecting the stream slides the admin session.** `_resolve_viewer` validates the admin through `_admin_session_valid`, which calls `touch()`. The stream reconnects every 300 s, so an open console never idles out. | **Confirmed** (pre-existing, not introduced by Phase 3) | Local test: a session last used 3 h ago, after one stream open: `last_used_at` moved to now and `expires_at` moved from +9 h to +12 h. This defeats the idle policy that the read-only heartbeat was meant to protect. |
| 6 | **Two streams per admin tab, three transiently.** On load the admin page opens two stream requests at the same instant; opening the conversations tab opens another and aborts one. Steady state is two per tab. | **Confirmed** | Playwright request log: opened at 0.3 s, 0.3 s, then 1.7 s (+ one `ERR_ABORTED`). |
| 7 | **Capacity cost of the design.** Each stream holds one gunicorn request thread for up to 300 s and runs one DB query per second plus a connection close/open per tick. With 24 threads and 2 streams per tab, about 12 open admin tabs consume the whole worker pool (arithmetic, unmeasured). nginx also caps streams per client (`limit_conn kg_sse 8`, per Phase 2 notes). | **Hypothesis from code and arithmetic**; arithmetic verified, load unmeasured | `events.py` tail loop (`_TAIL_INTERVAL_S = 1.0`), this session's request count. |
| 8 | Reconnect/cleanup in `openEventStream`: uses `fetch` + `AbortController`, cursor resume with `Last-Event-ID`, closes on unmount (via `useEventStream`). | Read, not stress-tested | `utils/api.jsx`, `utils/useEventStream.js`. |

### 2.2 Verdict on SSE as the primary staff channel
**Yes, SSE can remain primary**; delivery latency is about 1 s and the inbox reacts correctly. Polling stays as a resilience fallback (20 s, visible-tab only) because streams legitimately drop. The local failure was environmental (finding 1) and is invisible in CI because no CI test opens the stream under `runserver`.

### 2.3 Corrections: approved by the owner 2026-11-03 and implemented locally (uncommitted CI status: not yet pushed)
Status of the four items below: 1, 2 and 4 are in `api/events.py`, `api/admin_auth.py` and `api/test_sse_stream.py`; 3 is `utils/sharedEventStream.js` behind `useEventStream`. Local results are in the progress report; **CI and staging results do not exist yet**. The original proposals follow unchanged for the record.
1. **Remove the hop-by-hop header** (`resp['Connection']`) in `events.stream_view`. Impact: local `runserver` works; gunicorn/nginx unchanged (nginx manages Connection itself). Test: a Django test client streaming test asserting a 200, `text/event-stream`, and no `Connection` header. File is shared (`api/events.py`, not in the Phase 3 "do not touch" list but used by the ticket desk), so this is its own small change.
2. **Stop the stream from touching the admin session** (use the no-touch resolution added for the heartbeat). Impact: an open console now follows the 12 h idle limit like any other admin session; a person must perform an action to extend it. Test: stream open leaves `last_used_at`/`expires_at` unchanged; other endpoints still touch. Risk: staff who only watch the inbox for hours will be signed out after 12 h idle; acceptable and intended, but your decision.
3. **One stream per admin tab** (module-level shared subscription in `useEventStream`), planned already as M2 Task 2.4. Impact: halves stream and DB load per tab. Needs the shared hook edited, so it waits for your approval and for M2.
4. Add one CI test that streams the first frames (see 1), so a header regression cannot reappear.

### 2.4 What was not done
No QA or staging request was made; no infrastructure was changed; no speculative fix was applied. The diagnostic shim lives only in the untracked `.superpowers/` scratch folder.
