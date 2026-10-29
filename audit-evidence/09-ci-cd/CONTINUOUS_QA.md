# Continuous testing

## On every push (GitHub Actions, `.github/workflows/ci.yml`)

Unit and integration tests (backend and frontend), honest branch coverage
with a ratchet floor, SAST, dependency, secret and image scans; see
`REPRODUCE.md`. Since 2026-10-29 the backend suite runs **in a new random
order on every push** (`manage.py test --shuffle`), so a test that leaks state
into another fails the build instead of hiding behind a lucky order. The log
prints `Using shuffle seed: N`; `manage.py test --shuffle N` reproduces it.

Why this was added: the first shuffled runs (2026-10-29) failed in 2 of 3
random orders while the default order passed (defect D-31). After the fix,
the default order and seeds 11, 22 and 4242 all passed (850 tests), and the
first CI run with a generated seed (3961382278, run 40839842409) passed 896
tests.

## Nightly (QA stack on the production host) — ready, awaiting approval

`qa/nightly.sh`, scheduled by `ops/qa/kgkg-qa-nightly.timer` (01:30 UTC):

1. `qa/stack.sh up <head of work>`, production-like (throttles on)
2. Browser E2E (`qa/run_e2e.sh`)
3. Passive DAST (`qa/dast/run_zap.sh baseline`)
4. Single-user performance baseline against the thresholds (`qa/perf/run_perf.sh baseline`)
5. Stack torn down; results kept in `/opt/KGKG_qa/nightly/` (30 runs)

Results become Prometheus metrics (`kgkg_qa_suite_ok{suite}`,
`kgkg_qa_e2e_tests{result}`, `kgkg_qa_perf_p95_ms{kind}`,
`kgkg_qa_last_run_timestamp_seconds`) through the node-exporter textfile
collector that the deploy and the watchdog already use. The alert sweep
(`api/alert_rules.py`, `_qa`) warns by the existing SMS path when a suite
failed or results are older than 36 hours, and is silent until the first
run reports (tests: `api/test_qa_alert_rule.py`).

Verified by hand on 2026-10-29 against `174654d`: stack up, **E2E 42/42**,
summary and metrics written, stack down. In that run DAST aborted before
scanning (the ZAP image had been removed and the script stopped under
`set -e`; it now pulls on demand) and the performance baseline breached its
assistant threshold (p95 5.3 s vs 4 s) while the host ran at load ~40 from
unrelated jobs (observation O-2). The timer is **not installed**: it is
standing configuration on the production host and needs the owner's
approval (action A-07).

Install, when approved:

```bash
install -m 644 /opt/KGKG/ops/qa/kgkg-qa-nightly.service /opt/KGKG/ops/qa/kgkg-qa-nightly.timer /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now kgkg-qa-nightly.timer
```

## Before promotion

Work in progress on branch `claude/testing-cicd-assessment-review-1u9yhl`
(another session) makes `kgkg-promote` require a recorded passing E2E run
for the commit; it is not merged at the time of writing.
