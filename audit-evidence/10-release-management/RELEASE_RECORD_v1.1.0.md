# Release record — v1.1.0

Opened 2026-10-30 at the moment `VERSION` was bumped, filled as the evidence
arrived, closed when the release was promoted. That order is the point: the
v1.0.0 record was reconstructed two days after the fact, and this one is the
first in the project's history written the way `RELEASE_POLICY.md` asks.

| Field | Value |
|---|---|
| Version | **1.1.0** |
| Commit (full sha) | `8f6df9433ea95fec440940d4dd5146123fd29046` |
| Previous production commit | `5e4543a3db2b519c54f1538e34beaa2bec4b7138` |
| Classification | **minor** — new capability (pgvector dense retrieval, KG query adapter) plus the delivery and alerting work below |
| Date promoted (UTC) | 2026-10-30 05:32 → 05:43 |
| Deploy tag | `deploy-20261030-053247` — annotated `deployed 8f6df9433 version 1.1.0` |
| Approved and promoted by | the person at the host who typed `promote` |

## Verification

Every row is machine output on the **promoted commit**, not carried forward
from an earlier one. That distinction is why this release took two attempts.

| Check | Result | Evidence |
|---|---|---|
| CI run | **green**, all five jobs incl. `stage` | runs 41004433907 / 41004442108; `ci_evidence.sh verdict 8f6df943…` → `pass` |
| Backend tests | **1170** on PostgreSQL, randomised order | CI; and again in the server gate on the exact commit |
| Frontend unit tests | **178**, 0 failed | CI; server gate |
| Coverage | **58 %** combined, floor 57 | CI `backend` job |
| Security gates (bandit, pip-audit, npm audit, gitleaks, hadolint, shellcheck) | **all pass** | CI `security` job; server gate runs the same three via `ops/security/scan.sh` |
| Image scan (Trivy, fixable HIGH/CRITICAL) | **0 / 0** | CI `images` job |
| Staging smoke | **pass** — `GATE=pass`, `SMOKE=pass`, against a sanitized clone of the production database | `/opt/KGKG_release/staging.env`, staged 05:04 UTC |
| E2E suite | **42 passed / 42**, 0 failed, 0 flaky, `scope=full` | `/opt/KGKG_release/e2e/8f6df943….env`, 05:08 UTC |
| **Load profile within criteria** | **PASS on all four thresholds**, `error_rate 0.00 %` over 8347 requests | `../06-performance-and-load/run3-v1.1.0/` |
| **DAST full scan reviewed** | **`FAIL-NEW 0`, `WARN-NEW 2`, `PASS 141`** | `../07-security/dast-v1.1.0/` |
| Production smoke after promote | **pass**, twice (staging stack and production) | deploy log `deploy-20261030-053247` |
| Open High/Critical defects | **none** | `../14-risk-and-corrective-actions/CORRECTIVE_ACTIONS.md` |

### The load profile, in full

```
profile=load  requests=8347  throughput=21.38 req/s  iterations=1963  max_vus=10
error_rate=0.00%  http_req_failed=0.00%

latency (ms)        avg     p50     p90     p95     p99     max
page (landing)     12.5    10.8    17.7    20.9    27.4    43.4
api (me/fleet/..)  21.5    11.3    41.9    63.8   102.0   683.3
assist (RAG)      653.7   581.4   967.1  1065.3  1662.5  6394.3

kg_page_ms p(95)<1500 PASS   kg_api_ms p(95)<500 PASS
kg_assist_ms p(95)<4000 PASS kg_errors rate<0.01 PASS
```

Production was measured throughout, not assumed: the sampler polled the live
`/api/health/` every 2 s and recorded **97 of 97 samples HTTP 200**, p95
16.1 ms, max 19.4 ms, while host load peaked at 5.52 of 16 vCPU. The run uses
`KG_RL_DISABLE=1` and raised content-guard ceilings, because every virtual user
comes from one IP and a handful of accounts and with the throttles on the test
would only measure the rate limiter.

One observation kept rather than smoothed: an earlier run of the same profile
an hour before showed an API `max` of 4595.9 ms against a p99 of 98.1 ms. It did
not recur (683.3 ms here). Two runs, same code path, one with a 4.6-second tail
— that shape points at a cold cache on first touch rather than contention. Noted
because a record that only keeps the flattering run is not evidence.

### The DAST scan, and what it can and cannot say

141 active rules pass with zero failures, including SQL injection, Server Side
Template Injection (direct and blind), Remote OS Command Injection (time-based),
NoSQL injection and cloud-metadata exposure.

The two warnings are pre-existing and triaged, not new findings:

| Warning | Status |
|---|---|
| `CSP: style-src unsafe-inline` ×12 (Medium) | **Accepted** — React and manual content require it (`SECURITY_ASSESSMENT.md`) |
| `Cross-Origin-Embedder-Policy missing` ×6 (Low) | **Intentionally off** — the Turnstile iframe needs it off |

