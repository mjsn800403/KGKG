#!/usr/bin/env bash
# KGKG gated deploy:  gate -> staging -> promote -> verify (auto-rollback)
#
#   ops/deploy/deploy.sh <git-ref>            full pipeline to production
#   ops/deploy/deploy.sh --staging <git-ref>  gate + staging only (prod untouched)
#   ops/deploy/deploy.sh --rollback           back to the previously deployed release
#   ops/deploy/deploy.sh --status             what is live, and the previous release
#
# Rules it enforces:
#   * Production (/opt/KGKG) is never edited by hand any more. Changes are
#     committed elsewhere (e.g. the /opt/KGKG_work worktree, branch `work`) and
#     promoted here. The deploy refuses to run if the live tree has uncommitted
#     edits, and only fast-forwards, so prod history stays linear.
#   * The ref is tested in a fresh worktree (gate.sh: Django check, migration
#     drift, full test suite, lint ratchet, next build). Nothing reaches
#     staging unless the gate passes.
#   * Staging = the same code on 127.0.0.1:8110 (backend) / :3107 (frontend),
#     with a fresh COPY of the prod database, migrated, and SMS/Sentry/Metis
#     disabled; smoke.sh runs signed-in checks with a QA token minted in the
#     copy only.
#   * Production: DB backup, fast-forward, migrate, frontend built into its own
#     .next-<sha> (the live build is never overwritten), atomic symlink swap,
#     graceful gunicorn reload (HUP), frontend restart, smoke test. Any failure
#     after the swap rolls code + build back automatically. Migrations are NOT
#     reversed (keep them additive); the pre-deploy DB backup is kept.
set -Eeuo pipefail

PROD=/opt/KGKG
REL=/opt/KGKG_release
STG=/opt/KGKG_staging
VENV=$PROD/KG_backend/.venv/bin
STATE=$REL/state.env
STG_BE=8110
STG_FE=3107
QA_USER=${KG_STAGING_QA_USER:-qa_e_root}
KEEP_BUILDS=3
TS=$(date -u +%Y%m%d-%H%M%S)
mkdir -p "$REL/logs" "$REL/db-backups" "$STG/logs" "$STG/db"
LOG=$REL/logs/deploy-$TS.log
exec > >(tee -a "$LOG") 2>&1

