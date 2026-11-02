# Postmortem — 49 minutes blind to the application's own metrics

| | |
|---|---|
| Date | 2026-10-27, 14:00–14:48 UTC (49 minutes) |
| Severity | **P3.** No customer impact. Detection capability was lost, not the service |
| Customer impact | **None measured.** All four external probes stayed up for every sample in the window; the site served normally throughout |
| Detected by | nobody at the time. Found on 2026-10-29 while auditing the alert rules, two days later |
| Pages sent | **zero** |
| Written | 2026-10-30 |

This is written blameless and it is written about an incident that produced no
outage, because the interesting failure is not what broke — it is that nothing
said so, and that the same silence would have covered a real outage.

## What happened

`up{job="kgkg_app"}` — Prometheus's scrape of the application's own metrics
endpoint on the dedicated `:8081` listener — was 0 for 25 of the 36 samples
between 14:00 and 14:48 UTC, and the series was absent entirely for the other
10 samples of that 46-sample window. In the same window:

* `probe_success` for all four blackbox targets: **up for every sample**
* `up{job="node"}`: **up for every sample**
* production containers: `kgkg-backend-20261027-082926 ... Up 6 hours (healthy)`
* `SMOKE PASSED` on the deploy at 14:40:52

So the application was serving customers the whole time. What was lost was our
ability to see it.

The window coincides with a burst of deploy activity: staging runs at 14:19:06,
14:24:57 and 14:35:25, two runs that aborted on the deploy lock at 14:27:25 and
14:30:59, a status call at 14:30:52, and a full promote at 14:40:52
(`/opt/KGKG_release/logs/deploy-20261027-14*.log`). The scrape recovered as
that activity ended.

## Why nobody was told

This is the whole point of the postmortem.

`KG_backend/api/alert_rules.py::_infra()` is the rule evaluator — there is no
Alertmanager and no Prometheus `rule_files`, by design. At the time, its only
liveness rule was:

```
up{job="node"} == 0
```

Two independent reasons that rule could not fire for this:

1. **It covered the wrong job.** There was no rule for `job="kgkg_app"` at all.
   The node exporter was healthy, so the one liveness rule in the system was
   satisfied and said nothing.
2. **Its shape cannot detect absence.** A PromQL expression `<metric> == 0`
   matches no series when the metric does not exist. For 10 samples the series
   was gone entirely, and "no series returned" is byte-for-byte the answer the
   engine gets when everything is healthy. Every infra rule in the file had
   this shape, including the probe rules — meaning a dead blackbox exporter
   would have disarmed **all** availability paging and reported four healthy
   probes.

The watchdog over the alerting engine was running and healthy. It checks that
the engine is alive, not that the engine's rules cover anything.

## Root cause

The rules were written one at a time, each about the thing it was added for,
and each took the same shape. Nothing ever asked the question "what does this
rule do when the exporter behind it dies?" — so the monitoring system trusted
its own inputs, and silence was encoded as health.

The scrape interruption itself is a contributing cause, not the root cause; the
root cause is that losing a signal was indistinguishable from the signal being
good.

## What was done

Landed 2026-10-29 in PR #11, live in production as `5e4543a`:

* `max_over_time(up[Nm]) == 0` across **all** jobs, replacing the node-only
  rule, so a dead scrape target pages under its own key
* `absent()` guards on `probe_success` and `container_start_time_seconds`, so a
  dead exporter is loud rather than quiet
* watchdog freshness as a rule, closing the loop the other way
* rules for `kgkg_db_up`, `kgkg_rag_index_present` and the summed 5xx counter,
  which had no rule at all
* `RuleShapeTests` in `api/test_alert_infra.py`: it reads back **every** PromQL
  string the sweep sends and fails if any `== 0` comparison stands without a
  window or a companion `absent()` query. This is the part that matters — the
  class of bug is now rejected at test time, not the one instance of it.
* failed systemd units now page, which is how a related blindness was found:
  `boot.mount` had been failed since the 09:52 reboot that morning and the
  metric recorded all 56 samples of it while nobody was told

Verification: 21 tests in `api/test_alert_infra.py`; on the host after the
promote, `grep -c "absent(" alert_rules.py` is 3 and the watchdog reports
`prometheus ... 8 targets`.

## What was not done

* The scrape interruption's own mechanism was never isolated. By the time it
  was noticed it was two days gone and not reproducible from retained data.
  It is now *detectable*, which is the fix that was actually needed; if it
  recurs there will be a page and a timestamp to investigate.
* No alert on error-budget burn — only on hard down. In
  `SLA_AND_ONCALL.md` §6 as item 2.
* Prometheus retention is short enough that this window was at the edge of what
  could still be queried on 2026-10-29. Retention is not yet a documented
  decision.

## What this says about the rest of the monitoring

Honestly: the dashboards were fine and the alerting was not, and the
difference was invisible from the dashboards. Anything that exists only as a
Prometheus metric still reaches nobody's phone unless a rule for it is written
in `api/alert_rules.py` — so "it's in Grafana" is not the same as "we would be
told". That is now written in `CONTRIBUTING.md` where a rule author will read
it.

One irony worth recording: within an hour of the failed-unit paging going
live, it reported a *true* fault about a transient staging unit that had
already been reported red to CI and already been fixed — one tick from an SMS
every 12 hours about nothing. That was fixed in PR #12 the same evening. A
signal that fires about nothing becomes a signal people ignore, which is the
same failure as not firing at all, arriving from the other direction.
