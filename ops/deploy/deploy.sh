#!/usr/bin/env bash
# KGKG gated deploy (Docker):  gate -> images -> staging -> promote -> verify (auto-rollback)
#
#   ops/deploy/deploy.sh <git-ref>            full pipeline to production
#   ops/deploy/deploy.sh --staging <git-ref>  gate + images + staging only (prod untouched)
#   ops/deploy/deploy.sh --rollback           back to the previously deployed release
#   ops/deploy/deploy.sh --status             what is live, and the previous release
#   ops/deploy/deploy.sh --reload             restart the live release (no gap) to pick
#                                             up .env.prod changes, e.g. after rotate_secrets
#
# Rules it enforces:
#   * Production (/opt/KGKG) is never edited by hand. Changes are committed
#     elsewhere (e.g. the /opt/KGKG_work worktree, branch `work`) and promoted
#     here. The deploy refuses a dirty live tree and only fast-forwards. The
#     live tree still matters: host timers and the pipeline/crawler jobs run
#     from it with the host venv.
#   * The ref is tested in a fresh worktree (gate.sh), then built into two
#     images, kgkg-backend:<sha> and kgkg-frontend:<sha> (ops/docker/).
#   * Staging = those images on 127.0.0.1:8110 / :3107 against a fresh COPY of
#     the prod database, migrated, SMS/Sentry/Metis/host jobs disabled;
#     smoke.sh runs signed-in checks with a QA token minted in the copy.
#   * Production: DB backup, fast-forward, migrate (in the new image), then the
#     new backend container starts NEXT TO the old one on :8000 (SO_REUSEPORT)
#     and the old one stops only once the new one is healthy: no gap. The
#     frontend is swapped stop/start (about a second). Smoke test; any failure
#     rolls back to the previous images. Migrations are NOT reversed (keep
#     them additive); the pre-deploy DB backup is kept.
set -Eeuo pipefail

PROD=/opt/KGKG
REL=/opt/KGKG_release
STG=/opt/KGKG_staging
VENV=$PROD/KG_backend/.venv/bin
STATE=$REL/state.env
STG_BE=8110
STG_FE=3107
QA_USER=${KG_STAGING_QA_USER:-qa_e_root}
KEEP_IMAGES=4
TS=$(date -u +%Y%m%d-%H%M%S)
mkdir -p "$REL/logs" "$REL/db-backups" "$STG/logs" "$STG/db" "$STG/stagecfg"
LOG=$REL/logs/deploy-$TS.log
exec > >(tee -a "$LOG") 2>&1

