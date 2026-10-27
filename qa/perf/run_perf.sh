#!/usr/bin/env bash
# Run one k6 profile against the QA stack and sample container resources.
#   qa/perf/run_perf.sh baseline|load|stress|soak [out-dir]
# Capacity profiles run with the application's own throttles off
# (KG_RL_DISABLE=1, content-guard ceilings raised): every virtual user comes
# from one IP and a handful of accounts, so with them on the test would only
# measure the limiter. Start the stack for this with:
#   KG_QA_BACKEND_ENV="KG_RL_DISABLE=1 KG_CG_PAGE_BLOCK=1000000 KG_CG_PAGE_WARN=1000000" qa/stack.sh up <ref>
set -Eeuo pipefail
PROFILE=${1:?profile}
OUT=${2:-$(cd "$(dirname "$0")" && pwd)/results}
QA=${KG_QA_DIR:-/opt/KGKG_qa/stack}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
chmod 777 "$OUT"   # k6 runs as an unprivileged user inside its container
ORIGIN=$(sed -n 's/^QA_ORIGIN=//p' "$QA/stack.env")
TOKEN=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tokens"]["manager"])' "$QA/fixtures.json")

# Resource sampler: every 2 s, the QA containers' CPU/memory and host load.
( while true; do
    ts=$(date -u +%FT%TZ)
    docker stats --no-stream --format "$ts,{{.Name}},{{.CPUPerc}},{{.MemUsage}}" \
      kgkg-qa-backend kgkg-qa-frontend kgkg-qa-proxy 2>/dev/null
    echo "$ts,host-loadavg,$(cut -d' ' -f1 /proc/loadavg),"
    # Production must not notice: its health endpoint's latency, read-only.
    echo "$ts,prod-health-ms,$(curl -s -o /dev/null -w '%{http_code}:%{time_total}' --max-time 5 \
      http://127.0.0.1:8000/api/health/ 2>/dev/null),"
    sleep 2
  done ) > "$OUT/resources-$PROFILE.csv" &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true' EXIT

{ echo "profile=$PROFILE"; echo "started=$(date -u +%FT%TZ)"; grep QA_SHA "$QA/stack.env"
  echo "host=$(nproc) vCPU, $(free -g | awk '/Mem:/{print $2}') GiB RAM"
  docker inspect -f '{{.Name}} cpus={{.HostConfig.NanoCpus}} mem={{.HostConfig.Memory}}' \
    kgkg-qa-backend kgkg-qa-frontend kgkg-qa-proxy; } > "$OUT/env-$PROFILE.txt"

set +e
docker run --rm --network host --cpus 2 -v "$HERE":/scripts:ro -v "$OUT":/out \
  -e QA_ORIGIN="$ORIGIN" -e QA_TOKEN="$TOKEN" -e PROFILE="$PROFILE" \
  grafana/k6:0.57.0 run --quiet /scripts/k6-kgkg.js 2>&1 | tee "$OUT/k6-$PROFILE.log"
rc=${PIPESTATUS[0]}
echo "finished=$(date -u +%FT%TZ) exit=$rc" >> "$OUT/env-$PROFILE.txt"
exit $rc
