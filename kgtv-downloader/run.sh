#!/usr/bin/env bash
# One-command launcher for the KGTV source downloader.
# Creates a local virtualenv (.venv), installs deps into it, then runs the
# downloader. Works on a fresh Debian/Ubuntu server (no system pip pollution)
# and on macOS. The script asks for the link if you don't pass one.
set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "[run] creating virtualenv..."
  python3 -m venv "$VENV"
fi

PY="$VENV/bin/python"
"$PY" -m pip install -q --upgrade pip >/dev/null 2>&1 || true
"$PY" -m pip install -q requests beautifulsoup4 >/dev/null 2>&1 \
  || "$PY" -m pip install -q --break-system-packages requests beautifulsoup4 >/dev/null 2>&1 \
  || true

exec "$PY" downloader.py "$@"
