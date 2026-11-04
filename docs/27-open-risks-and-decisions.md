# 27 — Open risks and pending decisions

A register of known problems that documentation alone cannot fix. Each row says what is claimed, the evidence tag,
and where the work is tracked. It supersedes the ad-hoc "known limitations" lists scattered in docs 11/12/18 for
anything listed here (those docs keep the detail). **Verify the evidence before acting on a row; owners remove rows
when the issue closes, in the same PR that closes it.**

Last verified: 2026-11-04 against `origin/work` `8a380f6`, Slack `#kg-dev`, Jira KGTEC. Items tagged **[U]** were not verifiable
from the documentation work (no `.env.prod`, no live nginx, no PostgreSQL listing, no backup inspection; the second
server pass was refused by the permission layer).

| ID | Risk | Evidence | Tracked | Why it matters |
|---|---|---|---|---|
| R1 | **`kgkg_vec` (about 58 GB, all 222 manual cars) and the 15 parts catalogs have no verified recoverable backup.** Deploy `pg_dump`, hourly off-host snapshot and `portal.dump` cover database `kgkg` only; SQLite files are deleted after loading to PostgreSQL; `archive_mode` was off; rebuild from ZIPs not demonstrated | [D session ea4f3d3e 2026-11-03; deploy.sh `pg_backup` dumps `$PG_NAME` only, C]. Current state **[U]** | GH #80, KGTEC-18 | Disk loss or corruption would lose the product's main content |
| R2 | Far-side backup retention unknown: an hourly mirror can propagate corruption; only the provider's monthly backup may be older | [C doc 12 risk 1; D] | GH #63, KGTEC-18 | Restore point age |
| R3 | Secrets (`.env.prod`, Cloudflare origin key) are in no backup by design; escrow location unrecorded | [C doc 12] | GH #63 | Bare-metal rebuild needs them |
| R4 | One host runs production, staging, QA and observability; disk 75% | [S 2026-11-04], GH #25 | GH #25 | Single point of failure, shared resource contention |
| R5 | Staging uses the production `kgkg_vec` and a read-write warehouse mount; staging seed data is sanitized for `kgkg` only | [D 2026-11-03] | **none found** | A staging fault could read or alter production car data |
| R6 | Production activity log is 96.8% reconstructed rows that metrics read as genuine; two untracked files sit in `/opt/KGKG/KG_backend` | [D GH #64; S untracked files 2026-11-04]; PR #65 adds `audit-evidence/17-data-integrity/` | GH #64, KGTEC-20 | Reports and metrics may overstate usage; deploy dirty-tree handling |
| R7 | No independent penetration test | [D] | GH #23, KGTEC-19 | Assurance |
| R8 | SMS paging path never verified end to end | [D] | GH #24 | Alerts may not wake anyone |
| R9 | No password change/reset route for portal users or admins | [C `api/urls.py`] | **none found** | Account recovery is manual |
| R10 | No CSRF tokens; protected by SameSite=Lax + Origin guard | [C doc 21] | GH #62 closed | Residual risk if cookies lose Lax semantics |
| R11 | `deploy.sh` could bypass the `work` check; guard `ops/deploy/promote_guard.sh` written but not wired | [C CHANGELOG 2026-11-03, spec promote-drift-prevention] | **none found** | Promotion of an unmerged commit |
| R12 | `kgkg-backend.service` (old gunicorn unit) once crash-looped beside the container; left `disabled` with `Restart=always`; docs still describe restarting it | [D session f197e5f1; S not running 2026-11-04] | KGTEC-6 (host changes) | A restart or reboot path could re-create the port conflict **[U]** |
| R13 | Assistant retrieval: `RAG_QUERY_ADAPTER` pushed queries under the 0.60 grounding floor and was disabled in `.env.prod`; floor must be recalibrated first | [D #kg-dev 2026-11-03] | none found | Re-enabling silently drops all citations |
| R14 | Nightly QA performance: assist latency 13.9 s vs 4 s limit (suspected per-call PostgreSQL connections to car DBs); not proven | [D session 26d9f5ff] | none found | Slow answers under load |
| R15 | Backend test coverage 58% against a stated 80%; ratchet `ops/deploy/coverage_min` | [C file, D GH #22] | GH #22, KGTEC-11 | Regression risk |
| R16 | Migrations `0042`/`0043` reservation awaiting written confirmation | [D Slack 2026-11-03; answer **U**] | support chat | Number collision |
| R17 | Hung `claude --version` probes burning about 4 vCPU since 2026-10-24; xrdp service on the host | [D GH #26, #17] | KGTEC-6 | CPU waste; unnecessary attack surface |
| R18 | Pricing jumps between 29 and 30 seats | [D GH #28] | KGTEC-4 | Revenue/UX defect |
| R19 | Private key `khadamat.pem` sits in the workstation project root (not in git) | [D workspace CLAUDE.md] | owner chose to leave it 2026-11-02 | Exposure if the folder is shared |

## Decisions waiting on the owner (from `#kg-decisions`, Jira)

KGTEC-4 pricing · KGTEC-5 production checkout branch and CI access path · KGTEC-6 host changes · KGTEC-16 delete `rag-db-improvements` ·
KGTEC-18/R1 backup design for `kgkg_vec` and `_parts` · KGTEC-19 penetration test · KGTEC-20 disclose or remove reconstructed rows ·
ADR-0007 ratification (retrospective; does not settle R1 or R5) · enabling the support chat publicly (privacy notice, retention periods, RBAC mode).

## Claims in older docs that this register overrides

- Doc 11 §11.6: "the warehouse is derived; its loss costs a rebuild, not data" is **not established** (see R1, doc 23).
- README (before this change): "38 vehicles, rag-db-improvements branch, verified 2026-07-15" was stale.
- Doc 02/ADR-0001 "one read-only SQLite per vehicle": superseded in part by ADR-0007 and doc 23.
- Docs 01, 03, 06, 07 (before 2026-11-04): described the per-company `OrgRole` rank/scope model and the Members/Org chart/Roles tabs; both were removed (migration 0016, org-graph canvas). Corrected in those documents; see [06](06-permissions-rbac.md) §6.6.
- Doc 18 (2026-08-05) and doc 02 (before 2026-11-04): "no TLS" / "HTTP only" and systemd-only process model; current: TLS at nginx and container deployment ([33](33-system-design.md)).

## Findings from the 2026-11-04 verification pass (code, not production)

- **F1 Guidance anchors orphaned.** `guidance/content.js` and `hintRules.js` target `team-tabs`, `team-add`, `team-search` and signals `team.memberCount` / `team.drawer` that belonged to the removed `TeamView`; no component renders them ([07](07-frontend.md) §7.3, [13](13-guidance-system.md)). Fix is application code and was not made here.
- **F2 openapi.yaml lagged two views**: `POST api/admin/company-requests/` and `GET api/admin/company-requests/<id>/` existed in code but not in the spec; added 2026-11-04 (`test_openapi_routes.py` checks routes, not methods).
- **F3 No automated test** for the Grafana/VNC admin gates (FR-29) and no dedicated test module for the AI allowance (FR-25) or behaviour insights (FR-30).
- **F4 Timer units not in the repository.** Docs 02/11 name `kgkg-alerts.timer`, `kgkg-pipeline.timer`, `kgkg-detect.timer` and `kgkg-coverage.timer`, but no unit file
  for them exists under `ops/` (only `kgkg-watchdog`, `kgkg-outbox`, `kgkg-qa-nightly` and `kgkg-hostjobs` do). They are therefore hand-installed on the host
  or defined elsewhere **[U]**; rebuilding the host from the repository would not recreate them (compare the PR checklist item "nothing needs a hand-install").