say()  { printf '\n[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die()  { say "DEPLOY ABORTED: $*"; exit 1; }
prod_clean() { [[ -z $(git -C "$PROD" status --porcelain --untracked-files=no) ]]; }
sqlite_copy() {  # src dst   (online backup API: consistent even while prod writes)
  python3 - "$1" "$2" <<'PY'
import sqlite3, sys, os
src, dst = sys.argv[1], sys.argv[2]
tmp = dst + '.tmp'
for f in (tmp, tmp + '-wal', tmp + '-shm', dst + '-wal', dst + '-shm'):
    if os.path.exists(f): os.remove(f)
s = sqlite3.connect(f'file:{src}?mode=ro', uri=True, timeout=60)
d = sqlite3.connect(tmp)
s.backup(d); d.close(); s.close()
os.replace(tmp, dst)
PY
}
# Portal DB engine, from the live .env.prod (KG_DB_ENGINE). PostgreSQL is
# reached from the host as the `root` role over the local socket (peer auth).
env_val() { sed -n "s/^$1=//p" "${KG_BE_DIR:-$PROD/KG_backend}/.env.prod" 2>/dev/null | tail -1 | tr -d "\"' "; }
DB_ENGINE=$(env_val KG_DB_ENGINE | tr '[:upper:]' '[:lower:]')
[[ $DB_ENGINE == postgresql ]] && DB_ENGINE=postgres
PG_NAME=$(env_val KG_PG_NAME); PG_NAME=${PG_NAME:-kgkg}
PG_USER=$(env_val KG_PG_USER); PG_USER=${PG_USER:-kgkg}
PG_STAGING=${PG_NAME}_staging
is_pg() { [[ $DB_ENGINE == postgres ]]; }
pg_backup() {  # dst   (pg_dump runs in one snapshot: consistent while prod writes)
  pg_dump -Fc -f "$1.tmp" "$PG_NAME" && mv "$1.tmp" "$1"
}
pg_clone_staging() {  # fresh copy of the prod DB as $PG_STAGING, owned by the app role
  dropdb --if-exists --force "$PG_STAGING"
  createdb -O "$PG_USER" "$PG_STAGING"
  pg_dump -Fc "$PG_NAME" | pg_restore --no-owner --role="$PG_USER" --exit-on-error -d "$PG_STAGING"
}
# Release state, written by save_state below.
# shellcheck source=/dev/null
load_state() { CURRENT=; PREVIOUS=; [[ -f $STATE ]] && . "$STATE"; return 0; }
save_state() { printf 'CURRENT=%s\nPREVIOUS=%s\nDEPLOYED_AT=%s\n' "$1" "$2" "$TS" > "$STATE"; }

# Staging provenance: what was last proven against a copy of production data.
# kgkg-promote refuses a release that has no passing record here, and the
# textfile metrics below put the stage-to-promote gap on a dashboard.
STAGING_STATE=$REL/staging.env
save_staging_state() {  # sha, smoke-result
  printf 'STAGED_SHA=%s\nSTAGED_AT=%s\nGATE=%s\nSMOKE=%s\n' \
    "$1" "$(date -u +%FT%TZ)" pass "$2" > "$STAGING_STATE"
}

# node-exporter textfile collector (ops/observability): release state as
# metrics, so "what is live" and "how long since it was staged" are answerable
# from Grafana rather than only over SSH.
TEXTFILE_DIR=${KG_TEXTFILE_DIR:-/var/lib/node-exporter-textfile}
write_release_metrics() {
  local f=$TEXTFILE_DIR/kgkg_release.prom t
  mkdir -p "$TEXTFILE_DIR" 2>/dev/null || return 0
  t=$(mktemp "$TEXTFILE_DIR/.kgkg_release.XXXXXX") || return 0
  local cur='' prev='' staged='' staged_at='' smoke=''
  [[ -f $STATE ]] && { cur=$(sed -n 's/^CURRENT=//p' "$STATE"); prev=$(sed -n 's/^PREVIOUS=//p' "$STATE"); }
  if [[ -f $STAGING_STATE ]]; then
    staged=$(sed -n 's/^STAGED_SHA=//p' "$STAGING_STATE")
    staged_at=$(sed -n 's/^STAGED_AT=//p' "$STAGING_STATE")
    smoke=$(sed -n 's/^SMOKE=//p' "$STAGING_STATE")
  fi
  local staged_epoch=0
  [[ -n $staged_at ]] && staged_epoch=$(date -u -d "$staged_at" +%s 2>/dev/null || echo 0)
  {
    echo '# HELP kgkg_release_info Release currently live on this host, as labels.'
    echo '# TYPE kgkg_release_info gauge'
    echo "kgkg_release_info{current=\"${cur:0:9}\",previous=\"${prev:0:9}\"} 1"
    echo '# HELP kgkg_staging_info Last release proven against a copy of production data.'
    echo '# TYPE kgkg_staging_info gauge'
    echo "kgkg_staging_info{staged=\"${staged:0:9}\",smoke=\"${smoke:-none}\"} 1"
    echo '# HELP kgkg_staging_last_pass_timestamp_seconds Unix time of the last passing staging run.'
    echo '# TYPE kgkg_staging_last_pass_timestamp_seconds gauge'
    echo "kgkg_staging_last_pass_timestamp_seconds $staged_epoch"
    echo '# HELP kgkg_release_staged_matches_live 1 when the live release is the one that was last staged.'
    echo '# TYPE kgkg_release_staged_matches_live gauge'
    if [[ -n $cur && "$cur" == "$staged" ]]; then echo 'kgkg_release_staged_matches_live 1'; else echo 'kgkg_release_staged_matches_live 0'; fi
  } > "$t" && chmod 644 "$t" && mv "$t" "$f"
}
img_be() { echo "kgkg-backend:${1:0:9}"; }
img_fe() { echo "kgkg-frontend:${1:0:9}"; }
have_images() { docker image inspect "$(img_be "$1")" "$(img_fe "$1")" >/dev/null 2>&1; }

trap 'say "DEPLOY FAILED at line $LINENO: $BASH_COMMAND"' ERR


# Container helpers: from the commit being deployed once it is checked out,
# until then from this script's own checkout.
SELF_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source_containers() { . "${1:-$SELF_ROOT}/ops/docker/containers.sh"; }
source_containers

PROD_LABELS=(--label kgkg.env=prod)
# Sets LOG_OPTS as an array; callers splice "${LOG_OPTS[@]}" rather than
# relying on word splitting of a command substitution.
LOG_OPTS=()
log_opts() { LOG_OPTS=(--log-driver=journald --log-opt "tag=$1"); }

# ---------------------------------------------------------------------------
# nginx config lives in ops/nginx/ and is part of the release: the media-gate
# fix needs the normalized cache key there as well as the normalized path check
# in api/mediaauth.py, and neither half closes the hole alone.
NGINX_SITE=${KG_NGINX_SITE:-/etc/nginx/sites-enabled/kgkg}
NGINX_CONFD=${KG_NGINX_CONFD:-/etc/nginx/conf.d}
NGINX_BACKUPS=${KG_NGINX_BACKUPS:-/etc/nginx/config-backups}

nginx_config_differs() {  # 0 when the release config is not what is installed
  local src=$PROD/ops/nginx
  [[ -d $src ]] || return 1
  ! cmp -s "$src/kgkg.conf" "$NGINX_SITE" && return 0
  local f
  for f in "$src"/kgkg-limits.conf "$src"/kgkg-mediaauth.conf; do
    [[ -f $f ]] || continue
    ! cmp -s "$f" "$NGINX_CONFD/$(basename "$f")" && return 0
  done
  return 1
}

# Validate the release config against the running nginx without installing it:
# a syntax error must stop the deploy while production is still untouched.
nginx_config_check() {
  local src=$PROD/ops/nginx t
  t=$(mktemp -d)
  mkdir -p "$t/conf.d" "$t/sites-enabled"
  cp "$src/kgkg.conf" "$t/sites-enabled/kgkg"
  local f
  for f in "$src"/kgkg-limits.conf "$src"/kgkg-mediaauth.conf; do
    [[ -f $f ]] && cp "$f" "$t/conf.d/"
  done
  # Reuse the real nginx.conf, pointing its includes at the candidate copies.
  sed -e "s#include /etc/nginx/conf.d/\*\.conf;#include $t/conf.d/*.conf;#" \
      -e "s#include /etc/nginx/sites-enabled/\*;#include $t/sites-enabled/*;#" \
      /etc/nginx/nginx.conf > "$t/nginx.conf"
  local out
  if out=$(nginx -t -c "$t/nginx.conf" 2>&1); then
    rm -rf "$t"; return 0
  fi
  say "candidate nginx config is invalid:"; echo "$out" | tail -5
  rm -rf "$t"; return 1
}

install_nginx_config() {
  local src=$PROD/ops/nginx f dest changed=0
  mkdir -p "$NGINX_BACKUPS"
  local stamp; stamp=$(date -u +%Y%m%d-%H%M%S)

  # Backups go outside sites-enabled and conf.d on purpose: nginx includes
  # everything in those directories, and a backup left there breaks reloads.
  if ! cmp -s "$src/kgkg.conf" "$NGINX_SITE"; then
    cp "$NGINX_SITE" "$NGINX_BACKUPS/kgkg.bak-deploy-$stamp"
    install -m 644 "$src/kgkg.conf" "$NGINX_SITE"; changed=1
    say "installed $NGINX_SITE from the release"
  fi
  for f in "$src"/kgkg-limits.conf "$src"/kgkg-mediaauth.conf; do
    [[ -f $f ]] || continue
    dest=$NGINX_CONFD/$(basename "$f")
    if ! cmp -s "$f" "$dest"; then
      [[ -f $dest ]] && cp "$dest" "$NGINX_BACKUPS/$(basename "$f").bak-deploy-$stamp"
      install -m 644 "$f" "$dest"; changed=1
      say "installed $dest from the release"
    fi
  done
  (( changed )) || return 0

  if ! nginx -t >/dev/null 2>&1; then
    say "nginx rejected the installed config; restoring the previous files"
    [[ -f $NGINX_BACKUPS/kgkg.bak-deploy-$stamp ]] && install -m 644 "$NGINX_BACKUPS/kgkg.bak-deploy-$stamp" "$NGINX_SITE"
    for f in "$src"/kgkg-limits.conf "$src"/kgkg-mediaauth.conf; do
      [[ -f $NGINX_BACKUPS/$(basename "$f").bak-deploy-$stamp ]] \
        && install -m 644 "$NGINX_BACKUPS/$(basename "$f").bak-deploy-$stamp" "$NGINX_CONFD/$(basename "$f")"
    done
    nginx -t >/dev/null 2>&1 && systemctl reload nginx
    return 1
  fi
  systemctl reload nginx && say "nginx reloaded with the release config"
}

# ---------------------------------------------------------------------------
# Host job bridge (ops/hostjobs) must run before a backend container needs it.
ensure_hostjobs() {
  local unit=/etc/systemd/system/kgkg-hostjobs.service src=$PROD/ops/hostjobs/kgkg-hostjobs.service
  [[ -f $src ]] || return 0
  if ! cmp -s "$src" "$unit"; then
    cp "$src" "$unit"; systemctl daemon-reload
  fi
  systemctl enable -q kgkg-hostjobs
  systemctl restart kgkg-hostjobs   # picks up daemon code from the new tree
  sleep 1; systemctl is-active -q kgkg-hostjobs || die "kgkg-hostjobs did not start (journalctl -u kgkg-hostjobs)"
}

# Start <sha>'s backend beside whatever serves :8000, then retire the old one.
swap_backend() {
  local sha=$1 name=kgkg-backend-$TS old
  old=$(prod_containers backend)
  if systemctl is-active -q kgkg-backend 2>/dev/null; then
    # One-time cutover from the systemd gunicorn (it does not use
    # SO_REUSEPORT, so the container cannot share the port with it).
    say "cutover: stopping the systemd kgkg-backend (one-time, short gap)"
    systemctl stop kgkg-backend; systemctl disable -q kgkg-backend
  fi
  log_opts kgkg-backend
  run_backend "$name" "$(img_be "$sha")" 8000 "$KG_BE_DIR" /var/log/kgkg \
    "${PROD_LABELS[@]}" "${LOG_OPTS[@]}" --label "kgkg.sha=$sha"
  if ! wait_healthy "$name" 300; then
    docker logs --tail 40 "$name" || true
    docker rm -f "$name" >/dev/null 2>&1 || true
    [[ -z $old ]] && ! systemctl is-active -q kgkg-backend && { systemctl enable -q kgkg-backend; systemctl start kgkg-backend; }
    return 1
  fi
  local o; for o in $old; do docker stop -t 40 "$o" >/dev/null; docker rm "$o" >/dev/null; done
  return 0
}

swap_frontend() {
  local sha=$1 name=kgkg-frontend-$TS old T0
  old=$(prod_containers frontend)
  T0=$(date +%s%N)
  if systemctl is-active -q kgkg-frontend 2>/dev/null; then
    systemctl stop kgkg-frontend; systemctl disable -q kgkg-frontend
  fi
  local o; for o in $old; do docker stop -t 20 "$o" >/dev/null; docker rm "$o" >/dev/null; done
  log_opts kgkg-frontend
  run_frontend "$name" "$(img_fe "$sha")" 3000 http://127.0.0.1:8000 \
    "${PROD_LABELS[@]}" "${LOG_OPTS[@]}" --label "kgkg.sha=$sha"
  wait_healthy "$name" 120 || { docker logs --tail 40 "$name" || true; return 1; }
  say "frontend back after $(( ($(date +%s%N) - T0) / 1000000 )) ms"
}

rollback_to() {  # sha
  local sha=$1
  say "ROLLBACK to ${sha:0:9}"
  have_images "$sha" || die "images for ${sha:0:9} are gone; cannot roll back automatically"
  prod_clean || die "live tree has uncommitted edits; refusing to reset it. Inspect: git -C $PROD status"
  git -C "$PROD" reset -q --hard "$sha"
  swap_backend "$sha" || say "WARNING: backend rollback container did not become healthy"
  swap_frontend "$sha" || say "WARNING: frontend rollback container did not become healthy"
  say "Rolled back. Database migrations are not reversed; DB backups: $REL/db-backups/"
}

status() {
  load_state
  echo "live HEAD : $(git -C "$PROD" log -1 --format='%h %ci %s')"
  echo "state     : CURRENT=${CURRENT:0:9} PREVIOUS=${PREVIOUS:0:9}"
  docker ps --filter label=kgkg.env=prod --format '{{.Names}}  {{.Image}}  {{.Status}}'
  systemctl is-active -q kgkg-backend 2>/dev/null && echo "NOTE: systemd kgkg-backend still active (pre-Docker)"
  echo "hostjobs  : $(systemctl is-active kgkg-hostjobs 2>/dev/null)"
  prod_clean && echo "live tree : clean" || { echo "live tree : DIRTY"; git -C "$PROD" status --short --untracked-files=no; }
}

# ---------------------------------------------------------------------------
MODE=full; FORCE=0; REF=
while [[ $# -gt 0 ]]; do
  case $1 in
    --staging) MODE=staging ;;
    --rollback) MODE=rollback ;;
    --status) MODE=status ;;
    --reload) MODE=reload ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) REF=$1 ;;
  esac
  shift
