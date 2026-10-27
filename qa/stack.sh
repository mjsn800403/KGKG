#!/usr/bin/env bash
# Isolated QA stack for the E2E, load and DAST suites (qa/README.md).
#
#   qa/stack.sh up [git-ref]   build images if needed, start the stack
#   qa/stack.sh down           remove the stack's containers
#   qa/stack.sh reseed         re-issue the test accounts' sessions (before each suite run)
#   qa/stack.sh status
#
# What makes it safe to point a browser, a load generator or a scanner at:
#   * its own containers (label kgkg.env=qa), ports :8120 backend / :3117
#     frontend / :8130 single-origin proxy (qa/nginx-qa.conf) on loopback; production (:8000/:3000) and staging (:8110/:3107)
#     are never touched
#   * a fresh copy of the production database taken with SQLite's online
#     backup API and run through ops/deploy/sanitize_staging_db.py, so no real
#     account can log in and no real phone/e-mail is present
#   * SMS, Sentry, Turnstile, Metis (LLM) and host jobs disabled; the RAG
#     feedback store redirected into the copy (RAG_FEEDBACK_DB), so queries
#     and ratings never reach production's ranking signals
#   * CPU and memory caps, so a stress test cannot starve production
#   * test accounts from `manage.py seed_qa_fixtures` with a password minted
#     per run into $QA/qa.env (mode 600, never committed)
set -Eeuo pipefail

REPO=${KG_QA_REPO:-/opt/KGKG_work}
QA=${KG_QA_DIR:-/opt/KGKG_qa/stack}
BE_PORT=${KG_QA_BE_PORT:-8120}
FE_PORT=${KG_QA_FE_PORT:-3117}
BE_CPUS=${KG_QA_BE_CPUS:-6}
FE_CPUS=${KG_QA_FE_CPUS:-2}
PROD_DB=${KG_QA_SOURCE_DB:-/opt/KGKG/KG_backend/db.sqlite3}
PX_PORT=${KG_QA_PROXY_PORT:-8130}
BE=kgkg-qa-backend FE=kgkg-qa-frontend PX=kgkg-qa-proxy

