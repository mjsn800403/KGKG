# Independent-auditor challenge (adversarial self-review)

Written from the position of a sceptical evaluator who will run commands,
read assertions and look for claims the evidence does not carry. Where the
review found a weakness that could be fixed, it was fixed and re-run; the
rest is stated as open.

## The thirteen questions

**1. Can an independent engineer run every critical suite?** Yes for the
backend, frontend and security gates: `09-ci-cd/REPRODUCE.md` lists exact
commands, and GitHub Actions runs them on a clean runner (run 40609938821,
green). E2E, load, DAST and the retrieval evaluation need the server's data
(237 vehicle manuals, ~11 GB index) and Docker; the scripts are in `qa/`,
but an engineer without access to that host cannot reproduce those four.
*Weakness, not fixable in-repo.*

**2. Do tests verify behaviour or just execute code?** Spot-checked: the
new suites assert outcomes (status codes, which documents a seat holds, which
link survives, which bytes are served). The strongest evidence that they are
behavioural is that they found 30 real defects, including two critical ones.
*Weakness:* no mutation testing, so assertion strength is not measured.

**3. Are integration tests connected to representative components?** The
database, per-car manual DBs, org graph and rate-limit store are real;
externals (SMS, Turnstile, embedding model in CI) are faked. The E2E suite
runs against real images and a sanitized copy of production data. *Gap:* CI
fakes the embedding model, so retrieval quality is only checked by the
separate evaluation.

**4. Do E2E tests exercise complete journeys?** Signed-out redirects, fleet
→ vehicle → manual, assistant retrieval, settings, logout with server-side
revocation, cross-role and cross-tenant refusals, media gate, accessibility.
*Not complete:* login success through the UI is impossible without solving
Turnstile, so sessions are seeded; admin console, team management, SSE and
PDF reports are not covered.

**5. Are performance claims backed by measured workloads?** Yes: raw k6 JSON
and per-2-second resource samples are in `06-performance-and-load/`. The
acceptance thresholds were set by the team from measured baselines and
observed demand; they are not external SLAs, and the report says so. The
first stress run *failed* its error budget; the cause was found and fixed,
and the re-run is reported next to it rather than in place of it.

**6. Are security claims supported?** Scanner output and regression tests
back each fixed finding; the media-gate bypass has before/after reproduction
files. The first ZAP "full" scan was found during this review to have
reached only ~6 URLs (SPA); rather than present it as API coverage, an
OpenAPI spec and an API-driven scan were added. **No independent penetration
test exists**, and nothing in the package says otherwise.

**7. Is coverage measured and interpreted responsibly?** The CI figure was
previously inflated by counting test files (D-01); fixed. The report gives
line and branch coverage separately, by tier, and states that the 80 %
target is not met overall.

**8. Do the CI workflows actually execute?** Yes, and this review found that
on `work` they had been failing for 14 of the last 19 runs while releases
continued via the server gate (D-19). All three causes were fixed; run
40600862764 is the first fully green run; 40609938821 is green on the final code.

**9. Are documentation and diagrams consistent with the code?** Not before
this work: the API reference listed 8 removed endpoints and missed 41
(D-21), the security doc listed three risks already closed, and two nginx
files lived only on the server (D-08). All corrected; the API spec is now
enforced by a test, the rest is not mechanically enforced.

**10. Can the team reproduce failures and verify fixes?** Every fixed defect
has a regression test that failed first (the agent-generated tests were each
run with the marker removed to confirm the failure). Reproduction scripts for
the media bypass and the load errors are included.

**11. Is the release process controlled and traceable?** Promotion requires
staging and a typed confirmation; deploy tags record what shipped. *Gaps:*
SemVer is new and no versioned release has been promoted yet; E2E/load/DAST
are documented release steps but `kgkg-promote` does not yet enforce them.

**12. Gaps between documented capabilities and reality?** Found and fixed:
the "admin-only" evaluation endpoint was public (D-17); "staging cannot touch
production" was untrue for the RAG feedback store (D-02); "the gate blocks
paid media" was untrue for dot-segment paths (D-06). Open: wrong-vehicle
attribution in the assistant (46/60 on the gold set).

**13. Any claims based on assumptions?** Checked for this package:
* Team, roles and qualifications: **not claimed** (criteria 12–13 blocked).
* Expert validation of AI answers: **not claimed**.
* The off-host backup is cited from `docs/11` (restore verified 2026-10-27
  by the team); this review did not repeat the restore.
* "Production unaffected by load tests" rests on 607 health probes of the
  production backend during the runs, not on user-side measurements.
* The October retrieval evaluation used the first 100 rows of each set, so
  it is a regression check, not a statistically comparable re-measurement.

## Weaknesses that remain (ranked)

1. **Production is still exposed** to D-03, D-06, D-07, D-17 and D-30 until
   promotion and nginx installation. This is the most important item in the
   package.
2. Criteria 12 and 13 cannot be assessed from the repository.
3. No independent penetration test; no expert review of AI answers.
4. Coverage below the stated ambition outside critical modules.
5. E2E/load/DAST/eval depend on one host and are not run automatically.
6. Git history begins 2026-06-19.

## How this package was produced

Engineering work was done by the development team with AI-assisted tooling
(Claude), including parallel AI agents that wrote test suites; every agent
result was re-run and its findings re-verified before being recorded. Commits
carry co-authorship attribution. Nothing in the history was rewritten or
back-dated.
