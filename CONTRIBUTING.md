# Contributing

This is a commercial, closed codebase (see [LICENSE](LICENSE)); it is public so
that customers and evaluators can inspect it. Outside contributions are not
accepted. This document is how the maintainers work, written down so that the
process is checkable rather than remembered — and so a reviewer can tell
whether we actually follow it.

Security problems do not go through this process. See [SECURITY.md](SECURITY.md).

## The short version

```
branch off work  ->  push  ->  CI green  ->  PR into work  ->  merge
                                   |
                     CI stages the commit on the server
                                   |
     a person runs `kgkg-promote <sha>` on the host, and types the word
```

Nothing else reaches production. No timer, cron or CI path can promote: CI's
SSH key is pinned to a forced command whose role has no `deploy` verb, which is
matrix-tested in `ops/deploy/test_gate_roles.sh`.

## Branches

| Branch | Role |
|---|---|
| `work` | integration. Branch from here, merge back here by PR. A push here is staged on the server automatically |
| `main` | protected release branch: required checks, PR required, no force-push, no deletion, admins included |
| `<topic>/<slug>` | your working branch, e.g. `fix/transient-unit-lifecycle` |

## Commits

Conventional Commits — `type(scope): subject` — with these types in use:
`feat`, `fix`, `docs`, `test`, `ci`, `refactor`, `perf`, `build`, `deps`,
`ops`, `chore`.

Write the body for the person who will read it during an incident at 2 a.m.
What was wrong, how you know, what you changed, and what proves it. If a
commit cannot say how its change was verified, it is not finished. The repo's
history is itself evaluation evidence (criterion 4), so a subject line like
"fix stuff" costs the company something real.

Author identities are folded by [`.mailmap`](.mailmap). If you commit from a
new machine or from the GitHub web UI, add the alias there rather than leaving
yourself as a second contributor.

## Tests

Test-first for anything with a defined behaviour. The bar is not coverage, it
is this: **the test must fail before your change and pass after it.** A test
written after the fact that has never been seen red proves nothing.

```bash
cd KG_backend && python manage.py test --shuffle   # backend; shuffle is not optional
npm --prefix kg_frontend test                      # frontend units
bash ops/deploy/test_promote.sh                    # deploy gates (needs GNU date: Linux)
bash ops/deploy/test_gate_roles.sh                 # the role matrix
bash ops/deploy/ci_evidence.sh --selftest          # CI-evidence parsing
python3 ops/observability/watchdog.py --selftest    # the alerting watchdog
```

`--shuffle` matters: the suite once passed only in its default order (D-31).

The coverage floor in `ops/deploy/coverage_min` **may only ever move up**, and
it moves in the same commit that adds the tests earning it. Lowering it to make
CI pass, or excluding code from measurement to the same end, defeats the only
purpose the file has.

## Documentation

`docs/` is the source of truth and ships with the change that affects it — this
is [ADR-0006](docs/adr/0006-docs-as-code.md), not a preference. A new standing
decision gets an ADR. A new or changed endpoint gets `docs/openapi.yaml`
updated, which `api/test_openapi_routes.py` enforces across all 90 routes.

One rule learned the hard way: **do not describe infrastructure in the present
tense unless you have just checked it.** Two documents claimed CI reached the
server through a Cloudflare Tunnel while `cloudflared` was not even installed.
A document contradicted by one `systemctl` call devalues every other document
we have.

## Alerting

`KG_backend/api/alert_rules.py` is the rule evaluator; there is no
Alertmanager and no Prometheus `rule_files`, by design. So a new metric reaches
a phone only if you add a rule there — and `deliver()` sends an SMS for every
`infra:` key regardless of severity, so **every key you add is a page.**

Never write a rule shaped `<metric> == 0` on its own. When the exporter dies
the metric disappears, the expression matches nothing, and the engine reads
that as healthy. Evaluate it over a window or add an `absent()` guard;
`RuleShapeTests` in `api/test_alert_infra.py` will fail you if you forget.

## Things that will be sent back

* a host-side hand-install instead of a change in the release — `deploy.sh`
  refreshes those files on every promote, so your fix silently reverts
* a new `.md` file you had to `git add -f` — say so, because the ignore rules
  were wrong once already and may be wrong again
* a test that has never been red
* lowering a ratchet
* a claim in a document with nothing behind it
