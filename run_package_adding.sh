#!/usr/bin/env bash
# ============================================================
#  Double-click (or run ./run.sh) to open the parser GUI.
#  First run sets things up automatically (takes a minute).
#  Every run after that is instant. Nothing to type.
#
#  macOS / Linux. Make it runnable once:  chmod +x run.sh
# ============================================================
set -e
cd "$(dirname "$0")"

# --- find Python 3
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "Python 3 is not installed. Install it first:"
    echo "  macOS:   brew install python-tk"
    echo "  Ubuntu:  sudo apt install python3 python3-venv python3-tk"
    exit 1
fi

# --- create a private environment once
if [ ! -x ".venv/bin/python" ]; then
    echo "Setting up for the first time, please wait..."
    "$PY" -m venv .venv
    ".venv/bin/python" -m pip install --quiet --upgrade pip
    ".venv/bin/python" -m pip install --quiet beautifulsoup4 html5lib
fi

# --- launch the GUI
".venv/bin/python" parser_gui.py
