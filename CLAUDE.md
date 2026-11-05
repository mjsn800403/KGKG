Read `AGENTS.md` (root) and then `docs/AGENTS.md` before working in this repository. They route you to the right document per task
and list the rules that are easy to break. Do not duplicate their content here.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Graphify cross-layer index (project-specific; not managed by `graphify claude install`)

`graphify-out/merged-graph.json` = Graphify AST graph + companion layers built by `tools/graphify_xlayer/` (deterministic, no LLM):
frontend component → API client fn → HTTP method+endpoint → Django route → view → models/services, Django FK/O2O/M2M relations, and a docs index.

- Prefer: `graphify query "<symbol or topic>" --graph graphify-out/merged-graph.json`, `graphify path "A" "B" --graph graphify-out/merged-graph.json`.
- Full chain for one endpoint: `python3 tools/graphify_xlayer/xlayer.py trace "/api/team/members/"`.
- Edge confidence: EXTRACTED = read from source; INFERRED = ambiguous (e.g. client path also matches catch-all routes) or docs mentions. Treat INFERRED as a lead, then read the source.
- Not in the graph (verify in source): dynamic URLs (see `graphify-out/xlayer-report.json`), HTTP calls not via `fetch`, Django signals, string-built names.
- After edits: `./scripts/graphify-refresh-layers.sh`. Visual: open `graphify-out/architecture.html` (serve the folder: `python3 -m http.server -d graphify-out`).

## Operating framework (applies to every session; keep terse)

Goal: max quality / min total cost. Quality, security, verification never traded for token savings.

**Ask freely.** "Feel free to ask" is permanent. Ask (AskUserQuestion, 1-3 questions, with a recommended option) when ambiguity could change correctness, product behavior, scope, infra safety or architecture, or instructions conflict. Never present assumptions as facts; state them. Do NOT ask what project files, graph, memory or docs can answer.

**Skills = tools, not rituals.** Invoke by task size, smallest set that works. This overrides superpowers' "invoke on 1% chance" rule.
- Trivial (typo, rename, one-file read/answer): no skill; just do it.
- New feature / behavior change: `superpowers:brainstorming` (short) → `superpowers:writing-plans` only if ≥3 dependent steps → `superpowers:test-driven-development`.
- Bug: `superpowers:systematic-debugging` first; reproduce before fixing.
- Before claiming done / committing: `superpowers:verification-before-completion` (run the real command, show output).
- Multi-file review: `/code-review`; security-touching: `/security-review`; infra/deploy: `engineering:deploy-checklist`.
- Independent parallel work: subagents (`caveman:cavecrew-investigator` for read-only lookups). No subagents for small tasks.
- Caveman = output style, always on via plugin hook. Code, commits, PRs, security/irreversible warnings stay normal prose.

**Context order (cheapest first).** 1) auto-memory + this file → 2) `graphify query/path/explain` on `graphify-out/merged-graph.json` (structure, callers, FE→API→view→model) → 3) targeted Grep/Read of only the files the graph points to → 4) subagent only for wide sweeps. Graph is static: verify INFERRED edges and dynamic URLs in source. After code edits: `./scripts/graphify-refresh-layers.sh`.

**Execution discipline.**
- State goal, done-criteria, and plan (1-5 lines for small, structured only if complex) before editing.
- Follow plan; change it only on new evidence, and say so. Stay in scope; no drive-by refactors.
- Don't re-read/re-derive what's already established this session. Batch independent tool calls.
- Stuck signal: 2 failed attempts at same approach, or 3+ exploration calls with no new fact → stop, state what is known/unknown, switch approach or ask.
- Prefer bounded tool output (limits, file ranges, focused searches, `graphify --budget`), but never truncate what correctness, debugging, security analysis or verification needs; fetch more selectively when required.
- At a milestone with substantial context, assess whether compaction or a fresh session would help; first confirm objective, verified findings, decisions, open issues and exact next steps survive. Recommend only; never compact/reset without my approval. No token thresholds.
- Prefer real deliverables over documents. No new docs/plan files unless asked.

**Persistence (what actually survives sessions).** CLAUDE.md files, auto-memory (`~/.claude/projects/.../memory/`), `.claude/settings.json` hooks, git. Save to memory only durable, verified facts (decisions, constraints, gotchas, next steps) — not session chatter or things derivable from code/git. Update, don't duplicate. Do not claim persistence beyond these.

**Safety.** Never change prod infra, credentials, or unrelated projects as a side effect. Prod server is ahead of GitHub (see memory). Confirm before irreversible or outward-facing actions.

**Plugin portability.** `enabledPlugins` in `.claude/settings.json` only *enables* `caveman@caveman` and `superpowers@superpowers-dev`; it does not install them. On another machine, add the marketplaces first (`/plugin marketplace add JuliusBrussee/caveman`, `/plugin marketplace add obra/superpowers`) and install both, or the settings entry is inert.
