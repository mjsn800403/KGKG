# Supply-chain and security gates

Five gates run on every push and pull request (`.github/workflows/ci.yml`,
job `security`), plus an image vulnerability scan in the `images` job:

| Gate | Tool | Scope | Blocks on |
|---|---|---|---|
| Shell lint | shellcheck | every `ops/**/*.sh` + `ops/deploy/kg-deploy-gate` | any warning |
| Dockerfile lint | hadolint | `ops/docker/*.Dockerfile` | any warning (see `.hadolint.yaml` for the two ignored rules and why) |
| Secret scan | gitleaks | working tree + the pushed commits | any finding outside `.gitleaks.toml`'s allowlist |
| Python dependencies | pip-audit | `ops/docker/backend-requirements.lock` | any advisory not in `pip-audit-ignore.txt` |
| Node dependencies | npm audit | `kg_frontend/package-lock.json`, production deps | any advisory not in `npm-audit-allow.json`, at `high` or above |
| Image vulnerabilities | trivy | both production images | fixable `HIGH`/`CRITICAL` not in `.trivyignore.yaml` |

The gates fail closed. An advisory with a fix available is a bug to fix, not a
number to accept — the exception files exist for the cases where the fix is
genuinely unavailable or carries more risk than the finding.

## Adding an exception

Every entry needs four things, or it does not go in:

1. **The identifier** — the advisory or rule ID.
2. **Why it cannot be fixed now** — a dependency cap, a breaking major, an
   upgrade that needs a migration window. "Not exploitable" alone is not a
   reason; say what blocks the fix.
3. **Why it is tolerable** — the reachability argument. Which code path would
   have to be reached, and with what input, for this to matter here.
4. **A review date** — when someone looks again. Trivy enforces this natively
   (`expiredAt`); for the others the date is in the comment and the quarterly
   review reads it.

## Current exceptions

As of 2026-10-27, after the remediation described in
`docs/superpowers/specs/2026-10-27-devops-maturity-design.md`:

- **Python:** `setuptools` (2 advisories) — capped at `<82` by
  `torch 2.12.1`. Build-time only; nothing installs packages at runtime.
  Clears when torch moves.
- **Python:** `torch` PYSEC-2025-194 — the upgrade to 2.13 risks embedding
  drift against a 57k-blob vector index, so it needs a planned re-embed
  window, not a drive-by bump. The model files it loads are local and
  offline (`HF_HUB_OFFLINE=1`); no user input reaches `torch.load`.
- **Node:** none. `next` was upgraded 16.2.9 → 16.4.3 on 2026-10-27, which
  cleared the vulnerable range for several advisories including unauthenticated
  remote code execution in Image Optimization, `use cache` and `next/og`.
- **Images:** no fixable HIGH/CRITICAL remain. The base image's own OS
  packages are brought up to date during the build (`apt-get upgrade`).

## Quarterly review

Re-read every entry, drop the ones whose blocker is gone, and move the review
dates. If an entry has been renewed twice, the upgrade it defers has become
the work — schedule it instead of renewing a third time.
