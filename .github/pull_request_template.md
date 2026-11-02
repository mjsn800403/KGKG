## What and why

<!-- What was wrong or missing, and how you know. Link the defect ID from
CORRECTIVE_ACTIONS.md, the issue, or the CI run that showed it. -->

## How it was verified

<!-- Commands and their results, not intentions. "Tests pass" is not
verification; the output is. State which test failed before the change. -->

```
```

## Checklist

- [ ] The new or changed test **failed before this change** and passes after it
- [ ] `docs/` updated in this PR if behaviour, an endpoint or operations changed (ADR-0006)
- [ ] `docs/openapi.yaml` updated if a route changed (`test_openapi_routes.py` enforces it)
- [ ] An ADR added if this sets a standing decision
- [ ] No ratchet lowered (`ops/deploy/coverage_min`, `ops/deploy/lint_max_warnings`) and nothing excluded from coverage to pass it
- [ ] Any new alert rule is windowed or `absent()`-guarded, and I accept that each `infra:` key is a page
- [ ] Nothing here needs a hand-install on the host to work

## Risk and rollback

<!-- What breaks if this is wrong, who notices, and how it is undone.
Migrations: none / additive only / forward-only. -->
