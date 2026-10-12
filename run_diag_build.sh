#!/usr/bin/env bash
# ============================================================
#  Build the per-car DIAGNOSTIC sidecars (the DTC / symptom
#  "rule engine" layer) for the smart assistant. Runs fully
#  OFFLINE and NEVER writes to the original car databases
#  (read-only + checksum-verified). Output lives under
#  KG_backend/Database_warehouse/_rag/diag/ and can be deleted
#  to revert (the assistant then falls back to general search).
#
#  Run this AFTER ./run_rag_build.sh (it reuses the same bge-m3
#  embeddings and the unified index's labor/cross-vehicle links).
#
#  Usage:
#     ./run_diag_build.sh                 # all cars (rebuild)
#     ./run_diag_build.sh --car "bZ4X XLE, FWD"   # one car
#
#  Fast: ~30s per small car, ~2 min per large car.
#  When it prints "Diagnostic build complete", send me the log.
# ============================================================
cd "$(dirname "$0")"

BACKEND="KG_backend"
PY="$BACKEND/.venv/bin/python"
DIAG_DIR="$BACKEND/Database_warehouse/_rag/diag"

if [ ! -x "$PY" ]; then
    echo "[X] Backend is not set up yet (no $PY). Run ./check_prereqs.sh first."
    exit 1
fi

# Same offline + stable embedding settings as the RAG build. The diag layer MUST
# use the SAME embedding model as the unified index (a guard refuses a mismatch).
# Local offline build -> run in DEBUG mode so settings.py uses the dev secret
# key (production refuses to boot without DJANGO_SECRET_KEY). Matches run_server.sh.
export DJANGO_DEBUG="${DJANGO_DEBUG:-true}"
export RAG_EMBED_MODEL="${RAG_EMBED_MODEL:-bge-m3}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1

mkdir -p "$DIAG_DIR"
LOG="$DIAG_DIR/diag_build_$(date +%Y%m%d_%H%M%S).log"

# Default to a full rebuild of all cars; pass-through any args (e.g. --car "X").
ARGS="$*"
if [ -z "$ARGS" ]; then
    ARGS="--rebuild"
fi

{
    echo "==========================================================="
    echo " Diagnostic (DTC/symptom) build | model=$RAG_EMBED_MODEL"
    echo " args: $ARGS | offline=yes | started: $(date)"
    echo " log: $LOG"
    echo "==========================================================="
} | tee "$LOG"

"$PY" "$BACKEND/manage.py" build_diag $ARGS 2>&1 | grep -v "Loading weights" | tee -a "$LOG"
STATUS=${PIPESTATUS[0]}

{
    echo "==========================================================="
    if [ "$STATUS" = "0" ]; then
        echo " ✅ DONE. finished: $(date)"
        echo "     log: $LOG"
    else
        echo " ⚠️  stopped (exit $STATUS). See log: $LOG"
    fi
    echo "==========================================================="
} | tee -a "$LOG"
