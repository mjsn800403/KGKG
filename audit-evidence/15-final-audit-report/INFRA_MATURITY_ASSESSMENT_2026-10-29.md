# KGKG — Software & Operational Infrastructure Maturity Assessment

**Date:** 2026-10-29 18:20 UTC
**Scope:** repository `mjsn800403/KGKG`, production host `103.75.197.155`, GitHub Actions, observability stack
**Method:** direct inspection only. Every claim below was read off a command output, a CI run, a live
HTTP response, or a file on the production host. Nothing is taken from documentation that was not
separately verified against reality.

**Overall score: 70 / 100** (actual state, not intended state)

---

## 0. Verdict on the stated deficiency

> "Manual code deployment, the absence of automated CI/CD pipelines, and the lack of performance and
> error monitoring tools indicate insufficient operational infrastructure maturity and pose a
> significant risk to service stability."

**Status: substantially resolved — roughly 80 % closed. Three of the four clauses are no longer true.**

| Clause | Verdict | Proof |
|---|---|---|
| "Manual code deployment" | **No longer true.** Deployment is a containerised blue/green swap performed by `ops/deploy/deploy.sh` with automatic rollback. A human types `kgkg-promote <sha>`; the human does not edit files on the server, and `deploy.sh` refuses a dirty live tree. | `/opt/KGKG_release/state.env` (`CURRENT`/`PREVIOUS`/`DEPLOYED_AT`), 25+ `deploy-*` tags, `ops/deploy/test_promote.sh` |
| "Absence of automated CI/CD pipelines" | **No longer true.** A five-job GitHub Actions pipeline runs on every push and PR, and on `work` it then stages that exact commit on the server against a sanitised copy of the production database. | `.github/workflows/ci.yml` (333 lines), `mutation.yml`, run 40907083135 green end-to-end |
| "Lack of performance monitoring" | **No longer true.** Prometheus + Grafana + Loki + Alloy + blackbox + node-exporter + cAdvisor, four provisioned dashboards, plus k6 baseline/load/stress/soak suites with recorded results. | 15 containers up 8 h; all 8 Prometheus targets healthy; `audit-evidence/06-performance-and-load/` |
| "Lack of error monitoring" | **No longer true** for capture, **partially true for notification.** GlitchTip is self-hosted and wired into Django; a 5-minute alert sweep plus a watchdog-of-the-watcher run as systemd timers. But the rule engine has a proven silent-failure class (below), so some outages are captured and never announced. | `glitchtip-gt-*` containers; `kgkg-alerts.timer`, `kgkg-watchdog.timer` active; `api/alert_rules.py` |

The residual risk has **moved**. It is no longer "there is no pipeline and no monitoring". It is now
"the pipeline is not the only road into production, and the alerting layer can fail silently".

---

## 1. What an auditor will find and be unable to argue with

- **CI**: backend suite runs on PostgreSQL 16 (the production engine) in randomised order
  (`--shuffle`) with branch coverage and an upward-only ratchet file; migrations-match-models check;
  JUnit XML and HTML coverage published as 90-day artifacts. Frontend: eslint warning ratchet,
  `node:test` with coverage, production build. Security job: shellcheck over all of `ops/`, hadolint,
  gitleaks (filesystem mode, deliberately, so a broken scan fails loudly), bandit with a triaged
  baseline, pip-audit, npm audit, plus operations tests for the deploy gate, promote script, staging
  sanitiser and watchdog. Images job: both production Dockerfiles build, the backend boots, and Trivy
  fails the build on any fixable HIGH/CRITICAL.
- **Privilege separation that actually holds.** The CI SSH key is pinned to a forced command
  (`kg-ci-gate`) with no `deploy` verb; a leaked CI secret buys a staging run, not a production
  deploy. Matrix-tested by `ops/deploy/test_gate_roles.sh`. Verified on the host: `authorized_keys`
  contains exactly two forced-command entries (`kg-ci-gate`, `kg-sync-gate`), both with
  `no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding`.
- **Documentation that matches the code.** 16 numbered docs, a formal SRS (`docs/00-srs.md`,
  20 functional + 14 non-functional requirements against ISO/IEC/IEEE 29148 and ISO 25010, each
  naming its verifying test), six dated ADRs, and `docs/openapi.yaml` enforced by a test over all
  90 routes. I spot-checked the nginx documentation against the host: `/etc/nginx/sites-enabled/kgkg`
  is **byte-identical** to `ops/nginx/kgkg.conf`, and the two `conf.d` files match the release too.
