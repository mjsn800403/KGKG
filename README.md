# KGtechvault

[![ci](https://github.com/mjsn800403/KGKG/actions/workflows/ci.yml/badge.svg?branch=work)](https://github.com/mjsn800403/KGKG/actions/workflows/ci.yml)

**Official Toyota/Lexus service documentation, sold as subscription access to
Iranian after-sales companies, with a Persian AI assistant that answers only
from the manuals a company has actually paid for.**

Live at [kgtechvault.com](https://kgtechvault.com). Operated by
شرکت خدمات گستر سپهر گیتی (Khadamat Gostar Sepehr Giti).

This repository is public so that customers, evaluators and auditors can
inspect it. It is **not** open source — see [LICENSE](LICENSE). No manual
content, vehicle database or customer data is published here.

---

## What it does

A company buys specific vehicles and specific **document layers** for them, and
receives seats for its technicians. Those technicians browse the original
English manual content through a Persian, right-to-left portal, and ask
questions in Persian — including diagnostic trouble codes — of an assistant
that is grounded in the purchased manuals and nothing else.

38 vehicles are in the catalogue today.

## The two ideas that explain the architecture

**Content is immutable and sharded per vehicle.** Manuals arrive as crawled
HTML and are parsed once into one self-contained SQLite database per vehicle,
opened read-only when served. Adding the four-thousandth vehicle is a file copy
and a catalogue sync — no migration, no downtime. Everything else — companies,
seats, grants, analytics, events, jobs — lives in one relational database
(PostgreSQL in production since 2026-10-29).

**The AI must not be able to exceed what was paid for.** Retrieval, ranking and
the diagnostic rule engine are local and deterministic. The external LLM is
used only to phrase an answer over context that has already been retrieved, and
there is a no-LLM fallback that degrades rather than fails. The access check
lives *inside* retrieval, as a per-user vehicle allow-list, not only at the UI
— which is why the authorisation modules are the ones under mutation testing.

Standing decisions are recorded as ADRs in [`docs/adr/`](docs/adr/).

## Repository layout

| Path | Contents |
|---|---|
| `KG_backend/` | Django application: API, auth and entitlements, RAG, diagnostics, analytics |
| `kg_frontend/` | Next.js portal (fa/RTL) |
| `docs/` | The source of truth, including the [SRS](docs/00-srs.md) and [`openapi.yaml`](docs/openapi.yaml) |
| `ops/` | Deployment, the forced-command gates, nginx, observability, security scanning |
| `qa/` | The QA stack, E2E, load, DAST, mutation testing, nightly suite |
| `audit-evidence/` | Executed test evidence, per evaluation criterion |

## Running it locally

Requires Python 3.12 and Node 20.

```bash
# backend
cd KG_backend
pip install -r ../KG_backend/requirements.txt
DJANGO_DEBUG=true KG_ADMIN_TOKEN=dev KG_WARMUP=0 python manage.py migrate
DJANGO_DEBUG=true KG_ADMIN_TOKEN=dev KG_WARMUP=0 python manage.py runserver

# frontend, in another shell
npm --prefix kg_frontend ci
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 npm --prefix kg_frontend run dev
```

`KG_WARMUP=0` skips loading the embedding model, which you do not need in order
to browse the portal. `run_server.sh` does both with the project's defaults.

The vehicle warehouse is not in the repository, so manual content and the
assistant need a populated `Database_warehouse` and a built RAG index
(`run_rag_build.sh`); everything else works without them.

## Testing

```bash
cd KG_backend && python manage.py test --shuffle
npm --prefix kg_frontend test
bash ops/deploy/test_promote.sh        # 40 checks; needs GNU date, so Linux
bash ops/deploy/test_gate_roles.sh     # 24 checks, the role matrix
```

`--shuffle` is not decoration: the suite once passed only in its default order,
and CI now randomises every run.

Current figures, from CI run
[40934280389](https://github.com/mjsn800403/KGKG/actions/runs/40934280389):
1170 backend tests on PostgreSQL, 178 frontend, 42 Playwright E2E, 58 %
combined backend coverage against a floor that may only move up. The
authorisation modules sit at 96–100 % branch coverage and are mutation-tested.

## How it ships

Push to `work` → CI (tests and coverage ratchet, lint ratchet, shellcheck,
hadolint, gitleaks, bandit, pip-audit, npm audit, both production images built,
booted and Trivy-scanned) → CI asks the server to **stage** that exact commit
against a sanitised copy of the production database → smoke.

Then a person types `kgkg-promote <sha>` on the host. It refuses a commit whose
GitHub CI is not green, a commit that has not been staged, and a commit without
a passing full E2E run; each override is a typed sentence and is logged. No
timer, cron or CI path can promote — CI's key is pinned to a forced command
with no `deploy` verb. Deployment itself is a blue/green container swap with
automatic rollback.

The full description is [`docs/11-operations-deployment.md`](docs/11-operations-deployment.md);
the policy is
[`audit-evidence/10-release-management/RELEASE_POLICY.md`](audit-evidence/10-release-management/RELEASE_POLICY.md).

## Contributing, security, licence

* Outside contributions are not accepted; [CONTRIBUTING.md](CONTRIBUTING.md)
  documents how the maintainers work so the process is checkable.
* Found a vulnerability? [SECURITY.md](SECURITY.md). Please do not open a
  public issue. We have not commissioned an independent penetration test, and
  that is stated there plainly.
* [LICENSE](LICENSE) — proprietary, all rights reserved. Third-party
  components: [NOTICE](NOTICE).
