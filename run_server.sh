#!/usr/bin/env bash
# ============================================================
#  KGtechvault — start backend + frontend.
#  Assumes check_prereqs.sh has already been run once.
#  Opens your browser to localhost:3000 once the site is ready.
#
#  chmod +x run_all.sh && ./run_all.sh
# ============================================================
cd "$(dirname "$0")"

# RAG embedding model — MUST match the model run_rag_build.sh built with.
# Serving stays fully offline (uses the already-downloaded model from cache).
export RAG_EMBED_MODEL="${RAG_EMBED_MODEL:-bge-m3}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
# Warm the embedding model + index connection at startup so the first assistant
# query is fast (cold model load ~10-15s). Only the runserver child warms (apps.py).
export KG_WARMUP=1
# Local dev: DEBUG on (uses the built-in dev key, allows localhost). In
# production set DJANGO_DEBUG=false + DJANGO_SECRET_KEY + DJANGO_ALLOWED_HOSTS.
export DJANGO_DEBUG="${DJANGO_DEBUG:-true}"

# --- Security / abuse guards (api/ratelimit.py) -----------------------------
# Admin gate for ranking-mutating endpoints (/api/feedback/pin/) and the review
# queue (/api/feedback/recent/). In DEBUG these are open for convenience; in
# PRODUCTION you MUST set a token (the admin-review page prompts for it):
#   export KG_ADMIN_TOKEN="choose-a-long-random-secret"
# Per-IP rate limits are "requests/seconds"; override any with KG_RL_<NAME>:
#   KG_RL_ASSIST, KG_RL_DIAGNOSE, KG_RL_SEARCH, KG_RL_RATE, KG_RL_PIN, KG_RL_CLICK
#   (set KG_RL_DISABLE=1 to turn the limiter off entirely).
# Only set KG_TRUST_XFF=1 when running behind a proxy that sets X-Forwarded-For.
# export KG_ADMIN_TOKEN="..."          # required in production
# export KG_TRUST_XFF=1                # only behind a trusted reverse proxy

if [ ! -x "KG_backend/.venv/bin/python" ]; then
    echo "[X] Backend is not set up yet. Run ./check_prereqs.sh first."
    exit 1
fi
if [ ! -d "kg_frontend/node_modules" ]; then
    echo "[X] Frontend packages are not installed yet. Run ./check_prereqs.sh first."
    exit 1
fi

echo "Starting servers ..."

cleanup() { kill "$BACK_PID" "$FRONT_PID" 2>/dev/null; }
trap cleanup EXIT INT TERM

( cd KG_backend && .venv/bin/python manage.py runserver ) &
BACK_PID=$!

( cd kg_frontend && npm run dev ) &
FRONT_PID=$!

echo "Waiting for the frontend to be ready..."
until (exec 3<>/dev/tcp/localhost/3000) 2>/dev/null; do
    sleep 1
done
exec 3>&- 2>/dev/null || true

echo "Frontend is up. Opening browser..."
if command -v open >/dev/null 2>&1; then
    open http://localhost:3000           # macOS
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:3000       # Linux
fi

echo
echo "Both servers are running. Press Ctrl+C here to stop them."
wait
