#!/usr/bin/env bash
# Access-control test for the staging role (ops/deploy/staging_role.sql, staging_isolation.sh).
#
# It builds a THROWAWAY PostgreSQL cluster (initdb in a temp directory, unix socket only, a random
# port) that imitates the production layout -- a loader role that owns the vector schemas, an app role
# that only reads them and owns the portal database -- applies the role setup, and then connects AS
# the staging role to prove what it can and cannot do. It never touches any real server.
#
#   bash ops/deploy/test_staging_isolation.sh
#
# Needs PostgreSQL server binaries (initdb, pg_ctl, psql); without them it says SKIP and exits 0 --
# unless KG_REQUIRE_PG=1 (CI), which turns that into a failure. KG_PG_MAJOR=16 additionally pins the server major version.
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

PGBIN=${KG_PG_BIN:-}
if [[ -z $PGBIN ]]; then
  if command -v initdb >/dev/null 2>&1; then PGBIN=$(dirname "$(command -v initdb)")
  else
    for d in /usr/lib/postgresql/*/bin /opt/homebrew/opt/postgresql@*/bin /usr/local/opt/postgresql@*/bin; do
      [[ -x $d/initdb ]] && PGBIN=$d
    done
  fi
fi
if [[ -z $PGBIN || ! -x $PGBIN/initdb ]]; then
  # CI sets KG_REQUIRE_PG=1: a runner without the server binaries must fail, not pass by skipping.
  if [[ -n ${KG_REQUIRE_PG:-} ]]; then echo "FAIL: PostgreSQL server binaries (initdb) are required here and were not found (KG_PG_BIN='${KG_PG_BIN:-}')"; exit 1; fi
  echo "SKIP: no PostgreSQL server binaries (initdb) found; set KG_PG_BIN"; exit 0
fi
export PATH="$PGBIN:$PATH"
pg_version=$("$PGBIN/postgres" --version)
echo "PostgreSQL: $pg_version ($PGBIN)"
if [[ -n ${KG_PG_MAJOR:-} && $pg_version != *" ${KG_PG_MAJOR}."* ]]; then echo "FAIL: expected PostgreSQL ${KG_PG_MAJOR}.x, found: $pg_version"; exit 1; fi

T=$(mktemp -d)
PORT=$((54000 + RANDOM % 900))
SOCK=$T/s; mkdir -p "$SOCK"
cleanup() { pg_ctl -D "$T/data" stop -m immediate >/dev/null 2>&1; rm -rf "$T"; }
trap cleanup EXIT
initdb -D "$T/data" -A trust -U postgres --no-sync >/dev/null 2>&1 || { echo "initdb failed"; exit 1; }
pg_ctl -D "$T/data" -w -l "$T/pg.log" -o "-c listen_addresses='' -c unix_socket_directories=$SOCK -c port=$PORT -c fsync=off" start >/dev/null 2>&1 \
  || { echo "could not start the throwaway cluster"; cat "$T/pg.log"; exit 1; }

fails=0
ok() { printf '  ok    %s\n' "$1"; }
no() { printf '  FAIL  %s\n          %s\n' "$1" "${2:-}"; fails=$((fails + 1)); }
PSQL=(psql -X -At -h "$SOCK" -p "$PORT")
as()  { local u=$1 d=$2; shift 2; "${PSQL[@]}" -U "$u" -d "$d" -v ON_ERROR_STOP=1 "$@" 2>&1; }   # as <role> <db> -c "<sql>"
denied() {  # denied "<label>" <role> <db> "<sql>"  -> the statement must fail with a permission error
  local out; out=$(as "$2" "$3" -c "$4") && { no "$1" "statement succeeded"; return; }
  [[ $out == *"permission denied"* || $out == *"must be owner"* ]] && ok "$1" || no "$1" "$out"
}
allowed() { local out; out=$(as "$2" "$3" -c "$4") && ok "$1" || no "$1" "$out"; }

