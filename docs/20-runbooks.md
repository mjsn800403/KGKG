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
  Otherwise read `journalctl -t kgkg-backend -n 200 --no-pager` and
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

* **Answer text fails** (LLM provider down): the bot id and model are
  configuration (`METIS_BOT_ID`, `KG_LLM_MODEL`); point them at another
  provider's bot and `ops/deploy/deploy.sh --reload`. Retrieval, ranking and
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
