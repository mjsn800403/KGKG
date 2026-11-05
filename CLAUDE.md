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
