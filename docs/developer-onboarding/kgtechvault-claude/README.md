# KGTechVault — Claude Code developer environment (onboarding package)

Reproduce, on your own machine and your own Claude Code account, the AI development environment used on
KGTechVault (repo `mjsn800403/KGKG`): shared project instructions, hooks, plugins and the Graphify code graph.
Nothing here transmits code or secrets, calls an LLM, or needs an API key.

**Single source of truth:** the shared settings live in the repo itself (`CLAUDE.md`, `.claude/settings.json`,
`.claude/hooks/`, `.graphifyignore`, `scripts/*graphify*`, `tools/graphify_xlayer/`, [doc 48](../../48-graphify.md)).
This package only explains, installs the per-machine parts, and validates. It holds no copy of those files.
Evidence tags follow `docs/AGENTS.md`: **[C]** read from code/config, **[V]** run and observed, **[U]** not verified.

## Quick start (macOS / Linux)

```bash
git clone https://github.com/mjsn800403/KGKG.git && cd KGKG
git checkout <branch that contains this package>      # see "Delivery" below
docs/developer-onboarding/kgtechvault-claude/bootstrap.sh            # dry run: shows what is missing, changes nothing
docs/developer-onboarding/kgtechvault-claude/bootstrap.sh --apply    # installs missing plugins + builds the local graph, then validates
docs/developer-onboarding/kgtechvault-claude/validate.sh --full      # re-check any time
```

You must do these yourself: install Claude Code, sign in (`claude`), and approve the trust prompt for the repo.
`--apply` runs `claude plugin marketplace add` / `claude plugin install` (user scope, from GitHub) and
`scripts/setup-graphify.sh` (installs `graphifyy>=0.8.46,<0.9` via uv/pipx/pip, AST-only). Before touching user
config it copies `~/.claude/settings.json` and the plugin registry to `*.bak-<timestamp>`; to roll back, copy them
back and `claude plugin uninstall <id>`. Re-running is idempotent.

**Windows [U]:** the scripts and the session hook are bash. Use WSL (recommended) or Git Bash with `python3` on
PATH. This was not tested; treat any Windows result as a report to fix, not a guarantee.

## What a correct setup looks like

1. `validate.sh` ends with `0 failed`.
2. Open `claude` in the repo. The first reply must start with `Graphify loaded: <stats>; consulted for: <query>`
   (the hook demands it). If it says the graph was NOT loaded, run `scripts/setup-graphify.sh`.
3. Caveman style is active (terse replies), Superpowers is available, and greps/reads of source get a graph-first nudge.

## Required vs personal

| Item | Required? | Notes |
|---|---|---|
| `caveman@caveman`, `superpowers@superpowers-dev` | yes | Enabled by project settings; **installing is per machine** (the settings entry alone does nothing). |
| Graphify CLI + local graph | yes | Graph is gitignored and rebuilt per machine (~5 s). Never copy someone else's `graphify-out/`. |
| `claude-mem@thedotmack` | **no — disabled** | Deliberately `false` in project settings (nonfunctional here). Do not enable it. |
| `remember@claude-plugins-official` | optional, personal | Not pinned by the project; not needed. |
| `.claude/settings.local.json` | personal | Gitignored. Put your own permission allowances here, not in shared settings. |
| MCP servers | none | The project defines no `.mcp.json`; all MCP in the original environment are personal account connectors. |

Your own `~/.claude/*` is preserved. Project settings take precedence over user settings only for the keys they set
(`enabledPlugins` entries, hooks are additive); you keep your own model, theme and other plugins.

## Known issues (found while building this package)

- **xlayer vs current `work` [V]:** `tools/graphify_xlayer` was written against an older tree. On `origin/work` its
  accuracy suite fails 3 tests (extracts 96 of 101 `path()` routes, 46 of 48 foreign keys; the old example endpoint
  `/api/team/members/` no longer exists). The AST graph and the session hook are unaffected; cross-layer chains can
  miss some links. `validate.sh --full` reports this as a WARN. Fixing the extractor is a separate change.
- **Hook has a machine path [C]:** `.claude/hooks/graphify-session-start.sh` prepends `/opt/anaconda3/bin` to PATH
  and writes `/tmp/graphify-layers.log`. Harmless elsewhere, not portable to Windows.
- **Docs gate [C]:** every `.md` under `docs/` needs an `OWNERS.toml` entry (CI job `governance`); this package and
  doc 48 have entries. Re-review dates move when you confirm the content.
- **Branch drift [V]:** the config originated on `rag-db-improvements`, 446 commits behind `work`; `CLAUDE.md` on
  `work` is a 2-line router to `AGENTS.md`, so the shared framework was merged *under* that router.

## Delivery (how the second developer receives this)

Authoritative copy = a pull request into `work` (needs an issue reference per `docs/AGENTS.md`). Until it is merged,
fetch the branch `onboarding/kgtechvault-claude`. Pushing and opening the PR are the owner's decision.

## SECOND_DEVELOPER_HANDOFF

- Repo: `https://github.com/mjsn800403/KGKG` — package at `docs/developer-onboarding/kgtechvault-claude/`.
- Read order: this README → `MANIFEST.md` → `docs/48-graphify.md` → `AGENTS.md` → `docs/AGENTS.md`.
- Run: `bootstrap.sh` (dry run) → `bootstrap.sh --apply` → `validate.sh --full`.
- Shared config is in the repo; do not copy anyone's `~/.claude`, `graphify-out/` or `settings.local.json`.
- Graph-first: run `graphify query "<topic>" --graph graphify-out/merged-graph.json` before reading source; verify
  INFERRED edges and anything dynamic in the code.
- Never run `kgkg-promote`, read `.env.prod`/keys, or change `/opt/KGKG` without the owner's go-ahead (`docs/AGENTS.md`).
- Report any `FAIL` from `validate.sh` with its output; Windows and Linux results are unverified until you send them.