say()  { printf '\n[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die()  { say "DEPLOY ABORTED: $*"; exit 1; }
prod_clean() { [[ -z $(git -C "$PROD" status --porcelain --untracked-files=no) ]]; }
port_pid() { ss -ltnp "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2; }
stop_port() { local p; p=$(port_pid "$1"); [[ -n $p ]] && kill "$p" 2>/dev/null && sleep 2; return 0; }
wait_http() {  # url seconds
  local i
  for ((i = 0; i < $2; i++)); do
    [[ $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$1") =~ ^(200|30[0-9])$ ]] && return 0
    sleep 1
  done
  return 1
}
sqlite_copy() {  # src dst   (online backup API: consistent even while prod writes)
  python3 - "$1" "$2" <<'PY'
import sqlite3, sys, os
src, dst = sys.argv[1], sys.argv[2]
tmp = dst + '.tmp'
for f in (tmp, tmp + '-wal', tmp + '-shm'):
    if os.path.exists(f): os.remove(f)
s = sqlite3.connect(f'file:{src}?mode=ro', uri=True, timeout=60)
d = sqlite3.connect(tmp)
s.backup(d); d.close(); s.close()
os.replace(tmp, dst)
PY
}
load_state() { CURRENT=; PREVIOUS=; CURRENT_BUILD=; PREVIOUS_BUILD=; [[ -f $STATE ]] && . "$STATE"; return 0; }
save_state() {
  printf 'CURRENT=%s\nPREVIOUS=%s\nCURRENT_BUILD=%s\nPREVIOUS_BUILD=%s\nDEPLOYED_AT=%s\n' \
    "$1" "$2" "$3" "$4" "$TS" > "$STATE"
}

exec 9> "$REL/deploy.lock"
flock -n 9 || die "another deploy is running ($REL/deploy.lock)"

# ---------------------------------------------------------------------------
rollback_to() {  # sha build-dir-name(or empty)
  local sha=$1 build=$2
  say "ROLLBACK to ${sha:0:9} ${build:+(build $build)}"
  prod_clean || die "live tree has uncommitted edits; refusing to reset it. Inspect: git -C $PROD status"
  git -C "$PROD" reset -q --hard "$sha"
  if [[ -n $build && -d $PROD/kg_frontend/$build ]]; then
    ln -sfn "$build" "$PROD/kg_frontend/.next.new" && mv -Tf "$PROD/kg_frontend/.next.new" "$PROD/kg_frontend/.next"
    systemctl restart kgkg-frontend
  fi
  systemctl kill -s HUP --kill-whom=main kgkg-backend
  wait_http http://127.0.0.1:8000/api/health/ 60 || say "WARNING: backend health not back after rollback"
  wait_http http://127.0.0.1:3000/ 90 || say "WARNING: frontend not back after rollback"
  say "Rolled back. Database migrations are not reversed; DB backups: $REL/db-backups/"
}

status() {
  load_state
  echo "live HEAD : $(git -C "$PROD" log -1 --format='%h %ci %s')"
  echo "state     : CURRENT=${CURRENT:0:9} PREVIOUS=${PREVIOUS:0:9} build=$CURRENT_BUILD prev_build=$PREVIOUS_BUILD"
  echo ".next ->  : $(readlink "$PROD/kg_frontend/.next" 2>/dev/null || echo '(plain directory)')"
  prod_clean && echo "live tree : clean" || { echo "live tree : DIRTY"; git -C "$PROD" status --short --untracked-files=no; }
}

# ---------------------------------------------------------------------------
MODE=full; FORCE=0; REF=
while [[ $# -gt 0 ]]; do
  case $1 in
    --staging) MODE=staging ;;
    --rollback) MODE=rollback ;;
    --status) MODE=status ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) REF=$1 ;;
  esac
  shift
done

if [[ $MODE == status ]]; then status; exit 0; fi
if [[ $MODE == rollback ]]; then
  load_state
  [[ -n $PREVIOUS ]] || die "no previous release recorded in $STATE"
  rollback_to "$PREVIOUS" "$PREVIOUS_BUILD"
  bash "$PROD/ops/deploy/smoke.sh" http://127.0.0.1:8000 http://127.0.0.1:3000 || say "WARNING: smoke failed after rollback"
  save_state "$PREVIOUS" "$CURRENT" "$PREVIOUS_BUILD" "$CURRENT_BUILD"
  exit 0
fi

[[ -n $REF ]] || die "usage: deploy.sh [--staging] <git-ref>"
SHA=$(git -C "$PROD" rev-parse --verify "$REF^{commit}") || die "unknown ref $REF"
SHORT=${SHA:0:9}
PREV=$(git -C "$PROD" rev-parse HEAD)
say "deploy $REF = $SHORT (live: ${PREV:0:9}) mode=$MODE log=$LOG"
prod_clean || { git -C "$PROD" status --short --untracked-files=no; die "live tree has uncommitted edits. Commit them (or move them to the work branch) first."; }
git -C "$PROD" merge-base --is-ancestor "$PREV" "$SHA" || die "$SHORT does not contain the live commit ${PREV:0:9}; rebase/merge onto it first (prod only fast-forwards)."
if [[ $SHA == "$PREV" && $FORCE -eq 0 && $MODE == full ]]; then say "already live; nothing to do (use --force to rebuild)"; exit 0; fi

# ---- 1. gate ---------------------------------------------------------------
W=$REL/w-$SHORT
git -C "$PROD" worktree remove --force "$W" 2>/dev/null || rm -rf "$W"
git -C "$PROD" worktree prune
git -C "$PROD" worktree add -q --detach "$W" "$SHA"
say "1/4 GATE in $W"
KG_GATE_LOGS=$REL/logs/gate-$TS bash "$W/ops/deploy/gate.sh" "$W" || die "gate failed; production untouched (logs: $REL/logs/gate-$TS)"

# ---- 2. staging ------------------------------------------------------------
say "2/4 STAGING (backend :$STG_BE, frontend :$STG_FE, DB = fresh copy of prod)"
rsync -a --delete --exclude Database_warehouse --exclude static_warehouse --exclude 'db.sqlite3*' \
  --exclude .venv --exclude __pycache__ --exclude .gate-logs "$W/KG_backend/" "$STG/backend/"
ln -sfn "$PROD/KG_backend/Database_warehouse" "$STG/backend/Database_warehouse"
ln -sfn "$PROD/KG_backend/static_warehouse" "$STG/backend/static_warehouse"
sqlite_copy "$PROD/KG_backend/db.sqlite3" "$STG/db/db.sqlite3"
mkdir -p "$STG/stagecfg"
cat > "$STG/stagecfg/staging_settings.py" <<PY
# Staging backend (ops/deploy/deploy.sh): prod settings, a COPY of the prod DB.
from KG_backend.settings import *  # noqa
DATABASES["default"]["NAME"] = "$STG/db/db.sqlite3"
ALLOWED_HOSTS = ["*"]
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
PY
stg_env() {  # run a command with the staging backend environment
  ( cd "$STG/backend" && set -a && . "$PROD/KG_backend/.env.prod" && set +a &&
    unset SENTRY_DSN SMS_API_KEY SMS_USERNAME SMS_FROM TURNSTILE_SECRET KG_ALERT_PHONES &&
    export KG_WARMUP=0 KG_LOG_DIR=$STG/logs DJANGO_SETTINGS_MODULE=staging_settings \
           PYTHONPATH=$STG/stagecfg:$STG/backend HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 &&
    "$@" )
}
stg_env "$VENV/python" manage.py migrate --noinput > "$REL/logs/staging-migrate-$TS.log" 2>&1 \
  || die "migrations failed on the prod-data copy (log: $REL/logs/staging-migrate-$TS.log); production untouched"
TOKEN=$(stg_env "$VENV/python" manage.py shell -c \
  "from api.models import AuthToken, PortalUser; print(AuthToken.issue(PortalUser.objects.get(username='$QA_USER')).key)" 2>/dev/null | tail -1)
[[ ${#TOKEN} -ge 40 ]] || die "could not mint a staging QA token for $QA_USER"
stop_port $STG_BE
stg_env setsid nohup "$VENV/gunicorn" KG_backend.wsgi:application --bind 127.0.0.1:$STG_BE \
  --workers 2 --threads 4 --timeout 300 > "$STG/logs/backend.out" 2>&1 < /dev/null &
stop_port $STG_FE
TERMS=$(grep -E '^TERMS_JSON_PATH=' "$PROD/kg_frontend/.env.production" | cut -d= -f2- || true)
( cd "$W/kg_frontend" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/root NODE_ENV=production \
    BACKEND_URL=http://127.0.0.1:$STG_BE API_BASE_INTERNAL=http://127.0.0.1:$STG_BE TERMS_JSON_PATH="$TERMS" \
    setsid nohup npx next start -p $STG_FE -H 127.0.0.1 > "$STG/logs/frontend.out" 2>&1 < /dev/null & )
wait_http http://127.0.0.1:$STG_BE/api/health/ 90 || die "staging backend did not start (log: $STG/logs/backend.out)"
wait_http http://127.0.0.1:$STG_FE/ 90 || die "staging frontend did not start (log: $STG/logs/frontend.out)"
STG_OK=0
bash "$W/ops/deploy/smoke.sh" http://127.0.0.1:$STG_BE http://127.0.0.1:$STG_FE "$TOKEN" && STG_OK=1
if [[ ${KG_KEEP_STAGING:-0} != 1 ]]; then stop_port $STG_FE; stop_port $STG_BE; fi
(( STG_OK )) || die "staging smoke tests failed; production untouched"
if [[ $MODE == staging ]]; then say "STAGING PASSED for $SHORT (production untouched)"; exit 0; fi

# ---- 3. promote --------------------------------------------------------------
say "3/4 PROMOTE ${PREV:0:9} -> $SHORT"
prod_clean || die "live tree changed during the deploy; aborting before touching it"
sqlite_copy "$PROD/KG_backend/db.sqlite3" "$REL/db-backups/db-$TS-${PREV:0:9}.sqlite3"
ls -1t "$REL"/db-backups/db-*.sqlite3 | tail -n +4 | xargs -r rm -f
CHANGED=$(git -C "$PROD" diff --name-only "$PREV" "$SHA")
git -C "$PROD" merge -q --ff-only "$SHA"

FE_DIR=$PROD/kg_frontend
OLD_BUILD=$(readlink "$FE_DIR/.next" 2>/dev/null || true)
NEED_FE=0
{ grep -q '^kg_frontend/' <<<"$CHANGED" || [[ -z $OLD_BUILD || $FORCE -eq 1 ]]; } && NEED_FE=1

undo_code() { git -C "$PROD" reset -q --hard "$PREV"; }
if grep -q '^KG_backend/requirements.txt$' <<<"$CHANGED"; then
  "$VENV/pip" install -q -r "$PROD/KG_backend/requirements.txt" || { undo_code; die "pip install failed; code reset to ${PREV:0:9}"; }
fi
( cd "$PROD/KG_backend" && set -a && . ./.env.prod && set +a && "$VENV/python" manage.py migrate --noinput ) \
  || { undo_code; die "prod migrate failed; code reset to ${PREV:0:9} (DB backup: $REL/db-backups/)"; }

NEW_BUILD=$OLD_BUILD
if (( NEED_FE )); then
  NEW_BUILD=.next-$SHORT
  if grep -q '^kg_frontend/package-lock.json$' <<<"$CHANGED"; then
    ( cd "$FE_DIR" && npm ci --no-audit --no-fund ) || { undo_code; die "npm ci failed; code reset"; }
  fi
  rm -rf "${FE_DIR:?}/$NEW_BUILD"
  ( cd "$FE_DIR" && KG_NEXT_DIST=$NEW_BUILD nice -n 10 npm run build > "$REL/logs/prod-build-$TS.log" 2>&1 ) \
    || { git -C "$PROD" checkout -q -- kg_frontend/tsconfig.json 2>/dev/null; undo_code; die "prod build failed; code reset, live build untouched (log: $REL/logs/prod-build-$TS.log)"; }
  git -C "$PROD" checkout -q -- kg_frontend/tsconfig.json 2>/dev/null || true
  if [[ -d $FE_DIR/.next && ! -L $FE_DIR/.next ]]; then
    OLD_BUILD=.next-pre-${PREV:0:9}
    mv "$FE_DIR/.next" "$FE_DIR/$OLD_BUILD"
  fi
  ln -sfn "$NEW_BUILD" "$FE_DIR/.next.new" && mv -Tf "$FE_DIR/.next.new" "$FE_DIR/.next"
fi

systemctl kill -s HUP --kill-whom=main kgkg-backend
if (( NEED_FE )); then
  T0=$(date +%s%N)
  systemctl restart kgkg-frontend
  wait_http http://127.0.0.1:3000/ 90 || true
  say "frontend back after $(( ($(date +%s%N) - T0) / 1000000 )) ms"
fi
wait_http http://127.0.0.1:8000/api/health/ 60 || true

# ---- 4. verify -----------------------------------------------------------------
say "4/4 VERIFY production"
if ! bash "$PROD/ops/deploy/smoke.sh" http://127.0.0.1:8000 http://127.0.0.1:3000; then
  rollback_to "$PREV" "$OLD_BUILD"
  die "production smoke failed -> rolled back to ${PREV:0:9}"
fi

load_state
save_state "$SHA" "$PREV" "$NEW_BUILD" "$OLD_BUILD"
TAG=deploy-$TS
git -C "$PROD" tag -a "$TAG" -m "deployed $SHORT" "$SHA"
timeout 60 git -C "$PROD" push -q origin "HEAD:$(git -C "$PROD" rev-parse --abbrev-ref HEAD)" "$TAG" \
  || say "WARNING: push to origin failed (deploy itself is fine): git -C $PROD push origin HEAD $TAG"
# keep the live build, the rollback build and the newest KEEP_BUILDS others
( cd "$FE_DIR" && ls -1dt .next-*/ 2>/dev/null | sed 's#/$##' | grep -vxF -e "$NEW_BUILD" -e "$OLD_BUILD" \
    | tail -n +$((KEEP_BUILDS)) | xargs -r rm -rf )
git -C "$PROD" worktree remove --force "$W" 2>/dev/null || true
say "DEPLOYED $SHORT as $TAG (previous ${PREV:0:9}; rollback: ops/deploy/deploy.sh --rollback)"
