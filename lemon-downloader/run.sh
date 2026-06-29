#!/usr/bin/env bash
# One-command launcher for the LEMON manuals downloader.
# Installs deps, then runs the script (which asks for the link if you don't pass one).
set -euo pipefail
cd "$(dirname "$0")"

python3 -m pip install -q --upgrade requests beautifulsoup4 >/dev/null 2>&1 || true

exec python3 downloader.py "$@"
