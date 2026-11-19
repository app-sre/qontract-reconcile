-- owner-role provision mode: a NOLOGIN group role owns all managed
-- objects, the login user is a rotating member of it. The password is
-- set on every run, including for an existing login: the vault
-- password is reused while it exists, so this is a no-op in steady
-- state and lets a retry converge after a lost vault write (password
-- rotation = new login user in the same role).
-- rendered values: {database} {database_literal} {username} {username_literal} {admin_user} {role} {role_literal}
--                  {schemas_csv} {access_list} {revoke_list}
-- the user password is passed as the psql variable db_user_password via -v
\set ON_ERROR_STOP on

-- create the database if it does not exist (no-op for the admin
-- default database) and only revoke public access for freshly
-- created databases (postgres 15 compliance)
SELECT NOT EXISTS (SELECT FROM pg_database WHERE datname = '{database_literal}') AS dam_db_new \gset
SELECT 'CREATE DATABASE "{database}"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{database_literal}');\gexec
\if :dam_db_new
REVOKE ALL ON DATABASE "{database}" FROM public;
\endif

-- switch to the target database: everything below (ownership
-- transfer, grants, default privileges) is database-local
\c "{database}"

-- 1. the owner role: NOLOGIN group role that owns everything.
--    A duplicate_object error is tolerated: two entries sharing this
--    role can run their first provisioning concurrently.
--    Everything from here to the COMMIT is one transaction: a failure
--    rolls back the user creation including its password, so a retry
--    converges with a freshly generated password.
BEGIN;

DO $$
BEGIN
    CREATE ROLE "{role}" NOLOGIN;
EXCEPTION WHEN duplicate_object OR unique_violation THEN
    NULL;
END $$;

-- 2. the login user. The password is set on every run: the vault
--    password is reused while it exists, and a password generated for
--    a retry (after a lost vault write) converges automatically.
SELECT 'CREATE ROLE "{username_ident_literal}"'
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{username_literal}');\gexec

ALTER ROLE "{username}" WITH LOGIN PASSWORD :'db_user_password' VALID UNTIL 'infinity';

-- 3. role wiring: memberships and the session default that makes new
--    connections of the login user act as the owner role, so objects
--    created by the app are owned by the group role
DO $$
DECLARE
    role_name text := '{role_literal}';
    user_name text := '{username_literal}';
    db text := '{database_literal}';
    set_opt text := CASE WHEN current_setting('server_version_num')::int >= 160000
                         THEN ' WITH INHERIT TRUE, SET TRUE' ELSE '' END;
BEGIN
    -- the executor must be able to SET ROLE to the owner role for
    -- every ownership transfer below. NOTE (PG16+): the automatic
    -- grant a role gets when creating another role has ADMIN but
    -- neither INHERIT nor SET, so checking for membership alone is
    -- not enough here.
    IF NOT pg_has_role(current_user, role_name, 'USAGE') THEN
        EXECUTE format('GRANT %I TO %I%s', role_name, current_user, set_opt);
    END IF;
    -- the executor must control the login user to transfer objects of
    -- a previously managed user and to set its role default
    IF NOT pg_has_role(current_user, user_name, 'USAGE') THEN
        EXECUTE format('GRANT %I TO %I%s', user_name, current_user, set_opt);
    END IF;
    -- the login user becomes a member of the owner role
    EXECUTE format('GRANT %I TO %I%s', role_name, user_name, set_opt);
    -- new sessions of the login user act as the owner role
    BEGIN
        EXECUTE format('ALTER ROLE %I IN DATABASE %I SET role = %I',
                       user_name, db, role_name);
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'cannot set the role default for % -- run manually: ALTER ROLE % IN DATABASE % SET role = %;',
            user_name, user_name, db, role_name;
    END;
END $$;

-- 5. ownership transfer, grants and default privileges
DO $$
DECLARE
    role_name text := '{role_literal}';
    user_name text := '{username_literal}';
    schemas text[] := string_to_array('{schemas_csv}', ',');
    entry text;
    s text;
    g text;
    check_privs text;
    r RECORD;
