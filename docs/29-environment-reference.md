# 29 — Environment variable reference (operational and tuning variables)

**Scope.** Every variable below is read by code in this repository. Values are never recorded here: only names, meaning,
type, default and consumer. Defaults were read from the source on `origin/work` @ `f078878` **[C]**. Where a production
value is set in `.env.prod` it is not shown (and not known to this document) **[U]**. Persian version:
[fa/29-environment-reference.md](fa/29-environment-reference.md).

Conventions: *bool* = parsed with the helper named in the consumer (`'0'` disables for most `RAG_*` switches, `'1'` enables
for `ADMIN_REQUIRE_2FA`); *num* = parsed by `_env_num` / `float()` / `int()` at import time, so a bad value fails at start-up,
not at use. All `KG_ALERT_*`, `RAG_*`, `KG_CG_*`, `KG_PIPELINE_*` values are read **once at import**; changing `.env.prod`
needs a backend restart (a deploy does that).

Related: [11-operations-deployment.md](11-operations-deployment.md), [25-ops-inventory.md](25-ops-inventory.md),
[08-ai-assistant-rag.md](08-ai-assistant-rag.md), [23-data-layer.md](23-data-layer.md),
[generated/inventory.md](generated/inventory.md) (the complete machine-generated list).

## 29.1 Web, security and framework switches

| Variable | Default | Consumer | Meaning and implication |
|---|---|---|---|
| `DJANGO_CORS_ALLOW_ALL` | `DEBUG` value | `KG_backend/KG_backend/settings.py:104` | `true` allows every origin. Must stay off in production; otherwise `DJANGO_CORS_*` allow-list applies. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty list | `settings.py:277` | Comma-separated origins trusted for CSRF checks on cross-origin POSTs. |
| `DJANGO_SSL_REDIRECT` | `false` | `settings.py:267` | Django-level HTTP→HTTPS redirect. **Keep off** behind the Next.js proxy: it was switched on 2026-09-07, made server-side rendering call `https://127.0.0.1:8000` and fail, and was turned off again (comment in `settings.py`). TLS is terminated by nginx. |
| `ADMIN_REQUIRE_2FA` | unset (off) | `api/portal.py:958` | `1` forces the second factor (OTP) for the admin login. See [26-auth-and-sessions.md](26-auth-and-sessions.md). |
| `RUN_MAIN` | set by Django autoreload | `api/apps.py:21` | Only the autoreload child process warms caches in development; `false` is the watcher parent. Not an operator setting. |
| `KG_RELEASE` | `dev` (metrics) / unset (Sentry) | `settings.py:361`, `api/metrics_exposition.py:221` | Release identifier (commit SHA) attached to GlitchTip/Sentry events and exposed as the `release` label of the build-info metric. Set by the deploy. |
| `KG_TESTING` | unset | `KG_backend/KG_backend/jsonlog.py:166` | When set, structured JSON logging is not installed (tests use plain output). Also skipped when `test` is in `argv[:2]`. |
| `API_BASE_INTERNAL` | `http://backend:8000` in `docker-compose.yml` | `kg_frontend/src/utils/api.jsx` | Base URL the Next.js server uses for server-side calls to Django (`docker-compose.yml:31`). Override if the backend moves. |
| `KG_MEDIA_ROOT` | `/media` in compose | `kg_frontend/src/app/[brand]/[year]/[model]/[...path]/page.jsx:27` | Directory the frontend reads vehicle media from when rendering the manual viewer. |
| `KG_PUBLIC_MEDIA_PREFIX` | `/kg-api/media` | `api/sst.py:74` | Public URL prefix under which nginx serves the media store. A deployment fact, hence overridable. |

## 29.2 Storage locations and database access

