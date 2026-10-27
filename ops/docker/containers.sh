# KGKG container helpers, sourced by ops/deploy/deploy.sh (usable by hand).
# shellcheck shell=bash
#
# Both containers use the host network (nginx proxies to 127.0.0.1:8000/:3000,
# the TIS crawler panel talks to Chrome on 127.0.0.1:9222) and bind loopback
# only. Data stays on the host disk and is bind-mounted; the backend has no
# host access beyond its mounts, and host-side jobs go through the
# kgkg-hostjobs spool (ops/hostjobs).

KG_BE_DIR=${KG_BE_DIR:-/opt/KGKG/KG_backend}
KG_FE_ENV=${KG_FE_ENV:-/opt/KGKG/kg_frontend/.env.production}
KG_SPOOL=${KG_SPOOL:-/run/kgkg-hostjobs}

# docker args shared by the backend server and one-off backend commands.
#   <db-dir> holds db.sqlite3 (+ -wal/-shm; SQLite needs the whole directory).
be_args() {  # <db-dir> <log-dir>
  mkdir -p "$2" "$KG_SPOOL/req" "$KG_SPOOL/resp" /root/partsouq_crawl
  BE_ARGS=(--network host --env-file "$KG_BE_DIR/.env.prod"
    -e KG_DB_PATH=/data/db/db.sqlite3 -e KG_LOG_DIR=/var/log/kgkg
    -e KG_HOSTJOBS_DIR=/run/kgkg-hostjobs -e RAG_EMBED_MODEL=bge-m3
    -v "$1":/data/db
    -v "$KG_BE_DIR/Database_warehouse":"$KG_BE_DIR/Database_warehouse"
    -v "$KG_BE_DIR/static_warehouse":"$KG_BE_DIR/static_warehouse"
    -v "$KG_BE_DIR/.env.prod":"$KG_BE_DIR/.env.prod":ro
    -v /root/.cache/huggingface:/root/.cache/huggingface:ro
    -v "$2":/var/log/kgkg
    -v "$KG_SPOOL":/run/kgkg-hostjobs
    -v /root/downloads:/root/downloads:ro
    -v /root/Desktop/tis_crawler:/root/Desktop/tis_crawler:ro
    -v /root/partsouq_crawl:/root/partsouq_crawl:ro)
}

# run_backend <name> <image> <port> <db-dir> <log-dir> [extra docker args...]
run_backend() {
  local name=$1 image=$2 port=$3; be_args "$4" "$5"; shift 5
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" --restart unless-stopped --stop-timeout 40 \
    --label kgkg.role=backend "${BE_ARGS[@]}" \
    -e KG_PORT="$port" -e KG_HEALTH_PORT="$(free_port)" -e KG_WARMUP="${KG_WARMUP:-1}" \
    "$@" "$image" >/dev/null
}

# A loopback port in 18100-18199 nothing listens on, for one container's health check.
free_port() {
  local p
  for ((p = 18100; p < 18200; p++)); do
    ss -ltn "sport = :$p" | grep -q LISTEN || { echo $p; return 0; }
  done
  return 1
}

# be_run <image> <db-dir> <log-dir> [docker args...] -- <cmd...>   one-off, e.g. migrate
be_run() {
  local image=$1 extra=(); be_args "$2" "$3"; shift 3
  while [[ $# -gt 0 && $1 != -- ]]; do extra+=("$1"); shift; done
  [[ ${1:-} == -- ]] && shift
  docker run --rm "${BE_ARGS[@]}" -e KG_WARMUP=0 "${extra[@]}" "$image" "$@"
}

# run_frontend <name> <image> <port> <backend-url> [extra docker args...]
run_frontend() {
  local name=$1 image=$2 port=$3 be=$4; shift 4
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" --restart unless-stopped --network host \
    --label kgkg.role=frontend --stop-timeout 20 \
    --env-file "$KG_FE_ENV" \
    -e PORT="$port" -e BACKEND_URL="$be" -e API_BASE_INTERNAL="$be" \
    -v "$KG_BE_DIR/static_warehouse":"$KG_BE_DIR/static_warehouse":ro \
    -v "$KG_BE_DIR/Database_warehouse/_rag":"$KG_BE_DIR/Database_warehouse/_rag":ro \
    "$@" "$image" >/dev/null
}

# wait_healthy <name> <seconds>   (the image's HEALTHCHECK)
wait_healthy() {
  local i s
  for ((i = 0; i < $2; i++)); do
    s=$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null || echo gone)
    [[ $s == healthy ]] && return 0
    [[ $s == gone || $(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null) != true ]] && return 1
    sleep 1
  done
  return 1
}

# prod_containers <role>   ids of the live production containers of a role
prod_containers() {
  docker ps -aq --filter label=kgkg.env=prod --filter "label=kgkg.role=$1"
}
