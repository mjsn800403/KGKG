#!/usr/bin/env bash
# Throwaway stack for qa/e2e/tests/support-chat.spec.js on Linux (CI job
# support-chat-e2e, or a server shell). The Linux twin of
# local-support-chat-stack.ps1.
#
# Nothing here touches a shared, staging or production database: it creates its
# own SQLite file under STACK_DIR, never reads .env.prod (KG_ENV_FILE points at
# an empty file), runs Django with DEBUG (Turnstile verification is skipped
# server-side; the spec fakes the browser script), builds Next with the dev API
# proxy and serves both. The public chat is switched on only inside this stack.
#
#   qa/e2e/support-chat-stack.sh up   /tmp/scstack     # build, seed, start
#   SUPPORT_E2E_FIXTURES=/tmp/scstack/fixtures.json QA_ORIGIN=http://127.0.0.1:3200 \
#     SUPPORT_E2E_REQUIRED=1 npx playwright test support-chat.spec.js --project=chromium
#   qa/e2e/support-chat-stack.sh down /tmp/scstack
#
# KG_E2E_PYTHON picks the interpreter (default KG_backend/.venv/bin/python, then
# python3). Ports: SC_API_PORT (8200), SC_WEB_PORT (3200); playwright.config.js
# refuses 8000/3000, production's.
set -euo pipefail
CMD=${1:?up|down}; STACK=${2:?stack dir}
API=${SC_API_PORT:-8200}; WEB=${SC_WEB_PORT:-3200}
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BACKEND=$REPO/KG_backend
PY=${KG_E2E_PYTHON:-$BACKEND/.venv/bin/python}
[[ -x $PY ]] || PY=$(command -v python3)

down() {
  for f in "$STACK"/*.pid; do
    [[ -f $f ]] || continue
    kill "$(cat "$f")" 2>/dev/null || true
    rm -f "$f"
  done
}
if [[ $CMD == down ]]; then down; exit 0; fi
[[ $CMD == up ]] || { echo "usage: $0 up|down STACK_DIR" >&2; exit 2; }

mkdir -p "$STACK"
STACK=$(cd "$STACK" && pwd)
down
: > "$STACK/empty.env"
export KG_ENV_FILE=$STACK/empty.env
export KG_DB_ENGINE=sqlite
export KG_DB_PATH=$STACK/e2e.sqlite3
export KG_DATA_DIR=$STACK
export DJANGO_DEBUG=true
export KG_ADMIN_TOKEN=local-e2e-loopback
export KG_SUPPORT_CHAT_ENABLED=1
export TURNSTILE_SECRET=
export KG_SC_CREATE_IP=0/0       # one browser IP starts many test chats
export KG_SC_BAD_TOKEN_IP=0/0
export KG_WARMUP=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
rm -f "$KG_DB_PATH"*

cd "$BACKEND"
"$PY" manage.py migrate --noinput >/dev/null
"$PY" manage.py shell -c "
import json
from api.models import AdminAuthToken, PlatformAdmin
out = {}
for key, name in (('staff', 'e2e-staff'), ('staff2', 'e2e-staff-2')):
    a, _ = PlatformAdmin.objects.get_or_create(username=name, defaults={'password_hash': 'x', 'active': True})
    out[key] = {'id': a.id, 'username': a.username, 'token': AdminAuthToken.issue(a).key}
json.dump(out, open('$STACK/fixtures.json', 'w'))
"
nohup "$PY" manage.py runserver "127.0.0.1:$API" --noreload \
  > "$STACK/django.out.log" 2> "$STACK/django.err.log" &
echo $! > "$STACK/django.pid"

cd "$REPO/kg_frontend"
export KG_DEV_API_PROXY=http://127.0.0.1:$API
export API_BASE_INTERNAL=http://127.0.0.1:$API
# Switch the inbox's fallback polling off so the spec proves SSE alone delivers.
export NEXT_PUBLIC_SUPPORT_INBOX_REFRESH_S=3600
npx next build > "$STACK/next.build.log" 2>&1 || { tail -40 "$STACK/next.build.log"; exit 1; }
nohup npx next start -p "$WEB" -H 127.0.0.1 > "$STACK/next.out.log" 2> "$STACK/next.err.log" &
echo $! > "$STACK/next.pid"

for _ in $(seq 60); do
  if curl -sf "http://127.0.0.1:$API/api/health/" >/dev/null \
     && curl -sf -o /dev/null "http://127.0.0.1:$WEB/"; then
    echo "stack up: web http://127.0.0.1:$WEB  api http://127.0.0.1:$API  fixtures $STACK/fixtures.json"
    exit 0
  fi
  sleep 2
done
echo "stack did not come up; logs in $STACK" >&2
tail -20 "$STACK/django.err.log" "$STACK/next.err.log" >&2
exit 1
