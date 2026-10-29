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

**The server gate runs three of them too.** bandit, pip-audit and the npm audit gate run
from one script, `ops/security/scan.sh`. CI calls it, and so does `ops/deploy/gate.sh`, as
the first step of every staging and production deploy, with the same exception files.

* On the server, the scanners come from a pinned venv at `/opt/KGKG_release/sectools`
  (`KG_SECTOOLS`), created on first use.
* The scans fail closed there too: a scanner that cannot reach its advisory database fails
  the deploy.
* Why: before 2026-10-29 only CI ran these, so a commit that was red on bandit in CI
  (`8fa94dd`) still passed the server gate and shipped.

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

## Bandit (SAST) {#bandit}

CI runs bandit on `KG_backend/api` and `KG_backend/KG_backend` (tests and
migrations excluded) at medium severity and above. Findings present when the
gate was introduced (2026-10-27, bandit 1.9.4) were triaged one by one and
recorded in `bandit-baseline.json`; bandit compares by file, test and issue,
not line number, so moving code does not trip it but a new finding does.

Fixed rather than baselined:

- **B324** weak hash (3): `dataquality.py`, `partsingest.py`, `rag/ingest.py`
  use SHA-1 as a content fingerprint, never for security; now declared with
  `usedforsecurity=False`.
- **B613** Trojan-Source bidi characters (3): invisible RLM/LRM literals in
  Persian normalisation tables (`assist_lookup.py`, `rag/glossary.py`,
  `rag/terms.py`) are now written as `\u200f` / `\u200e` escapes. String
  constants are unchanged (checked with `ast`), and the one raw-string regex
  matches exactly the same three code points.

Baselined, with the reason:

- **B608** string-built SQL (29). Every site was read. The interpolated part
  is a constant (`NODE_COLUMNS`, a fixed table name from a literal tuple), a
  run of `?` placeholders, or a comma-joined list of `int()`-cast ids; user
  values are always bound parameters. Most sites are offline build commands.
  LIKE patterns built from user input are escaped (`cardb.like_escape`).
  2026-10-29: `ingest.py` ledger migration (`INSERT ... VALUES (?,?,…)`,
  placeholders only, added with the PostgreSQL cutover) reviewed and added.
- **B310** `urlopen` (10). Every URL is a constant `https://` endpoint (SMS
  provider, Cloudflare Turnstile, the LLM API) or the loopback health URL;
  none is built from request data, so `file:` and SSRF are not reachable.
- **B108** `/tmp` path (1). `ratelimit.py`'s shared counter store defaults to
  `/tmp/kg_ratelimit.sqlite3` inside the backend container (private `/tmp`,
  one tenant); it holds only hit counters and is overridable by
  `KG_RL_STORE`.

Low-severity findings (`try/except/pass`, `random` for non-security jitter,
subprocess with fixed argument lists) are not gated; they are listed in the
dossier's SAST report.

To accept a new finding, fix it if at all possible. If it is a false
positive, add a reason here and regenerate the baseline in the same commit:

    bandit -r KG_backend/api KG_backend/KG_backend \
      -x '*/test_*,*/tests.py,*/tests_parts.py,*/migrations/*' -ll \
      -f json -o ops/security/bandit-baseline.json

## Quarterly review

Re-read every entry, drop the ones whose blocker is gone, and move the review
dates. If an entry has been renewed twice, the upgrade it defers has become
the work — schedule it instead of renewing a third time.
