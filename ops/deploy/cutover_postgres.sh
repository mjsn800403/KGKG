#!/usr/bin/env bash
# One-time move of the portal database from SQLite to PostgreSQL.
#
#   ops/deploy/cutover_postgres.sh            do it
#   ops/deploy/cutover_postgres.sh --rehearse copy + verify into the target DB,
#                                             but do not switch the site
#   ops/deploy/cutover_postgres.sh --back     return to SQLite (emergency)
#
# Prerequisites (checked): the live release already contains this code
# (copy_sqlite_to_postgres, psycopg), .env.prod has KG_PG_NAME/USER/PASSWORD/
# HOST, and the target database exists and is owned by KG_PG_USER.
#
# Sequence, with no lost writes:
#   1. migrate the empty PostgreSQL schema, using the live release image;
#   2. full copy from an online backup of db.sqlite3 while the site runs;
#   3. second copy (data-quality runs reused: immutable, the slow part),
#      recording the max id of every append-only log table;
#   4. KG_DB_ENGINE=postgres in .env.prod, `deploy.sh --reload` (zero-gap
#      container swap; the old SQLite container serves until the new is healthy);
#   5. catch-up: log rows the old container wrote after step 3 are appended.
# db.sqlite3 itself is left in place, frozen, as the pre-move copy.
set -Eeuo pipefail
PROD=/opt/KGKG
BE=$PROD/KG_backend
ENV=$BE/.env.prod
TS=$(date -u +%Y%m%d-%H%M%S)
LOG=/opt/KGKG_release/logs/pg-cutover-$TS.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
say() { printf '\n[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { say "CUTOVER ABORTED: $*"; exit 1; }
trap 'say "CUTOVER FAILED at line $LINENO: $BASH_COMMAND"' ERR

. "$PROD/ops/docker/containers.sh"
. /opt/KGKG_release/state.env
IMG=kgkg-backend:${CURRENT:0:9}
env_val() { sed -n "s/^$1=//p" "$ENV" | tail -1 | tr -d "\"' "; }

MODE=${1:-cutover}
if [[ $MODE == --back ]]; then
  cp "$ENV" "$ENV.bak-pgback-$TS"
  sed -i '/^KG_DB_ENGINE=/d' "$ENV"
  say "KG_DB_ENGINE removed (SQLite); reloading"
  bash "$PROD/ops/deploy/deploy.sh" --reload
  say "back on SQLite. Writes made on PostgreSQL since the cutover are NOT in db.sqlite3"
  exit 0
fi

# ---- preflight ---------------------------------------------------------------
[[ $(env_val KG_DB_ENGINE) == postgres ]] && die "already on PostgreSQL"
for v in KG_PG_NAME KG_PG_USER KG_PG_PASSWORD KG_PG_HOST; do
  [[ -n $(env_val $v) ]] || die "$v missing from $ENV"
done
PGDB=$(env_val KG_PG_NAME)
psql -d "$PGDB" -Atc 'select 1' >/dev/null || die "database $PGDB not reachable"
docker run --rm --entrypoint test "$IMG" -f /opt/KGKG/KG_backend/api/management/commands/copy_sqlite_to_postgres.py \
  || die "live image $IMG predates the PostgreSQL support; deploy it first"

PGENV=(-e KG_DB_ENGINE=postgres)
snapshot() {  # online backup of the live SQLite file into the data dir
  python3 - "$BE/db.sqlite3" "$BE/$1" <<'PY'
import sqlite3, sys, os
s = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True, timeout=60)
d = sqlite3.connect(sys.argv[2] + '.tmp'); s.backup(d); d.close(); s.close()
os.replace(sys.argv[2] + '.tmp', sys.argv[2])
PY
}
mgr() { be_run "$IMG" "$BE" /var/log/kgkg "${PGENV[@]}" -e SENTRY_DSN= -- python manage.py "$@"; }

say "1/5 schema: migrate $PGDB"
mgr migrate --noinput | tail -3

say "2/5 full copy (site still on SQLite)"
snapshot pgcut-src.sqlite3
mgr copy_sqlite_to_postgres /data/db/pgcut-src.sqlite3 | tail -6

if [[ $MODE == --rehearse ]]; then
  rm -f "$BE/pgcut-src.sqlite3"
  say "REHEARSAL OK: $PGDB holds a verified copy; the site is still on SQLite"
  exit 0
fi

say "3/5 final copy + watermarks"
snapshot pgcut-src.sqlite3
mgr copy_sqlite_to_postgres /data/db/pgcut-src.sqlite3 --reuse api_dataqualityrun \
  --watermarks /data/db/pgcut-marks.json | tail -4

say "4/5 switch: KG_DB_ENGINE=postgres + zero-gap reload"
cp "$ENV" "$ENV.bak-pgcut-$TS"
echo 'KG_DB_ENGINE=postgres' >> "$ENV"
if ! bash "$PROD/ops/deploy/deploy.sh" --reload; then
  cp "$ENV.bak-pgcut-$TS" "$ENV"
  bash "$PROD/ops/deploy/deploy.sh" --reload || true
  die "reload on PostgreSQL failed; .env.prod restored and reloaded on SQLite"
fi

say "5/5 catch-up of log rows written during the switch"
snapshot pgcut-late.sqlite3
mgr copy_sqlite_to_postgres /data/db/pgcut-late.sqlite3 --catchup /data/db/pgcut-marks.json
rm -f "$BE/pgcut-src.sqlite3" "$BE/pgcut-late.sqlite3"
say "CUTOVER DONE: portal DB is PostgreSQL ($PGDB). db.sqlite3 is frozen as the pre-move copy."
say "emergency return: ops/deploy/cutover_postgres.sh --back"
