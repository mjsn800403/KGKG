#!/usr/bin/env bash
# Reproduce the KGTechVault Claude Code environment on this machine.
#   bootstrap.sh            DRY RUN: report what is missing and what --apply would do. Changes nothing.
#   bootstrap.sh --apply    perform the missing steps (idempotent; safe to re-run).
# Writes: ~/.claude/plugins (via `claude plugin ...`, user scope) and the gitignored graphify-out/.
# Never edits ~/.claude/settings.json by hand, never touches .claude/settings.local.json, never uses an API key/LLM.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
say(){ printf '%s\n' "$*"; }
todo=0

command -v git >/dev/null    || { say "MISSING git"; exit 1; }
command -v claude >/dev/null || { say "MISSING claude CLI: install Claude Code first (https://claude.com/claude-code), sign in yourself, then re-run."; exit 1; }
python3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>/dev/null || { say "MISSING python3 >= 3.10 (on Windows use WSL or Git Bash with python3 on PATH)"; exit 1; }
git remote get-url origin | grep -qi 'mjsn800403/KGKG' || { say "STOP: origin is not mjsn800403/KGKG; refusing to configure a different repository."; exit 1; }

# 1) Back up personal user config before anything can touch it (only when applying).
if [ $APPLY -eq 1 ]; then
  TS=$(date +%Y%m%d-%H%M%S)
  for f in "$HOME/.claude/settings.json" "$HOME/.claude/installed_plugins.json" "$HOME/.claude/plugins/installed_plugins.json"; do
    [ -f "$f" ] && cp -p "$f" "$f.bak-$TS" && say "backup: $f.bak-$TS"
  done
fi

# 2) Marketplaces + plugins (project settings only ENABLE them; they must be installed per machine).
#    id | marketplace name | marketplace source
PLUGINS="caveman@caveman|caveman|JuliusBrussee/caveman
superpowers@superpowers-dev|superpowers-dev|obra/superpowers"
MK=$(claude plugin marketplace list 2>/dev/null || true)
PL=$(claude plugin list --json 2>/dev/null || echo "[]")
while IFS='|' read -r id mk src <&3; do
  if ! echo "$PL" | python3 -c "import json,sys;sys.exit(0 if any(p.get('id')=='$id' for p in json.load(sys.stdin)) else 1)"; then
    say "MISSING plugin $id (marketplace $mk <- $src)"
    if [ $APPLY -eq 1 ]; then
      echo "$MK" | grep -q "$mk" || claude plugin marketplace add "$src"
      claude plugin install "$id"
    fi
  else say "ok      plugin $id"; fi
done 3<<<"$PLUGINS"
say "note: claude-mem is intentionally disabled for this project by .claude/settings.json; Remember is optional and personal. Neither is required."

# 3) Graphify CLI + AST graph + cross-layer index: delegate to the repo's own idempotent script.
if command -v graphify >/dev/null && [ -s graphify-out/graph.json ] && [ -s graphify-out/merged-graph.json ]; then
  say "ok      graphify $(graphify --version 2>/dev/null | head -1) and local graph present"
else
  say "MISSING graphify CLI or local graph -> scripts/setup-graphify.sh (pinned graphifyy>=0.8.46,<0.9; AST-only, no LLM)"
  [ $APPLY -eq 1 ] && ./scripts/setup-graphify.sh
fi

if [ $APPLY -eq 0 ]; then say "DRY RUN complete. Re-run with --apply to perform the steps marked MISSING."; exit 0; fi
say "Applied. Validating..."
exec "$(dirname "$0")/validate.sh"