say() { printf '[qa %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { say "ERROR: $*"; exit 1; }

down() { docker rm -f "$BE" "$FE" "$PX" >/dev/null 2>&1 || true; say "stack removed"; }

status() {
  docker ps -a --filter label=kgkg.env=qa --format '{{.Names}}  {{.Image}}  {{.Status}}'
  [[ -f $QA/stack.env ]] && cat "$QA/stack.env"
}

up() {
  local ref=${1:-HEAD} sha short w
  sha=$(git -C "$REPO" rev-parse --verify "$ref^{commit}") || die "unknown ref $ref"
  short=${sha:0:9}
  # shellcheck source=../ops/docker/containers.sh
  . "$REPO/ops/docker/containers.sh"

  if ! docker image inspect "kgkg-backend:$short" "kgkg-frontend:$short" >/dev/null 2>&1; then
    say "building images for $short"
    w=$(dirname "$QA")/build-$short
    git -C "$REPO" worktree remove --force "$w" 2>/dev/null || rm -rf "$w"
    git -C "$REPO" worktree add -q --detach "$w" "$sha"
    local fe_public
    fe_public=$(grep -E '^NEXT_PUBLIC_API_BASE=' "$KG_FE_ENV" | cut -d= -f2- || true)
    ( cd "$w" &&
      nice -n 10 docker build -q -f ops/docker/backend.Dockerfile -t "kgkg-backend:$short" --build-arg KG_RELEASE="$short" . &&
      nice -n 10 docker build -q -f ops/docker/frontend.Dockerfile -t "kgkg-frontend:$short" --build-arg KG_RELEASE="$short" \
        ${fe_public:+--build-arg NEXT_PUBLIC_API_BASE="$fe_public"} . ) >"$QA.build-$short.log" 2>&1 \
      || { tail -30 "$QA.build-$short.log"; die "image build failed"; }
    git -C "$REPO" worktree remove --force "$w"
  fi

  down >/dev/null
  mkdir -p "$QA/db" "$QA/logs" "$QA/cfg"
  rm -f "$QA"/db/*
  say "copying + sanitizing the production database"
  python3 - "$PROD_DB" "$QA/db/db.sqlite3" <<'PY'
import sqlite3, sys
s = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True, timeout=60)
d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
PY
  python3 -I "$REPO/ops/deploy/sanitize_staging_db.py" "$QA/db/db.sqlite3" --quiet \
    || die "sanitizer failed; refusing to serve the copy"
  : > "$QA/db/.qa-stack"
  # The backend resolves the warehouses next to its database (/data/db): give
  # the copy the same view production has. Staging relies on a hand-made
  # symlink for this; here it is part of the script.
  ln -sfn "$KG_BE_DIR/Database_warehouse" "$QA/db/Database_warehouse"
  ln -sfn "$KG_BE_DIR/static_warehouse" "$QA/db/static_warehouse"
  cat > "$QA/cfg/qa_settings.py" <<'PY'
# QA stack backend (qa/stack.sh): production settings on a sanitized COPY.
from KG_backend.settings import *  # noqa
ALLOWED_HOSTS = ["*"]
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
PY

  local pw
  pw=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
  umask 077
  printf 'KG_QA_USER=qa_e2e_manager\nKG_QA_PASSWORD=%s\n' "$pw" > "$QA/qa.env"
  umask 022

  export KG_SPOOL=/run/kgkg-hostjobs-qa   # nothing serves it: no host jobs from QA
  local nosec=(-e SENTRY_DSN= -e SMS_API_KEY= -e SMS_USERNAME= -e SMS_FROM= -e TURNSTILE_SECRET=
    -e KG_ALERT_PHONES= -e RAG_FEEDBACK_DB=/data/db/feedback.db
    -e DJANGO_SETTINGS_MODULE=qa_settings -e PYTHONPATH=/qacfg -v "$QA/cfg":/qacfg:ro
    --label kgkg.env=qa)
  say "migrating the copy"
  be_run "kgkg-backend:$short" "$QA/db" "$QA/logs" "${nosec[@]}" -- python manage.py migrate --noinput \
    > "$QA/logs/migrate.log" 2>&1 || die "migrate failed ($QA/logs/migrate.log)"
  say "seeding test accounts"
  be_run "kgkg-backend:$short" "$QA/db" "$QA/logs" "${nosec[@]}" -e KG_QA_STACK=1 -e KG_QA_PASSWORD="$pw" \
    -- python manage.py seed_qa_fixtures | tail -1 > "$QA/fixtures.json" || die "seeding failed"
  chmod 600 "$QA/fixtures.json"

  say "starting backend :$BE_PORT (cpus=$BE_CPUS) and frontend :$FE_PORT (cpus=$FE_CPUS)"
  KG_WARMUP=1 run_backend "$BE" "kgkg-backend:$short" "$BE_PORT" "$QA/db" "$QA/logs" \
    "${nosec[@]}" --cpus "$BE_CPUS" --memory 10g --restart no
  run_frontend "$FE" "kgkg-frontend:$short" "$FE_PORT" "http://127.0.0.1:$BE_PORT" \
    -e METIS_API_KEY= -e SENTRY_DSN= --label kgkg.env=qa --cpus "$FE_CPUS" --memory 3g --restart no
  wait_healthy "$BE" 300 || { docker logs --tail 40 "$BE"; die "backend not healthy"; }
  wait_healthy "$FE" 120 || { docker logs --tail 40 "$FE"; die "frontend not healthy"; }
  sed -e "s/__PROXY_PORT__/$PX_PORT/" -e "s/__BE_PORT__/$BE_PORT/g" -e "s/__FE_PORT__/$FE_PORT/g" \
    "$(dirname "$0")/nginx-qa.conf" > "$QA/cfg/nginx-qa.conf"
  docker run -d --name "$PX" --network host --label kgkg.env=qa --cpus 1 \
    -v "$QA/cfg/nginx-qa.conf":/etc/nginx/conf.d/default.conf:ro -v "$QA/logs":/var/log/nginx \
    -v "$KG_BE_DIR/static_warehouse":/static_warehouse:ro \
    nginx:1.27-alpine >/dev/null
  for _ in $(seq 30); do curl -fs -o /dev/null "http://127.0.0.1:$PX_PORT/kg-api/api/health/" && break; sleep 1; done
  curl -fsS -o /dev/null "http://127.0.0.1:$PX_PORT/kg-api/api/health/" || die "proxy not answering"
  cat > "$QA/stack.env" <<EOF
QA_SHA=$sha
QA_STARTED=$(date -u +%FT%TZ)
QA_BACKEND=http://127.0.0.1:$BE_PORT
QA_FRONTEND=http://127.0.0.1:$FE_PORT
QA_ORIGIN=http://127.0.0.1:$PX_PORT
EOF
  say "QA stack up for $short"; cat "$QA/stack.env"
}

reseed() {
  # shellcheck disable=SC1091
  . "$QA/qa.env"
  docker exec -e KG_QA_STACK=1 -e KG_QA_PASSWORD="$KG_QA_PASSWORD" "$BE" \
    python manage.py seed_qa_fixtures | tail -1 > "$QA/fixtures.json.new" || die "reseed failed"
  chmod 600 "$QA/fixtures.json.new" && mv "$QA/fixtures.json.new" "$QA/fixtures.json"
  say "sessions re-issued"
}

case ${1:-} in
  up) up "${2:-HEAD}" ;;
  down) down ;;
  reseed) reseed ;;
  status) status ;;
  *) echo "usage: qa/stack.sh up [git-ref] | down | reseed | status" >&2; exit 2 ;;
esac
