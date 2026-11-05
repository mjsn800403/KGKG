#!/usr/bin/env bash
# Rebuild the deterministic companion layers on top of an existing graphify-out/graph.json.
# No LLM, no network. Safe to run repeatedly. Never modifies graph.json.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# Use the interpreter graphify itself runs on: it is guaranteed to have tree-sitter (a graphify dependency),
# whether installed via uv tool, pipx, pip or conda.
GB=$(command -v graphify) || { echo "graphify not on PATH" >&2; exit 1; }
SHEBANG=$(head -1 "$GB" | sed -n 's/^#!//p')
set -- $SHEBANG                                  # "#!/path/python" or "#!/usr/bin/env python3"
case "$(basename "${1:-x}")" in env) INTERP=$(command -v "${2:-python3}") ;; *) INTERP=${1:-} ;; esac
PY=${PYTHON:-${INTERP:-python3}}
$PY -c "import tree_sitter_javascript" 2>/dev/null || { echo "interpreter $PY lacks tree_sitter_javascript (reinstall graphifyy)" >&2; exit 1; }
$PY -I tools/graphify_xlayer/xlayer.py build >/dev/null
$PY -I tools/graphify_xlayer/docs_index.py >/dev/null
$PY -I tools/graphify_xlayer/viewer.py >/dev/null
graphify merge-graphs graphify-out/graph.json graphify-out/xlayer.json graphify-out/docsindex.json \
  --out graphify-out/merged-graph.json >/dev/null
echo "layers OK: graphify-out/{xlayer,docsindex,merged-graph}.json, architecture.html"
