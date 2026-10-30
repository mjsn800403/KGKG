# Service levels, on-call and escalation

Adopted 2026-10-30. This is the first version; before it, the service had
monitoring and paging but no stated target and no written escalation path,
which the audit of 2026-10-29 recorded as the weakest part of criterion 8.

Targets here are **chosen to be met from measured behaviour**, not aspirational.
Where the current measurement does not support a number, this document says so
rather than promising it.

## 1. Availability

| | Commitment |
|---|---|
| Service | the customer portal and its API at `kgtechvault.com` |
| Target | **99.5 % per calendar month**, measured monthly |
| Error budget | 3 h 39 m per 30-day month |
| Measurement | the external HTTP probes in Prometheus (`probe_success`, blackbox, four targets through Cloudflare), evaluated over the month |
| Excluded | announced maintenance (see §4), failures of Cloudflare or the upstream network, and the customer's own connectivity |

**Why 99.5 % and not 99.9 %.** Over the seven days to 2026-10-29 the four
public probes measured 100 %, 99.99 %, 98.80 % and 98.63 %. The two weakest
would already breach 99.9 %, so committing to it would be committing to
something not yet true. 99.5 % is met today with headroom. Raising the target
is a decision for after §6 is done, not before.

What is *not* claimed: no uptime guarantee with financial remedy, no
multi-region redundancy. The service runs on one host (see §7).

## 2. Response targets

Measured from when a report reaches a channel in
`SUPPORT_AND_INCIDENTS.md` §"Channels", during the hours in §3.

| Severity | Meaning | First response | Workaround or fix |
|---|---|---|---|
| **P1** | Service unreachable, sign-in broken for all users, or a cross-tenant data exposure | 1 hour | work starts immediately and continues until resolved |
| **P2** | A major function unusable — manual content, the assistant, purchase flow — with the rest of the service working; or a security issue below cross-tenant | 4 hours | 2 working days |
| **P3** | A function degraded or wrong with a workaround; a single company or seat affected | next working day | next release |
| **P4** | Cosmetic, documentation, or a request for change | 3 working days | scheduled, no commitment |

A severity is set by the operator on first response and may be raised by the
customer's objection; it is never lowered silently.

These are response targets, not resolution guarantees, with one exception: a
P1 cross-tenant data exposure is worked continuously and disclosed to affected
customers, whatever else is in flight.

## 3. Hours

| | |
|---|---|
| Business hours | Saturday–Wednesday 09:00–17:00, Thursday 09:00–13:00, Iran time (IRST/IRDT) |
| Closed | Friday and Iranian public holidays |
| P1 outside hours | the paging path in §5 operates 24/7; the 1-hour target applies at all times |
| P2–P4 outside hours | the clock starts at the next business hour |

## 4. Maintenance

Deployments are a blue/green container swap and do not need a window: the
last promote measured **6.7 seconds** of frontend unavailability
(`deploy-20261029-191834`), and the backend swap is gapless. Routine releases
are therefore not announced and not excluded from the availability figure.

Work that does need a window — a host reboot, a database engine change, a
storage migration — is announced at least 48 hours ahead through the in-product
notice and is excluded from §1. The PostgreSQL cutover of 2026-10-29 is the
only such event so far.

## 5. On-call and escalation

The service is operated by a team of two. This section describes what is true,
not a rota borrowed from a larger organisation.

| Level | Who | Reached by | When |
|---|---|---|---|
| L1 — automated | `api/alert_rules.py`, swept every 5 minutes by `kgkg-alerts.timer` | SMS to the phone numbers in `KG_ALERT_PHONES` | any `infra:` key opening; 6 h per-key cooldown |
| L2 — the watchdog over L1 | `ops/observability/watchdog.py`, every 5 minutes | SMS under its own key, 12 h cooldown | the alerting engine itself is dead, stalled, or a systemd unit has failed |
| L3 — operator | repository owner (`@mjsn800403`) | the SMS above; then the host | every page |
| L4 — retrieval and RAG | `@alistp27` | operator escalates | assistant or diagnostic-engine faults |

**Escalation rule.** If a P1 has no first response within 30 minutes of the
page, the operator calls L4 directly rather than waiting for the second SMS.
If a P1 is not understood within 2 hours, roll back first
(`ops/deploy/deploy.sh --rollback`) and diagnose afterwards — the previous
release's images are retained for exactly this.

**Honest limitations, because an evaluator will find them anyway:**

* Two people, no rota, no follow-the-sun coverage. If both are unreachable,
  nobody responds. This is the single largest gap in this document.
* Paging is SMS only, to a single Iranian provider. If that provider is down,
  paging is down. The watchdog detects a dead alert engine but cannot detect a
  dead SMS path end-to-end; `_sms_failures()` only sees failures the provider
  reports.
* There is no Alertmanager and no Prometheus `rule_files` — by design.
  `api/alert_rules.py` *is* the rule evaluator, so a metric reaches a phone
  only if a rule is written there. Anything not in that file is unmonitored
  for paging purposes, however good the dashboard looks.
* `deliver()` sends an SMS for every `infra:` key regardless of severity, so
  there is no severity-based routing and no quiet hours.

## 6. What has to be true before the target is raised

In order, each with the finding it answers:

1. Investigate the two probes measuring 98.6–98.8 % and either fix the cause or
   document why those targets are expected to fail. **Until this is done, no
   higher target is credible.**
2. Alert on error-budget burn, not only on hard down — a rule in
   `api/alert_rules.py` over `probe_success` across the month.
3. Move staging and the QA stack off the production host, so a test run cannot
   consume the service's own CPU (§7).
4. End-to-end verification of the SMS path, so a dead provider is detectable.
5. Second host or managed failover. Until then 99.9 % is not a target this
   architecture can honestly hold.

## 7. Known single points of failure

One VPS runs production, staging, the QA stack, the observability stack,
GlitchTip and Umami. A host failure is a total outage; a heavy test run
competes with production for CPU. Disk was 74.5 % of 290 G on 2026-10-30.
Backups are pulled hourly off-host by an internal server and were
restore-verified on 2026-10-27, so the data survives the host — the service
does not.

## 8. How this document is kept true

Reviewed at each MINOR or MAJOR release, and after every P1. The availability
figure for the previous month is recorded in the release record. If a number
here cannot be evidenced from Prometheus or from a deploy log, it is removed
rather than rounded.
