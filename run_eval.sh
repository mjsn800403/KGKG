#!/usr/bin/env bash
# ============================================================
#  OFFLINE evaluation of the RAG retrieval quality. Makes ZERO
#  LLM calls and does NOT touch the live site. Reads the gold
#  set at KG_backend/Database_warehouse/_rag/eval/goldset.jsonl
#  and writes a run report under .../_rag/eval/runs/.
#
#  Usage:
#     ./run_eval.sh --bootstrap     # seed a goldset from click logs
#     ./run_eval.sh                 # score against the goldset
#     ./run_eval.sh --k 8 --limit 200
#
#  Reuses the same bge-m3 embeddings as the index (offline).
# ============================================================
cd "$(dirname "$0")"

BACKEND="KG_backend"
PY="$BACKEND/.venv/bin/python"
EVAL_DIR="$BACKEND/Database_warehouse/_rag/eval"

if [ ! -x "$PY" ]; then
    echo "[X] Backend is not set up yet (no $PY). Run ./check_prereqs.sh first."
    exit 1
fi

# Same offline + stable embedding settings as the build/serve path.
export RAG_EMBED_MODEL="${RAG_EMBED_MODEL:-bge-m3}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1

mkdir -p "$EVAL_DIR/runs"
LOG="$EVAL_DIR/eval_$(date +%Y%m%d_%H%M%S).log"

{
    echo "==========================================================="
    echo " RAG evaluation | model=$RAG_EMBED_MODEL | args: $* | $(date)"
    echo "==========================================================="
} | tee "$LOG"

"$PY" "$BACKEND/manage.py" eval_rag "$@" 2>&1 | grep -v "Loading weights" | tee -a "$LOG"
STATUS=${PIPESTATUS[0]}

{
    if [ "$STATUS" = "0" ]; then
        echo " ✅ DONE. $(date)  log: $LOG"
    else
        echo " ⚠️  stopped (exit $STATUS). See log: $LOG"
    fi
} | tee -a "$LOG"