- **Testing depth.** 1141 backend tests, 178 frontend, 41 Playwright E2E, k6 load/stress/soak, ZAP
  DAST (baseline, API and full, reports attached), mutation testing of the authorisation modules
  with 14 surviving mutants hunted down and killed. 42 defects logged with regression tests.
- **Backups that have been restored.** Hourly off-host pull by an internal server through a
  forced-command gate. Verified live at 18:00 UTC today: `portal.dump` (25 MB `pg_dump -Fc`, the
  live PostgreSQL portal DB), `db.sqlite3`, `terms.db`, `translation.db`, code and config, with a
  `SNAPSHOT_AT` stamp. The watchdog alerts if that stamp goes stale (6 h threshold).
- **Edge hardening.** Cloudflare in front; origin certificate; HSTS, a nonce-based CSP,
  `X-Frame-Options: DENY`, COOP/CORP, permissions-policy. ufw admits 80/443 from Cloudflare ranges
  only. 0 open Dependabot alerts, 0 secret-scanning alerts.
- **Evidence package.** `audit-evidence/` — 16 numbered sections, machine output throughout, with an
  honest status vocabulary where "a document existing is never by itself a Verified".

---

## 2. Findings — what still gives an evaluator a legitimate criticism

Ordered by how badly each one damages the story.

### F-1 — Production is running a commit whose CI is red. **Severity: critical**

`/opt/KGKG_release/state.env` reports `CURRENT=536ac91`. That commit is the tip of
`rag-db-improvements`, and its CI run (40926974767) **failed**: the backend job died at the coverage
ratchet with `TOTAL ... 55%` against `coverage floor: 56%`.

It reached production because the server-side gate (`gate.sh` → stage → smoke) is independent of
GitHub's verdict: `kgkg-promote` requires a *staging* record, and nowhere does it read the GitHub CI
conclusion for the sha. So the pipeline is **not the only road into production**, which is the exact
shape of the original deficiency wearing new clothes.

Compounding it: `536ac91` is not on `work` or `main` at all. `main` is 11 commits behind `work`,
`qa-audit` is 50 commits ahead of `main` and unmerged, and `claude/testing-cicd-assessment-review-1u9yhl`
(which contains the E2E-gated promote and ~110 extra tests) is also unmerged. The code in production
is on a fourth line of development.

**Fix:** make `kgkg-promote` query the GitHub check-run conclusion for the exact sha and refuse
anything not green, with the override being a typed phrase that is logged. Then reconcile the four
branches onto one trunk.

### F-2 — The alerting engine has a proven silent-failure class. **Severity: critical**

There is no Alertmanager and no `rule_files` — by design; `api/alert_rules.py::_infra()` *is* the
rule evaluator, querying Prometheus over HTTP and sending SMS. Verified on the host:

- `grep -c "absent(" api/alert_rules.py` → **0**. Not one guard.
- The only liveness rule is `up{job="node"} == 0`. There is **no rule for `up{job="kgkg_app"}`**.
- `max_over_time(probe_success[Nm]) == 0` and `kgkg_qa_suite_ok == 0` have the same shape.

A `== 0` expression matches nothing when the metric disappears, and the engine reads "nothing
matched" as healthy. So if an exporter or the app scrape dies, availability paging **disarms itself**.
This is not theoretical: `up{job="kgkg_app"}` was 0 for about 50 minutes in the week to 2026-10-29
and no message was sent.

The fix exists and is tested — `infra-rules.patch` in `/root/pending/` (14 KB, with
`test_alert_infra.py`) — and it is **not deployed**, because it is application code.

**Fix:** land `infra-rules.patch`; wrap every availability rule in `absent()`; add
`up{job="kgkg_app"}`; add a test that fails if any rule in the module is a bare `== 0`.

### F-3 — The watchdog's failed-unit paging was silently reverted by the last promote. **Severity: high**

`watchdog-page-failed-units.patch` was installed on the host; `deploy.sh` refreshes
`/usr/local/lib/kgkg/watchdog.py` from the release on every promote, and the promote of `536ac91`
duly overwrote it. Verified by md5: the installed file, `/root/pending/watchdog.py.pre-units` and
`/opt/KGKG/ops/observability/watchdog.py` are **all the same hash** — the patch is gone.

Consequence: a failed systemd unit does not page anyone. (No unit is currently failed.) This is also
a process finding: host-side hand-installs do not survive deployment, so they must not be the
delivery mechanism for anything that matters.