| Variable | Default | Consumer | Meaning and implication |
|---|---|---|---|
| `KG_DB_PATH` | unset | `settings.py:132` | Path of the SQLite main DB (development / frozen former production file). With PostgreSQL there is no path. |
| `KG_DATA_DIR` | parent of `KG_DB_PATH`, else `BASE_DIR` | `settings.py:133`; 12 files | Directory for non-DB data (warehouse, `_rag/`, spools). Introduced because with PostgreSQL there is no DB file to take the parent of. |
| `KG_LOG_DIR` | `/var/log/kgkg` | `settings.py:288`; `KG_backend/Dockerfile:6` | Where the application writes its rotating log files. |
| `KG_WAREHOUSE` | `/opt/KGKG/KG_backend/Database_warehouse` | `KG_backend/scripts/wal_checkpoint.py:21` | Warehouse root for the WAL-checkpoint helper (SQLite files only; `kgkg_vec` is unaffected). |
| `KG_PG_USER` | `kgkg` | `settings.py:147` | PostgreSQL role for the portal DB. |
| `KG_PG_PASSWORD` | empty | `settings.py:148` | **Secret.** Empty means peer/trust auth. Never write the value in docs or logs. |
| `KG_PG_HOST` | `127.0.0.1` | `settings.py:150` | Empty string = local Unix socket (peer auth). The deploy gate uses the socket as `root`. |
| `KG_PG_PORT` | `5432` | `settings.py:151`; also `api/rag/config.py:688` | Port; also forwarded into the pgvector DSN. |
| `KG_PG_TEST_NAME` | unset | `settings.py:157` | Name of Django's test database. The gate sets a per-run name (`test_kgkg_gate_$$`) so a CI gate and a deploy gate cannot drop each other's database. |
| `KG_CARDB_ADMIN_DSN` | `dbname=kgkg_vec` | `api/cardb_pg.py:203` | libpq DSN used by `adopt()`/loaders to create and fill per-car schemas in `kgkg_vec`. Requires create-schema rights. See [23-data-layer.md](23-data-layer.md). |
| `RAG_PGVEC_DB` | `kgkg_vec` | `api/rag/config.py:686` | Database name of the pgvector store. **Set to PostgreSQL in production** (`RAG_VEC_BACKEND=pgvector`, `RAG_FTS_BACKEND=pg`, observed 2026-11-04); active only when `RAG_VEC_BACKEND`/`RAG_FTS_BACKEND` select PostgreSQL. |
| `RAG_INDEX_DB` | `_rag/index.rag.db` | `api/rag/config.py:33` | Alternate RAG index file for offline experiments. Unset in production. |
| `RAG_PARTS_DB` | resolved by `config.py:66` | `api/rag/config.py:66` | Override for the parts catalog DB used by the assistant. |
| `RAG_FEEDBACK_DB` | `_rag/feedback.db` | `api/rag/config.py:654` | Sidecar SQLite with query log and ratings. **Staging/QA stacks mount production's `_rag/` and must set this**, otherwise their queries and ratings land in production's store and re-rank live results. |

## 29.3 Backend process model and container runtime

| Variable | Default | Consumer | Meaning |
|---|---|---|---|
| `KG_BIND` | `127.0.0.1` | `ops/docker/backend.Dockerfile:49`, `frontend.Dockerfile:28` | Listen address inside the container (nginx is the only public listener). |
| `KG_PORT` | `8000` | `backend.Dockerfile:49`; `ops/docker/containers.sh:39` | Backend listen port; `containers.sh` picks a free host port per container. |
| `KG_HEALTH_PORT` | `18999` | `backend.Dockerfile:40`; `containers.sh:39` | A second port unique to the container, used by the Docker `HEALTHCHECK` so the main port alone cannot say which container answered. |
| `KG_WORKERS` | `3` (staging uses `2`) | `backend.Dockerfile:51`; `deploy.sh:424` | gunicorn worker processes. Worker class `gthread`, `--timeout 300`, recycled by request count (comment in the Dockerfile). |
| `KG_THREADS` | `8` (staging `4`) | same | Threads per worker. Concurrency = workers × threads. |
| `KG_FE_ENV` | `/opt/KGKG/kg_frontend/.env.production` | `ops/docker/containers.sh:11` | Env file passed to the frontend container. |
| `KG_ENV_FILE` | `DEFAULT_ENV` of the command; `/tmp/ci-dummy.env` in CI | `management/commands/rotate_secrets.py:118`; `ci.yml:43,354` | Env file read/rotated by `rotate_secrets`; CI points it at a dummy file. |
| `KG_ENV_FILE_WATCHDOG` | `/opt/KGKG/KG_backend/.env.prod` | `ops/observability/watchdog.py:47` | Env file the host watchdog reads for SMS credentials. Read-only use. |
| `KG_HOSTJOBS_DIR` | empty | `api/hostjobs.py:33`; `ops/hostjobs/hostjobs_daemon.py` | Spool directory of the host-jobs bridge. Inside the container it is set; empty means "run the job locally" (host timers, management commands). |
| `KG_BACKEND_DIR` | `/opt/KGKG/KG_backend` | `ops/hostjobs/hostjobs_daemon.py:19` | Backend checkout the host daemon runs jobs from. |
| `KG_SPOOL` | per stack | `ops/deploy/deploy.sh:417-420` | Spool dir given to staging containers so staging jobs do not enter production's queue. |

