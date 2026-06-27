#!/usr/bin/env bash
# ============================================================
#  Build (or RESUME) the local RAG index + relationship graph for the
#  car-service assistant. Runs fully OFFLINE on this Mac and never writes to the
#  original car databases (read-only + checksum-verified). Output lives under
#  KG_backend/Database_warehouse/_rag/ and can be deleted to revert.
#
#  Usage:
#     ./run_rag_build.sh               # build, or RESUME if it was interrupted
#     RAG_REBUILD=1 ./run_rag_build.sh  # WIPE progress and start fresh (rare)
#
#  RESUME is automatic and safe: if the build stops, your Mac sleeps, or you
#  close the terminal, just run ./run_rag_build.sh again — it CONTINUES from
#  where it left off and never re-embeds pages it already did. The index file is
#  only ever wiped when you explicitly pass RAG_REBUILD=1.
#
#  Takes ~1.5–2.5h for all 9 cars the first time; a resume only does what's left.
#
#  HOW TO TELL IT'S WORKING (not hung):
#    * the build prints "embedded X/Y (rate, ETA)" lines as it goes, AND
#    * every 60s a "[HH:MM:SS] heartbeat — embedded N/M (+k since last)" line
#      prints even during the silent ~30s model load. If the +k stays 0 for
#      several minutes WHILE embedding, it may be stuck — stop (Ctrl-C) and
#      re-run; it resumes.
#  When it prints "RAG build complete", send me the log file shown at the end.
# ============================================================
cd "$(dirname "$0")"

BACKEND="KG_backend"
PY="$BACKEND/.venv/bin/python"
RAG_DIR="$BACKEND/Database_warehouse/_rag"
IDX="$RAG_DIR/index.rag.db"

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

# --- decide fresh vs resume (bash 3.2-safe: a plain string, no arrays) -----
# IMPORTANT: an existing index is RESUMED, never wiped, unless RAG_REBUILD=1.
REBUILD=""
if [ "${RAG_REBUILD:-0}" = "1" ]; then
    REBUILD="--rebuild"
    MODE="FRESH BUILD (RAG_REBUILD=1 -> wiping previous progress)"
elif [ ! -f "$IDX" ]; then
    MODE="FIRST BUILD (no index yet — all 9 cars)"
else
    MODE="RESUME / CONTINUE (keeping existing progress; never starts over)"
fi

# How far a previous run got. vec_blobs_rowids / blobs are PLAIN tables, so a
# stock sqlite3 can read them without the vec0 extension.
count_db() { sqlite3 "$IDX" "SELECT count(*) FROM $1" 2>/dev/null || echo "?"; }
emb0="0"; tot0="0"
if [ -f "$IDX" ]; then emb0=$(count_db vec_blobs_rowids); tot0=$(count_db blobs); fi

{
    echo "==========================================================="
    echo " RAG build | model=$RAG_EMBED_MODEL"
    echo " mode: $MODE"
    echo " progress so far: ${emb0}/${tot0} pages embedded"
    echo " offline=yes  started: $(date)"
    echo " log: $LOG"
    echo "==========================================================="
} | tee "$LOG"

# --- heartbeat: prove it's alive + show progress every 60s -----------------
heartbeat() {
    prev=$(count_db vec_blobs_rowids); case "$prev" in ''|*[!0-9]*) prev=0;; esac
    while true; do
        sleep 60
        emb=$(count_db vec_blobs_rowids); tot=$(count_db blobs)
        delta="?"
        case "$emb" in ''|*[!0-9]*) :;; *) delta=$((emb - prev)); prev=$emb;; esac
        echo "[$(date +%H:%M:%S)] heartbeat — embedded ${emb}/${tot}  (+${delta} in last 60s)" | tee -a "$LOG"
    done
}
heartbeat &
HB_PID=$!
# kill the heartbeat whenever this script exits (normal, error, or Ctrl-C)
trap 'kill "$HB_PID" 2>/dev/null' EXIT INT TERM

# --- run the build, streaming to screen AND log ----------------------------
# $REBUILD is intentionally unquoted: empty => no extra arg; "--rebuild" => one.
"$PY" "$BACKEND/manage.py" build_rag $REBUILD 2>&1 | tee -a "$LOG"
STATUS=${PIPESTATUS[0]}

kill "$HB_PID" 2>/dev/null

{
    echo "==========================================================="
    if [ "$STATUS" = "0" ]; then
        echo " ✅ DONE. finished: $(date)"
        echo " >>> send me this log file:"
        echo "     $LOG"
    else
        echo " ⚠️  stopped (exit $STATUS). Just run ./run_rag_build.sh again to CONTINUE"
        echo "     from here — do NOT set RAG_REBUILD unless you want to start over."
        echo "     log: $LOG"
    fi
    echo "==========================================================="
} | tee -a "$LOG"
