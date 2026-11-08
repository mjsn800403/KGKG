#!/usr/bin/env bash
# One-shot, idempotent Graphify setup for a new machine / developer.
# Installs the CLI (pinned), registers the Claude skill, builds the graph, verifies.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
PIN="graphifyy>=0.8.46,<0.9"
if ! command -v graphify >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then uv tool install "$PIN"
  elif command -v pipx >/dev/null 2>&1; then pipx install "$PIN"
  else python3 -m pip install --user "$PIN"; fi
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v graphify >/dev/null || { echo "graphify not on PATH; add ~/.local/bin"; exit 1; }
# Optional: user-level /graphify skill (writes to ~/.claude). Not needed for the session hook.
[ "${1:-}" = "--with-skill" ] && graphify install
# NOTE: deliberately does NOT run `graphify hook install` (it edits git hooks; this repo uses core.hooksPath=.githooks).
graphify update .                                # AST-only, no LLM/API key, ~5s
test -s graphify-out/graph.json
./scripts/graphify-refresh-layers.sh
graphify query "project architecture" --budget 300 >/dev/null
echo "OK: graphify $(graphify --version 2>/dev/null | head -1) ready. Session hook: .claude/hooks/graphify-session-start.sh"