## 29.4 Ingestion pipeline and crawlers

| Variable | Default | Consumer | Meaning |
|---|---|---|---|
| `KG_PIPELINE_BATCH` | `32` | `management/commands/run_pipeline.py:398` | Items per batch in the embedding stage. |
| `KG_PIPELINE_THREADS` | `12` | `api/pipeline.py:308` | OpenMP threads for the pipeline; an explicit `KG_PARSE_WORKERS`/`KG_PIPELINE_THREADS` outranks auto-sizing. Deliberately below total cores so serving stays responsive. |
| `KG_PIPELINE_DISK_RECOVERY_MARGIN` | `1.1` | `api/ingest.py:134` | Recovery headroom multiplier for the disk-floor guard, so the alert does not flap at the boundary. |
| `KG_PARSER_PATH` | resolved in `ingest.py:90` | `api/ingest.py` | Path of the manual parser executable/script. |
| `KG_TIS_PARSER_PATH` | resolved in `ingest.py:107` | `api/ingest.py` | Path of the TIS parser. |
| `KG_CG_PAGE_WARN` / `KG_CG_PAGE_BLOCK` | `300` / `900` | `api/contentguard.py:27` | Content guard: page-count thresholds (warn / block) for an ingested manual. |
| `KG_CG_MEDIA_WARN` / `KG_CG_MEDIA_BLOCK` | `2000` / `6000` | `contentguard.py:28` | Same for media-file counts. |
| `KG_TIS_DIR` | `/root/Desktop/tis_crawler` | `api/tis_crawler.py:25` | Working directory of the TIS crawler. |
| `KG_TIS_DISPLAY` | `:99` | `tis_crawler.py:38` | X display exposed over VNC (localhost only, reached through an SSH tunnel) so a person can type the one-time code. |
| `KG_TIS_CHROME_PROFILE` | `/root/.chrome-tis-profile` | `tis_crawler.py:39` | Chrome profile directory kept between runs. |
| `KG_PS_DIR` | `/root/partsouq_crawl` | `api/partsouq_crawler.py:23` | Output root of the PartSouq VIN crawler (`<vehicle>/`). |
| `KG_PS_SCRIPT` | `/opt/KGKG/ops/partsouq/partsouq_vin_crawl.py` | `partsouq_crawler.py:25` | Script run **on the host** (the backend container has no `ops/` tree and asks the host through the host-jobs bridge). |

## 29.5 Alert thresholds (`api/alert_rules.py`, `api/monitoring.py`)

All numeric, import-time, overridable from `.env.prod` without code change. Alerts are delivered by SMS with a cooldown
(see [11-operations-deployment.md](11-operations-deployment.md), [25-ops-inventory.md](25-ops-inventory.md)).

