#!/usr/bin/env bash
# ============================================================
#  Build the local RAG index + relationship graph for the
#  car-service assistant. Runs fully OFFLINE on this Mac and
#  never writes to the original car databases (read-only +
#  checksum-verified). Everything it produces lives under
#  KG_backend/Database_warehouse/_rag/ and can be deleted to revert.
#
#  Usage:
#     ./run_rag_build.sh              # build, or resume if interrupted
#     RAG_REBUILD=1 ./run_rag_build.sh # wipe the index and start fresh
#
#  Takes ~1.5–2.5h for all 9 cars. Resumable: if it stops, just run it
#  again — the long embedding stage continues where it left off.
#  When it prints "RAG build complete", send me the log file shown at the end.
# ============================================================
cd "$(dirname "$0")"

BACKEND="KG_backend"
PY="$BACKEND/.venv/bin/python"
RAG_DIR="$BACKEND/Database_warehouse/_rag"

if [ ! -x "$PY" ]; then
    echo "[X] Backend is not set up yet (no $PY). Run ./check_prereqs.sh first."
    exit 1
fi

# Fully offline + stable embedding settings (uses the model already cached on
# this Mac; no internet needed). bge-m3 is loaded in float16 with a bounded
# sequence length so Apple-Silicon GPU stays fast and never runs out of memory.
# Local offline build -> run in DEBUG mode so settings.py uses the dev secret
# key (production refuses to boot without DJANGO_SECRET_KEY). Matches run_server.sh.
export DJANGO_DEBUG="${DJANGO_DEBUG:-true}"
export RAG_EMBED_MODEL="${RAG_EMBED_MODEL:-bge-m3}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1

mkdir -p "$RAG_DIR"
LOG="$RAG_DIR/build_$(date +%Y%m%d_%H%M%S).log"

# Decide fresh vs resume (bash 3.2-safe: a plain string, no arrays).
REBUILD=""
MODE="RESUME / CONTINUE (re-run anytime; it picks up where it left off)"
if [ "${RAG_REBUILD:-0}" = "1" ] || [ ! -f "$RAG_DIR/index.rag.db" ]; then
    REBUILD="--rebuild"
    MODE="FRESH BUILD (all 9 cars)"
fi

{
    echo "==========================================================="
    echo " RAG build | model=$RAG_EMBED_MODEL | $MODE"
    echo " offline=yes  started: $(date)"
    echo " log: $LOG"
    echo "==========================================================="
} | tee "$LOG"

# Run the build, streaming to the screen AND the log file.
# $REBUILD is intentionally unquoted: empty => no extra arg; "--rebuild" => one arg.
"$PY" "$BACKEND/manage.py" build_rag $REBUILD 2>&1 | tee -a "$LOG"
STATUS=${PIPESTATUS[0]}

{
    echo "==========================================================="
    if [ "$STATUS" = "0" ]; then
        echo " ✅ DONE. finished: $(date)"
        echo " >>> send me this log file:"
        echo "     $LOG"
    else
        echo " ⚠️  stopped (exit $STATUS). Just run ./run_rag_build.sh again to continue."
        echo "     log: $LOG"
    fi
    echo "==========================================================="
} | tee -a "$LOG"