# ---- a production-shaped cluster ------------------------------------------------------------
as postgres postgres -c "CREATE ROLE ldr LOGIN SUPERUSER; CREATE ROLE app LOGIN; CREATE ROLE other LOGIN;" >/dev/null
as postgres postgres -c "CREATE DATABASE vec OWNER app" >/dev/null
as postgres postgres -c "CREATE DATABASE portal OWNER app" >/dev/null
# PostgreSQL 15+ (what production runs) no longer lets PUBLIC create in schema public; older servers do.
# The check below would catch that on an older server; here the throwaway cluster is made to behave like 15+.
as postgres vec -c "REVOKE CREATE ON SCHEMA public FROM PUBLIC" >/dev/null
as postgres portal -c "REVOKE CREATE ON SCHEMA public FROM PUBLIC" >/dev/null
as postgres postgres -c "REVOKE CREATE ON SCHEMA public FROM PUBLIC" >/dev/null
as ldr vec -c "
  CREATE SCHEMA rag; CREATE SCHEMA car_a;
  CREATE TABLE public.car_dbs(filename text, nodes int); INSERT INTO public.car_dbs VALUES ('a.db', 3);
  CREATE TABLE rag.terms(t text); INSERT INTO rag.terms VALUES ('x');
  CREATE TABLE car_a.nodes(id int, body text); INSERT INTO car_a.nodes VALUES (1,'one'),(2,'two'),(3,'three');
  GRANT USAGE ON SCHEMA rag, car_a TO app; GRANT SELECT ON ALL TABLES IN SCHEMA rag, car_a TO app;
  GRANT SELECT ON public.car_dbs TO app;" >/dev/null
as postgres postgres -c "CREATE DATABASE other_db OWNER other" >/dev/null
as postgres other_db -c "REVOKE CREATE ON SCHEMA public FROM PUBLIC" >/dev/null
as postgres other_db -c "CREATE TABLE secrets(i int); ALTER TABLE secrets OWNER TO other" >/dev/null
as postgres portal -c "CREATE TABLE users(id int, secret text); INSERT INTO users VALUES (1, 'real customer'); ALTER TABLE users OWNER TO app" >/dev/null

# ---- setup via the real script ----------------------------------------------------------------
ENVF=$T/isolation.env
export KG_STG_ISOLATION_ENV=$ENVF KG_STG_PG_ROLE=kgkg_stg KG_STG_VEC_DB=vec KG_STG_LOADER_ROLE=ldr
export KG_STG_PSQL="psql -X -At -h $SOCK -p $PORT -U postgres"
# a wrapper that records the arguments psql was started with, to prove the password is never on one
cat > "$T/psqlw" <<EOF
#!/bin/sh
echo "\$@" >> "$T/psql-argv.log"
exec psql -X -At -h "$SOCK" -p "$PORT" -U postgres "\$@"
EOF
chmod +x "$T/psqlw"
export KG_STG_PSQL_ADMIN="$T/psqlw"

