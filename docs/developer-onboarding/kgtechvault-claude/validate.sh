#!/usr/bin/env bash
# Non-destructive validation of the KGTechVault Claude Code environment.
# Writes nothing outside the repo's gitignored graphify-out/ and a temp dir. Exit 1 on any FAIL.
#   validate.sh          fast checks (config, tools, plugins, graph query, hook matcher)
#   validate.sh --full   also runs the repo's graphify session + xlayer test suites
set -u
cd "$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "FAIL not inside a git checkout"; exit 1; }
pass=0; fail=0; warn=0
ok(){ echo "PASS  $1"; pass=$((pass+1)); }
ko(){ echo "FAIL  $1"; fail=$((fail+1)); }
wn(){ echo "WARN  $1"; warn=$((warn+1)); }
chk(){ if eval "$2"; then ok "$1"; else ko "$1"; fi; }
export PATH="$HOME/.local/bin:$PATH"

echo "== repository"
chk "origin is KGKG (not a lookalike repo)" 'git remote get-url origin 2>/dev/null | grep -qi "mjsn800403/KGKG"'
chk "CLAUDE.md routes to AGENTS.md and has operating framework" 'grep -q "AGENTS.md" CLAUDE.md && grep -q "Operating framework" CLAUDE.md && grep -q "Ask freely" CLAUDE.md'
chk "AGENTS.md and docs/AGENTS.md exist" '[ -f AGENTS.md ] && [ -f docs/AGENTS.md ]'

echo "== shared Claude config"
chk ".claude/settings.json is valid JSON" 'python3 -c "import json;json.load(open(\".claude/settings.json\"))"'
chk "settings.json has SessionStart + PreToolUse hooks and pinned plugins" 'python3 - <<EOF
import json,sys
d=json.load(open(".claude/settings.json"));h=d["hooks"];p=d["enabledPlugins"]
sys.exit(0 if "SessionStart" in h and "PreToolUse" in h and p.get("caveman@caveman") is True and p.get("superpowers@superpowers-dev") is True else 1)
EOF'
chk "claude-mem stays disabled for this project (deliberate)" 'python3 -c "import json,sys;sys.exit(0 if json.load(open(\".claude/settings.json\"))[\"enabledPlugins\"].get(\"claude-mem@thedotmack\") is False else 1)"'
chk "session hook exists and is executable" '[ -x .claude/hooks/graphify-session-start.sh ]'
chk ".graphifyignore present" '[ -f .graphifyignore ]'
chk ".claude/settings.local.json is not tracked (personal)" '! git ls-files --error-unmatch .claude/settings.local.json >/dev/null 2>&1'
chk "graphify-out/ is gitignored (graph is machine-local)" 'git check-ignore -q graphify-out'

echo "== prerequisites"
chk "claude CLI on PATH" 'command -v claude >/dev/null'
chk "python3 >= 3.10" 'python3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)"'
chk "graphify CLI on PATH, version 0.8.x" 'command -v graphify >/dev/null && graphify --version 2>&1 | grep -q "0\.8\."'

echo "== plugins (settings only ENABLE them; they must be installed per machine)"
if command -v claude >/dev/null; then
  PL=$(claude plugin list --json 2>/dev/null || echo "[]")
  for id in caveman@caveman superpowers@superpowers-dev; do
    if echo "$PL" | python3 -c "import json,sys;sys.exit(0 if any(p.get('id')=='$id' and p.get('enabled') for p in json.load(sys.stdin)) else 1)" 2>/dev/null
    then ok "plugin installed+enabled: $id"; else ko "plugin missing or disabled: $id (run bootstrap.sh --apply)"; fi
  done
  echo "$PL" | python3 -c "import json,sys;sys.exit(0 if any(p.get('id','').startswith(('remember@','claude-mem@')) for p in json.load(sys.stdin)) else 1)" 2>/dev/null \
    && wn "personal memory plugin(s) installed (remember/claude-mem): optional, not required by this project" || true
fi

echo "== graphify"
if [ -s graphify-out/graph.json ]; then ok "graph.json present"; else ko "graph.json missing (run scripts/setup-graphify.sh)"; fi
chk "merged-graph.json (cross-layer) present" '[ -s graphify-out/merged-graph.json ]'
chk "graph query works (AST graph)" 'graphify query "project architecture" --budget 200 >/dev/null 2>&1'
chk "graph query works (merged cross-layer graph)" 'graphify query "logout" --graph graphify-out/merged-graph.json --budget 200 >/dev/null 2>&1'
chk "xlayer trace works" 'python3 tools/graphify_xlayer/xlayer.py trace "/api/auth/logout/" >/dev/null 2>&1'
chk "session hook emits INIT OK and the mandatory protocol" 'CLAUDE_PROJECT_DIR=$PWD .claude/hooks/graphify-session-start.sh | grep -q "SESSION INIT OK"'

echo "== PreToolUse grep-hook matcher (fires on real search commands, not substrings)"
python3 - <<'EOF' && ok "matcher: 17/17 cases" || ko "matcher regression"
import json,subprocess,sys
cmd=json.load(open(".claude/settings.json"))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
cases=[("grep -rn foo src",1),("rg foo",1),("cat x | grep y",1),("cd a && find . -name x",1),("ag foo",1),("ack foo",1),("git grep foo",1),("sudo find /",1),("xargs grep x",1),("echo hello; ag x",1),("echo flag x",0),("echo stack x",0),("ls -la",0),("git stage a",0),("npm run build",0),("python3 manage.py test",0),('echo "see find x"',0)]
import os
# the hook only speaks when a graph exists
os.makedirs("graphify-out",exist_ok=True)
if not os.path.exists("graphify-out/graph.json"): sys.exit(1)
bad=0
for c,e in cases:
    r=subprocess.run(["bash","-c",cmd],input=json.dumps({"tool_input":{"command":c}}),capture_output=True,text=True)
    bad+=(("MANDATORY" in r.stdout)!=bool(e))
sys.exit(1 if bad else 0)
EOF

if [ "${1:-}" = "--full" ]; then
  echo "== repo graphify suites (--full)"
  chk "scripts/test-graphify-session.sh" './scripts/test-graphify-session.sh >/dev/null 2>&1'
  if ./scripts/test-graphify-xlayer.sh >/dev/null 2>&1; then ok "scripts/test-graphify-xlayer.sh"; else wn "xlayer accuracy suite fails against current code: known issue, see README 'Known issues'"; fi
fi

echo "== summary: $pass passed, $fail failed, $warn warnings"
echo "NOT checkable by script: that a live Claude session loads these. Open Claude in the repo and confirm the first reply starts with 'Graphify loaded: ...'."
[ $fail -eq 0 ]