### F-4 — SSH port 22 is open to the entire internet, and so is 3389. **Severity: high**

`ufw status`:

```
[ 1] 3389/tcp    ALLOW IN    Anywhere
[ 2] 22/tcp      ALLOW IN    Anywhere
[20] 3389/tcp (v6) ALLOW IN  Anywhere (v6)
[21] 22/tcp (v6)   ALLOW IN  Anywhere (v6)
```

`systemctl is-active cloudflared` → **inactive**; `cloudflared` is not installed. So the Cloudflare
Tunnel described in `docs/11-operations-deployment.md` §"How GitHub reaches this server", in
`ops/deploy/README.md` and in the merged PR titled *"Connect CI to the server through a Cloudflare
Tunnel (port 22 stays closed)"* **is not the live configuration**. CI reaches the host over plain
public SSH.

Two separate problems: an unnecessary public attack surface (3389/RDP on a Linux box serves no
purpose at all), and a documentation-versus-reality gap, which is the finding an auditor enjoys most
because it devalues every other document.

**Fix:** either bring the tunnel up and close 22, or correct the docs and the ADR to describe
direct SSH honestly and add fail2ban plus source restrictions. Delete the 3389 rules either way.

### F-5 — Repository governance is effectively absent. **Severity: high**

- `GET /branches/main/protection` → **404 Branch not protected**. `GET /rulesets` → `[]`.
  Nothing requires CI to pass before a merge to `main`; nothing prevents a direct push to it.
  The pipeline is advisory, not a gate.
- The `production` environment exists with **no protection rules** (no required reviewers).
- Missing from the repository root: `README.md`, `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`,
  `CODEOWNERS`, `.github/pull_request_template.md`.
- The repository is **public**. With no LICENSE and no SECURITY.md, that is a deliberate-looking
  choice with none of the hygiene that normally accompanies it.
- Author identity is fragmented: 9 distinct `name <email>` pairs for about 3 humans plus bots.
- Conventional-commit discipline is good but not uniform: 49 of the last 60 subjects conform.

### F-6 — Release management is policy without artifacts. **Severity: medium**

`VERSION` says `1.0.0`; `RELEASE_POLICY.md` and `RELEASE_RECORD_TEMPLATE.md` exist; rollback is
real and tested. But: **zero GitHub Releases, and zero SemVer git tags** — the only tags are 25+
`deploy-<timestamp>` markers. No alpha/beta channel (staging plays the RC role, which the docs state
honestly). No release record has actually been filled in. `docs/CHANGELOG.md` has no per-version
release entries.

For criterion 6 this is the weakest area in the whole estate: the policy is written, the practice has
produced no evidence.

### F-7 — Issue tracking and support have no history. **Severity: medium**

Issue templates (`defect.yml`, `support-escalation.yml`) are in place and good. **`gh issue list`
returns nothing — zero issues, ever.** In-product ticketing (`CompanyRequest`, 28 tests, ~5 live
tickets) is real but is customer-facing, not engineering defect tracking. There is no SLA, no on-call
rota, no escalation policy, and no postmortem has been written.

### F-8 — Coverage is honest but short of its own target. **Severity: medium**

60 % combined on `work` (floor 56); the commit in production measures 55 %. Critical modules are
excellent — `access.py` 99/96, `quota.py` 100/100, `mediaauth.py` 100/100, `portal_auth.py` 100/100,
`ratelimit.py` 100/97 — and mutation-tested. Offline tooling sits at 18 %, and the stated 80 %
ambition is not met. No coverage service (Codecov/Coveralls) and no badge; coverage artifacts expire
after 90 days, so there is no long-run trend an auditor can inspect.

### F-9 — Pipeline coverage gaps. **Severity: medium**

E2E, k6 and ZAP are **not** triggered by CI — the security job only syntax-checks those files
(`node --check`). They run on the server, by hand or by the nightly timer. The E2E-gated
`kgkg-promote` exists on an unmerged branch; the version installed on the host is the Oct 27 one and
does **not** require an E2E record. `qa/nightly.sh` and `kgkg-qa-nightly.timer` exist in the repo
but no `kgkg-qa-nightly` timer is active on the host.

### F-10 — Single host, no HA, shared blast radius. **Severity: medium**

One VPS runs production, staging, the QA stack, the observability stack, GlitchTip and Umami.
7-day `avg_over_time(probe_success[7d])` across the four probes: 100 %, 99.99 %, **98.80 %**,
**98.63 %** — the last two are roughly 2 hours of weekly unavailability, and there is no declared SLO
to measure against. Disk is at 70 % of 290 G. `/boot` had to be mounted by hand after the 09:52
reboot. Load average 7–8 on 16 vCPU with everything co-resident.

