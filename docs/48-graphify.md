# 48 — Graphify (code knowledge graph for Claude Code)

Every Claude Code session in this repo starts by consulting a Graphify knowledge graph
of the codebase. Configuration is shared through Git; the graph itself is rebuilt locally.

## What is shared vs. local

| Item | Where | Shared via Git? |
|---|---|---|
| Session-start hook | `.claude/hooks/graphify-session-start.sh` | yes |
| Hook registration + graphify PreToolUse nudges | `.claude/settings.json` | yes |
| Agent rules | `CLAUDE.md` (graphify section) | yes |
| Corpus exclusions | `.graphifyignore` | yes |
| Machine bootstrap / contract test | `scripts/setup-graphify.sh`, `scripts/test-graphify-session.sh` | yes |
| The graph (`graphify-out/`) | local | **no** (gitignored) |
| Personal permissions | `.claude/settings.local.json` | no |

**Why the graph is not shared:** graphify has no server/sync protocol (Graphify Cloud is a
separate paid product, not used here). The AST graph rebuilds in ~5 s with no LLM or API
key, deterministically from the commit, so each machine regenerates it and cannot drift
from its own checkout. Committing `graph.json` (~2 MB) would cause merge noise and
absolute-path leaks (`.graphify_root`). If an LLM semantic layer (docs/PDF) is ever built
(costly), revisit: commit that output and enable graphify's `merge-driver`.

## New machine

```bash
git clone https://github.com/mjsn800403/KGKG.git && cd KGKG
./scripts/setup-graphify.sh      # installs graphifyy (pinned <0.9) if missing, builds graph + cross-layer layers
./scripts/setup-graphify.sh --with-skill   # also installs the user-level /graphify skill (writes ~/.claude)
```
Then open Claude Code in the repo. Requirements: Python 3.10+ and one of uv / pipx / pip; `python3` on PATH.

## Session-start contract (mandatory)

On `startup|resume|clear|compact` the hook:
1. locates the `graphify` CLI — if missing, injects a **FAILED** notice ordering Claude to tell the user the graph was not loaded (never to pretend);
2. builds the graph only if missing; refreshes (`graphify update .`) only if source files are newer than `graph.json`; otherwise reuses it;
3. injects stats + God Nodes + surprising connections, and instructs Claude to run `graphify query` on the task topic and open its first reply with `Graphify loaded: …`.

During work, PreToolUse hooks nudge Claude to query the graph before grep/Read; after edits run `graphify update .`.

## Cross-layer companion index (`tools/graphify_xlayer/`)

Graphify 0.8.46 parses code per language and has no model of HTTP calls, Django URL routing or ORM relations.
It also has no supported hook to add edges during `update`, so the companion layer is **separate files**:
`xlayer.json` (same node/link schema, every link has file:line evidence), `docsindex.json`, merged with
`graphify merge-graphs` into `merged-graph.json`. `graph.json` is never modified (asserted by a test).

| Relationship | Method | Confidence |
|---|---|---|
| component → API client fn | tree-sitter: named import from the api module + use site | EXTRACTED |
| client fn → method + endpoint | tree-sitter: `fetch`/wrapper calls, template literals → `<param>` | EXTRACTED; INFERRED when the client path also matches other Django routes |
| endpoint → Django route → view | `ast` over `urls.py`, Django first-match semantics | EXTRACTED |
| view → models / services | `ast`: model names referenced, calls resolved through imports (1 hop) | EXTRACTED |
| model → model | `ast`: ForeignKey / OneToOneField / ManyToManyField | EXTRACTED |
| doc section → code | backticked paths / symbols / routes in Markdown | INFERRED (a mention, not a proof) |

Unresolvable items (dynamic URLs, etc.) go to `graphify-out/xlayer-report.json`, never into the graph.
Stale doc references (paths in docs that no longer exist) go to `docsindex-report.json`.

Commands: `./scripts/graphify-refresh-layers.sh` (all layers + viewer + merge), `python3 tools/graphify_xlayer/xlayer.py trace "/api/…/"`.
`graphify-out/architecture.html` = filterable module-level view (layers, prod/test, confidence, edge types, endpoint chains, unresolved list); `graph.html` stays the detailed native view.

## Verify

```bash
bash scripts/test-graphify-session.sh   # hook contract: OK path, loud failure path, fresh-checkout build
bash scripts/test-graphify-xlayer.sh    # accuracy of the cross-layer index (8 tests)
bash scripts/verify-graphify-usage.sh   # needs `claude auth login`: fresh session must run a real graphify query
```

## Permissions & portability notes

- Shared `.claude/settings.json` auto-allows only read-only graph queries (`graphify query|path|explain|affected`,
  `xlayer.py trace`). `graphify update` and `scripts/graphify-refresh-layers.sh` write to the gitignored
  `graphify-out/` and are run by the SessionStart hook itself; Claude asks before running them. Personal permissions
  belong in `.claude/settings.local.json` (ignored).
- The setup script does **not** run `graphify hook install` (it edits git hooks; this repo uses `core.hooksPath=.githooks`).
- Needs bash, python3, git. The layer scripts run on graphify's own interpreter (found from the `graphify` shebang,
  incl. `#!/usr/bin/env python3`), which carries tree-sitter. If `python3` is missing the hook degrades to plain-text context.
- **Tested only on macOS (bash 3.2, conda-installed graphifyy 0.8.46).** Not yet tested: Linux, WSL, uv/pipx installs,
  a clean machine without graphify, Windows (not supported: bash scripts).

## Limitations

- Cross-layer limits: only `fetch`-based calls; dynamic URLs unresolved; view→model is direct references only (1-hop services); Django signals/middleware/DRF-style dispatch not modelled; `re_path` and class-based views are reported, not graphed.
- Graph is **AST-only**: 196 code files (py/js/jsx/sh…). Markdown docs, PDFs and images are not in it (needs an LLM backend: `GEMINI_API_KEY`/`ANTHROPIC_API_KEY` + `/graphify --update`).
- Community names are placeholders ("Community N") until `graphify label` is run with an LLM backend.
- Hook output is context for the model; compliance (first-reply status line) is instructed, not enforced by Claude Code.
- `.claude/settings.json` was previously gitignored; `.gitignore` now un-ignores it and `hooks/`.
- The existing user-level `~/.claude/CLAUDE.md` graphify trigger is per-user; it is not needed for this project's hook.
