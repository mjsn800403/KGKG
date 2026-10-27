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
sqlite_copy "$KG_BE_DIR/db.sqlite3" "$STG/db/db.sqlite3"
# Staging runs real code against real data shapes, which means a copy of real
# customers. Strip what identifies a person or opens a door before anything is
# served from it: a session token lifted from staging would otherwise work
# against production. Representative row counts and relationships are kept.
python3 -I "$W/ops/deploy/sanitize_staging_db.py" "$STG/db/db.sqlite3" --quiet \
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
       -e DJANGO_SETTINGS_MODULE=staging_settings -e PYTHONPATH=/stagecfg -v "$STG/stagecfg":/stagecfg:ro)
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
  say "STAGING PASSED for $SHORT (production untouched)"
  say "promote it with: kgkg-promote $SHA"
  exit 0
fi

# ---- 4. promote --------------------------------------------------------------
say "4/5 PROMOTE ${PREV:0:9} -> $SHORT"
prod_clean || die "live tree changed during the deploy; aborting before touching it"
sqlite_copy "$KG_BE_DIR/db.sqlite3" "$REL/db-backups/db-$TS-${PREV:0:9}.sqlite3"
{ ls -1t "$REL"/db-backups/db-*.sqlite3 2>/dev/null | tail -n +4 | xargs -r rm -f; } || true
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

# ---- 5. verify -----------------------------------------------------------------
say "5/5 VERIFY production"
KG_SMOKE_NGINX=${KG_SMOKE_NGINX:-http://127.0.0.1} bash "$PROD/ops/deploy/smoke.sh" http://127.0.0.1:8000 http://127.0.0.1:3000 || fail_promote "production smoke failed"

load_state
save_state "$SHA" "$PREV"
write_release_metrics
TAG=deploy-$TS
git -C "$PROD" tag -a "$TAG" -m "deployed $SHORT" "$SHA"
timeout 60 git -C "$PROD" push -q origin "HEAD:$(git -C "$PROD" rev-parse --abbrev-ref HEAD)" "$TAG" \
  || say "WARNING: push to origin failed (deploy itself is fine): git -C $PROD push origin HEAD $TAG"
# Keep the live and rollback images plus the newest few others.
for repo in kgkg-backend kgkg-frontend; do
  docker images "$repo" --format '{{.Tag}}' | grep -xE '[0-9a-f]{9}' | grep -vxF -e "$SHORT" -e "${PREV:0:9}" \
    | tail -n +$KEEP_IMAGES | xargs -r -I{} docker image rm -f "$repo:{}" >/dev/null 2>&1 || true
done
git -C "$PROD" worktree remove --force "$W" 2>/dev/null || true
say "DEPLOYED $SHORT as $TAG (previous ${PREV:0:9}; rollback: ops/deploy/deploy.sh --rollback)"