### F-11 — Knowledge management has no platform and no named owners. **Severity: low**

Docs-as-code is a defensible and well-executed answer to criterion 2 (ADR-0006, a maintenance
protocol in force since 2026-07, docs shipped with the change). But there is no wiki/Confluence/Notion,
ownership is assigned by role rather than to named people, and no review cadence has been evidenced.

### F-12 — No independent penetration test, no backlog export. **Severity: low (but unarguable)**

Automated DAST is thorough; nobody independent has attacked the system. Criterion 1 asks for a
Product Backlog; there is no backlog tool and therefore no export. Criteria 11–13 (market evidence,
HR participation, personnel qualifications) remain blocked — they cannot be produced from a
repository, and no data was invented.

---

## 3. Score

| # | Criterion | Score | Driver |
|---|---|---:|---|
| 1 | Design & architecture documentation | 82 | SRS + 6 ADRs + enforced OpenAPI; no backlog export |
| 2 | Knowledge-management infrastructure | 68 | Docs-as-code works; no platform, no named owners (F-11) |
| 3 | Technical infrastructure for development | 85 | Full toolchain exercised; issue tracker unused (F-7) |
| 4 | Source-code history & traceability | 62 | Good commits, but no branch protection, no governance files, 9 identities (F-5) |
| 5 | CI/CD infrastructure | 72 | Strong pipeline, but prod runs a red-CI commit and CI is not a merge gate (F-1, F-5, F-9) |
| 6 | Versioning & release management | 55 | Policy without artifacts: no Releases, no SemVer tags, no filled record (F-6) |
| 7 | QA/QC processes | 84 | Unit→mutation→E2E→load→DAST all executed with evidence; no pentest, no sign-off record |
| 8 | Post-development support | 55 | In-product tickets real; zero engineering issues, no SLA, no on-call (F-7) |
| 9 | Automated test coverage | 65 | 60 % honest, auth modules 96–100 %; 80 % target unmet, no trend service (F-8) |
| 10 | DevOps process maturity | 70 | Blue/green + rollback + full observability, undercut by silent alerting and open ports (F-2, F-3, F-4, F-10) |
| | **Overall** | **70** | |

### How to read 70

This is a **genuinely above-average small-team setup** — the pipeline, the evidence package, the
privilege separation on the deploy key and the restore-verified off-host backup are better than most
organisations of this size can show. It is not a 90, for three reasons that are each demonstrable in
one command:

1. Production is running code that CI rejected (F-1).
2. The alerting layer cannot be trusted to announce an outage (F-2, F-3).
3. `main` has no protection, so the pipeline is advice rather than a gate (F-5).

Those three are what turns "we have CI/CD and monitoring" into "we have CI/CD and monitoring that
can be bypassed and that can go quiet". Every one of them is fixable in days, not months.

---

## 4. Remediation, ordered

**Tier 1 — closes the audit's own words (days)**

1. `kgkg-promote` refuses a sha whose GitHub check-runs are not green; override is a logged typed phrase. (F-1)
2. Land `infra-rules.patch`; `absent()` on every availability rule; add `up{job="kgkg_app"}`; add a test that bans bare `== 0` rules. (F-2)
3. Re-land `watchdog-page-failed-units.patch` through the release so the next promote cannot revert it. (F-3)
4. Delete the 3389 ufw rules; either activate the tunnel and close 22, or correct the docs/ADR and add fail2ban. (F-4)
5. Protect `main`: require the four CI jobs, require a PR, require a review; add required reviewers to the `production` environment. (F-5)
6. Reconcile `work`, `qa-audit`, `claude/testing-cicd-assessment-review-1u9yhl`, `rag-db-improvements` onto one trunk, then promote from it. (F-1)

**Tier 2 — closes criteria 4, 6, 8 (one to two weeks)**

7. Add `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS`, PR template. Decide public-versus-private deliberately. (F-5)
8. Tag `v1.0.0`, cut a GitHub Release with notes generated from the commits, fill the first release record, start per-version CHANGELOG entries. (F-6)
9. Unify git author identities via `.mailmap`. (F-5)
10. Open GitHub issues for every item in `CORRECTIVE_ACTIONS.md` so criterion 8 has a history; publish an SLA and an on-call/escalation page; write a postmortem for the 50-minute unpaged outage. (F-7)

