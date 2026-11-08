#!/usr/bin/env bash
# Accuracy tests for the cross-layer companion index (needs graphify-out/graph.json; run graphify update . first).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
GB=$(command -v graphify); PY=$(head -1 "$GB" | sed -n 's/^#!\(.*\)$/\1/p' | awk '{print $1}')
exec "${PY:-python3}" -I tools/graphify_xlayer/test_xlayer.py -v
