# 48 — Handoff: taking the project over

For a developer or AI coding agent who has to continue this project with no access to the people, chat
history or workstation that built it. It does not repeat the reference documents; it says what exists, what
does not live in this repository, and in which order to close the gaps. Entry point for day-to-day work
remains [AGENTS.md](AGENTS.md).

Evidence tags as in [AGENTS.md](AGENTS.md) §1. Written 2026-11-11 against `origin/work` `bc48130`. Production
and third-party facts are quoted from the dated documents named beside them and were **not** re-observed for
this document.

## 48.1 What this repository gives you, and what it does not

| You get from a clone | You do not get |
|---|---|
| All application code, tests, CI, deploy and gate scripts, nginx config, observability config | Any secret: `.env.prod`, `.env.production`, SSH keys, API keys, the Cloudflare origin key |
| The documentation set (`docs/`, ADRs, runbooks, SRS, OpenAPI) and executed audit evidence (`audit-evidence/`) | The vehicle content: PostgreSQL database `kgkg_vec`, parts catalogs, `Database_warehouse/`, `static_warehouse/` media, the RAG index |
| Issues, pull requests and review history (on GitHub, not in git) | The portal database `kgkg` (companies, seats, grants, activity) |
| Container image definitions; CI rebuilds the images from any commit | The production host, its hand-installed systemd timer units ([27](27-open-risks-and-decisions.md) F4), DNS, TLS |
| | Accounts at the external providers ([24](24-integrations.md)) |

A clone therefore runs the portal locally with an empty catalogue. Manual content and the assistant need a
populated warehouse and a built index ([README](../README.md) "Running it locally"). [C]

## 48.2 Before you start: three traps

1. **Clone the right branch.** GitHub's default branch is `main`; the integration branch is `work` and the two
   have diverged. `git clone -b work https://github.com/mjsn800403/KGKG.git`. [C AGENTS.md §4]
2. **`*.md` is globally gitignored.** New documents need `git add -f`. [C]
3. **Nothing an agent does may reach production.** Staging is automatic from CI; production changes only when
   a person runs the promotion command on the host ([ADR 0004](adr/README.md), [11 §11.3](11-operations-deployment.md)).

## 48.3 Install, run, test

| Step | Command or document | Notes |
|---|---|---|
| Prerequisites | Python 3.12, Node 20; `check_prereqs.sh` (`.bat` twin on Windows) | [C README] |
| Run locally | [README](../README.md) "Running it locally", or `run_server.sh` | `KG_WARMUP=0` skips the embedding model |
| Configure | [29 — Environment reference](29-environment-reference.md) | There is no `.env.example`; doc 29 lists every variable with default and consumer. Record names, never values |
| Backend tests | `cd KG_backend && python manage.py test --shuffle` | CI runs them on PostgreSQL; `KG_RL_DISABLE=1` turns the rate limiter off |
| Frontend tests | `npm --prefix kg_frontend ci && npm --prefix kg_frontend test` | |
| Full gate | `ops/deploy/gate.sh <clean-checkout-dir>` | Linux; security scans, backend, frontend lint/test/build |
| Browser journeys | `qa/stack.sh up <ref>`, `qa/run_e2e.sh` | [32](32-testing-and-qa.md) |
| Debug | [20 — Runbooks](20-runbooks.md), [33](33-system-design.md) failure scenarios | |
| Change something | [AGENTS.md](AGENTS.md) §3 (task → document map) and §4 (rules) | |

## 48.4 Where the current state is recorded

Do not copy status into this file; these are the registers that are kept true.

| Question | Document |
|---|---|
| What is really implemented and enabled in production | [38 — Implementation status matrix](38-implementation-status-matrix.md) |
| Known risks, pending owner decisions, claims in older docs that are overridden | [27 — Open risks and decisions](27-open-risks-and-decisions.md) |
| Engineering and operations follow-ups with status | [47 — Engineering follow-ups](47-engineering-followups.md) |
| What is still undocumented | [41 — Documentation coverage and backlog](41-documentation-coverage-and-backlog.md) |
| Outstanding work | GitHub issues and milestones (`gh issue list -R mjsn800403/KGKG`); on 2026-11-11: 33 open issues, 4 open pull requests, milestones `1.2.0` and `Backlog` [D] |
| Why things are the way they are | [ADRs](adr/README.md), [CHANGELOG](CHANGELOG.md), dated designs under `superpowers/` |

## 48.5 What must be obtained from the owner

None of this can be derived from the repository. Ask for each item explicitly; record where it is kept, never
its value.

| Item | Needed for | Reference |
|---|---|---|
| GitHub: admin on the repository (one admin account exists today [D 2026-11-11]) | Branch protection, Actions secrets, releases | [36](36-cicd-and-deployment.md) |
| Actions secrets `DEPLOY_HOST`, `DEPLOY_KNOWN_HOSTS`, `DEPLOY_SSH_KEY` | The `stage` job. The key is pinned on the host to a forced command that cannot promote | [11 §11.3](11-operations-deployment.md) "Keys and privilege" |
| A personal SSH key on the production host | Operations. Keys are never shared | [19](19-onboarding.md) |
| `.env.prod`, `.env.production` and where they are escrowed | Any rebuild of the host. Not in any backup by design (R3) | [29](29-environment-reference.md), [12](12-security.md) |
| Cloudflare account (DNS, proxy, origin certificate, Turnstile) | Public entry, login bot check | [24](24-integrations.md), [18](18-security-hardening.md) |
| Metis AI account | Assistant phrasing; the product degrades to a no-LLM answer without it | [24](24-integrations.md), [08](08-ai-assistant-rag.md) |
| Melipayamak account | OTP login, alert paging, support SMS | [24](24-integrations.md) |
| Access to the company backup server and the hosting provider panel | Knowing what is actually backed up (R1, R2) | [11 §11.6](11-operations-deployment.md), [44](44-data-lifecycle.md) |
| Domain registrar access | Domain renewal | — |
| Jira, Slack | Decisions and history that are not in GitHub | [28](28-team-workflow.md) |

## 48.6 Continuity gaps, in the order to close them

1. **Vehicle content has no verified backup** (R1, E2, GitHub #80). Until this is closed, loss of the host
   disk may lose the product's content.
2. **Secrets escrow is unrecorded** (R3, GitHub #63).
3. **No restore drill on record** (E3). [Runbook R11](20-runbooks.md) has never been executed end to end.
4. **Host units missing from the repository** (F4, E11): a rebuilt host would lack several timers.
5. **One host, one GitHub admin** (R4, §48.5): both are single points of failure.

## 48.7 Working with AI coding agents

`AGENTS.md` and `CLAUDE.md` at the repository root route an agent to [AGENTS.md](AGENTS.md) in this
directory; `kg_frontend/AGENTS.md` covers the frontend. Rules for agents are the same as for people (§4
there). Agent memory files, chat transcripts and workstation-local tooling are **not** a place of record
([AGENTS.md](AGENTS.md) §5): a decision that matters is written into a pull request, an ADR or one of the
registers in §48.4 before the session ends.

## 48.8 Maintenance

Update this document when an item in §48.5 or §48.6 changes (a gap closes, a provider is replaced, a second
admin is added). Status lives in docs 27, 38 and 47, not here.
