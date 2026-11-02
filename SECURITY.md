# Security policy

## Reporting a vulnerability

**Please do not open a public GitHub issue for a security problem.**

Use GitHub's private vulnerability reporting on this repository
(*Security → Report a vulnerability*), which opens a channel visible only to
the maintainers. If that is unavailable to you, open a normal issue containing
only the words "security report, please contact me" and no technical detail,
and a maintainer will reply with a private channel.

Please include, as far as you have it: the affected URL or endpoint, the
request that demonstrates the problem, what you were able to read or do that
you should not have been able to, and whether any real customer data was
exposed. A reproduction against the public site is more useful to us than a
description, and we would rather receive a rough report quickly than a polished
one later.

## What we commit to

| Stage | Target |
|---|---|
| Acknowledgement | 2 working days |
| Initial assessment and severity | 5 working days |
| Fix for a Critical or High issue | released as a patch version, ahead of other work |
| Fix for Medium or Low | scheduled into the next release |
| Update to you | at each of the stages above, and when the fix ships |

Severity follows the register in
`audit-evidence/14-risk-and-corrective-actions/CORRECTIVE_ACTIONS.md`:
**Critical** means cross-tenant data or money, **High** means a broken access
rule or an exposed endpoint, then Medium and Low.

Every fix ships with a regression test that fails before the change and passes
after it. That is not a courtesy — it is how the register is kept honest, and
you can check it: each row names its test.

## Scope

In scope: the production service at `kgtechvault.com`, the API under
`/kg-api/`, the code and configuration in this repository, and the deployment
and alerting tooling under `ops/`.

Out of scope: denial of service and volumetric testing against production
(ask first and we will give you an isolated target), social engineering of
staff or customers, physical attacks, reports consisting only of automated
scanner output with no demonstrated impact, and findings in third-party
services we consume (report those to their owners).

Please test against your own account and your own company's data. Do not
access, modify or retain another customer's data; if you reach it
accidentally, stop, tell us what you saw, and delete it.

## Testing we already do, so you can skip it

Reporting something already listed here is not wasted, but it will be closed
as known:

* static analysis (bandit), dependency audit (pip-audit, npm audit), container
  scanning (Trivy, fail-closed on fixable HIGH/CRITICAL) and secret scanning
  (gitleaks) on every push — `.github/workflows/ci.yml`
* dynamic scanning with OWASP ZAP, baseline, API (OpenAPI-driven) and full —
  `qa/dast/run_zap.sh`, results in `audit-evidence/07-security/dast-final/`
* mutation testing of the authorisation modules — `qa/mutation/run.sh`
* browser tests for the access rules, the content shield, CSP and anti-framing
  headers, and server-side session invalidation — `qa/e2e/tests/`
* a written security assessment —
  `audit-evidence/07-security/SECURITY_ASSESSMENT.md`

**What we have not done:** no independent penetration test has been
commissioned. All of the above is our own testing, automated or written by us.
If you are reading this to judge our security posture, that is the gap to
weigh.

## Safe harbour

If you follow this policy in good faith, we will not pursue or support any
action against you for your research, and we will treat your report as
authorised testing. We will credit you if you want to be credited, and not if
you do not.