**Tier 3 — closes criteria 5, 9, 10 (a month)**

11. Run E2E, k6 and ZAP from CI on a schedule, publishing results as artifacts; activate `kgkg-qa-nightly.timer`. (F-9)
12. Raise the coverage floor toward 70 %, starting with `portal.py` (64 %); add a coverage trend service and badge. (F-8)
13. Declare an SLO (99.9 % suggested) and alert on error budget burn; investigate the two probes sitting at 98.6–98.8 %. (F-10)
14. Move staging and the QA stack off the production host. (F-10)
15. Commission an independent penetration test. (F-12)

**Not fixable from here:** criteria 11–13 need market research, contracts and CVs. Templates T-11/T-12/T-13 exist and must be filled from real records.

---

# Addendum — state after remediation, 2026-10-29 19:45 UTC

The sections above are kept exactly as written at 18:20 UTC, so the before and
after are both auditable. Everything below was done in the hours after, and
every claim names the command or run that proves it.

**Score after remediation: 75 / 100** (was 70).

## What changed

| Finding | Status | Proof |
|---|---|---|
| F-1 Production on a red-CI commit | **Closed** | `/opt/KGKG_release/state.env` → `CURRENT=5e4543a…`, `PREVIOUS=536ac915e`. CI run 40934280389 green on all five jobs including `stage`. `536ac91` is now an ancestor of `work` |
| F-1 Promote could not see CI | **Closed** | `ops/deploy/ci_evidence.sh`; on the host it reads `536ac915e` as `fail backend=failure` and the gate refuses the normal word, printing `promote 536ac915e without ci and staging and e2e`. `test_promote.sh` 22 → 40 checks |
| F-2 Alerting could starve silently | **Closed** | 3 `absent()` guards live in `/opt/KGKG/KG_backend/api/alert_rules.py`; `up` watched across all jobs; `RuleShapeTests` fails any future bare `== 0`; 21 tests in `api/test_alert_infra.py` |
| F-3 Watchdog unit paging reverted by promote | **Closed** | `/usr/local/lib/kgkg/watchdog.py` md5 `32800c26…`, no longer the pre-patch `a2233f33…`. It survived this promote because it came through the release |
| F-4 3389 open to the internet | **Closed** | `ufw delete allow 3389/tcp` (v4+v6); confirmed unreachable from outside while 22 still answers. Rule files backed up at `/root/ufw-user*.rules.bak-20261029-183306` |
| F-4 Docs claimed a tunnel that was not running | **Closed** | `docs/11` and `ops/deploy/README.md` now state the live posture first, dated, with the commands that establish it |
| F-5 `main` unprotected | **Closed** | Required checks backend/frontend/security/images, strict, PR required, `enforce_admins`, no force-push, no deletion, conversation resolution; `production` environment given a required reviewer |
| F-1 Four divergent lines of development | **Mostly closed** | `work` == `rag-db-improvements` == `5e4543a`. `main` still diverges (see below) |

## Release evidence for 5e4543a, the first promote with all three gates satisfied

- **CI**: run 40934280389, five jobs green, 58 % combined coverage against a floor raised 56 → 57
- **Server gate**: 1170 backend tests on PostgreSQL, 178 frontend, bandit / pip-audit / npm audit all PASS, migrations rollback-safe
- **Staging**: `STAGED_SHA=5e4543a…`, `GATE=pass`, `SMOKE=pass`, against a sanitised clone of the production database
- **E2E**: 42 passed, 0 failed, 0 flaky, `E2E_SCOPE=full`, recorded at `/opt/KGKG_release/e2e/5e4543a….env` — including content shield, per-request CSP nonce, anti-framing headers, server-side logout and entitlement-scoped fleet listing
- **Production smoke**: 22 checks across backend, frontend and the reverse proxy, all pass; metrics refused publicly (403); `sites-enabled` clean
- **Live**: `/` 200, `/purchase` 200, `/login` 200, `/kg-api/api/health/` 200, `/kg-api/api/metrics/` 403
- Tagged `deploy-20261029-191834`; rollback to `536ac915e` remains one command

## A bug the remediation itself created, and closed

Within an hour of the failed-unit paging going live, the watchdog reported
`FAIL systemd_units  failed: kgkg-stage-20261029-184014.service` — a transient
unit from the staging `deploy.sh` had aborted earlier in the evening. systemd
keeps a non-zero exit in `failed` for ever and nothing cleared it, so a run
that was already red in CI and already fixed was one tick from an SMS every 12
hours. A true signal that fires about nothing is how people learn to ignore the
signal.

