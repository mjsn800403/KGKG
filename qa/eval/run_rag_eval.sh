#!/usr/bin/env bash
# Offline retrieval evaluation of a release image against the production
# index, with zero LLM calls (KG_backend/api/management/commands/run_evalsuite.py).
#   qa/eval/run_rag_eval.sh <git-ref> [--sets a,b] [--systems hybrid]
# Gold sets are the versioned files in KG_backend/Database_warehouse/_rag/eval/gold/.
# Results: qa/eval/results/<ref>/results.json and a text summary.
# Query logging is off and the feedback store is redirected, so the run leaves
# no trace in production data; CPU is capped so production keeps serving.
set -Eeuo pipefail
REPO=${KG_QA_REPO:-/opt/KGKG_work}
REF=${1:?git ref}; shift
SHA=$(git -C "$REPO" rev-parse --verify "$REF^{commit}"); SHORT=${SHA:0:9}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/results/$SHORT; mkdir -p "$OUT"
docker image inspect "kgkg-backend:$SHORT" >/dev/null || { echo "build the image first (qa/stack.sh up $REF)" >&2; exit 2; }
WH=/opt/KGKG/KG_backend/Database_warehouse
# The backend finds the warehouse next to its database, so the run gets its own
# copy of the (sanitized) QA database with the warehouse mounted beside it.
DBDIR=$(mktemp -d)
cp /opt/KGKG_qa/stack/db/db.sqlite3 "$DBDIR/"
# Record exactly which gold files were used (they live in the warehouse and
# are versioned in git under the same path).
( cd "$WH/_rag/eval/gold" && sha256sum ./*.jsonl ) > "$OUT/gold-sha256.txt"
{ echo "ref=$REF sha=$SHA"; echo "started=$(date -u +%FT%TZ)"; echo "args=$*"; } > "$OUT/env.txt"
docker run --rm --cpus "${KG_QA_EVAL_CPUS:-4}" --network none \
  -e DJANGO_DEBUG=true -e KG_ADMIN_TOKEN=x -e KG_ENV_FILE=/tmp/x.env -e KG_WARMUP=0 \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e RAG_EMBED_MODEL=bge-m3 \
  -e RAG_LOG_QUERIES=0 -e RAG_FEEDBACK_DB=/tmp/feedback.db -e KG_DB_PATH=/evaldb/db.sqlite3 \
  -v /root/.cache/huggingface:/root/.cache/huggingface:ro \
  -v "$DBDIR":/evaldb -v "$WH":/evaldb/Database_warehouse \
  -v "$OUT":/out \
  "kgkg-backend:$SHORT" python manage.py run_evalsuite --out /out "$@" 2>&1 | tee "$OUT/run.log"
rc=${PIPESTATUS[0]}
rm -rf "$DBDIR"
echo "finished=$(date -u +%FT%TZ) exit=$rc" >> "$OUT/env.txt"
exit $rc
