# 24 — External integrations

Every third party the system calls, what for, which configuration names it reads (names only; values live in
`.env.prod` / `kg_frontend/.env.production` on the host and are never recorded in the repo), and what happens when
it fails. **[C]** = read from code at `8a380f6`; **[D]** = Slack/session claim.

| Integration | Used for | Where | Configuration names | Failure behaviour |
|---|---|---|---|---|
| **Metis AI** (`api.metisai.ir`, paid) | Phrases assistant answers from retrieved passages; also fa→en query translation | `kg_frontend/src/app/api/chat/route.js` (server side; `RAG_MQ_TRANSLATE` is read there and gated by a `FeatureFlag`, migration 0034). Offline tools also call it: `evalsuite/answer_eval.py`, `manage.py translate_terms` | `METIS_API_KEY`, `METIS_BOT_ID`, `METIS_FALLBACK_BOT_IDS` (the base URL is a constant in the code, not configuration) | `withFallback` retries on the fallback bot IDs in order; if all fail the deterministic Persian renderer answers from the passages (no-LLM fallback, ADR-0002). Fallback chain set 2026-11-03: `deepseek-v4-1-flash-1017`, then `gpt-6-luna`, then `gpt-5.4-mini` [D]; the primary bot returned 503/400 that day |
| **Melipayamak** (SMS) | OTP login codes, security notices, alert paging, support-chat SMS | OTP/security: `api/portal.py`, `api/notify.py`; alerts: `api/alert_rules.py`; customer messages: `api/notifications/providers.py` | `SMS_USERNAME`, `SMS_API_KEY`, `SMS_FROM`; outbox switches `KG_NOTIFY_SMS`, `KG_NOTIFY_EMAIL`, `KG_NOTIFY_SMS_MAX_PER_HOUR` (doc 11) | Missing config logs a warning and skips. The end-to-end paging path has never been verified (GitHub #24, A-18) [D] |
| **E-mail (SMTP)** | Customer notifications via the outbox only | `api/notifications/providers.py` | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `KG_NOTIFY_FROM_EMAIL` | No SMTP exists in production as of 2026-11-01 [D memory, **U now**]; outbox is off by default |
| **Cloudflare Turnstile** | Bot check on portal and admin login | `api/portal.py` `_verify_turnstile` | `TURNSTILE_SECRET`, `TURNSTILE_HOSTNAMES` | Calls `challenges.cloudflare.com`; a host with no IPv6 route once stalled ~40 s (fixed in `backend.Dockerfile`, 2026-11-03 [D]) |
| **Cloudflare (proxy/DNS/TLS)** | Public entry, origin certificate | nginx `ops/nginx/kgkg.conf` trusts `CF-Connecting-IP`; docs 11, 18 | origin key excluded from backups by design (doc 12) | Dashboard settings are not in the repo **[U]** |
| **GitHub** | Source, CI, CodeQL, Dependabot, secret scanning | `.github/` | Actions secrets `DEPLOY_HOST`, `DEPLOY_KNOWN_HOSTS`, `DEPLOY_SSH_KEY` (names only) [D]; environment `production` requires reviewer | `stage` job red if secrets missing |
| **GlitchTip** (self-hosted Sentry API) | Error tracking for backend and frontend | doc 18 §error monitoring; compose in `/opt/glitchtip` | `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_RATE` (frontend); backend DSN in env | Project ids: `kgkg-backend` 1, `kgkg-frontend` 2 (doc 18) |
| **Prometheus, Loki, Grafana, Alloy, cAdvisor, blackbox** | Metrics, logs, dashboards, probes | `ops/observability/`; compose in `/opt/observability` | `KG_PROMETHEUS_URL`, `KG_ALERT_*` thresholds, `KG_ALERT_SLO_MONTHLY` | Probes include Metis and the SMS provider; those two are third-party budgets, not ours (CHANGELOG 2026-11-03) |
| **Umami** | Product analytics | `/opt/umami`, `ops/umami/` | not read | **[U]** |
| **Jira (KGTEC), Trello, Slack** | Task tracking, mirror board, communication | not in code; scheduled task `kgkg-daily-reconcile` in the desktop app | n/a | See doc 28 |
| **TIS (Toyota Technical Information System)** | Source of manuals (crawler / downloads) | `api/tis_crawler.py`, `/kg-vnc/` gate (`vncauth.py`), `/opt/toyota_tis` | `KG_TIS_*` | Credentials never recorded; legal/licensing posture **[U]** |
| **Partsouq** | Parts catalog crawl | `api/partsouq_crawler.py`, `api/partsouq_build.py`, `ops/partsouq/partsouq_vin_crawl.py` | `KG_PS_*` | Only in docs 00, 16 until now |

## Rules for changing an integration

1. Add or rename a configuration name → run `python3 ops/governance/gen_inventory.py` and describe the variable here or in the matching reference doc.
2. Anything that calls a paid API must have a rate limit and a fallback; `api/quota.py` and `CHAT_RL_LIMIT` / `CHAT_RL_WINDOW` (frontend) exist for the assistant.
3. Do not log provider responses that may contain user text or keys.
