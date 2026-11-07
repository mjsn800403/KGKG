#!/usr/bin/env bash
# Staging isolation (risk R5): the staging containers use their OWN PostgreSQL login,
# which can read the vector database and can write only the staging copy.
#
#   source ops/deploy/staging_isolation.sh        # deploy.sh does this, from the live tree
#   ops/deploy/staging_isolation.sh setup         # once, as root on the server (creates the role); run it from the
#                                                 # commit you will promote, extracted with `git archive` (README)
#   ops/deploy/staging_isolation.sh check         # read-only: is the role as narrow as it must be?
#
# deploy.sh --staging calls stg_iso_load + stg_iso_check and REFUSES to start staging when
# either fails: a missing or too-wide role stops the run instead of quietly falling back to
# the production login. Nothing here runs against production on its own; `setup` is the only
# part that changes the database, and only an operator starts it.
#
# Settings (all optional; the defaults are the production host):
#   KG_STG_ISOLATION_ENV  credentials file, root-only            /opt/KGKG_staging/isolation.env
#   KG_STG_PG_ROLE        role name `setup` creates              kgkg_stg
#   KG_STG_VEC_DB         the vector database                    kgkg_vec
#   KG_STG_LOADER_ROLE    role that creates car schemas          root
#   KG_STG_PSQL           psql command for the read-only checks  "psql -X -At"
#   KG_STG_PSQL_ADMIN     psql command for `setup` (superuser)   "psql -X -At"
# shellcheck shell=bash

STG_ISO_ENV=${KG_STG_ISOLATION_ENV:-/opt/KGKG_staging/isolation.env}
STG_ISO_ROLE_DEFAULT=${KG_STG_PG_ROLE:-kgkg_stg}
STG_ISO_VEC_DB=${KG_STG_VEC_DB:-kgkg_vec}
STG_ISO_LOADER=${KG_STG_LOADER_ROLE:-root}
STG_ISO_USER=
STG_ISO_PASSWORD=

_stg_iso_here() { cd "$(dirname "${BASH_SOURCE[0]}")" && pwd; }

# One key from the credentials file. The file is parsed, never sourced.
_stg_iso_conf() { sed -n "s/^$1=//p" "$STG_ISO_ENV" 2>/dev/null | tail -1 | tr -d "\"' "; }