BEGIN
    ------------------------------------------------------------------
    -- 5a. schema ownership: only schemas the executor controls,
    --     skipping already transferred ones. Grants back to the
    --     executor keep the old app (master user) working during the
    --     migration window.
    ------------------------------------------------------------------
    FOR r IN
        SELECT n.nspname AS schema_name
        FROM pg_namespace n
        WHERE n.nspname = ANY (schemas)
          AND n.nspowner <> role_name::regrole
          AND pg_has_role(current_user, n.nspowner, 'USAGE')
    LOOP
        EXECUTE format('ALTER SCHEMA %I OWNER TO %I', r.schema_name, role_name);
        EXECUTE format('GRANT ALL PRIVILEGES ON SCHEMA %I TO %I',
                       r.schema_name, current_user);
    END LOOP;

    ------------------------------------------------------------------
    -- 5a-bis. for schemas that could not be transferred (e.g. public
    --     in the postgres database, owned by pg_database_owner on
    --     PG15+), grant the owner role sufficient privileges to
    --     receive table ownership. Without CREATE on the schema,
    --     ALTER TABLE ... OWNER TO fails on PG16+.
    ------------------------------------------------------------------
    FOR r IN
        SELECT n.nspname AS schema_name
        FROM pg_namespace n
        WHERE n.nspname = ANY (schemas)
          AND n.nspowner <> role_name::regrole
    LOOP
        BEGIN
            EXECUTE format('GRANT USAGE, CREATE ON SCHEMA %I TO %I',
                           r.schema_name, role_name);
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'cannot grant USAGE+CREATE on schema % to % (executor has no grant option)',
                r.schema_name, role_name;
        END;
    END LOOP;

    ------------------------------------------------------------------
    -- 5b. relations: tables, partitioned tables, partitions, views,
    --     materialized views, foreign tables (indexes follow their
    --     table). Owned by the executor or a role it controls,
    --     skipping extension members and already transferred objects.
    ------------------------------------------------------------------
    FOR r IN
        SELECT n.nspname AS schema_name,
               c.relname AS obj_name,
               CASE c.relkind
                   WHEN 'r' THEN 'TABLE'
                   WHEN 'p' THEN 'TABLE'
                   WHEN 'v' THEN 'VIEW'
                   WHEN 'm' THEN 'MATERIALIZED VIEW'
                   WHEN 'f' THEN 'FOREIGN TABLE'
               END AS obj_type
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY (schemas)
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND c.relowner <> role_name::regrole
          AND pg_has_role(current_user, c.relowner, 'USAGE')
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.classid = 'pg_class'::regclass
                AND d.objid = c.oid AND d.deptype = 'e')
    LOOP
        EXECUTE format('ALTER %s %I.%I OWNER TO %I',
                       r.obj_type, r.schema_name, r.obj_name, role_name);
    END LOOP;

    ------------------------------------------------------------------
    -- 5c. sequences
    ------------------------------------------------------------------
    FOR r IN
        SELECT n.nspname AS schema_name, c.relname AS obj_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY (schemas)
          AND c.relkind = 'S'
          AND c.relowner <> role_name::regrole
          AND pg_has_role(current_user, c.relowner, 'USAGE')
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.classid = 'pg_class'::regclass
                AND d.objid = c.oid AND d.deptype = 'e')
    LOOP
        EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO %I',
                       r.schema_name, r.obj_name, role_name);
    END LOOP;

    ------------------------------------------------------------------
    -- 5d. statistics objects (CREATE STATISTICS)
    ------------------------------------------------------------------
    FOR r IN
        SELECT n.nspname AS schema_name, s.stxname AS obj_name
        FROM pg_statistic_ext s
        JOIN pg_namespace n ON n.oid = s.stxnamespace
        WHERE n.nspname = ANY (schemas)
          AND s.stxowner <> role_name::regrole
          AND pg_has_role(current_user, s.stxowner, 'USAGE')
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.classid = 'pg_statistic_ext'::regclass
                AND d.objid = s.oid AND d.deptype = 'e')
    LOOP
        EXECUTE format('ALTER STATISTICS %I.%I OWNER TO %I',
                       r.schema_name, r.obj_name, role_name);
    END LOOP;

    ------------------------------------------------------------------
    -- 5e. functions, procedures, aggregates
    --     (exact signature via pg_get_function_identity_arguments,
    --      extension members are skipped)
    ------------------------------------------------------------------
    FOR r IN
        SELECT n.nspname AS schema_name,
               p.proname AS obj_name,
               pg_get_function_identity_arguments(p.oid) AS obj_args,
               CASE p.prokind
                   WHEN 'p' THEN 'PROCEDURE'
                   WHEN 'a' THEN 'AGGREGATE'
                   ELSE 'FUNCTION'
               END AS obj_type
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY (schemas)
          AND p.proowner <> role_name::regrole
          AND pg_has_role(current_user, p.proowner, 'USAGE')
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.classid = 'pg_proc'::regclass
                AND d.objid = p.oid AND d.deptype = 'e')
    LOOP
        EXECUTE format('ALTER %s %I.%I(%s) OWNER TO %I',
                       r.obj_type, r.schema_name, r.obj_name, r.obj_args,
                       role_name);
    END LOOP;

    ------------------------------------------------------------------
    -- 5f. types (enums, composite) and domains
    --     (table row-types are skipped, extension types are skipped)
    ------------------------------------------------------------------
    FOR r IN
        SELECT n.nspname AS schema_name,
               t.typname AS obj_name,
               CASE t.typtype WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END AS obj_type
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = ANY (schemas)
          AND t.typtype IN ('c', 'e', 'd', 'r')
          AND t.typowner <> role_name::regrole
          AND pg_has_role(current_user, t.typowner, 'USAGE')
          AND NOT EXISTS (
              SELECT 1 FROM pg_class c
              WHERE c.reltype = t.oid AND c.relkind IN ('r', 'p', 'v', 'm', 'f'))
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.classid = 'pg_type'::regclass
                AND d.objid = t.oid AND d.deptype = 'e')
    LOOP
        EXECUTE format('ALTER %s %I.%I OWNER TO %I',
                       r.obj_type, r.schema_name, r.obj_name, role_name);
    END LOOP;

    ------------------------------------------------------------------
    -- 5g. safety-net grants for the owner role on everything the
    --     executor controls but could not transfer (e.g. objects
    --     owned by third-party roles where the executor is a member)
    ------------------------------------------------------------------
    FOR r IN
        SELECT n.nspname AS schema_name, c.relname AS obj_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY (schemas)
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
          AND c.relowner <> role_name::regrole
          AND pg_has_role(current_user, c.relowner, 'USAGE')
    LOOP
        EXECUTE format('GRANT ALL PRIVILEGES ON %I.%I TO %I',
                       r.schema_name, r.obj_name, role_name);
    END LOOP;

    FOR r IN
        SELECT n.nspname AS schema_name,
               p.proname AS obj_name,
               pg_get_function_identity_arguments(p.oid) AS obj_args
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY (schemas)
          AND p.proowner <> role_name::regrole
          AND pg_has_role(current_user, p.proowner, 'USAGE')
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.classid = 'pg_proc'::regclass
                AND d.objid = p.oid AND d.deptype = 'e')
    LOOP
        EXECUTE format('GRANT ALL PRIVILEGES ON ROUTINE %I.%I(%s) TO %I',
                       r.schema_name, r.obj_name, r.obj_args, role_name);
    END LOOP;

    ------------------------------------------------------------------
    -- 5h. configured grants and revokes for the owner role. On
    --     schemas the role owns these are redundant (membership
    --     includes all privileges), on schemas owned by other roles
    --     they provide cross-schema access. Such schemas also need
    --     USAGE on the schema itself: PostgreSQL denies access to
    --     objects in a schema the role has no USAGE on, regardless of
    --     object privileges.
    ------------------------------------------------------------------
    FOREACH entry IN ARRAY string_to_array('{revoke_list}', ';') LOOP
        IF entry <> '' THEN
            s := split_part(entry, '|', 1);
            -- skip revokes for schemas that do not exist (e.g. from
            -- a stale pending configuration)
            IF EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = s) THEN
                -- revoke from the owner role and from the login itself:
                -- a login migrated from legacy mode keeps its direct
                -- grants, which the session role default does not remove
                EXECUTE format('REVOKE %s ON ALL TABLES IN SCHEMA %I FROM %I',
                               split_part(entry, '|', 2), s, role_name);
                EXECUTE format('REVOKE %s ON ALL TABLES IN SCHEMA %I FROM %I',
                               split_part(entry, '|', 2), s, user_name);
                IF NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_namespace ns
                    JOIN pg_catalog.pg_roles ro ON ro.oid = ns.nspowner
                    WHERE ns.nspname = s AND ro.rolname = role_name
                ) THEN
                    EXECUTE format('REVOKE USAGE ON SCHEMA %I FROM %I',
                                   s, role_name);
                    EXECUTE format('REVOKE USAGE ON SCHEMA %I FROM %I',
                                   s, user_name);
                END IF;
            END IF;
        END IF;
    END LOOP;

    FOREACH entry IN ARRAY string_to_array('{access_list}', ';') LOOP
        IF entry <> '' THEN
            s := split_part(entry, '|', 1);
            EXECUTE format('GRANT %s ON ALL TABLES IN SCHEMA %I TO %I',
                           split_part(entry, '|', 2), s, role_name);
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_namespace ns
                JOIN pg_catalog.pg_roles ro ON ro.oid = ns.nspowner
                WHERE ns.nspname = s AND ro.rolname = role_name
            ) THEN
                EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I',
                               s, role_name);
                -- a grant without grant option only produces a warning
                -- and grants nothing. Without this check the
                -- transaction would commit while the owner role cannot
                -- reach the schema's objects at all.
                IF NOT has_schema_privilege(role_name, s, 'USAGE') THEN
                    RAISE EXCEPTION 'owner role % has no USAGE on schema %',
                        role_name, s;
                END IF;
            END IF;
            -- the same warning-without-error behavior applies to the
            -- table grants themselves: verify the requested privileges
            -- on every table in scope, on owned and foreign schemas
            -- alike. An empty schema passes, there is nothing to check.
            -- Each privilege is checked individually:
            -- has_table_privilege with a comma separated list returns
            -- true when ANY privilege is present.
            IF split_part(entry, '|', 2) = 'ALL' THEN
                check_privs := 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER';
                IF current_setting('server_version_num')::int >= 170000 THEN
                    check_privs := check_privs || ',MAINTAIN';
                END IF;
            ELSE
                check_privs := split_part(entry, '|', 2);
            END IF;
            FOR r IN
                SELECT c.relname AS obj_name
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace ns ON ns.oid = c.relnamespace
                WHERE ns.nspname = s
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
            LOOP
                FOREACH g IN ARRAY string_to_array(check_privs, ',') LOOP
                    IF NOT has_table_privilege(
                           role_name,
                           quote_ident(s) || '.' || quote_ident(r.obj_name),
                           g) THEN
                        RAISE EXCEPTION 'owner role % lacks % on %.%',
                            role_name, g, s, r.obj_name;
                    END IF;
                END LOOP;
            END LOOP;
        END IF;
    END LOOP;

    ------------------------------------------------------------------
    -- 5i. default privileges in BOTH directions for the migration
    --     window:
    --     * objects created by the executor (old app still running)
    --       are usable by the owner role -- and therefore by all its
    --       members
    --     * objects created by the owner role (new app sessions act
    --       as it) remain usable by the executor
    ------------------------------------------------------------------
    FOREACH s IN ARRAY schemas LOOP
        IF s = '' THEN
            CONTINUE;
        END IF;
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL PRIVILEGES ON TABLES TO %I',
            current_user, s, role_name);
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL PRIVILEGES ON SEQUENCES TO %I',
            current_user, s, role_name);
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL PRIVILEGES ON ROUTINES TO %I',
            current_user, s, role_name);

        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL PRIVILEGES ON TABLES TO %I',
            role_name, s, current_user);
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL PRIVILEGES ON SEQUENCES TO %I',
            role_name, s, current_user);
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL PRIVILEGES ON ROUTINES TO %I',
            role_name, s, current_user);
    END LOOP;
END $$;

COMMIT;

-- 4. database ownership: only when the executor controls the current
--    owner. On some managed services the default database is owned by
--    a service role and cannot be transferred; the app works without
--    database ownership. Must stay outside the transaction: ALTER
--    DATABASE cannot run in a transaction block.
SELECT format('ALTER DATABASE %I OWNER TO %I', '{database_literal}', '{role_literal}')
FROM pg_database
WHERE datname = '{database_literal}'
  AND pg_has_role(current_user, datdba, 'USAGE');\gexec
