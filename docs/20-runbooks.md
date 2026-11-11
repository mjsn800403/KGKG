# 20 — Runbooks

What to do when a specific thing goes wrong. Each runbook is: how you notice,
how you confirm, what to do, and how you know it is fixed. Commands run on the
production host from `/opt/KGKG_work` unless stated. General command snippets
are in [11.7](11-operations-deployment.md#117-operational-runbook-snippets);
severity and escalation are in
`audit-evidence/11-operations-and-support/SUPPORT_AND_INCIDENTS.md`.

After any SEV1/SEV2: a short postmortem and a regression test.

## R1 — The site is down or returns 502

* **Notice:** SMS "API down", blackbox probe red in Grafana, users report it.
* **Confirm:** `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health/`
  and `docker ps --filter label=kgkg.env=prod`. If loopback is healthy but the
  public probe is not, go to R2.
* **Do:** if a deploy happened in the last hour, `ops/deploy/deploy.sh --rollback`.
  Otherwise read the backend container log (`docker logs --tail 200 <kgkg-backend container>`; the `journalctl -t kgkg-backend`
  tag belongs to the retired systemd unit and may be empty **[U]**) and
  `ops/deploy/deploy.sh --reload`.
* **Fixed when:** the smoke suite passes
  (`KG_SMOKE_NGINX=http://127.0.0.1 ops/deploy/smoke.sh http://127.0.0.1:8000 http://127.0.0.1:3000`).

## R2 — An alert fired but the site is up

* **Usual cause:** the probe's DNS lookup failed, not the service. The alert
  rules check loopback health first and only raise a network warning after 30
  minutes.
* **Do:** check Cloudflare status and the blackbox DNS list; do not restart
  anything. If an alert is wrong, fix the rule (`api/alert_rules.py`) with a
  test, not by muting it.

## R3 — Pages are slow

* **Usual cause:** CPU starvation from a runaway process (a crawler, a build,
  a stuck pipeline job), not the database.
* **Confirm:** `top -o %CPU`; Grafana → server tab.
* **Do:** pause the pipeline from the admin panel or stop the offending unit.
  Never `pkill -f` a pattern that also matches your own SSH command.
* **Fixed when:** p95 latency on the Grafana business tab is back to normal.

## R4 — A deploy failed

* The pipeline stops on its own and production is untouched unless the
  promote step started; a failed production smoke rolls back automatically.
* **Read:** the log under `/opt/KGKG_release/logs/`.
* **Common causes:** the live commit is not an ancestor of yours (merge
  `/opt/KGKG` HEAD into `work` first); a bandit or pip-audit finding; a test
  expecting old behaviour.
* "push to origin failed" is a warning only — the deploy itself is fine.

## R5 — The AI assistant fails or is slow

* **Answer text fails** (LLM provider down): the bot is configuration
  (`METIS_BOT_ID`, plus the fallback chain `METIS_FALLBACK_BOT_IDS` that the chat route tries automatically; `KG_LLM_MODEL` is only the label shown in the
  AI-cost insights, `api/insights.py`, and does not choose a model); point `METIS_BOT_ID` at another
  provider's bot in the frontend env and `ops/deploy/deploy.sh --reload`. Retrieval, ranking and
  the diagnostic engine run locally and keep working.
* **Slow first answer:** the KG-Reranker loads on first use (≈15 s, then ≈4 s).
  To switch it off, remove `RAG_RERANK=1` from `.env.prod` and reload.
* **Feature flags** in `api/flags.py` switch individual features off without
  a deploy.

## R6 — The disk is filling up

* **Confirm:** `df -h /`; Grafana disk alert.
* **Do:** `docker image prune` (the deploy keeps the live and rollback images),
  trim old logs under `/opt/KGKG_release/logs/`, check that backup rotation is
  running. Never delete vehicle schemas or `kgkg_vec` tables by hand.

## R7 — Restore the portal database

* Pre-deploy dumps: `/opt/KGKG_release/db-backups/` (last three, `.pgdump`).
  The hourly off-host snapshot also holds `portal.dump`.
* **Rehearse on staging first.** `pg_restore` into a scratch database, run
  `ops/observability/verify_restore.py`, then swap.
* **Fixed when:** row counts and max ids match the snapshot and the smoke
  suite passes.

## R8 — Add a vehicle

1. Crawl the manual, then queue its ZIP or drop the parsed `.db` into
   `Database_warehouse/`.
2. Start the pipeline from the admin panel (or let autopilot take it):
   catalog → RAG → diag → **pgcar** (loads the car into PostgreSQL and
   removes the SQLite file) → audit.
3. **Fixed when:** the car opens in the browser and an assistant question
   about it returns a source from that car.

## R9 — SMS alerts are not arriving

* The provider refuses some bodies silently: Persian text without the opt-out
  line, or anything that looks like a link, an `@domain`, an IP or a
  percentage. Use the envelope in `api/alert_rules.deliver`.
* **Confirm:** `python3 -I ops/observability/watchdog.py --dry-run`; a real send
  returns a long record id — anything else means nobody was paged.

## R10 — Human support chat: incident, shutdown and rollback

The chat is human-only (no AI). Everything here is a person's decision; none of it is a deploy.

* **Before enabling it in production:** the CI job `support-chat-e2e` must be green for the commit
  being enabled: every browser test in `support-chat.spec.js` (21 on 2026-11-04: S1-S10, F1-F10) runs on a throwaway stack
  (`qa/e2e/support-chat-stack.sh`, own SQLite, no env file, no production data) and
  `qa/e2e/support_chat_guard.py` fails the job if any is skipped, failed or missing. Its
  `results/` are kept as the artifact `support-chat-e2e-<sha>` (90 days). The shared QA stack
  (`qa/run_e2e.sh`) still skips them; that is intended, the chat is not enabled there (#78).

* **Notice:** a `support:unanswered` alert (warning) or `support:unanswered:critical` (see below), staff
  reporting waiting visitors, `manage.py support_health --fail-on warn` exiting 1, or a privacy/abuse
  report. The alert rule is **off by default**: `KG_SUPPORT_ALERTS=1` raises the warning on the existing
  alert engine (dashboard only, never an SMS); `KG_SUPPORT_ALERTS=page` also raises the critical alert
  past `KG_SUPPORT_WAIT_CRIT_S`, which the existing delivery path SMSes once (6 h cooldown). Both close by
  themselves when the queue is answered. Until a person sets it, check `support_health` by hand in hours.
* **Confirm:** `python manage.py support_health` (waiting count, oldest wait, by intent; read-only),
  `curl -s https://<site>/kg-api/api/support-chat/status/` (`enabled`, `mode`).
* **Emergency shutdown:** remove `KG_SUPPORT_CHAT_ENABLED` (or set it to anything but `1`) in
  `.env.prod` and in the web server environment, then `ops/deploy/deploy.sh --reload` (the widget also needs the web container to see the change, see the row in 11). New visitor
  threads stop immediately; existing threads and staff replies keep working; the widget disappears
  after the web server picks up the change. Rollback of the shutdown is setting it back to `1`.
* **Staff cannot sign in or see threads:** check `KG_SUPPORT_RBAC` first. Unset or `off` means flat
  admin access. A typo is enforced (403 `rbac_invalid_mode`): fix the value, reload. In `enforce` with no
  owner (403 `rbac_no_owner`) set `KG_SUPPORT_OWNERS` to an active admin username. Run
  `python manage.py support_roles check` (read-only) to see exactly why.
* **Inbox not updating:** the console shows «اتصال زنده قطع است» while the stream is down and keeps
  refreshing every 20 s; it catches up the moment the stream returns (the browser retries after 3 s, doubling
  to 60 s, and reconnects at once when the network returns). If the stream is the problem, check nginx
  `/kg-api/api/events/stream/` (`proxy_buffering off`, `limit_conn kg_sse 8`, read timeout above the 300 s
  recycle; `ops/governance/test_nginx_sse.py` guards these) and R1. Each open admin or portal tab holds one
  gunicorn thread for up to 300 s (24 threads in total, 3 workers x 8): many open tabs can starve the API.
* **Production runs a commit that is not on `work`** (staging aborts with "does not contain the live commit"):
  do not force anything. Fetch the commit from its deploy tag, push it to a branch, merge it into `work`
  through a PR (as #72 did for `3a65964`), and the next staging passes. `deploy.sh --rollback` and `--reload`
  never depend on GitHub. A guard that stops direct `deploy.sh` runs from promoting off-work commits exists as a
  tested patch, not yet applied (`docs/superpowers/specs/2026-11-03-promote-drift-prevention.md`).
* **Backups of the chat data:** it lives in PostgreSQL. The hourly off-host snapshot includes
  `/root/backup_snapshot/portal.dump` (`pg_dump -Fc`, contains the support-chat and outbox tables), and
  `/opt/KGKG_release/db-backups/db-*.pgdump` is taken before each promote. Check an archive without
  restoring: `pg_restore -l <file> | grep -c 'TABLE DATA'`. A restore into a scratch database has not been
  rehearsed, and `verify_restore.py` does not cover `portal.dump`.
* **Abuse or spam wave:** raise nothing blindly; read `KG_SC_*` limits in 11, mark threads spam from
  the console, and shut down per above if limits do not contain it.
* **Never** run `purge_support_chat --apply`, enable notifications, or promote from this runbook.
* **Fixed when:** `support_health` reports `ok`, the status endpoint reports the intended state, and the
  incident is noted in the CHANGELOG or issue with ids only (never message text or contact details).

## R11 — Rebuild the project from nothing (host lost, or a new owner starting cold)

**Never executed end to end** ([47](47-engineering-followups.md) E3). It is the order of work and where each
piece comes from, not a tested script; the first person to run it should correct it here. What must be
obtained from the owner beforehand is listed in [48 §48.5](48-handoff.md).

* **Notice:** the host is unrecoverable, or the project is being moved to a new host or team.
* **Confirm what you actually hold** before touching anything: a clone of `work`; `.env.prod` and
  `.env.production` from escrow (R3); a `portal.dump` and its age; whether any copy of `kgkg_vec`, the parts
  catalogs and the media exists (R1) or only the source ZIPs; the nginx origin certificate.
* **Do, in this order:**
  1. **Code:** `git clone -b work`; CI rebuilds both images from any commit (job `images`).
  2. **Host:** Ubuntu 24 with Docker, nginx and PostgreSQL 16; layout, units and env files per
     [11.1](11-operations-deployment.md); nginx from `ops/nginx/`; the forced-command keys per 11.3 "Keys and
     privilege". Timer units that exist only on the old host are **not** in the repository (doc 27 F4):
     recreate them from docs 11 and 25.
  3. **Secrets:** place the env files; record names only ([29](29-environment-reference.md)). If any secret
     may have been exposed with the old host, rotate it (`manage.py rotate_secrets`, [18](18-security-hardening.md)).
  4. **Portal database:** restore `portal.dump` as in R7, run `ops/observability/verify_restore.py`.
  5. **Vehicle content:** restore `kgkg_vec` and the parts catalogs from a backup if one exists. If none
     does, re-ingest from the source ZIPs through the pipeline (R8, [15](15-vehicle-schema.md),
     [16](16-parts-catalog.md)); the time this takes for the whole catalogue is unknown **[U]**.
  6. **Derived data:** rebuild the RAG index (`run_rag_build.sh`) and diagnostics (`run_diag_build.sh`).
  7. **Observability and error tracking:** `ops/observability/`, [31](31-ops-files-reference.md).
  8. **Release:** stage the commit, run the full E2E, then a person runs `kgkg-promote <sha>`.
  9. **Outside the host:** DNS and proxy at Cloudflare, the GitHub Actions secrets for the `stage` job, and
     the provider allow-lists if the address changed ([24](24-integrations.md)).
* **Fixed when:** the smoke suite passes through the public address, a seat can sign in by OTP, a granted
  vehicle opens with content, the assistant cites that vehicle, and the watchdog dry run is clean (R9).
* **Afterwards:** write down what differed from this runbook, and close or update R1, R3 and E3.
