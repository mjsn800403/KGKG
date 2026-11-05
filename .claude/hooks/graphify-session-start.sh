#!/usr/bin/env bash
# SessionStart hook: make every Claude Code session begin by consulting Graphify.
#  - finds the graphify CLI (fails LOUD if absent)
#  - builds the graph only if missing, refreshes only if code is newer than it
#  - injects a graph digest + a mandatory "report graph status first" instruction
# Output: JSON on stdout (hookSpecificOutput.additionalContext). Never exits non-zero.
cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}" || exit 0
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/opt/anaconda3/bin:$PATH"

emit() { # $1 = context text
  command -v python3 >/dev/null 2>&1 || { printf '%s\n' "$1"; return 0; }   # plain stdout is also injected as context
  python3 - "$1" <<'PY'
import json,sys
print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":sys.argv[1]}}))
PY
}
fail() {
  emit "GRAPHIFY SESSION INIT FAILED: $1
MANDATORY: your FIRST reply must tell the user, verbatim in substance, that Graphify graph context was NOT loaded and why. Do NOT claim you reviewed the project graph. Fix: run ./scripts/setup-graphify.sh (see docs/15-graphify.md). Until fixed, fall back to normal exploration and say so."
  exit 0
}

GRAPHIFY=${GRAPHIFY_BIN:-$(command -v graphify)}
[ -x "$GRAPHIFY" ] || fail "graphify CLI not found on PATH (package: graphifyy)."
G=graphify-out/graph.json
LAYERS="graphify-out/merged-graph.json"
layers() { [ -x scripts/graphify-refresh-layers.sh ] && ./scripts/graphify-refresh-layers.sh >/tmp/graphify-layers.log 2>&1 && LAYER_STATE="cross-layer index + docs index + merged graph ready" || LAYER_STATE="cross-layer layers UNAVAILABLE (see /tmp/graphify-layers.log) - base AST graph only"; }
LAYER_STATE=""
STAMP=graphify-out/.last_refresh   # graph.json is not rewritten when nothing changed, so track our own refresh time
[ -f "$STAMP" ] || STAMP=$G
ACTION="reused existing graph"
if [ ! -f "$G" ]; then
  "$GRAPHIFY" update . >/tmp/graphify-session.log 2>&1 || fail "graph missing and 'graphify update .' failed (see /tmp/graphify-session.log)."
  ACTION="built graph (was missing)"
elif [ "$(git rev-parse HEAD 2>/dev/null)" != "$(python3 -c "import json;print(json.load(open('$G')).get('built_at_commit',''))" 2>/dev/null)" ]; then
  # branch switch / new commits / pull: HEAD differs from the commit the graph was built at (catches pure deletions mtime misses)
  "$GRAPHIFY" update . >/tmp/graphify-session.log 2>&1 || fail "graph built at a different commit and 'graphify update .' failed (see /tmp/graphify-session.log)."
  ACTION="refreshed graph (HEAD moved since last build)"
elif [ -n "$(find . \( -name node_modules -o -name .venv -o -name .next -o -name graphify-out -o -name .git -o -name worktrees \) -prune -o -type f \( -name '*.py' -o -name '*.js' -o -name '*.jsx' -o -name '*.ts' -o -name '*.tsx' -o -name '*.sh' -o -name '*.sql' \) -newer "$STAMP" -print -quit 2>/dev/null)" ]; then
  "$GRAPHIFY" update . >/tmp/graphify-session.log 2>&1 || fail "graph stale and 'graphify update .' failed (see /tmp/graphify-session.log)."
  ACTION="refreshed stale graph (AST-only, no LLM)"
fi
[ -s "$G" ] || fail "graph.json empty after build."
if [ "$ACTION" != "reused existing graph" ] || [ ! -s "$LAYERS" ]; then layers; else LAYER_STATE="cross-layer index + docs index + merged graph ready (reused)"; fi
touch graphify-out/.last_refresh

R=graphify-out/GRAPH_REPORT.md
DIGEST=$(sed -n '1,16p;/^## God Nodes/,/^## Import Cycles/p' "$R" 2>/dev/null | cut -c1-220 | head -70)
MERGED_HINT=""; [ -s "$LAYERS" ] && MERGED_HINT=" --graph graphify-out/merged-graph.json"
STATS=$(python3 -c "import json;d=json.load(open('$G'));print(len(d.get('nodes',[])),'nodes,',len(d.get('links',d.get('edges',[]))),'edges')" 2>/dev/null || echo "unknown size")

emit "GRAPHIFY SESSION INIT OK ($ACTION; $STATS). Layers: $LAYER_STATE.
MANDATORY session protocol:
1. Before the user's task, run a task-relevant query, e.g. 'graphify query \"<topic>\"$MERGED_HINT' (merged graph = AST + frontend->API->Django route->view->model links). For one endpoint's full chain: 'python3 tools/graphify_xlayer/xlayer.py trace \"/api/<path>/\"'. Relationships: 'graphify path \"A\" \"B\"$MERGED_HINT'.
2. Begin your FIRST reply with one line: 'Graphify loaded: <stats>; consulted for: <the query you ran>'. If a query fails, say so.
3. Graph is static analysis: EXTRACTED = read from source, INFERRED = ambiguous/convention. Where a needed relationship is absent or INFERRED (dynamic URLs, HTTP calls not via fetch, Django signals, string-built names), read the source files to confirm; list gaps in graphify-out/xlayer-report.json.
4. After code edits run './scripts/graphify-refresh-layers.sh' (and 'graphify update .').
Graph digest (GRAPH_REPORT.md excerpt):
$DIGEST"