`kg-deploy-gate` now resets its own unit on failure (PR #12, merged). The
launch path got tests for the first time — `test_gate_roles.sh` 21 → 24 checks,
asserting that a failed run reports its own status *and* resets its unit, and
that a clean run resets nothing. The leftover unit was cleared by hand before
it paged; `systemctl list-units --state=failed` is now empty.

## Revised scores

| # | Criterion | Was | Now | Why it moved |
|---|---|---:|---:|---|
| 1 | Design & architecture documentation | 82 | **83** | Two documents corrected against the host; backlog export still missing |
| 2 | Knowledge-management infrastructure | 68 | **70** | The docs are now verifiably accurate on the point easiest to check; still no platform, still no named owners |
| 3 | Technical infrastructure for development | 85 | **85** | Unchanged; the issue tracker is still empty |
| 4 | Source-code history & traceability | 62 | **76** | `main` protected and CI is a merge gate; governance files, 9 author identities and the missing pre-June history remain |
| 5 | CI/CD infrastructure | 72 | **86** | The pipeline is now the only road into production, fail-closed and tested; first fully green end-to-end run on `work`; trunk reconciled. E2E/k6/ZAP still not CI-triggered |
| 6 | Versioning & release management | 55 | **58** | One release promoted with complete evidence; still no GitHub Release, no SemVer tag, no filled release record |
| 7 | QA/QC processes | 84 | **86** | E2E served as release evidence for a real promote; the deploy gate's launch path is tested |
| 8 | Post-development support | 55 | **55** | Unchanged. Zero engineering issues, no SLA, no on-call, no postmortem |
| 9 | Automated test coverage | 65 | **68** | 58 % measured on the trunk, floor ratcheted up, `alert_rules.py` covered; 80 % ambition still unmet |
| 10 | DevOps process maturity | 70 | **82** | Alerting can no longer go quiet and has a regression guard; the host no longer reverts the fix; 3389 closed; docs match reality. Single host, no SLO, no on-call rota remain |
| | **Overall** | **70** | **75** | |

## What an evaluator can still legitimately raise

Unchanged from the list above, minus what closed:

1. **Criterion 6 is the weakest at 58.** Zero GitHub Releases, zero SemVer tags — only `deploy-<timestamp>` markers — and no release record has been filled in despite the template and policy existing. One tag and one filled record would move this more than any other hour of work available.
2. **Criterion 8 at 55.** `gh issue list` is still empty, so the templates have no history; no SLA, no on-call rota, no escalation policy, and the 50-minute unpaged outage still has no postmortem.
3. **Repository hygiene.** No `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS` or PR template, on a **public** repository. Nine author identities for about three people.
4. **`main` still diverges from `work`** by 11 commits each way. `main` holds three commits `work` lacks, including a fix for four failing RAG tests. One reconciliation pass is owed.
5. **Production's own checkout sits on branch `rag-db-improvements`,** and `deploy.sh` pushes `HEAD:<that branch>` after every promote. That is how a fourth line of development came to exist in the first place, and it will happen again. `/opt/KGKG` should be on `work` or detached.
6. **Two host files are ahead of the live release** by hand: `kg-deploy-gate` (installed tonight as an interim; PR #12 makes it permanent at the next promote). Hand-installs are how F-3 happened — this one is logged and reverts to a release-identical file.
7. **`xrdp` is still installed and enabled.** The port is firewalled, so it is unreachable, but the service should be removed.
8. **Coverage 58 % against an 80 % ambition**; offline tooling near zero, including the 602 statements of training commands that arrived with `536ac91`. No coverage trend service, and artifacts expire after 90 days.
9. **E2E, k6 and ZAP are not CI-triggered**, and `kgkg-qa-nightly.timer` is in the repository but not active on the host.
10. **One host** runs production, staging, QA and observability. 7-day probe availability 98.6–98.8 % on two of four probes, with no declared SLO. Disk 74.5 %.
11. **No independent penetration test.** Criteria 11–13 need contracts, CVs and market research; the templates exist and nothing was invented.
12. **A promote briefly reads its own commit as `unknown`.** `deploy.sh` pushes to the production checkout's branch, which starts a second CI run on the same sha, so `ci_evidence.sh` answers `unknown still running` for a few minutes afterwards. Fail-closed and harmless, but it is the kind of thing to know before it surprises someone at 2 a.m.