| Variable | Default | Unit / window | Condition |
|---|---|---|---|
| `KG_ALERT_LOGIN_FAIL_IP` | 20 | per 15 min | Failed logins from one IP. |
| `KG_ALERT_LOGIN_FAIL_ACCOUNT` | 10 | per 15 min | Failed logins for one account. |
| `KG_ALERT_ADMIN_FAILS` | 5 | per 15 min | Failed admin logins. |
| `KG_ALERT_SMS_FAILS` | 3 | per 1 h | SMS delivery failures. |
| `KG_ALERT_AI_DEGRADED` | 0.3 | share per 1 h | Share of assistant answers served in degraded (non-LLM) mode. |
| `KG_ALERT_AI_MIN_N` | 5 | answers | Minimum answers before the degraded share is judged. |
| `KG_ALERT_AI_COST_X` | 3.0 | × | 24 h assistant cost vs the 7-day daily average. |
| `KG_ALERT_AI_COST_FLOOR` | 0.5 | currency units of the cost log | Ignore spikes below this absolute spend. |
| `KG_ALERT_SMS_COOLDOWN_H` | 6 | hours | Minimum gap between repeats of the same alert. |
| `KG_ALERT_ADMIN_NO2FA` | on (`1`) | switch | `0` silences the "admin without OTP" alert (for deliberate cases). |
| `KG_ALERT_DISK_PCT` | 85 | % used | Disk alert in the rule engine. |
| `KG_ALERT_MEM_FREE_PCT` | 10 | % free | Low free-memory alert. |
| `KG_ALERT_RESTARTS` | 3 | per 30 min | Container restarts. |
| `KG_ALERT_TLS_DAYS` | 14 | days | Certificate expiry warning. |
| `KG_ALERT_NETWORK_DOWN_MIN` | 30 | min | Almost every probe failing together is the host's network, alerted only when it lasts this long. |
| `KG_ALERT_SCRAPE_DOWN_MIN` | 10 | min | A metrics target missing; blip suppression so a promote does not page. |
| `KG_ALERT_WATCHDOG_STALE_S` | 1800 | s | Watchdog heartbeat older than this (its timer runs every 5 min; 30 min = six misses). |
| `KG_ALERT_5XX` | 5 | per hour | 5xx responses; chosen because the 7-day max before 2026-10-29 was 0. |
| `KG_ALERT_BUDGET_MIN_H` | 24 | hours | Minimum observed window before a budget-burn alert is judged. |
| `KG_ALERT_CANARY_DAYS` | 7 | days | Days between SMS paging canaries (one test SMS to every `KG_ALERT_PHONES` number, 10:00-12:00 Tehran); `0` turns the canary off. |
| `KG_ALERT_CANARY_WAIT_H` | 2 | hours | How long a canary may go without a delivered receipt before `infra:sms_canary` opens. |
| `KG_ALERT_QA_STALE_H` | 36 | hours | Nightly QA result older than this. |
| `KG_LOCAL_HEALTH_URL` | `http://127.0.0.1:8000/api/health/` | URL | Local health probe used by both the rule engine and the watchdog. |
| `KG_ALERT_DISK_WARN` / `KG_ALERT_DISK_CRIT` | 85 / 93 | % | Admin monitoring page colour thresholds (`monitoring.py:283-284`). |
| `KG_ALERT_MEM_WARN` | 92 | % used | Same page, memory. |
| `KG_ALERT_ERR_RATE` | 0.05 | ratio | Same page, error-rate warning. |
| `KG_ALERT_ERR_MIN_N` | 50 | requests | Minimum requests before the error rate is judged. |
| `KG_ALERT_LATENCY_MS` | 5000 | ms | Same page, latency warning. |

## 29.6 Host watchdog (`ops/observability/watchdog.py`, unit `kgkg-watchdog.service`)

| Variable | Default | Meaning |
|---|---|---|
| `KG_WATCHDOG_STATE` | `/var/lib/kgkg-watchdog` | State directory (failure counters, last-sent stamps). |
| `KG_WATCHDOG_STALE_S` | 1200 | The alert sweep runs every 5 min; 3 misses = stall. |
| `KG_WATCHDOG_COOLDOWN_H` | 6 | Gap between repeated notifications. |
| `KG_WATCHDOG_PAGE_AFTER` | 2 | Consecutive failures before paging (≈10 min detection with a 5-min timer). |
| `KG_WATCHDOG_UNITS_COOLDOWN_H` | 12 | Longer cooldown for "systemd unit failed" notices that need a human. |
| `KG_WATCHDOG_IGNORE_UNITS` | empty | Comma-separated units excluded from paging (still counted, so silencing is visible). |
| `KG_SNAPSHOT_STAMP` | `/root/backup_snapshot/SNAPSHOT_AT` | File whose age proves the hourly off-host snapshot ran. |
| `KG_TEXTFILE_DIR` | `/var/lib/node-exporter-textfile` | Node-exporter textfile directory; also used by `deploy.sh` to publish "what is live / when staged" metrics. |

## 29.7 RAG and assistant tuning (`api/rag/config.py`)

Details of how each knob affects the pipeline: [30-ai-assistant-deep-dive.md](30-ai-assistant-deep-dive.md) and
[08-ai-assistant-rag.md](08-ai-assistant-rag.md).

