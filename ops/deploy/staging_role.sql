-- Least-privilege PostgreSQL role for the STAGING containers (risk R5).
--
-- Before this, the staging backend ran with the production login (--env-file
-- .env.prod): the owner of the production portal database and a reader of the
-- vector database kgkg_vec. This role is what staging uses instead:
--
--   * kgkg_vec          SELECT on every table, USAGE on every schema -- and nothing else.
--                       No CREATE on the database or any schema, no write on any table.
--                       Schemas and tables the loaders (role :loader_role) create LATER are
--                       readable too, through default privileges, so a new car needs no re-run.
--   * the portal DB     no table privileges at all (the role may CONNECT, as PUBLIC can,
--                       but every production table is owned by the app role with no PUBLIC grant).
--   * <name>_staging    created by deploy.sh with this role as OWNER, so migrations, the QA
--                       token and the smoke tests write there and only there.
--
-- Idempotent; safe to re-run after every new car (it is not needed for that) or to rotate
-- the password. Run on the server as a superuser (the `postgres` OS user or root):
--
--   psql -X -v ON_ERROR_STOP=1 -v stg_role=kgkg_stg -v loader_role=root -v vec_db=kgkg_vec \
--        -v stg_pw="$PASSWORD" -f ops/deploy/staging_role.sql
--
-- `ops/deploy/staging_isolation.sh setup` does exactly this and writes the credentials file
-- deploy.sh reads. Undo: see "Rollback" in ops/deploy/README.md.
\set ON_ERROR_STOP on
\if :{?stg_role} \else \set stg_role kgkg_stg \endif
\if :{?loader_role} \else \set loader_role root \endif
\if :{?vec_db} \else \set vec_db kgkg_vec \endif
\if :{?stg_pw} \else \set stg_pw '' \endif

-- 0. The password is sent as a statement: keep it out of the server log, also if the statement fails.
SET log_statement = 'none';
SET log_min_error_statement = 'panic';

-- 1. The role: login only, no attribute that could reach beyond its own database.
SELECT format('CREATE ROLE %I LOGIN', :'stg_role')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'stg_role') \gexec
SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 40',
              :'stg_role') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'stg_role', :'stg_pw')
 WHERE :'stg_pw' <> '' \gexec

-- 2. kgkg_vec: read only.
\connect :"vec_db"

SELECT format('REVOKE CREATE ON DATABASE %I FROM %I', :'vec_db', :'stg_role') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'vec_db', :'stg_role') \gexec

-- Every user schema that exists now (public, rag, the car_* schemas).
SELECT format('REVOKE CREATE ON SCHEMA %I FROM %I', nspname, :'stg_role')
  FROM pg_namespace WHERE nspname !~ '^(pg_|information_schema$)' \gexec
SELECT format('GRANT USAGE ON SCHEMA %I TO %I', nspname, :'stg_role')
  FROM pg_namespace WHERE nspname !~ '^(pg_|information_schema$)' \gexec
SELECT format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA %I FROM %I',
              nspname, :'stg_role')
  FROM pg_namespace WHERE nspname !~ '^(pg_|information_schema$)' \gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I', nspname, :'stg_role')
  FROM pg_namespace WHERE nspname !~ '^(pg_|information_schema$)' \gexec

-- Whatever the loaders create from now on (cardb_pg.load_sqlite grants the app role the
-- same way, per schema; this does it for the staging role without a code change).
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I GRANT USAGE ON SCHEMAS TO %I', :'loader_role', :'stg_role') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I GRANT SELECT ON TABLES TO %I', :'loader_role', :'stg_role') \gexec

-- 3. Show the result (the checks in staging_isolation.sh are the enforcing version of this).
SELECT format('%s: SELECT on %s tables, write privileges on %s, CREATE on database %s',
              :'stg_role',
              count(*) FILTER (WHERE has_table_privilege(:'stg_role', c.oid, 'SELECT')),
              count(*) FILTER (WHERE has_table_privilege(:'stg_role', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')),
              has_database_privilege(:'stg_role', :'vec_db', 'CREATE'))
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind IN ('r','p','v','m','f') AND n.nspname !~ '^(pg_|information_schema$)';
