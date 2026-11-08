#!/usr/bin/env bash
# Priority-4 check: does a FRESH, AUTHENTICATED Claude Code session actually (1) get the hook context,
# (2) run a real graphify query, (3) then read source files? Exits 2 if claude is not logged in (cannot verify).
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"
if ! claude auth status 2>/dev/null | grep -q '"loggedIn": true'; then
  echo "BLOCKED: claude CLI not authenticated (run: claude auth login). Nothing verified."; exit 2; fi
T=$(mktemp); claude -p "Which Django view serves the endpoint that teamApi.members calls, and which models does it touch? Answer in 3 lines." \
  --output-format stream-json --verbose --max-turns 12 --permission-mode acceptEdits </dev/null >"$T" 2>&1
python3 - "$T" <<'PY'
import json,sys,re
hook=q=read=False; first=''; order=[]; errs=[]
for l in open(sys.argv[1]):
    try: d=json.loads(l)
    except Exception: continue
    s=json.dumps(d)
    if d.get('type')=='system' and 'GRAPHIFY SESSION INIT OK' in s: hook=True
    if d.get('type')=='user':
        for c in (d.get('message',{}).get('content') or []):
            if isinstance(c,dict) and c.get('type')=='tool_result' and c.get('is_error'): errs.append(str(c.get('content'))[:120])
    if d.get('type')=='assistant':
        for c in d['message']['content']:
            if c['type']=='text' and not first: first=c['text']
            if c['type']=='tool_use':
                cmd=json.dumps(c['input'])
                if c['name']=='Bash' and re.search(r'graphify (query|path|explain|affected)|xlayer\.py trace',cmd): q=True; order.append('graphify')
                elif c['name'] in('Read','Grep','Glob') or (c['name']=='Bash' and re.search(r'\b(cat|sed|grep|rg)\b',cmd)): read=True; order.append('source')
print('tool errors/denials:',errs[:3])
print(f"1 hook context injected : {hook}\n2 real graphify query run : {q}\n3 source inspected after  : {read} (order: {order[:8]})\nfirst text: {first[:160]!r}\nstarts with 'Graphify loaded': {first.startswith('Graphify loaded')}")
sys.exit(0 if (hook and q and first.startswith('Graphify loaded')) else 1)
PY