| Variable | Default | Effect |
|---|---|---|
| `RAG_EMBED_MODEL` | `bge-m3` | Embedding model. `build_rag` refuses to extend an index built with a different model. Also forwarded to host jobs. |
| `RAG_EMBED_FP16` | on | Half precision on GPU: ~2.3 GB → ~1.2 GB resident; ignored on CPU. |
| `RAG_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | Cross-encoder; active only with `RAG_RERANK=1`. |
| `RAG_RERANK_FUSE` | `1.0` | Blend weight of cross-encoder vs first-stage score; `1.0` = pure rerank (old behaviour). A 2-fold-CV result in the source comment favoured about 0.4 on the gold sets (EN nDCG@5 +0.12, FA Hit@1 +0.19). The default was not changed. |
| `RAG_SEARCH_SIM_FLOOR` | `0.55` | Minimum dense similarity to keep a hit. The source comment records that 0.55 leaves 1 of 81 real queries empty. |
| `RAG_SEARCH_OVERFETCH` | `4` | Candidate over-fetch multiplier before filtering. |
| `RAG_SEARCH_MAX_DEPTH` | `120` | Hard cap on candidate depth. |
| `RAG_SCOPE_FTS_K` | `30` | In-car FTS candidates. |
| `RAG_SCOPE_FTS_SCAN` | `4000` | Depth of the single-table FTS scan before intersecting with the car's blobs. |
| `RAG_CAR_VEC_K` | `40` | Dense depth for the pinned-car pass. |
| `RAG_CAR_BLOBS_CACHE` | `8` | Per-car blob-id sets kept in memory (~7 k ints each). |
| `RAG_FTS_CLEAN` | on | Shorter, cleaned MATCH string; measured p50 1168→819 ms (EN), 1048→842 ms (FA) per the source comment. |
| `RAG_FTS_W_TEXT` / `RAG_FTS_W_TITLE` / `RAG_FTS_W_COMP` | 1.0 / 4.0 / 12.0 | BM25 column weights (body, title, component). |
| `RAG_NEARMISS_GUARD` | on | Component-scope guard against near-miss evidence; `0` falls back to the title-anchored guard without a deploy. |
| `RAG_GRAPH_WORKERS` | `0` | Processes for the semantic kNN pass of graph building (`0` = leave cores for serving). |
| `RAG_CACHE_TTL` / `RAG_CACHE_MAX` | 900 s / 512 | In-process answer cache keyed by normalised query + scope. |
| `RAG_DIAG_CACHE_TTL` | 900 s | Diagnostic-result cache. |
| `RAG_SEM_CACHE` | on | Paraphrase-tolerant answer cache on the already-computed query vector. |
| `RAG_SEM_CACHE_SIM` | `0.95` | Similarity needed for a semantic-cache hit; meant to catch typos/punctuation/inflection only. |
| `RAG_LOG_QUERIES` | on | Log every query to `feedback.db`. Privacy implication: user questions are persisted. |
| `RAG_FEEDBACK_BOOST` | on | Apply stored ratings to ranking. |
| `RAG_FB_CACHE_TTL` | 300 s | Refresh period of the boost map. |
| `RAG_MQ_CACHE` | `/root/paraphrases_known_item_fa.json` | Offline evaluation baseline cache (`api/evalsuite/baselines.py:341`). A developer-machine path; not used in serving. |

## 29.8 Deploy, gate, smoke and CI scripts

| Variable | Default | Consumer | Meaning |
|---|---|---|---|
| `KG_BE_DIR` | `$PROD/KG_backend` | `ops/deploy/deploy.sh:62` | Backend dir whose `.env.prod` the deploy reads (only the engine switch). |
| `KG_PROD_DIR` | `/opt/KGKG` | `kg-deploy-gate`, `ci_evidence.sh` | Production checkout root. |
| `KG_PROD_ENV` | `/opt/KGKG/KG_backend/.env.prod` | `gate.sh:24` | Used to detect `KG_DB_ENGINE=postgres` and choose the gate's database. |
| `KG_VENV` | `/opt/KGKG/KG_backend/.venv/bin` | `gate.sh:11` | Interpreter location for the gate. |
| `KG_GATE_LOGS` | `$W/.gate-logs` | `gate.sh:12`, `deploy.sh:368` | Where gate logs are written (`$REL/logs/gate-<ts>` on deploy). |
| `KG_MIGRATION_BASE` | `HEAD` of `/opt/KGKG` | `gate.sh:62` | Base revision for the additive-only migration check. |
| `KG_SECTOOLS` / `KG_SECTOOLS_BIN` | `/opt/KGKG_release/sectools` | `gate.sh`, `ops/security/scan.sh` | Where bandit/pip-audit live; created on first use. A scanner that cannot run fails the gate rather than being skipped. |
| `KG_DEPLOY_LOCK_WAIT` | `1800` s | `deploy.sh:316` | How long a deploy waits for the lock; `0` restores fail-fast. |
| `KG_KEEP_STAGING` | `0` | `deploy.sh:430` | `1` keeps the staging containers after the run. |
| `KG_STAGING_QA_USER` | `qa_e_root` | `deploy.sh:37` | QA account used for staging checks. |
| `KG_NGINX_SITE` / `KG_NGINX_CONFD` / `KG_NGINX_BACKUPS` | `/etc/nginx/sites-enabled/kgkg`, `/etc/nginx/conf.d`, `/etc/nginx/config-backups` | `deploy.sh:146-148` | nginx files the deploy installs and backs up. |
| `KG_SMOKE_HOST` | `kgtechvault.com` | `smoke.sh:91` | `Host:` header for the reverse-proxy smoke check. |
| `KG_SMOKE_SCRAPE` | `http://127.0.0.1:8081` | `smoke.sh:98` | Scrape listener; must answer 403 for everything but metrics. |
| `KG_SMOKE_TOKEN` | generated by the smoke run | `smoke.sh:82`, `smoke_fleet.py` | **Secret** portal token used by the fleet smoke test. |
| `KG_SMOKE_SAMPLE` | `3` (1..20) | `smoke_fleet.py:392` | Vehicles opened per category. |
| `KG_DOCKER` / `KG_IMAGE_REPOS` / `KEEP_IMAGES` | `docker` / `kgkg-backend kgkg-frontend` | `prune_images.sh` | Image pruning (the binary is replaceable for tests). |
| `KG_BIN_DIR` / `KG_SSH_DIR` / `KG_HOST_KEY` | `/usr/local/bin`, `/root/.ssh`, `/etc/ssh/ssh_host_ed25519_key.pub` | `setup_ci_access.sh` | CI-access installer paths; it refuses to proceed if sshd serves a different host key. |
| `KG_CI_SSH_DIR` | `$HOME/.ssh` | `ci_ssh.sh:33` | Replaces `~/.ssh` for tests. |
| `KG_CI_REPO` / `KG_CI_REQUIRED` / `KG_CI_TIMEOUT` / `KG_CI_FETCH` / `KG_CI_REQUIRED_ARG` | origin remote / `backend frontend security images` / `20` s / curl / internal | `ci_evidence.sh` | How the deploy proves that the commit's required CI jobs passed. `KG_CI_FETCH` replaces the HTTP call (tests); `KG_CI_REQUIRED_ARG` is an internal hand-over to an embedded script. |
| `KG_TIP_CMD` | `git ls-remote` | `ci_is_tip.sh:33` | Replaces the tip lookup (tests). |
| `GITHUB_EVENT_PATH` | set by GitHub Actions | `ops/governance/check_traceability.py:44` | Pull-request event payload used by the traceability check. |

## 29.9 QA stack

| Variable | Meaning |
|---|---|
| `KG_QA_STACK` | Must be `1` for `seed_qa_fixtures` to run. One of three independent guards that keep the seeder off production. |
| `KG_QA_PASSWORD` | **Secret.** Generated per run by `qa/stack.sh`; the seeder refuses to run without it. |

## 29.10 What this document does not cover

Values in production `.env.prod`, whether each optional switch is currently set, and variables read by third-party
components (nginx, Prometheus, Grafana, Umami) are not covered here **[U]**. Metis/LLM credentials and the
`RAG_VEC_BACKEND`, `RAG_FTS_BACKEND`, `RAG_RERANK`, `KG_CARDB_PG`, `KG_DB_ENGINE` family are documented in
[08](08-ai-assistant-rag.md) and [23](23-data-layer.md).