echo "== setup"
out=$(bash "$HERE/staging_isolation.sh" setup 2>&1); rc=$?
[[ $rc == 0 && $out == *"isolation check: OK"* ]] && ok "setup creates the role and the check passes" || no "setup" "$out"
mode=$(stat -c %a "$ENVF" 2>/dev/null || stat -f %Lp "$ENVF")
[[ $mode == 600 ]] && ok "credentials file is mode 600" || no "credentials file mode" "$mode"
PW=$(sed -n 's/^KG_STG_PG_PASSWORD=//p' "$ENVF")
[[ ${#PW} == 48 ]] && ok "a 48-hex-digit password was generated" || no "password length" "${#PW}"
grep -qF "$PW" "$T/psql-argv.log" 2>/dev/null && no "password stays off the psql command line" "found in argv" || ok "the password is never on a command line"

echo "== what the staging role can do in the vector database"
SR=kgkg_stg
allowed "SELECT public.car_dbs" $SR vec "SELECT count(*) FROM public.car_dbs"
allowed "SELECT rag.terms" $SR vec "SELECT count(*) FROM rag.terms"
allowed "SELECT car_a.nodes" $SR vec "SELECT count(*) FROM car_a.nodes"
denied  "INSERT is refused" $SR vec "INSERT INTO car_a.nodes VALUES (9,'x')"
denied  "UPDATE is refused" $SR vec "UPDATE car_a.nodes SET body='x'"
denied  "DELETE is refused" $SR vec "DELETE FROM car_a.nodes"
denied  "TRUNCATE is refused" $SR vec "TRUNCATE car_a.nodes"
denied  "DROP TABLE is refused" $SR vec "DROP TABLE car_a.nodes"
denied  "DROP SCHEMA ... CASCADE is refused" $SR vec "DROP SCHEMA car_a CASCADE"
denied  "ALTER TABLE is refused" $SR vec "ALTER TABLE car_a.nodes ADD COLUMN z int"
denied  "CREATE TABLE in public is refused" $SR vec "CREATE TABLE public.junk(i int)"
denied  "CREATE SCHEMA is refused" $SR vec "CREATE SCHEMA junk"
denied  "INSERT into the registry is refused" $SR vec "INSERT INTO public.car_dbs VALUES ('evil.db', 1)"
[[ $(as app vec -c "SELECT count(*) FROM car_a.nodes") == 3 ]] && ok "the data is untouched after those attempts" || no "data changed"

echo "== the portal database"
denied "SELECT users in the portal database is refused" $SR portal "SELECT * FROM users"
denied "INSERT into the portal database is refused" $SR portal "INSERT INTO users VALUES (2, 'x')"
denied "CREATE TABLE in the portal database is refused" $SR portal "CREATE TABLE junk(i int)"

echo "== a car added later is readable without re-running the setup"
as ldr vec -c "CREATE SCHEMA car_b; CREATE TABLE car_b.nodes(id int); INSERT INTO car_b.nodes VALUES (1);
               GRANT USAGE ON SCHEMA car_b TO app; GRANT SELECT ON ALL TABLES IN SCHEMA car_b TO app;" >/dev/null
allowed "SELECT car_b.nodes (new schema)" $SR vec "SELECT count(*) FROM car_b.nodes"
denied  "INSERT car_b.nodes (new schema) is refused" $SR vec "INSERT INTO car_b.nodes VALUES (2)"

echo "== the staging copy is writable"
as postgres postgres -c "CREATE DATABASE stg_copy OWNER $SR" >/dev/null
allowed "CREATE TABLE in its own database" $SR stg_copy "CREATE TABLE t(i int)"
allowed "INSERT / UPDATE / DELETE in its own database" $SR stg_copy "INSERT INTO t VALUES (1); UPDATE t SET i=2; DELETE FROM t"
allowed "DROP TABLE in its own database" $SR stg_copy "DROP TABLE t"

echo "== the check catches a role that is too wide"
check() { bash "$HERE/staging_isolation.sh" check 2>&1; }
check_fails() {  # label  fix-sql(db)  expected-text
  local out; out=$(check) && { no "$1" "check passed on a too-wide role"; return; }
  [[ $out == *"$2"* ]] && ok "$1" || no "$1" "$out"
}
as ldr vec -c "GRANT INSERT ON car_a.nodes TO $SR" >/dev/null
check_fails "INSERT on a car table is caught" "INSERT car_a.nodes"
as ldr vec -c "REVOKE INSERT ON car_a.nodes FROM $SR" >/dev/null
as ldr vec -c "GRANT CREATE ON SCHEMA public TO $SR" >/dev/null
check_fails "CREATE on a schema is caught" "CREATE in schema public"
as ldr vec -c "REVOKE CREATE ON SCHEMA public FROM $SR" >/dev/null
as postgres vec -c "GRANT CREATE ON DATABASE vec TO $SR" >/dev/null
check_fails "CREATE on the database is caught" "CREATE in database vec"
as postgres vec -c "REVOKE CREATE ON DATABASE vec FROM $SR" >/dev/null
as app portal -c "GRANT SELECT ON users TO $SR" >/dev/null
check_fails "access to the portal database is caught" "SELECT public.users"
as app portal -c "REVOKE SELECT ON users FROM $SR" >/dev/null
as postgres postgres -c "ALTER ROLE $SR CREATEDB" >/dev/null
check_fails "an extra role attribute is caught" "CREATEDB"
as postgres postgres -c "ALTER ROLE $SR NOCREATEDB" >/dev/null
as postgres postgres -c "GRANT other TO $SR" >/dev/null
check_fails "membership in another role is caught" "member of other"
as postgres postgres -c "REVOKE other FROM $SR" >/dev/null
as ldr vec -c "ALTER DEFAULT PRIVILEGES FOR ROLE ldr REVOKE SELECT ON TABLES FROM $SR" >/dev/null
check_fails "missing default privileges (future cars) are caught" "no global default SELECT"
as ldr vec -c "ALTER DEFAULT PRIVILEGES FOR ROLE ldr GRANT SELECT ON TABLES TO $SR" >/dev/null
as postgres vec -c "CREATE TABLE car_a.hidden(i int)" >/dev/null     # not created by the loader role: no default privilege covers it
check_fails "a table the role cannot read is caught" "cannot SELECT car_a.hidden"
as postgres vec -c "DROP TABLE car_a.hidden" >/dev/null
as ldr vec -c "ALTER DEFAULT PRIVILEGES FOR ROLE ldr REVOKE SELECT ON TABLES FROM $SR; ALTER DEFAULT PRIVILEGES FOR ROLE ldr IN SCHEMA rag GRANT SELECT ON TABLES TO $SR" >/dev/null
check_fails "a per-schema default (not global) is not accepted" "no global default SELECT"
as ldr vec -c "ALTER DEFAULT PRIVILEGES FOR ROLE ldr IN SCHEMA rag REVOKE SELECT ON TABLES FROM $SR; ALTER DEFAULT PRIVILEGES FOR ROLE ldr GRANT SELECT ON TABLES TO $SR" >/dev/null
as postgres postgres -c "CREATE ROLE kgkgxstg LOGIN" >/dev/null     # differs from kgkg_stg only where '_' is a LIKE wildcard
as ldr vec -c "ALTER DEFAULT PRIVILEGES FOR ROLE ldr REVOKE SELECT ON TABLES FROM $SR; ALTER DEFAULT PRIVILEGES FOR ROLE ldr GRANT SELECT ON TABLES TO kgkgxstg" >/dev/null
check_fails "a look-alike role name does not satisfy the default-privilege check" "no global default SELECT"
as ldr vec -c "ALTER DEFAULT PRIVILEGES FOR ROLE ldr REVOKE SELECT ON TABLES FROM kgkgxstg; ALTER DEFAULT PRIVILEGES FOR ROLE ldr GRANT SELECT ON TABLES TO $SR" >/dev/null
as ldr vec -c "ALTER DEFAULT PRIVILEGES FOR ROLE ldr GRANT INSERT ON TABLES TO $SR" >/dev/null
check_fails "default privileges that would grant writes are caught" "default privileges would give the role INSERT"
as ldr vec -c "ALTER DEFAULT PRIVILEGES FOR ROLE ldr REVOKE INSERT ON TABLES FROM $SR" >/dev/null
as other other_db -c "GRANT SELECT ON secrets TO $SR" >/dev/null
check_fails "access to a third database is caught" "SELECT public.secrets"
as other other_db -c "REVOKE SELECT ON secrets FROM $SR" >/dev/null
out=$(check) && ok "the check passes again once everything is back" || no "check after restore" "$out"

echo "== setup is idempotent; --rotate changes the password"
bash "$HERE/staging_isolation.sh" setup >/dev/null 2>&1
[[ $(sed -n 's/^KG_STG_PG_PASSWORD=//p' "$ENVF") == "$PW" ]] && ok "re-running setup keeps the password" || no "setup changed the password"
bash "$HERE/staging_isolation.sh" setup --rotate >/dev/null 2>&1
[[ $(sed -n 's/^KG_STG_PG_PASSWORD=//p' "$ENVF") != "$PW" ]] && ok "--rotate writes a new password" || no "--rotate kept the password"

echo "== credentials file handling (stg_iso_load)"
load_case() {  # label  expected(0/1)  prod-role  [setup commands run first in a subshell]
  local label=$1 want=$2 prod=$3; shift 3
  ( eval "$*"; . "$HERE/staging_isolation.sh"; stg_iso_load "$prod" >/dev/null 2>&1 ); local rc=$?
  { [[ $want == 0 && $rc == 0 ]] || [[ $want == 1 && $rc != 0 ]]; } && ok "$label" || no "$label" "rc=$rc"
}
GOOD=$(cat "$ENVF")
load_case "a good file loads" 0 kgkg ":"
load_case "the production role is refused" 1 kgkg_stg ":"
load_case "a missing file is refused" 1 kgkg "KG_STG_ISOLATION_ENV=$T/none.env"
cp "$ENVF" "$T/wide.env"; chmod 644 "$T/wide.env"
load_case "a world-readable file is refused" 1 kgkg "KG_STG_ISOLATION_ENV=$T/wide.env"
printf 'KG_STG_PG_USER=kgkg_stg\nKG_STG_PG_PASSWORD=short\n' > "$T/short.env"; chmod 600 "$T/short.env"
load_case "a short password is refused" 1 kgkg "KG_STG_ISOLATION_ENV=$T/short.env"
printf 'KG_STG_PG_USER=bad;name\nKG_STG_PG_PASSWORD=%s\n' "$PW" > "$T/badname.env"; chmod 600 "$T/badname.env"
load_case "an odd role name is refused" 1 kgkg "KG_STG_ISOLATION_ENV=$T/badname.env"
: "$GOOD"

echo "== containers.sh: read-only warehouse mounts"
mounts() {  # prints the Database_warehouse/static_warehouse -v arguments be_args builds
  ( export KG_BE_DIR=/srv/be KG_SPOOL=$T/spool; [[ ${1:-} == ro ]] && export KG_STAGING_ISOLATED=1
    . "$HERE/../docker/containers.sh"; be_args "$T/db" "$T/logs" 2>/dev/null
    printf '%s\n' "${BE_ARGS[@]}" | grep -E 'Database_warehouse|static_warehouse|\.env\.prod' )
}
rw=$(mounts); ro=$(mounts ro)
[[ $(grep -c '^/srv/be/\(Database\|static\)_warehouse:/srv/be/\(Database\|static\)_warehouse$' <<<"$rw") == 2 ]] \
  && ok "production mounts stay read-write" || no "production mounts changed" "$rw"
[[ $(grep -c '_warehouse:.*:ro$' <<<"$ro") == 2 ]] && ok "staging mounts both warehouses :ro" || no "staging mounts" "$ro"
[[ $rw == *".env.prod:/srv/be/.env.prod:ro"* ]] && ok "production still mounts .env.prod" || no "production lost the .env.prod mount" "$rw"
[[ $ro != *".env.prod:/srv/be/.env.prod:ro"* ]] && ok "staging does not mount .env.prod" || no "staging mounts .env.prod" "$ro"

echo "== stg_iso_check_mounts (what Docker reports after the start)"
mkdir -p "$T/bin"
cat > "$T/bin/docker" <<'EOF'
#!/bin/sh
[ "$STUB_MODE" = fail ] && exit 1
printf '%s' "$STUB_MOUNTS"
EOF
chmod +x "$T/bin/docker"
mcheck() { ( PATH="$T/bin:$PATH" STUB_MODE="${3:-ok}" STUB_MOUNTS="$2"; export STUB_MODE STUB_MOUNTS; . "$HERE/staging_isolation.sh"; stg_iso_check_mounts "$1" /srv/be >/dev/null 2>&1 ); }
RO=$'/data/db true\n/srv/be/Database_warehouse false\n/srv/be/static_warehouse false\n'
mcheck c "$RO" && ok "both warehouses read-only: accepted" || no "read-only mounts rejected"
mcheck c $'/srv/be/Database_warehouse true\n/srv/be/static_warehouse false\n' && no "a writable Database_warehouse was accepted" || ok "a writable Database_warehouse is rejected"
mcheck c $'/srv/be/Database_warehouse false\n' && no "a missing static_warehouse mount was accepted" || ok "a missing mount is rejected"
mcheck c "$RO" fail && no "a failed docker inspect was accepted" || ok "a failed docker inspect is rejected (fail closed)"

echo "== deploy.sh wiring"
d=$HERE/deploy.sh
line() { grep -n "$1" "$d" | head -1 | cut -d: -f1; }
l_load=$(line 'stg_iso_load "\$PG_USER"'); l_check=$(line 'stg_iso_check \\'); l_clone=$(line 'STG_PG_USER=\$STG_ISO_USER pg_clone_staging')
l_export=$(line 'export KG_STAGING_ISOLATED=1'); l_unset=$(line 'unset KG_STAGING_ISOLATED'); l_run=$(line 'KG_SPOOL=\$STG_SPOOL KG_WARMUP=0 run_backend')
l_mounts=$(line 'stg_iso_check_mounts kgkg-stg-backend'); l_wait=$(line 'wait_healthy kgkg-stg-backend'); l_src=$(line '^\. "\$SELF_ROOT/ops/deploy/staging_isolation.sh"'); l_unsetenv=$(line '^unset KG_STG_ISOLATION_ENV')
bash -n "$d" && ok "deploy.sh parses" || no "deploy.sh does not parse"
[[ -n $l_load && -n $l_check && -n $l_clone && -n $l_export && -n $l_unset && -n $l_run ]] && ok "all the wiring is present" || no "wiring missing" "$l_load $l_check $l_clone $l_export $l_unset $l_run"
(( l_load < l_check && l_check < l_clone && l_clone < l_export && l_export < l_run && l_run < l_unset )) \
  && ok "order: load, check, clone, export, start containers, unset" || no "wrong order" "$l_load $l_check $l_clone $l_export $l_run $l_unset"
(( l_run < l_mounts && l_mounts < l_wait )) && ok "the mounts are confirmed after the backend starts and before it is trusted" || no "mounts check order" "$l_run $l_mounts $l_wait"
(( l_unsetenv < l_src )) && ok "test-hook variables are unset before the library is sourced" || no "KG_STG_* hooks reach the library" "$l_unsetenv $l_src"
grep -q 'refusing to start staging' "$d" && ok "an empty staging login stops the run" || no "no empty-login guard"
for v in RAG_PGVEC_DSN KG_CARDB_PG_DSN KG_CARDB_ADMIN_DSN; do grep -q "NOSEC=(.*-e $v=" "$d" && ok "staging blanks $v" || no "staging does not blank $v"; done
grep -q '^\. "\$SELF_ROOT/ops/deploy/staging_isolation.sh"' "$d" && ok "the library is sourced from the running tree, not from the commit under test" || no "library source line"
sed -n '/3\/5 STAGING/,/STAGING PASSED/p' "$d" | grep -v '^ *#' | grep -q -- '--env-file' && no "the staging step passes an env file by itself" || ok "the staging step adds no env file of its own (the production one comes in only through be_args, with the login overridden)"

echo
(( fails == 0 )) && echo "staging isolation: all checks passed" || { echo "staging isolation: $fails check(s) FAILED"; exit 1; }
