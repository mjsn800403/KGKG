#!/usr/bin/env bash
# ============================================================
#  KGtechvault — check & install prerequisites only.
#  Run this once (or whenever you add a new dependency).
#  Safe to re-run: every package is checked first and only
#  installed if it's actually missing.
#
#  chmod +x check_prereqs.sh && ./check_prereqs.sh
# ============================================================
set -e
cd "$(dirname "$0")"

echo
echo "===== Checking system tools ====="

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "[X] Python 3 is not installed."
    echo "    macOS:   brew install python"
    echo "    Ubuntu:  sudo apt install python3 python3-venv"
    exit 1
fi
echo "[OK] Python found."

if ! command -v npm >/dev/null 2>&1; then
    echo "[X] Node.js / npm is not installed."
    echo "    macOS:   brew install node"
    echo "    Ubuntu:  sudo apt install nodejs npm"
    exit 1
fi
echo "[OK] Node.js found."

# ===== Backend virtual environment =====
# Recreate if it's missing, OR if it exists but was made WITHOUT
# --system-site-packages (so it can't see your already-installed packages).
NEED_NEW_VENV=0
if [ ! -x "KG_backend/.venv/bin/python" ]; then
    NEED_NEW_VENV=1
elif [ -f "KG_backend/.venv/pyvenv.cfg" ] && ! grep -qi "include-system-site-packages = true" "KG_backend/.venv/pyvenv.cfg"; then
    NEED_NEW_VENV=1
fi

if [ "$NEED_NEW_VENV" = "1" ]; then
    echo
    echo "===== Creating backend virtual environment ====="
    rm -rf KG_backend/.venv
    "$PY" -m venv --system-site-packages KG_backend/.venv
else
    echo "[OK] Backend virtual environment already exists."
fi
VENV_PY=KG_backend/.venv/bin/python

# ===== Backend Python packages (checked one by one) =====
echo
echo "===== Checking backend Python packages ====="
while IFS= read -r line; do
    # strip comments/blank lines, then the package name before any version spec
    pkg="${line%%#*}"
    pkg="$(echo "$pkg" | sed -E 's/[<>=,;].*$//' | xargs)"
    [ -z "$pkg" ] && continue
    if "$VENV_PY" -m pip show "$pkg" >/dev/null 2>&1; then
        echo "  [OK] $pkg already installed"
    else
        echo "  installing $pkg ..."
        "$VENV_PY" -m pip install "$pkg"
    fi
done < KG_backend/requirements.txt

# ===== Backend database migrations =====
echo
echo "===== Applying backend migrations ====="
( cd KG_backend && .venv/bin/python manage.py migrate )

# ===== Frontend packages =====
echo
echo "===== Checking frontend packages ====="
if [ ! -d "kg_frontend/node_modules" ]; then
    echo "  installing frontend packages, this may take a few minutes ..."
    ( cd kg_frontend && npm install )
else
    echo "[OK] Frontend packages already installed."
    echo "     (run 'npm install' inside kg_frontend manually if you changed package.json)"
fi

echo
echo "===== All prerequisites are ready. ====="
echo "You can now run ./run_all.sh"