done

if [[ $MODE == status ]]; then status; exit 0; fi

# The lock lives below --status on purpose: asking what is live is read-only,
# and it is most wanted precisely while a deploy holds the lock.
#
# It waits rather than refuses. Two pushes a minute apart are a queue, not an
# error, and a CI run that goes red because another run held the lock teaches
# people to ignore red runs. KG_DEPLOY_LOCK_WAIT=0 restores fail-fast.
LOCK_WAIT=${KG_DEPLOY_LOCK_WAIT:-1800}
exec 9> "$REL/deploy.lock"
if ! flock -n 9; then
  say "another deploy is running; waiting up to ${LOCK_WAIT}s for the lock"
  flock -w "$LOCK_WAIT" 9 || die "still locked after ${LOCK_WAIT}s ($REL/deploy.lock)"
fi
if [[ $MODE == reload ]]; then
  load_state
  [[ -n $CURRENT ]] && have_images "$CURRENT" || die "no live release image recorded in $STATE"
  say "reloading ${CURRENT:0:9} (new backend container beside the old one)"
  swap_backend "$CURRENT" || die "reloaded backend did not become healthy; the old one is still serving"
  KG_SMOKE_NGINX=${KG_SMOKE_NGINX:-http://127.0.0.1} bash "$PROD/ops/deploy/smoke.sh" http://127.0.0.1:8000 http://127.0.0.1:3000 || die "smoke failed after reload"
  say "RELOADED ${CURRENT:0:9}"
  exit 0
fi
if [[ $MODE == rollback ]]; then
  load_state
  [[ -n $PREVIOUS ]] || die "no previous release recorded in $STATE"
  rollback_to "$PREVIOUS"
  KG_SMOKE_NGINX=${KG_SMOKE_NGINX:-http://127.0.0.1} bash "$PROD/ops/deploy/smoke.sh" http://127.0.0.1:8000 http://127.0.0.1:3000 || say "WARNING: smoke failed after rollback"
  save_state "$PREVIOUS" "$CURRENT"
  write_release_metrics
  exit 0
fi

[[ -n $REF ]] || die "usage: deploy.sh [--staging] <git-ref>"
SHA=$(git -C "$PROD" rev-parse --verify "$REF^{commit}") || die "unknown ref $REF"
SHORT=${SHA:0:9}
PREV=$(git -C "$PROD" rev-parse HEAD)
say "deploy $REF = $SHORT (live: ${PREV:0:9}) mode=$MODE log=$LOG"
prod_clean || { git -C "$PROD" status --short --untracked-files=no; die "live tree has uncommitted edits. Commit them (or move them to the work branch) first."; }
git -C "$PROD" merge-base --is-ancestor "$PREV" "$SHA" || die "$SHORT does not contain the live commit ${PREV:0:9}; rebase/merge onto it first (prod only fast-forwards)."
if [[ $SHA == "$PREV" && $FORCE -eq 0 && $MODE == full ]] && [[ -n $(prod_containers backend) ]]; then
  say "already live; nothing to do (use --force to rebuild)"; exit 0
fi

# ---- 1. gate ---------------------------------------------------------------
for old in "$REL"/w-*; do [[ -d $old ]] && git -C "$PROD" worktree remove --force "$old" 2>/dev/null; done; rm -rf "$REL"/w-*
W=$REL/w-$SHORT
git -C "$PROD" worktree prune
git -C "$PROD" worktree add -q --detach "$W" "$SHA"
# A bad nginx config must stop the deploy here, with production untouched,
# rather than after the containers have been swapped.
if nginx_config_differs; then
  say "nginx config in this release differs from what is installed; validating it"
  nginx_config_check || die "the release nginx config does not validate; production untouched"
fi

say "1/5 GATE in $W"
KG_GATE_LOGS=$REL/logs/gate-$TS bash "$W/ops/deploy/gate.sh" "$W" || die "gate failed; production untouched (logs: $REL/logs/gate-$TS)"
source_containers "$W"

# ---- 2. images -------------------------------------------------------------
say "2/5 IMAGES $(img_be "$SHA") $(img_fe "$SHA")"
FE_PUBLIC=$(grep -E '^NEXT_PUBLIC_API_BASE=' "$PROD/kg_frontend/.env.production" | cut -d= -f2- || true)
( trap - ERR; cd "$W" &&
  nice -n 10 docker build -q -f ops/docker/backend.Dockerfile -t "$(img_be "$SHA")" --build-arg KG_RELEASE="$SHORT" . &&
  nice -n 10 docker build -q -f ops/docker/frontend.Dockerfile -t "$(img_fe "$SHA")" --build-arg KG_RELEASE="$SHORT" \
    ${FE_PUBLIC:+--build-arg NEXT_PUBLIC_API_BASE="$FE_PUBLIC"} . ) > "$REL/logs/images-$TS.log" 2>&1 \
  || { tail -30 "$REL/logs/images-$TS.log"; die "image build failed; production untouched (log: $REL/logs/images-$TS.log)"; }

# ---- 3. staging ------------------------------------------------------------
say "3/5 STAGING (backend :$STG_BE, frontend :$STG_FE, DB = fresh copy of prod)"
docker rm -f kgkg-stg-backend kgkg-stg-frontend >/dev/null 2>&1 || true
STG_DB_ENV=()
if is_pg; then
  pg_clone_staging || die "could not copy the prod database into $PG_STAGING"
  STG_DB_ENV=(-e KG_PG_NAME="$PG_STAGING")
else
  sqlite_copy "$KG_BE_DIR/db.sqlite3" "$STG/db/db.sqlite3"
fi
# The backend finds the warehouses next to its database (/data/db). This link
# used to exist only because someone made it by hand; recreate it every run.
ln -sfn "$KG_BE_DIR/Database_warehouse" "$STG/db/Database_warehouse"
# Staging runs real code against real data shapes, which means a copy of real
# customers. Strip what identifies a person or opens a door before anything is
# served from it: a session token lifted from staging would otherwise work
# against production. Representative row counts and relationships are kept.
if is_pg; then
  "$VENV/python" -I "$W/ops/deploy/sanitize_staging_db.py" --pg "dbname=$PG_STAGING" --quiet
else
  python3 -I "$W/ops/deploy/sanitize_staging_db.py" "$STG/db/db.sqlite3" --quiet
fi \
  || die "could not sanitize the staging database copy; refusing to serve real credentials from staging"
cat > "$STG/stagecfg/staging_settings.py" <<'PY'
# Staging backend (ops/deploy/deploy.sh): prod settings on a COPY of the prod DB.
from KG_backend.settings import *  # noqa
ALLOWED_HOSTS = ["*"]
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
PY
NOSEC=(-e SENTRY_DSN= -e SMS_API_KEY= -e SMS_USERNAME= -e SMS_FROM= -e TURNSTILE_SECRET= -e KG_ALERT_PHONES=
       -e RAG_FEEDBACK_DB=/data/db/feedback.db
       -e DJANGO_SETTINGS_MODULE=staging_settings -e PYTHONPATH=/stagecfg -v "$STG/stagecfg":/stagecfg:ro
       "${STG_DB_ENV[@]}")
STG_SPOOL=/run/kgkg-hostjobs-staging   # nobody serves it: staging can never start host jobs
KG_SPOOL=$STG_SPOOL be_run "$(img_be "$SHA")" "$STG/db" "$STG/logs" "${NOSEC[@]}" -- python manage.py migrate --noinput \
  > "$REL/logs/staging-migrate-$TS.log" 2>&1 \
  || die "migrations failed on the prod-data copy (log: $REL/logs/staging-migrate-$TS.log); production untouched"
TOKEN=$(KG_SPOOL=$STG_SPOOL be_run "$(img_be "$SHA")" "$STG/db" "$STG/logs" "${NOSEC[@]}" -- python manage.py shell -c \
  "from api.models import AuthToken, PortalUser; print(AuthToken.issue(PortalUser.objects.get(username='$QA_USER')).key)" 2>/dev/null | tail -1)
[[ ${#TOKEN} -ge 40 ]] || die "could not mint a staging QA token for $QA_USER"
KG_SPOOL=$STG_SPOOL KG_WARMUP=0 run_backend kgkg-stg-backend "$(img_be "$SHA")" $STG_BE "$STG/db" "$STG/logs" \
  "${NOSEC[@]}" -e KG_WORKERS=2 -e KG_THREADS=4
run_frontend kgkg-stg-frontend "$(img_fe "$SHA")" $STG_FE http://127.0.0.1:$STG_BE -e METIS_API_KEY= -e SENTRY_DSN=
wait_healthy kgkg-stg-backend 240 || { docker logs --tail 40 kgkg-stg-backend; die "staging backend did not become healthy"; }
wait_healthy kgkg-stg-frontend 120 || { docker logs --tail 40 kgkg-stg-frontend; die "staging frontend did not become healthy"; }
STG_OK=0
bash "$W/ops/deploy/smoke.sh" http://127.0.0.1:$STG_BE http://127.0.0.1:$STG_FE "$TOKEN" && STG_OK=1
[[ ${KG_KEEP_STAGING:-0} == 1 ]] || docker rm -f kgkg-stg-backend kgkg-stg-frontend >/dev/null 2>&1 || true
(( STG_OK )) || die "staging smoke tests failed; production untouched"
save_staging_state "$SHA" pass
write_release_metrics
if [[ $MODE == staging ]]; then
  # Retention, which used to live only at the end of a full promote. Staging
  # builds a 3.46 GB image pair and exits several hundred lines before that
  # block, so on 2026-10-30 six staging runs in nine hours had left ~21 GB
  # behind and the root filesystem had gone 74.5 % -> 77 % with 70 G free.
  # Keep the live release and the rollback target (never this run's business
  # to delete) and the sha just staged, since that is the one about to be
  # promoted and a rebuild would be pure waste.
  load_state
  # From $PROD, not the staged worktree, for the same reason the gates are:
  # a commit under test must not be able to choose which images get deleted.
  # The first staging after this lands finds no script there and prunes
  # nothing, which is why the call tolerates a missing file.
  pruned=$(KEEP_IMAGES=$KEEP_IMAGES bash "$PROD/ops/deploy/prune_images.sh" \
             "$SHA" "$CURRENT" "$PREVIOUS" 2>/dev/null || echo 0)
  if [[ ${pruned:-0} =~ ^[0-9]+$ ]] && (( pruned )); then say "removed $pruned superseded release image(s)"; fi
  # The builder also leaves untagged intermediates on this path, for the same
  # reason and at the same rate as on a promote.
  reclaimed=$(docker image prune -f 2>/dev/null | sed -n 's/^Total reclaimed space: //p')
  if [[ -n ${reclaimed:-} && $reclaimed != 0B ]]; then say "pruned dangling build images ($reclaimed)"; fi
  say "STAGING PASSED for $SHORT (production untouched)"
  say "promote it with: kgkg-promote $SHA"
  exit 0
fi

# ---- 4. promote --------------------------------------------------------------
say "4/5 PROMOTE ${PREV:0:9} -> $SHORT"
prod_clean || die "live tree changed during the deploy; aborting before touching it"
if is_pg; then
  pg_backup "$REL/db-backups/db-$TS-${PREV:0:9}.pgdump" || die "pg_dump backup failed; production untouched"
  { ls -1t "$REL"/db-backups/db-*.pgdump 2>/dev/null | tail -n +4 | xargs -r rm -f; } || true
else
  sqlite_copy "$KG_BE_DIR/db.sqlite3" "$REL/db-backups/db-$TS-${PREV:0:9}.sqlite3"
  { ls -1t "$REL"/db-backups/db-*.sqlite3 2>/dev/null | tail -n +4 | xargs -r rm -f; } || true
fi
CHANGED=$(git -C "$PROD" diff --name-only "$PREV" "$SHA")
git -C "$PROD" merge -q --ff-only "$SHA"
undo_code() { git -C "$PROD" reset -q --hard "$PREV"; }

# Host jobs (timers, pipeline, crawler) keep using the host venv: keep it in step.
if grep -qE '^(KG_backend/requirements.txt|ops/docker/backend-requirements.lock)$' <<<"$CHANGED"; then
  "$VENV/pip" install -q -r "$PROD/ops/docker/backend-requirements.lock" --extra-index-url https://download.pytorch.org/whl/cpu \
    || { undo_code; die "host venv pip install failed; code reset to ${PREV:0:9}"; }
fi
be_run "$(img_be "$SHA")" "$KG_BE_DIR" /var/log/kgkg -- python manage.py migrate --noinput > "$REL/logs/prod-migrate-$TS.log" 2>&1 \
  || { undo_code; die "prod migrate failed; code reset to ${PREV:0:9} (log: $REL/logs/prod-migrate-$TS.log, DB backup: $REL/db-backups/)"; }
ensure_hostjobs

# The forced-command gate, the CI wrapper and the promote wrapper live in
# /usr/local/bin as copies of ops/deploy/*. Nothing re-installed them, so they
# could drift from the release that defines them — and the gate is the file
# that decides whether a key may promote. Refresh them from the tree that was
# just promoted.
for w in kg-deploy-gate kg-ci-gate kgkg-promote; do
  if [[ -f $PROD/ops/deploy/$w ]] && ! cmp -s "$PROD/ops/deploy/$w" "/usr/local/bin/$w"; then
    install -m 755 "$PROD/ops/deploy/$w" "/usr/local/bin/$w" && say "refreshed /usr/local/bin/$w"
  fi
done

# The alerting watchdog runs from outside the git tree for the same reason its
# unit says: an untracked file where the release wants to add one would make a
# fast-forward refuse.
if [[ -f $PROD/ops/observability/watchdog.py ]]; then
  install -d /usr/local/lib/kgkg
  if ! cmp -s "$PROD/ops/observability/watchdog.py" /usr/local/lib/kgkg/watchdog.py; then
    install -m 755 "$PROD/ops/observability/watchdog.py" /usr/local/lib/kgkg/watchdog.py \
      && say "refreshed /usr/local/lib/kgkg/watchdog.py"
  fi
fi

# Its systemd units too: the sandbox in the unit file is part of the code (a
# ProtectHome setting silently broke the backup check today), so it must not
# be left behind by a deploy.
#
# The nightly QA units are here for a different reason: they were committed on
# 2026-10-27 and were still not installed on the host three days later, because
# nothing installed them. A unit file that only exists in the repository runs
# nowhere. Managing them from the release means the schedule cannot drift from
# the suite it runs, and that enabling it is a promote rather than someone
# remembering to log in.
_units_changed=0
for spec in observability:kgkg-watchdog.service observability:kgkg-watchdog.timer \
            qa:kgkg-qa-nightly.service qa:kgkg-qa-nightly.timer; do
  d=${spec%%:*}; u=${spec#*:}
  if [[ -f $PROD/ops/$d/$u ]] && ! cmp -s "$PROD/ops/$d/$u" "/etc/systemd/system/$u"; then
    install -m 644 "$PROD/ops/$d/$u" "/etc/systemd/system/$u" && _units_changed=1
    say "refreshed /etc/systemd/system/$u"
  fi
done
if (( _units_changed )); then
  systemctl daemon-reload
  # Enabling the timer, not the service: the service is oneshot and the timer
  # is what decides when it runs.
  for t in kgkg-watchdog.timer kgkg-qa-nightly.timer; do
    [[ -f /etc/systemd/system/$t ]] || continue
    systemctl enable -q --now "$t" || say "WARNING: could not enable $t"
  done
fi

PREV_IMG_OK=0; have_images "$PREV" && PREV_IMG_OK=1
fail_promote() {
  if (( PREV_IMG_OK )); then rollback_to "$PREV"; else
    undo_code
    say "no images for ${PREV:0:9} (pre-Docker release): restoring the systemd services"
    for r in backend frontend; do for c in $(prod_containers $r); do docker rm -f "$c" >/dev/null; done; done
    systemctl enable -q kgkg-backend kgkg-frontend; systemctl start kgkg-backend kgkg-frontend
  fi
  die "$1 -> rolled back to ${PREV:0:9}"
}
swap_backend "$SHA" || fail_promote "new backend container did not become healthy"
swap_frontend "$SHA" || fail_promote "new frontend container did not become healthy"

# nginx last, so the config pairs with the code that is now serving. The
# media-gate fix needs both halves: the normalized path check in
# api/mediaauth.py and the normalized cache key here. A failure rolls the
# release back rather than leaving a half-applied pair, and the verify smoke
# below then exercises the real end state.
install_nginx_config || fail_promote "the release nginx config could not be installed"

# ---- 5. verify -----------------------------------------------------------------
say "5/5 VERIFY production"
KG_SMOKE_NGINX=${KG_SMOKE_NGINX:-http://127.0.0.1} bash "$PROD/ops/deploy/smoke.sh" http://127.0.0.1:8000 http://127.0.0.1:3000 || fail_promote "production smoke failed"

load_state
save_state "$SHA" "$PREV"
write_release_metrics
TAG=deploy-$TS
VERSION=$(git -C "$PROD" show "$SHA:VERSION" 2>/dev/null | head -1 || true)
git -C "$PROD" tag -a "$TAG" -m "deployed $SHORT${VERSION:+ version $VERSION}" "$SHA"
timeout 60 git -C "$PROD" push -q origin "HEAD:$(git -C "$PROD" rev-parse --abbrev-ref HEAD)" "$TAG" \
  || say "WARNING: push to origin failed (deploy itself is fine): git -C $PROD push origin HEAD $TAG"
# Keep the live and rollback images plus the newest few others. The same
# retention now runs at the end of a staging run too (see the staging exit
# above): this block was correct and only ever reached on a promote, so the
# images staging built on every push to `work` were never considered.
pruned=$(KEEP_IMAGES=$KEEP_IMAGES bash "$PROD/ops/deploy/prune_images.sh" "$SHA" "$PREV" 2>/dev/null || echo 0)
if [[ ${pruned:-0} =~ ^[0-9]+$ ]] && (( pruned )); then say "removed $pruned superseded release image(s)"; fi

# The builder leaves an untagged intermediate per build step, twice per run,
# and nothing removed them: 102 had piled up by 2026-10-28, worth ~40GB of
# disk. Dangling only — `prune -a` would delete tagged-but-unused images,
# which is precisely the previous release that --rollback restores.
reclaimed=$(docker image prune -f 2>/dev/null | sed -n 's/^Total reclaimed space: //p')
# The `|| true` matters: a bare `[[ ]] && say` returns non-zero when nothing
# was reclaimed, and with set -e plus the ERR trap that would make a perfectly
# good deploy announce DEPLOY FAILED on its last line.
if [[ -n ${reclaimed:-} && $reclaimed != 0B ]]; then say "pruned dangling build images ($reclaimed)"; fi
git -C "$PROD" worktree remove --force "$W" 2>/dev/null || true
say "DEPLOYED $SHORT as $TAG (previous ${PREV:0:9}; rollback: ops/deploy/deploy.sh --rollback)"