# stg_iso_load [production-role]  -> sets STG_ISO_USER / STG_ISO_PASSWORD, or explains and fails.
stg_iso_load() {
  local prod_role=${1:-} mode owner
  STG_ISO_USER=; STG_ISO_PASSWORD=
  if [[ ! -f $STG_ISO_ENV ]]; then
    echo "staging isolation is not set up: $STG_ISO_ENV is missing." >&2
    echo "  Create the read-only staging role once with the script from the commit being promoted (it is not in /opt/KGKG until that promote): see 'Staging isolation' in ops/deploy/README.md" >&2
    return 1
  fi
  mode=$(stat -c %a "$STG_ISO_ENV" 2>/dev/null || stat -f %Lp "$STG_ISO_ENV")
  owner=$(stat -c %u "$STG_ISO_ENV" 2>/dev/null || stat -f %u "$STG_ISO_ENV")
  if [[ $mode != 600 && $mode != 400 ]] || [[ $owner != "$(id -u)" ]]; then
    echo "$STG_ISO_ENV must be owned by the user running the deploy and mode 600 (is $owner/$mode)" >&2
    return 1
  fi
  STG_ISO_USER=$(_stg_iso_conf KG_STG_PG_USER)
  STG_ISO_PASSWORD=$(_stg_iso_conf KG_STG_PG_PASSWORD)
  if ! [[ $STG_ISO_USER =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
    echo "KG_STG_PG_USER in $STG_ISO_ENV is missing or not a plain role name" >&2; return 1
  fi
  if (( ${#STG_ISO_PASSWORD} < 24 )); then
    echo "KG_STG_PG_PASSWORD in $STG_ISO_ENV is missing or shorter than 24 characters" >&2; return 1
  fi
  if [[ -n $prod_role && $STG_ISO_USER == "$prod_role" ]]; then
    echo "KG_STG_PG_USER is the production role ($prod_role): that is the problem this setup removes" >&2; return 1
  fi
  return 0
}

# stg_iso_check  -> 0 when the role is as narrow as it must be; prints every violation and returns 1 otherwise.
# Only reads the catalogs (has_*_privilege, pg_roles, pg_class); it writes nothing anywhere.
stg_iso_check() {
  local out="" part psql_cmd
  # shellcheck disable=SC2206  # a command with arguments, split on purpose
  psql_cmd=(${KG_STG_PSQL:-psql -X -At})
  [[ -n $STG_ISO_USER ]] || { echo "stg_iso_check: run stg_iso_load first" >&2; return 1; }

  # shellcheck disable=SC2016  # :'r' is psql syntax, not a shell expansion
  part=$("${psql_cmd[@]}" -v ON_ERROR_STOP=1 -v r="$STG_ISO_USER" -v loader="$STG_ISO_LOADER" -d "$STG_ISO_VEC_DB" -f - 2>&1 <<'SQL'
select 'role does not exist' where not exists (select 1 from pg_roles where rolname = :'r')
union all select 'role has attribute ' || a from pg_roles, lateral (values
    (case when rolsuper then 'SUPERUSER' end), (case when rolcreatedb then 'CREATEDB' end),
    (case when rolcreaterole then 'CREATEROLE' end), (case when rolreplication then 'REPLICATION' end),
    (case when rolbypassrls then 'BYPASSRLS' end)) v(a)
  where rolname = :'r' and a is not null
union all select 'role is a member of ' || pg_get_userbyid(roleid) from pg_auth_members
  where member = (select oid from pg_roles where rolname = :'r')
union all select 'role can CREATE in database ' || current_database()
  where exists (select 1 from pg_roles where rolname = :'r') and has_database_privilege(:'r', current_database(), 'CREATE')
union all select 'role can CREATE in schema ' || nspname from pg_namespace
  where exists (select 1 from pg_roles where rolname = :'r') and nspname !~ '^(pg_|information_schema$)'
    and has_schema_privilege(:'r', oid, 'CREATE')
union all select 'role cannot USE schema ' || nspname from pg_namespace
  where exists (select 1 from pg_roles where rolname = :'r') and nspname !~ '^(pg_|information_schema$)'
    and not has_schema_privilege(:'r', oid, 'USAGE')
union all (select 'role can ' || p || ' ' || n.nspname || '.' || c.relname
  from pg_class c join pg_namespace n on n.oid = c.relnamespace,
       unnest(array['INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p
  where exists (select 1 from pg_roles where rolname = :'r') and c.relkind in ('r','p','v','m','f')
    and n.nspname !~ '^(pg_|information_schema$)' and has_table_privilege(:'r', c.oid, p) limit 5)
union all (select 'role cannot SELECT ' || n.nspname || '.' || c.relname
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
  where exists (select 1 from pg_roles where rolname = :'r') and c.relkind in ('r','p','v','m','f')
    and n.nspname !~ '^(pg_|information_schema$)' and not has_table_privilege(:'r', c.oid, 'SELECT') limit 5)
union all select 'role owns objects in ' || current_database() from pg_roles r
  where r.rolname = :'r' and (exists (select 1 from pg_class where relowner = r.oid)
                              or exists (select 1 from pg_namespace where nspowner = r.oid))
union all select 'no global default SELECT on tables created by ' || :'loader' || ': new car tables would not be readable'
  where not exists (select 1 from pg_default_acl a, lateral aclexplode(a.defaclacl) x
                     where a.defaclrole = (select oid from pg_roles where rolname = :'loader') and a.defaclnamespace = 0
                       and a.defaclobjtype = 'r' and x.grantee = (select oid from pg_roles where rolname = :'r')
                       and x.privilege_type = 'SELECT')
union all select 'no global default USAGE on schemas created by ' || :'loader' || ': new car schemas would not be readable'
  where not exists (select 1 from pg_default_acl a, lateral aclexplode(a.defaclacl) x
                     where a.defaclrole = (select oid from pg_roles where rolname = :'loader') and a.defaclnamespace = 0
                       and a.defaclobjtype = 'n' and x.grantee = (select oid from pg_roles where rolname = :'r')
                       and x.privilege_type = 'USAGE')
union all select 'default privileges would give the role ' || x.privilege_type || ' on future ' || a.defaclobjtype::text || ' objects'
  from pg_default_acl a, lateral aclexplode(a.defaclacl) x
  where x.grantee = (select oid from pg_roles where rolname = :'r')
    and ((a.defaclobjtype = 'r' and x.privilege_type <> 'SELECT') or (a.defaclobjtype = 'n' and x.privilege_type <> 'USAGE')
         or a.defaclobjtype not in ('r', 'n'));
SQL
  ) || { echo "isolation check could not query $STG_ISO_VEC_DB: $part" >&2; return 1; }
  [[ -z $part ]] || out+="[$STG_ISO_VEC_DB]"$'\n'"$part"$'\n'

  # Every OTHER connectable database (the portal database, the QA/trial copies, the gate database ...):
  # PUBLIC may CONNECT to all of them, so the role must hold no privilege inside any it does not own.
  local db dbs
  dbs=$("${psql_cmd[@]}" -v ON_ERROR_STOP=1 -d postgres -c \
        "select datname from pg_database where datallowconn and not datistemplate and datname <> '$STG_ISO_VEC_DB' and pg_get_userbyid(datdba) <> '$STG_ISO_USER' order by 1" 2>&1) \
    || { echo "isolation check could not list the databases: $dbs" >&2; return 1; }
  for db in $dbs; do
    # shellcheck disable=SC2016
    part=$("${psql_cmd[@]}" -v ON_ERROR_STOP=1 -v r="$STG_ISO_USER" -d "$db" -f - 2>&1 <<'SQL'
select 'role can ' || p || ' ' || n.nspname || '.' || c.relname
  from pg_class c join pg_namespace n on n.oid = c.relnamespace,
       unnest(array['SELECT','INSERT','UPDATE','DELETE','TRUNCATE']) p
  where c.relkind in ('r','p','v','m','f') and n.nspname !~ '^(pg_|information_schema$)'
    and has_table_privilege(:'r', c.oid, p)
union all select 'role can CREATE in schema ' || nspname from pg_namespace
  where nspname !~ '^(pg_|information_schema$)' and has_schema_privilege(:'r', oid, 'CREATE')
union all select 'role can CREATE in database ' || current_database()
  where has_database_privilege(:'r', current_database(), 'CREATE')
limit 10;
SQL
    ) || { echo "isolation check could not query $db: $part" >&2; return 1; }
    [[ -z $part ]] || out+="[$db]"$'\n'"$part"$'\n'
  done

  if [[ -n $out ]]; then
    echo "staging role $STG_ISO_USER is NOT isolated:" >&2
    printf '%s' "$out" | sed 's/^/  /' >&2
    return 1
  fi
  return 0
}

# stg_iso_check_mounts <container> <warehouse-base-dir>  -> 0 only if both warehouse mounts of the RUNNING container are read-only.
# Asks Docker what it actually did, so it holds even if the commit under test changed how the mounts are built.
stg_iso_check_mounts() {
  local container=$1 base=$2 mounts
  mounts=$(docker inspect -f '{{range .Mounts}}{{.Destination}} {{.RW}}{{"\n"}}{{end}}' "$container" 2>/dev/null) || {
    echo "cannot inspect $container" >&2; return 1; }
  awk -v a="$base/Database_warehouse" -v b="$base/static_warehouse" '
    $1 == a || $1 == b { n++; if ($2 != "false") bad = 1 }
    END { exit !(n == 2 && !bad) }' <<<"$mounts" || {
    echo "the staging container does not have both warehouses mounted read-only:" >&2
    sed 's/^/  /' <<<"$mounts" >&2; return 1; }
}

# stg_iso_setup [--rotate]  -> creates/updates the role (ops/deploy/staging_role.sql) and the credentials file.
# The password goes to psql on stdin and into the 0600 file, never onto a command line.
stg_iso_setup() {
  local rotate=0 here role pw="" tmp admin   # pw="": `local pw` leaves it UNSET in bash >= 4.4, and ${#pw} below fails under set -u
  [[ ${1:-} == --rotate ]] && rotate=1
  here=$(_stg_iso_here); role=$STG_ISO_ROLE_DEFAULT
  # shellcheck disable=SC2206
  admin=(${KG_STG_PSQL_ADMIN:-psql -X -At})
  if [[ -f $STG_ISO_ENV && $rotate == 0 ]]; then
    pw=$(_stg_iso_conf KG_STG_PG_PASSWORD); role=$(_stg_iso_conf KG_STG_PG_USER)
  fi
  if (( ${#pw} < 24 )); then pw=$(openssl rand -hex 24); fi
  { printf "\\\\set stg_pw '%s'\n" "$pw"; cat "$here/staging_role.sql"; } \
    | "${admin[@]}" -d postgres -v ON_ERROR_STOP=1 -v stg_role="$role" -v loader_role="$STG_ISO_LOADER" \
        -v vec_db="$STG_ISO_VEC_DB" -f - || { echo "staging role setup failed; the credentials file was not written" >&2; return 1; }
  tmp=$(umask 077; mktemp "$(dirname "$STG_ISO_ENV")/.isolation.XXXXXX")
  printf 'KG_STG_PG_USER=%s\nKG_STG_PG_PASSWORD=%s\n' "$role" "$pw" > "$tmp"
  chmod 600 "$tmp" && mv -f "$tmp" "$STG_ISO_ENV"
  echo "wrote $STG_ISO_ENV (role $role)"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  set -uo pipefail
  case ${1:-} in
    setup) shift; stg_iso_setup "$@"; rc=$? ; (( rc )) && exit "$rc"
           stg_iso_load && stg_iso_check && echo "staging isolation check: OK" ;;
    check) stg_iso_load "${KG_STG_PROD_ROLE:-}" && stg_iso_check && echo "staging isolation check: OK" ;;
    *)     echo "usage: $0 setup [--rotate] | check" >&2; exit 2 ;;
  esac
fi
