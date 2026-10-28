# Knowledge management and transferability (criterion 2, and criterion 15 of the directive)

## Where knowledge lives

| Store | Content | Size / state on 2026-10-27 |
|---|---|---|
| `docs/` (versioned with the code) | 15 maintainer documents: overview, architecture, data model, backend and API reference, RBAC, frontend, AI/RAG, realtime, analytics, operations, security, in-app guidance, terminology, vehicle schema; plus `CHANGELOG.md` | 2,411 lines; changed in 12 commits since 2026-07-18 |
| In-product guidance | User-facing help articles in `kg_frontend/src/guidance/content.js`, each linked by `docRef` to the doc section it summarizes | Ships with the frontend |
| Code comments | Non-obvious decisions are explained at the point of use (e.g. why the media gate normalizes paths, why staging gets its own feedback DB) | Reviewable in any file |
| Commit history | 163 commits before this remediation; messages explain the *why* for most recent work | `git log` |
| Test suites | Executable specification of business rules: 843 backend tests, 178 frontend unit tests, 41 E2E journeys | `KG_backend/api/test_*.py`, `kg_frontend/src/lib/__tests__/`, `qa/e2e/` |
| `audit-evidence/` | This package: baseline, strategy, results, defects, decisions | New |

There is no separate wiki (Confluence/Notion). The team keeps documentation
in the repository on purpose: it is versioned, reviewed and shipped with the
change it describes. Whether that satisfies the evaluator's expectation of a
"knowledge management system" is a judgement for the evaluator; the content
and its update discipline are what this section can evidence.

## Update and review process

`docs/README.md` § *Maintenance protocol* (in force since 2026-07):

1. A commit that changes behaviour edits the affected doc section in the same commit.
2. `CHANGELOG.md` gets a dated entry per shipped change.
3. Guidance articles follow their `docRef` sections.
4. Sections record *why*, so a maintainer can predict a change's blast radius.

Added with this release:

| Document set | Owner (role) | Review cycle |
|---|---|---|
| `docs/02, 03, 05, 06` (architecture, data, API, RBAC) | Engineering lead | Every minor release; on any auth/entitlement change |
| `docs/11, 12` (operations, security) | Operations owner | Quarterly, and after every incident |
| `docs/08` (AI/RAG) | Retrieval owner | After index rebuilds or ranking changes |
| `audit-evidence/01` test strategy | QA owner | Every minor release |
| `ops/security/README.md` exceptions | Security owner | Quarterly (dates inside the file) |

Role names, not people: assigning them to named staff belongs to the team
records in `13-team-and-domain-evidence/`.

Verification done for this package: architecture and security docs were
spot-checked against the running system on 2026-10-27. One stale table was
found and corrected (`docs/12-security.md` §12.2: the per-process rate
limiter, JS-readable token and missing password reset had all been replaced
in code, but the risks were still listed as open).

## Onboarding path (reproducible by a new engineer)

1. Read `docs/README.md` reading order (overview → architecture → RBAC → area doc → operations).
2. Run the backend suite locally: see `09-ci-cd/REPRODUCE.md`.
3. Bring up the QA stack and run E2E: `qa/stack.sh up <ref>` then `qa/run_e2e.sh`.
4. Make a change test-first; the CI gates and staging tell you the rest.

## Internal knowledge vs third-party dependencies

Developed in-house (source in this repository): manual crawling and parsing,
per-vehicle manual stores, entitlement model, org graph, retrieval ranking
(hybrid scoring, centrality, adaptive depth, semantic cache, feedback loop),
DTC/symptom rule engine, terminology store and QA-gated translation, content
shield and anti-scraping, delivery gate and staging sanitizer, watchdog.

Supplied by third parties and used as-is: Django, Next.js/React, gunicorn,
SQLite and sqlite-vec, the bge-m3 embedding model (BAAI) via
sentence-transformers/PyTorch, the Metis LLM API (answer phrasing only — the
retrieval and the rule engine decide what the answer may contain), Cloudflare
(DNS, TLS, Turnstile), the SMS gateway, nginx + ModSecurity/OWASP CRS,
Prometheus/Grafana/Loki/GlitchTip, Docker, GitHub Actions. The OEM manual
content itself is third-party data.
