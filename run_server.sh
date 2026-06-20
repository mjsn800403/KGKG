#!/usr/bin/env bash
# ============================================================
#  KGtechvault — start backend + frontend.
#  Assumes check_prereqs.sh has already been run once.
#  Opens your browser to localhost:3000 once the site is ready.
#
#  chmod +x run_all.sh && ./run_all.sh
# ============================================================
cd "$(dirname "$0")"

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
