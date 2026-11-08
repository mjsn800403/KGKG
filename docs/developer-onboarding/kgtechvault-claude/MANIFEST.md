# Manifest and configuration map

Audited 2026-11-08 on macOS 27.0.1 arm64, Claude Code 2.1.318, Python 3.12.2. Repo `mjsn800403/KGKG`.

## Shared (in Git — authoritative, not copied here)

| Path | Role | Status |
|---|---|---|
| `CLAUDE.md` | Router to `AGENTS.md` + graphify rules + operating framework (ask-freely, skills by task size, context order, execution discipline, safety, founder-partner stance, plugin portability) | [V] loads in a fresh session |
| `.claude/settings.json` | SessionStart + 2 PreToolUse hooks, graphify permissions, `enabledPlugins` | [V] valid JSON |
| `.claude/hooks/graphify-session-start.sh` | Builds/refreshes graph, injects digest, demands `Graphify loaded:` line; fails loudly if CLI missing | [V] contract test passes |
| `.graphifyignore` | Corpus exclusions | [C] |
| `scripts/setup-graphify.sh` | Idempotent install + build (pins `graphifyy>=0.8.46,<0.9`) | [V] rebuilt a graph in an isolated checkout |
| `scripts/graphify-refresh-layers.sh` | Rebuild xlayer/docsindex/merged graph (deterministic, no LLM) | [V] |
| `scripts/test-graphify-session.sh`, `test-graphify-xlayer.sh`, `verify-graphify-usage.sh` | Test suites | session [V] pass; xlayer [V] **3 fail on current `work`** |
| `tools/graphify_xlayer/` | Custom cross-layer extension (frontend → API → route → view → model; docs index; viewer) | [V] runs; accuracy gaps vs `work` |
| `docs/48-graphify.md` | Graphify design and contract (renumbered from 15, which `work` already used) | [V] |

## Package (this folder)

`README.md` entry point · `bootstrap.sh` (dry-run by default) · `validate.sh` (non-destructive, `--full`) · this file.

## Per-machine (installed by `bootstrap.sh --apply`)

| Component | Verified original version | Source | Install |
|---|---|---|---|
| Claude Code | 2.1.318 [V] | user | own install + sign-in |
| `caveman@caveman` | git `25d22f864ad6` [V] | marketplace `caveman` ← `JuliusBrussee/caveman` | `claude plugin install` (installs the marketplace's current version; exact pin not supported by the CLI [U]) |
| `superpowers@superpowers-dev` | 6.0.3 / `896224c4` [V] | marketplace `superpowers-dev` ← `obra/superpowers` | same |
| `graphifyy` (CLI `graphify`) | 0.8.46 [V] | PyPI, `/opt/anaconda3/bin` on original machine | uv / pipx / pip, pinned `>=0.8.46,<0.9` |
| Python | 3.12.2 [V] | needs ≥ 3.10 | own |

Graphify details [C]: AST-only extraction (tree-sitter), no LLM or network; outputs in gitignored `graphify-out/`:
`graph.json` (AST), `xlayer.json`, `docsindex.json`, `merged-graph.json`, `GRAPH_REPORT.md`, `architecture.html`.
Rebuild: `scripts/setup-graphify.sh` (first time) / `graphify update .` + `scripts/graphify-refresh-layers.sh`.
The `D:\programing\tools\` Graphify path from earlier notes is **not referenced anywhere in this repo** (searched; no hits), so it is not part of this environment.

## Where each source maps (original machine → new machine)

| Original source | Class | Destination | Action |
|---|---|---|---|
| Repo `CLAUDE.md`, `.claude/settings.json`, hook, scripts, tools | shared | same repo path | `git checkout` the branch |
| `~/.claude/settings.json` (`enabledPlugins`, `extraKnownMarketplaces`, theme, model, statusLine, voice, autoMode) | user | **not exported** | each dev keeps their own |
| `~/.claude/plugins/*` caches and registry | machine | rebuilt by `claude plugin install` | via `bootstrap.sh --apply` |
| `~/.claude.json` (account, sessions, MCP connectors) | user/secret | **not exported** | each dev signs in |
| `.claude/settings.local.json` | user | gitignored | personal; contains broad `git push`/`gh` allowances — do not copy |
| `.claude/worktrees/`, `.claude/launch.json` | local | gitignored / untracked | not part of the package |
| `graphify-out/` | machine | rebuilt | never transfer (absolute-path leaks, stale) |
| `~/.claude/projects/*/memory/` (auto-memory) | user | **not exported** | personal; contains server details |
| `.remember/` and Remember plugin | user | optional | not required |
| claude-mem (`~/.claude-mem`) | user | **disabled in project** | do not enable |
| MCP servers | user/account | none defined by project | none to install |

## Verification matrix

| Claim | Level |
|---|---|
| `validate.sh --full` passes (23 pass, 0 fail, 2 warn) in an isolated worktree of `origin/work` + this package, using the original machine's installed tools | verified on original machine only |
| `bootstrap.sh` dry run with an empty HOME reports both plugins MISSING and makes no changes | verified (no install executed) |
| `bootstrap.sh --apply` actually installing plugins and the graph from scratch | **requires second machine** (plugin download path untested) |
| Linux, Windows (WSL/Git Bash) | **unverified** |
| Fresh interactive Claude session printing `Graphify loaded:` on the second machine | **requires second machine** |
| xlayer accuracy vs current `work` | **known failing** (3 tests) |
| Precedence of project vs user settings | documented from Claude Code behaviour [U] beyond `enabledPlugins`/hook additivity observed here |