The 2026-10-27 full scan reported the same `141 pass, 0 fail` and the same two
warnings, so this run says the security posture did not move. The QA proxy has
no WAF, so these findings are what the application itself permits; production
additionally runs ModSecurity with the OWASP core rule set, which makes the
scan stricter than production reality. That is the right direction for a gate.

## Two promote attempts, and why the first was refused

**Attempt 1, `281ffd7`, 04:33 UTC — aborted by the gate. Production untouched.**

All three evidence gates passed first:

```
CI evidence     : 281ffd7c3 passed every required job on GitHub
staging evidence: 281ffd7c3 passed gate=pass and smoke=pass 0h 58m ago
E2E evidence    : 281ffd7c3 passed 42 browser tests 0h 30m ago
```

`deploy.sh` then re-ran the full suite on the exact commit, as the policy
requires — *"CI's result is evidence, not permission"* — and one test failed:

```
FAIL: test_current_epoch_keys_match_the_server_side_keys
  self.assertTrue(0 < d['ttl'] <= shield.EPOCH)
AssertionError: False is not true
[04:40:30] DEPLOY ABORTED: gate failed; production untouched
```

It was not a flaky test. `/api/shield/key/` computed `int(EPOCH - now % EPOCH)`
on a float, so for the final second of every 600-second epoch the result
truncated to **zero** and the endpoint told the client its freshly minted key
had already expired — one call in 600. Logged as **D-43**, fixed in PR #37 with
two tests that fail on the old arithmetic (`ttl fell to 0 at +599.5s`) and pass
on the new.

Severity Low, and the reason is worth stating rather than inflating: the client
already clamps (`Math.max(5, k.ttl - 5)` in `kg_frontend/src/lib/shield.js`), so
the cost was one spurious key refetch and no user ever saw an error. The real
cost was a deploy gate that failed at random, and a gate nobody trusts is a gate
people learn to override.

**Attempt 2, `8f6df94`, 05:32 UTC — promoted.** Every verification row above was
re-run on this commit rather than carried over from `281ffd7`, although the diff
between them is one line of integer arithmetic and two tests. Carrying evidence
forward "because the diff is small", on the first release meant to demonstrate
this policy, is how gates erode — and an auditor comparing this record's sha
against `env-load.txt` and `env-full.txt` would find it in a minute.

## Changes

`docs/CHANGELOG.md`, `## 1.1.0`. In summary: the CI gate on promotion
(`ci_evidence.sh`), alert rules that cannot starve silently plus a test that
rejects the shape, failed-unit paging that survives a deploy, a transient unit
that no longer outlives its run, image retention that runs on the staging path,
branch protection on `main`, the governance files, `.mailmap`, the markdown
ignore fix, three documents reconciled with the host, and D-43.

No customer-visible behaviour changes, which is also why the load and DAST rows
were expected to be clean: there is no new request path. That is a reason to
expect a clean result, never a reason to skip the run.

## Rollback plan

`ops/deploy/deploy.sh --rollback` returns to `5e4543a`'s images, which are
retained; a pre-deploy database backup is in `/opt/KGKG_release/db-backups/`.
Migrations in this release: **none** — confirmed by the gate's
"migrations are rollback-safe" step.

One consequence specific to this release: `deploy.sh` refreshes
`/usr/local/bin/{kg-deploy-gate,kg-ci-gate,kgkg-promote}` and
`/usr/local/lib/kgkg/watchdog.py` from the deployed tree, so a rollback also
reverts the failed-unit paging, the transient-unit reset and the CI gate on
promotion. Acceptable for a short rollback, not as a resting state: if 1.1.0 is
rolled back, re-apply those files by hand and record it here.

## Post-deploy

| Check | Result |
|---|---|
| Deploy duration | 05:32:47 → 05:43:19, with 6.7 s of frontend unavailability on the last comparable swap |
| Production smoke | 22 checks pass, incl. metrics refused publicly (403) and `sites-enabled` clean |
| Public endpoints | `/` 200, `/purchase` 200, `/login` 200, `/kg-api/api/health/` 200 |
| Containers | `kgkg-backend-20261030-053247`, `kgkg-frontend-20261030-053247`, both healthy |
| Failed systemd units | none |
| Alerts opened within the hour | none |
| Disk | 215 G of 290 G, **75 G free (75 %)** — the promote's retention took 8 sha-tagged image pairs to 5 |

### A note on the retention, since this release is what ships it

`kgkg-promote` resolves `deploy.sh` from the **live** tree before the code
swap, so this promote ran `5e4543a`'s deploy script and its old inline
retention block — which is why the log shows the dangling prune (859.5 MB) and
no `removed N superseded release image(s)` line. The block still did its job:
8 pairs down to 5, disk 68 G → 75 G free.

The new behaviour this release adds — retention on the **staging** path, which
runs on every push to `work` rather than only on a promote — takes effect from
the next staging run, because the live tree now contains
`ops/deploy/prune_images.sh`. Verified separately rather than assumed.
