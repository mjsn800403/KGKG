#!/usr/bin/env bash
# Verifies the session-init contract: OK path emits context; FAIL paths say so loudly.
set -u
cd "$(git rev-parse --show-toplevel)"
H=.claude/hooks/graphify-session-start.sh; pass=0; fail=0
chk(){ if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }
out=$(CLAUDE_PROJECT_DIR=$PWD $H)
chk "OK path reports INIT OK + mandatory protocol" 'echo "$out" | grep -q "SESSION INIT OK" && echo "$out" | grep -q "MANDATORY"'
chk "OK path includes god nodes digest" 'echo "$out" | grep -q "God Nodes"'
chk "settings.json registers SessionStart" 'grep -q graphify-session-start .claude/settings.json'
out2=$(GRAPHIFY_BIN=/nonexistent/graphify CLAUDE_PROJECT_DIR=$PWD $H)
chk "missing CLI -> loud FAILED message, no fake success" 'echo "$out2" | grep -q "SESSION INIT FAILED" && ! echo "$out2" | grep -q "INIT OK"'
chk "FAILED message orders user-visible report" 'echo "$out2" | grep -q "FIRST reply"'
T=$(mktemp -d); cp -R .claude "$T/.claude"
out3=$(GRAPHIFY_BIN=$(command -v graphify) CLAUDE_PROJECT_DIR=$T $H 2>&1)
chk "fresh checkout w/o graph -> builds it (or fails loud)" 'echo "$out3" | grep -q "SESSION INIT OK\|SESSION INIT FAILED"'
rm -rf "$T"
T2=$(mktemp -d); (cd "$T2" && git init -q && git config user.email t@t && git config user.name t && mkdir -p .claude/hooks scripts && echo 'x=1' > a.py \
  && printf '#!/bin/sh\nexit 1\n' > scripts/graphify-refresh-layers.sh && chmod +x scripts/*.sh && git add -A && git commit -qm i) >/dev/null 2>&1
cp .claude/hooks/graphify-session-start.sh "$T2/.claude/hooks/"
CLAUDE_PROJECT_DIR=$T2 "$T2/.claude/hooks/graphify-session-start.sh" >/dev/null 2>&1; echo '{"x":1}' > "$T2/graphify-out/merged-graph.json"
o4=$(CLAUDE_PROJECT_DIR=$T2 "$T2/.claude/hooks/graphify-session-start.sh" 2>&1); o5=$(CLAUDE_PROJECT_DIR=$T2 "$T2/.claude/hooks/graphify-session-start.sh" 2>&1)
chk "failed layer refresh is retried and a stale merged graph is not recommended" 'echo "$o4$o5" | grep -q UNAVAILABLE && ! echo "$o4$o5" | grep -q "graph graphify-out/merged-graph.json"'
rm -rf "$T2"
echo "$pass passed, $fail failed"; [ $fail -eq 0 ]
