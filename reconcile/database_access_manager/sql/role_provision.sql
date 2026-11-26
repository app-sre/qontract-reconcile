-- owner-role provision mode: a NOLOGIN group role owns all managed
-- objects, the login user is a rotating member of it. The password is
-- set on every run, including for an existing login: the vault
-- password is reused while it exists, so this is a no-op in steady
-- state and lets a retry converge after a lost vault write (password
-- rotation = new login user in the same role).
-- rendered values: {database} {database_literal} {username} {username_literal} {admin_user} {role} {role_literal}
--                  {schemas_csv} {access_list} {revoke_list}
-- the user password is passed as the psql variable db_user_password via -v;
-- the PRE-TRANSACTION search-path capture (section 0) embeds it twice: as
-- the login's password pre-set (so the application-connection capture can
-- authenticate even while the password is being rotated) and, conninfo-
-- escaped, in that application-login connection itself
\set ON_ERROR_STOP on

-- create the database if it does not exist (no-op for the admin
-- default database) and only revoke public access for freshly
-- created databases (postgres 15 compliance)
SELECT NOT EXISTS (SELECT FROM pg_database WHERE datname = '{database_literal}') AS dam_db_new \gset
SELECT 'CREATE DATABASE "{database}"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{database_literal}');\gexec
\if :dam_db_new
/* revoke only CREATE for postgres 15 compliance (public cannot create
   objects in the database). CONNECT stays with PUBLIC: multiple
   managed roles on the same database need database access, and the
   owner change from ALTER DATABASE would otherwise lock them out. */
REVOKE CREATE ON DATABASE "{database}" FROM public;
\endif

-- remember the database this job started in (the admin database from
-- the connection secret): the ownership transfer at the end of the
-- script never applies to it
SELECT current_database() AS dam_admin_db \gset

-- switch to the target database: everything below (ownership
-- transfer, grants, default privileges) is database-local
\c "{database}"

-- the capture-ELIGIBILITY context, read before the transaction below
-- creates anything and carried as PSQL VARIABLES (\gset): the
-- PRE-TRANSACTION search-path capture in section 0 reconnects as the
-- application login and back BEFORE the transaction, and while
-- session GUCs die with their backend, psql variables survive every
-- \c hop. Two facts decide whether that capture may OBSERVE the
-- login's effective search path: whether the login already exists (a
-- pre-existing legacy tenant has session behavior worth preserving),
-- and whether a previous role-mode run already manages it (its
-- per-database role default proves it: a login DAM provisioned
-- carries one, a legacy login does not). The effective search_path
-- VALUE itself is no longer reconstructed from the catalogs here:
-- PostgreSQL itself resolves the complete precedence (the login's
-- per-database setting, its role-wide setting, the database-wide
-- setting, the server-wide value, the built-in "$user", public) when
-- the application login connects, and the capture observes exactly
-- that on a real connection of the login -- a value the executor's
-- own search_path can neither mask nor corrupt.
SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles
               WHERE rolname = '{username_literal}') AS dam_login_existed \gset
SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_db_role_setting s
               JOIN pg_catalog.pg_database d ON d.oid = s.setdatabase
               CROSS JOIN LATERAL unnest(s.setconfig) AS cfg
               WHERE s.setrole = (SELECT oid FROM pg_catalog.pg_roles
                                  WHERE rolname = '{username_literal}')
                 AND d.datname = '{database_literal}'
                 AND cfg LIKE 'role=%') AS dam_login_role_default \gset

-- 0. the search-path CAPTURE, deliberately BEFORE the transaction
--    below: the login's effective search path must be observed
--    before ANY permanent DAM change exists -- above all before the
--    role default of section 3. The previous placement (post-commit)
--    had a retry corner: a failed application connection aborted the
--    job AFTER the transaction had already made the role default
--    permanent, so the retry classified the login as already
--    role-managed, SKIPPED the capture and converged on the
--    configured order -- the same job reported SUCCESS while the
--    login's unqualified resolution silently flipped. Capturing
--    pre-transaction closes that corner: a failed capture connection
--    aborts the job with nothing persistent but the password pre-set
--    below, and a retry is still capture-eligible.
--
--    A capture run is one where the login pre-existed (a legacy
--    tenant has session behavior worth preserving), no earlier
--    role-mode run manages it (its per-database role default would
--    prove one -- re-capturing then would freeze DAM's own
--    previously written path as an untouchable prefix, so an
--    intentional order change could never apply), and the persistent
--    store is not initialized (a capture writes it).
SELECT (:'dam_login_existed'::boolean
        AND NOT :'dam_login_role_default'::boolean
        AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_db_role_setting rs
                        JOIN pg_catalog.pg_database d ON d.oid = rs.setdatabase
                        CROSS JOIN LATERAL unnest(rs.setconfig) AS cfg
                        WHERE rs.setrole = (SELECT oid FROM pg_catalog.pg_roles
                                            WHERE rolname = '{role_literal}')
                          AND d.datname = '{database_literal}'
                          AND cfg LIKE 'search_path=%')) AS dam_capture \gset
\if :dam_capture
-- the PASSWORD PRE-SET: the application-connection capture below
-- must authenticate as the login even when the password is being
-- rotated (no vault secret), so the job's password is set on the
-- login BEFORE the connection. It is idempotent when the vault
-- password is reused (the normal migration case: the legacy login
-- already carries it), and it needs exactly the privileges the
-- in-transaction password write of section 2 already requires (a
-- legacy-managed login carries the legacy template's grant to the
-- admin). Residual window, taken deliberately: a job abort after
-- this point leaves the DATABASE password ahead of the vault until
-- the next successful run -- the same staleness window the previous
-- post-commit failure mode had, and strictly better than a silent
-- resolution flip.
ALTER ROLE "{username}" PASSWORD :'db_user_password';
-- the two connection strings of the observation hop, built in SQL
-- so that every value is CONNINFO-ESCAPED (single-quoted, with
-- backslashes and single quotes backslash-escaped -- chr(92)/chr(39)
-- keep the template free of string-literal ambiguity): psql does
-- NOT interpolate :variables inside the double-quoted argument of a
-- \c command, but an UNQUOTED :dam_app_conninfo does interpolate,
-- as one conninfo argument. -reuse-previous=on keeps the host and
-- port of the current connection. The admin string is built while
-- still connected as the executor (current_user IS the executor);
-- the application string carries the password as the psql variable
-- db_user_password -- the very password the pre-set above just made
-- the login's own. The user change of each hop makes psql drop the
-- previous connection's password (the hop back as the executor
-- authenticates with the job's PGPASSWORD or the local trust
-- policy, never with the application password).
SELECT 'dbname=' ||
       chr(39) || replace(replace('{database_literal}', chr(92), chr(92) || chr(92)), chr(39), chr(92) || chr(39)) || chr(39) ||
       ' user=' ||
       chr(39) || replace(replace('{username_literal}', chr(92), chr(92) || chr(92)), chr(39), chr(92) || chr(39)) || chr(39) ||
       ' password=' ||
       chr(39) || replace(replace(:'db_user_password', chr(92), chr(92) || chr(92)), chr(39), chr(92) || chr(39)) || chr(39)
       AS dam_app_conninfo,
       'dbname=' ||
       chr(39) || replace(replace('{database_literal}', chr(92), chr(92) || chr(92)), chr(39), chr(92) || chr(39)) || chr(39) ||
       ' user=' ||
       chr(39) || replace(replace(current_user::text, chr(92), chr(92) || chr(92)), chr(39), chr(92) || chr(39)) || chr(39)
       AS dam_admin_conninfo \gset
\c -reuse-previous=on :dam_app_conninfo
-- the observation: PostgreSQL's own resolution of the login's
-- effective search_path, as a psql variable (it survives the hop
-- back; a session GUC would not). Nothing DAM writes exists yet:
-- this is the login's genuine pre-migration behavior.
SELECT current_setting('search_path') AS dam_observed_sp \gset
\c -reuse-previous=on :dam_admin_conninfo
-- hand the observation to the settlement block inside the
-- transaction below: a session GUC in THIS executor session (set
-- after every reconnect, so no hop can lose it, and read by the
-- settlement DO block on the same backend)
SELECT set_config('dam.observed_sp', :'dam_observed_sp', false);
\else
-- not a capture run (a fresh login, a login an earlier role-mode
-- run already manages, or a store that already governs the role):
-- no application connection and no password pre-set are needed, the
-- maintained path below is computed from the store or from the
-- configured order alone
\endif

-- 1. the owner role: NOLOGIN group role that owns everything.
--    A duplicate_object error is tolerated: two entries sharing this
--    role can run their first provisioning concurrently.
--    Everything from here to the COMMIT is one transaction: a failure
--    rolls back the user creation including its password, so a retry
--    converges with a freshly generated password. The search-path
--    settlement (section 6) is part of the SAME transaction: the
--    role default and the login's search path activate together or
--    not at all.
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
--    created by the app are owned by the group role. This block is
--    also the SINGLE derivation of the managed schema set (written
--    into the dam.managed_schemas session setting for section 5).
--    The search path is not OBSERVED here: the observation already
--    ran pre-transaction (section 0), before anything DAM writes
--    existed. The login/store writes of the settlement run later in
--    THIS transaction (section 6, after section 5): the role default
--    and the search path activate TOGETHER or not at all -- a
--    failure anywhere in the transaction rolls both back, so the
--    login never ends up role-defaulted without its preserved path.
DO $$
DECLARE
    role_name text := '{role_literal}';
    user_name text := '{username_literal}';
    db text := '{database_literal}';
    schemas_arr text[] := string_to_array('{schemas_csv}', ',');
    managed text[] := ARRAY[]::text[];
    own_schema boolean;
    set_opt text := CASE WHEN current_setting('server_version_num')::int >= 160000
                         THEN ' WITH INHERIT TRUE, SET TRUE' ELSE '' END;
    s text;
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

    -- the login's OWN schema (the ENTRY-SCOPED NAME RULE): a schema
    -- NAMED after this entry's login that exists and is owned by
    -- the login OR by the owner role -- exactly what legacy mode
    -- auto-creates next to its login (the one-time ownership
    -- takeover at migration), and the same schema after that
    -- takeover transferred it to the owner role. The legacy entry
    -- itself carries the memory: while the entry exists, its
    -- reconciliations keep managing its login's (transferred)
    -- schema, so late objects the still-open legacy session creates
    -- keep being adopted and rotation logins of the same role keep
    -- their resolution; once the entry is deleted, its login is
    -- dropped and can no longer create late objects, so management
    -- is no longer needed. Ownership of a login or role ALONE is
    -- NEVER evidence that a schema is managed or on the path: a
    -- schema the application created while acting as the owner
    -- role (role-owned from birth), or one that left the access
    -- list, is a leftover, not managed state.
    SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_namespace n
        WHERE n.nspname = user_name
          AND pg_get_userbyid(n.nspowner) IN (user_name, role_name)
    ) INTO own_schema;

    -- the managed schema set (single derivation, shared with section
    -- 5 through the dam.managed_schemas session setting): the
    -- configured access list plus the ENTRY-SCOPED NAME RULE above
    -- (the schema named after this entry's login while it exists and
    -- is owned by the login or the owner role). NO persistent
    -- memory, deliberately: the previous design read the owner
    -- role's pg_default_acl rows as "what DAM manages", but an
    -- ordinary PostgreSQL default privilege set BY THE APP (acting
    -- as the role) creates exactly the same catalog row without any
    -- DAM intent behind it -- on the next unchanged run an admin
    -- table in a never-configured (or already-removed) role-owned
    -- schema flipped to the app role. Ownership by the role alone
    -- proves nothing either (app-created schemas are role-owned from
    -- birth). The entry itself carries the memory instead: while
    -- the entry exists, its reconciliations keep managing its
    -- login's (transferred) schema -- late objects of a still-open
    -- legacy session keep being adopted, and rotation logins of the
    -- same role are covered because the LEGACY entry keeps
    -- reconciling while it exists; once the entry is deleted, its
    -- login is dropped and can no longer create late objects, so
    -- management is no longer needed. Bootstrap stays correct: the
    -- first run manages exactly the access list plus the name rule,
    -- and later runs of the same entry keep managing exactly that.
    FOREACH s IN ARRAY schemas_arr LOOP
        IF s <> '' AND NOT managed @> ARRAY[s] THEN
            managed := array_append(managed, s);
        END IF;
    END LOOP;
    IF own_schema AND NOT managed @> ARRAY[user_name] THEN
        managed := array_append(managed, user_name);
    END IF;
    PERFORM set_config('dam.managed_schemas', array_to_string(managed, ','), false);

    -- new sessions of the login user act as the owner role
    BEGIN
        EXECUTE format('ALTER ROLE %I IN DATABASE %I SET role = %I',
                       user_name, db, role_name);
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'cannot set the role default for % -- run manually: ALTER ROLE % IN DATABASE % SET role = %;',
            user_name, user_name, db, role_name;
    END;
    -- verify the login can actually connect: without CONNECT on the
    -- database, the credential would be published but rejected
    IF NOT has_database_privilege(user_name, db, 'CONNECT') THEN
        BEGIN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', db, user_name);
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE EXCEPTION 'login % has no CONNECT on database % and the executor cannot grant it',
                user_name, db;
        END;
        IF NOT has_database_privilege(user_name, db, 'CONNECT') THEN
            RAISE EXCEPTION 'login % has no CONNECT on database % after explicit grant',
                user_name, db;
        END IF;
    END IF;
END $$;

-- 5. ownership transfer, grants and default privileges
DO $$
DECLARE
    role_name text := '{role_literal}';
    user_name text := '{username_literal}';
    -- the managed schema set, computed ONCE by section 3 and read
    -- from the dam.managed_schemas session setting (plain names,
    -- comma-joined -- exactly the format section 3 writes): the
    -- configured schemas PLUS the entry-scoped name rule (the
    -- schema named after this entry's login while it exists and is
    -- owned by the login or the owner role -- exactly what legacy
    -- mode auto-creates next to its login; the one-time ownership
    -- takeover at migration, and the same schema after the
    -- takeover). NO default-ACL memory: an ordinary PostgreSQL
    -- default privilege the app set is not a management mandate,
    -- and ownership of a login or role alone is never evidence that
    -- a schema is managed -- role-owned leftovers (an app-created
    -- schema, a schema that left the access list) are not managed
    -- here.
    schemas text[] := COALESCE(
        string_to_array(NULLIF(current_setting('dam.managed_schemas', true), ''), ','),
        ARRAY[]::text[]);
    write_schemas text[] := ARRAY[]::text[];
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
    --     The CREATE privilege is TRANSIENT: it is needed for the
    --     ownership transfers below and revoked again in 5j, so a
    --     SELECT-only entry never keeps object-creation rights in a
    --     schema it does not own.
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
                    -- the transient CREATE grant (5a-bis) and the
                    -- default privileges (5i) must not outlive the
                    -- schema's membership in the access list
                    EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM %I',
                                   s, role_name);
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL PRIVILEGES ON TABLES FROM %I',
                        current_user, s, role_name);
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL PRIVILEGES ON SEQUENCES FROM %I',
                        current_user, s, role_name);
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL PRIVILEGES ON ROUTINES FROM %I',
                        current_user, s, role_name);
                END IF;
                -- reverse-direction default privileges (5i): the
                -- executor keeps access to objects the owner role
                -- creates in schemas it no longer manages
                EXECUTE format(
                    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL PRIVILEGES ON TABLES FROM %I',
                    role_name, s, current_user);
                EXECUTE format(
                    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL PRIVILEGES ON SEQUENCES FROM %I',
                    role_name, s, current_user);
                EXECUTE format(
                    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL PRIVILEGES ON ROUTINES FROM %I',
                    role_name, s, current_user);
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
    -- 5i. default privileges for the migration window:
    --     objects created by the executor (old app still running)
    --     are usable by the owner role -- and therefore by all its
    --     members. On schemas the owner role OWNS, this covers all
    --     object types (the migration window is a full takeover).
    --     On foreign schemas, future grants are limited to the
    --     CONFIGURED access: a SELECT-only entry must not gain
    --     INSERT on future executor-created tables.
    --     Objects created by the owner role remain usable by the
    --     executor (reverse direction, all managed schemas).
    ------------------------------------------------------------------
    FOREACH s IN ARRAY schemas LOOP
        IF s = '' THEN
            CONTINUE;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_catalog.pg_namespace ns
            JOIN pg_catalog.pg_roles ro ON ro.oid = ns.nspowner
            WHERE ns.nspname = s AND ro.rolname = role_name
        ) THEN
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL PRIVILEGES ON TABLES TO %I',
                current_user, s, role_name);
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL PRIVILEGES ON SEQUENCES TO %I',
                current_user, s, role_name);
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL PRIVILEGES ON ROUTINES TO %I',
                current_user, s, role_name);
        ELSE
            FOREACH entry IN ARRAY string_to_array('{access_list}', ';') LOOP
                IF entry <> '' AND split_part(entry, '|', 1) = s THEN
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT %s ON TABLES TO %I',
                        current_user, s, split_part(entry, '|', 2), role_name);
                END IF;
            END LOOP;
        END IF;

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

    ------------------------------------------------------------------
    -- 5j. remove the transient CREATE privilege (5a-bis) on schemas
    --     the owner role does not own: it was only needed for the
    --     ownership transfers above (PG16+ ALTER ... OWNER TO).
    --     EXCEPTION: when the entry's configured access for such a
    --     schema is write access (ALL or any grant beyond SELECT),
    --     the role KEEPS CREATE: DAM could not deliver ownership of
    --     the schema (e.g. public in the admin database on PG15+)
    --     and the application must still run its DDL migrations
    --     there. The 5h revoke path (a schema that moved away from
    --     ALL) removes CREATE together with the old grants, so it is
    --     actively GRANTed back here -- and the result is VERIFIED: a
    --     GRANT without grant option only produces a WARNING (no
    --     exception), so the effective CREATE privilege of the owner
    --     role is checked before the commit, like the section-3
    --     CONNECT verification. An executor that cannot deliver CREATE
    --     fails the job instead of silently breaking the application's
    --     DDL migrations. A role that needs
    --     to create objects in a schema it owns is unaffected -- DAM
    --     takes ownership of managed schemas in 5a whenever the
    --     executor controls them.
    --     Read-only (SELECT only) entries never keep CREATE.
    ------------------------------------------------------------------
    FOREACH entry IN ARRAY string_to_array('{access_list}', ';') LOOP
        IF entry <> '' THEN
            FOREACH g IN ARRAY string_to_array(split_part(entry, '|', 2), ',') LOOP
                IF g NOT IN ('SELECT', '') THEN
                    s := split_part(entry, '|', 1);
                    IF NOT write_schemas @> ARRAY[s] THEN
                        write_schemas := array_append(write_schemas, s);
                    END IF;
                    EXIT;
                END IF;
            END LOOP;
        END IF;
    END LOOP;

    FOR r IN
        SELECT n.nspname AS schema_name
        FROM pg_namespace n
        WHERE n.nspname = ANY (schemas)
          AND n.nspowner <> role_name::regrole
    LOOP
        IF r.schema_name = ANY (write_schemas) THEN
            BEGIN
                EXECUTE format('GRANT CREATE ON SCHEMA %I TO %I',
                               r.schema_name, role_name);
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE NOTICE 'cannot grant CREATE on schema % to % (executor has no grant option)',
                    r.schema_name, role_name;
            END;
            -- the WARNING-without-error counterpart of the USAGE check
            -- in 5h: a GRANT the executor had no grant option for
            -- grants nothing, and DAM promised the application DDL in
            -- this schema -- the transaction must not commit while
            -- the owner role effectively lacks CREATE
            IF NOT has_schema_privilege(role_name, r.schema_name, 'CREATE') THEN
                RAISE EXCEPTION 'owner role % lacks CREATE on schema % required for DDL migrations -- the executor cannot grant it',
                    role_name, r.schema_name;
            END IF;
        ELSE
            EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM %I',
                           r.schema_name, role_name);
        END IF;
    END LOOP;
END $$;

-- 6. the search-path settlement (INSIDE the transaction,
--    deliberately: the store write and the login's search_path
--    write activate in the SAME transaction as the role default of
--    section 3 -- together or not at all -- so a failure anywhere
--    above or below rolls the whole switch back and the login keeps
--    its old behavior; the login never ends up role-defaulted
--    without its preserved path). The migration itself no longer
--    depends on reconstructing the path here: the observation
--    already happened (section 0, PRE-transaction, on a real
--    application-login connection -- PostgreSQL itself resolved
--    every level there), and it is carried in the dam.observed_sp
--    session setting that the section-0 hop back set on this
--    backend.
--
--    WHY AN APPLICATION CONNECTION (section 0): the login's
--    effective search_path is the resolution of every level (the
--    login's per-database setting, its role-wide setting, the
--    database-wide setting, the server-wide value, the built-in
--    "$user", public). Reading it from the job session is
--    unreliable -- pg_settings reflects the EXECUTOR's session,
--    whose own override (a private path, or even an explicitly
--    EMPTY one) masks the server-wide value. The previous
--    workaround reset the executor's own setting, reconnected, read
--    and restored it -- and that restore could corrupt the
--    executor's setting itself (an explicitly empty executor path
--    made the restore fail with a zero-length delimited identifier,
--    leaving the executor's setting reset). The executor's
--    persistent search_path is therefore NEVER modified for reading:
--    the capture connects AS the application login and asks
--    PostgreSQL directly. current_setting('search_path') there
--    returns the true effective raw value with every level resolved
--    by PostgreSQL itself -- an explicitly empty resolution as the
--    canonical empty value, no setting at all as the built-in
--    "$user", public -- and the executor's private path is
--    irrelevant to it.
--
--    Residual corner, deliberately failed loudly: if the capture
--    connection itself fails (e.g. a pg_hba rule that admits the
--    executor but not the application login), ON_ERROR_STOP aborts
--    the job BEFORE the transaction -- nothing but the password
--    pre-set persisted; the login has NO role default and NO path
--    change, so its old behavior stays functional, and a retry
--    (still capture-eligible: no role default, no store) captures
--    correctly. The abort's only residue is the pre-set: the
--    database password is ahead of the vault until the next
--    successful run -- the same staleness window the previous
--    post-commit failure mode had, and strictly better than a
--    silent resolution flip. The executor's settings are never
--    touched.
DO $$
DECLARE
    role_name text := '{role_literal}';
    user_name text := '{username_literal}';
    db text := '{database_literal}';
    schemas_arr text[] := string_to_array('{schemas_csv}', ',');
    in_scope text[] := ARRAY[]::text[];
    legacy text[] := ARRAY[]::text[];
    prefix text[] := ARRAY[]::text[];
    sp_elems text[] := ARRAY[]::text[];
    revoked text[] := ARRAY[]::text[];
    observed text;
    captured boolean;
    store_raw text;
    raw_value text;
    path_empty boolean := false;
    cands text[];
    cand text;
    tokens text[];
    cur text;
    ch text;
    i int;
    j int;
    in_quotes boolean;
    s text;
    t text;
    sp text;
    store_sp text;
BEGIN
    -- the observation of the capture run (the session GUC set in the
    -- section-0 \if branch; NULL on every other run)
    observed := current_setting('dam.observed_sp', true);
    captured := observed IS NOT NULL;

    -- the persistent LEGACY-PATH STORE: the owner role's per-database
    -- search_path setting. Pure storage: session startup only ever
    -- applies settings of the LOGIN's own role OID (and the
    -- database-wide and global rows), so a setting on the owner role
    -- never reaches a member login -- and search_path is a known
    -- USERSET parameter, so a non-superuser executor with ADMIN on
    -- the role (granted automatically to the creator on PG16+, and
    -- held by any CREATEROLE role on older versions) can write it. A
    -- custom-named parameter would need a parameter ACL that RDS-like
    -- executors do not hold. DAM stores schema NAMES here:
    -- quote_ident-joined on write (the ONLY place identifiers are
    -- formatted) and decoded back to names on read by the parser
    -- below, so no quote round-trip can corrupt the value. The store
    -- holds ONLY the legacy prefix, never the configured segment
    -- (that is rebuilt from the current configuration every run).
    -- Present-but-empty means "the role's resolution is deliberately
    -- empty" -- see the empty-state rule below.
    SELECT substring(cfg FROM position('=' IN cfg) + 1)
    INTO store_raw
    FROM pg_catalog.pg_db_role_setting rs
    JOIN pg_catalog.pg_database d ON d.oid = rs.setdatabase
    CROSS JOIN LATERAL unnest(rs.setconfig) AS cfg
    WHERE rs.setrole = (SELECT oid FROM pg_catalog.pg_roles
                        WHERE rolname = role_name)
      AND d.datname = db
      AND cfg LIKE 'search_path=%';

    -- the raw value to parse this run: the store when present
    -- (rotation and every later run read the store -- the live
    -- defaults are never captured again), otherwise the observation
    -- of the capture run. A run that neither reads the store nor
    -- captured (a brand-new login, or a login an earlier role-mode
    -- run already manages without a store) has no raw value: there
    -- is no behavior to preserve beyond the current configuration.
    -- The EMPTY state is a property of the ROLE's resolution, never
    -- of the CURRENT login's own setting: a present-but-empty store
    -- (the canonical empty value) keeps the applied path empty for
    -- EVERY login of the role, so an explicitly empty resolution
    -- survives password rotation (regression: the path construction
    -- used to check only the current login's captured emptiness --
    -- after rotating to a second login of the same role, the
    -- unqualified query silently resolved through the configured
    -- schemas to the public twin).
    IF store_raw IS NOT NULL THEN
        raw_value := store_raw;
        IF store_raw IN ('', '""') THEN
            path_empty := true;
        END IF;
    ELSIF captured THEN
        raw_value := observed;
        IF observed IN ('', '""') THEN
            path_empty := true;
        END IF;
    ELSE
        raw_value := NULL;
    END IF;

    -- the schemas the search path is maintained towards: the
    -- configured access list (in configured order, deduplicated,
    -- empty entries dropped) plus public appended when absent
    FOREACH s IN ARRAY schemas_arr LOOP
        IF s <> '' AND NOT in_scope @> ARRAY[s] THEN
            in_scope := array_append(in_scope, s);
        END IF;
    END LOOP;
    IF NOT in_scope @> ARRAY['public'] THEN
        in_scope := array_append(in_scope, 'public');
    END IF;

    -- schemas that just left the configuration: the rendered revoke
    -- list carries every removed schema
    revoked := ARRAY(
        SELECT DISTINCT btrim(split_part(e, '|', 1))
        FROM unnest(string_to_array('{revoke_list}', ';')) AS e
        WHERE e <> ''
    );

    -- THE PARSER (the single derivation of schema names from a raw
    -- setting value -- the store's, or the captured observation).
    -- PostgreSQL's flatten code stores a search_path value as its
    -- elements joined with ", ", each
    -- quote_identifier-ed -- so a schema name that needs quoting
    -- appears as a double-quoted token with inner quotes doubled,
    -- and a value that was set as a single string is wrapped in
    -- outer quotes as a whole. The parser mirrors PostgreSQL's own
    -- list reader (SplitIdentifierString): decode the outer wrap
    -- first (strip the wrapping quotes, un-double), fall back to the
    -- raw value when that does not tokenize; split at commas OUTSIDE
    -- quoted segments; the scan itself un-quotes each token (the
    -- surrounding quotes vanish, doubled pairs collapse to one).
    -- From here on schema names are NAMES, never pre-formatted SQL
    -- fragments -- quote_ident is applied exactly once, when the
    -- login's search_path is written below.
    tokens := ARRAY[]::text[];
    IF raw_value IS NOT NULL AND raw_value <> '' THEN
        IF raw_value LIKE '"%"' THEN
            -- the RAW value first: it mirrors what PostgreSQL's own
            -- list reader applies at session start -- a quoted
            -- segment stays ONE name, however many separators it
            -- contains. The de-wrapped variant (a value stored as a
            -- single string is wrapped in outer quotes as a whole)
            -- is only a fallback for values the raw scan cannot
            -- tokenize: de-quoting first would split a name that
            -- merely CONTAINS a separator.
            cands := ARRAY[
                raw_value,
                replace(substring(raw_value FROM 2 FOR length(raw_value) - 2),
                        '""', '"')];
        ELSE
            cands := ARRAY[raw_value];
        END IF;
        FOREACH cand IN ARRAY cands LOOP
            -- an EMPTY array (not NULL) marks the scan as valid so
            -- far: a value without any comma is a valid
            -- single-element list, and only invalid syntax NULLs
            -- the scan -- the final element is appended after the
            -- loop whenever the scan stayed valid (regression: a
            -- single-element value used to degenerate to the empty
            -- list because the final element was appended only when
            -- a comma had already produced a token)
            tokens := ARRAY[]::text[];
            cur := '';
            in_quotes := false;
            i := 1;
            WHILE i <= length(cand) LOOP
                ch := substring(cand FROM i FOR 1);
                IF in_quotes THEN
                    IF ch = '"' THEN
                        IF substring(cand FROM i + 1 FOR 1) = '"' THEN
                            cur := cur || '"';
                            i := i + 2;
                        ELSE
                            in_quotes := false;
                            i := i + 1;
                        END IF;
                    ELSE
                        cur := cur || ch;
                        i := i + 1;
                    END IF;
                ELSIF ch = '"' THEN
                    in_quotes := true;
                    i := i + 1;
                ELSIF ch = ',' THEN
                    t := btrim(cur);
                    IF t = '' THEN
                        -- an empty element is invalid list syntax
                        tokens := NULL;
                        EXIT;
                    END IF;
                    tokens := array_append(tokens, t);
                    cur := '';
                    i := i + 1;
                ELSIF ch ~ '\s' THEN
                    IF cur = '' THEN
                        -- leading whitespace (at the start of the
                        -- value or right after a separator): skip it
                        i := i + 1;
                    ELSE
                        -- an unquoted name ends at whitespace: only
                        -- a separator or the end of the value may
                        -- follow
                        j := i;
                        WHILE j <= length(cand)
                              AND substring(cand FROM j FOR 1) ~ '\s' LOOP
                            j := j + 1;
                        END LOOP;
                        IF j > length(cand)
                           OR substring(cand FROM j FOR 1) = ',' THEN
                            i := j;
                        ELSE
                            tokens := NULL;
                            EXIT;
                        END IF;
                    END IF;
                ELSE
                    cur := cur || ch;
                    i := i + 1;
                END IF;
            END LOOP;
            IF tokens IS NOT NULL THEN
                IF in_quotes THEN
                    -- an unterminated quoted segment is invalid syntax
                    tokens := NULL;
                ELSE
                    t := btrim(cur);
                    IF t <> '' THEN
                        tokens := array_append(tokens, t);
                    END IF;
                END IF;
            END IF;
            EXIT WHEN tokens IS NOT NULL;
        END LOOP;
        IF tokens IS NULL THEN
            RAISE NOTICE 'cannot parse the stored search_path value "%" as a schema name list', raw_value;
            tokens := ARRAY[]::text[];
        END IF;
    END IF;

    -- the legacy names for this run
    IF store_raw IS NOT NULL THEN
        -- the store governs: rotation and later runs never re-capture
        FOREACH t IN ARRAY tokens LOOP
            IF t <> '' AND NOT legacy @> ARRAY[t] THEN
                legacy := array_append(legacy, t);
            END IF;
        END LOOP;
    ELSIF NOT captured THEN
        -- a run that did not capture: brand-new, or already managed
        -- by an earlier role-mode run -- no behavior to preserve
        -- beyond the current configuration
        legacy := ARRAY[]::text[];
    ELSIF path_empty THEN
        -- the captured resolution is EXPLICITLY EMPTY: the tenant
        -- deliberately emptied its resolution -- nothing to preserve
        -- (unqualified access keeps failing; the append below is
        -- gated off too)
        legacy := ARRAY[]::text[];
    ELSE
        -- the capture run: preserve the login's effective current
        -- resolution, parsed as names above. $user resolves to the
        -- login name, and the login-name token only stays while a
        -- schema of that name exists. When the login had no setting
        -- at all, the observation IS the built-in "$user", public --
        -- this branch preserves it exactly like a DBA-set value.
        FOREACH t IN ARRAY tokens LOOP
            IF t = '$user' THEN
                t := user_name;
            END IF;
            IF t = user_name
               AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
                               WHERE n.nspname = user_name) THEN
                CONTINUE;
            END IF;
            IF t <> '' AND NOT legacy @> ARRAY[t] THEN
                legacy := array_append(legacy, t);
            END IF;
        END LOOP;
    END IF;

    -- the prefix: the legacy names minus the schemas that just left
    -- the configuration (in the rendered revoke list AND not in
    -- scope) -- removed schemas drop from the store permanently
    FOREACH s IN ARRAY legacy LOOP
        IF s <> ''
           AND NOT (revoked @> ARRAY[s] AND NOT in_scope @> ARRAY[s]) THEN
            prefix := array_append(prefix, s);
        END IF;
    END LOOP;

    -- the path: the legacy prefix, then the in-scope schemas in
    -- their CURRENT configured order. The configured segment is
    -- rebuilt from the ordered access list every run: an intentional
    -- order change applies, and an unchanged configuration
    -- reproduces the path deterministically. EXCEPT when the role's
    -- resolution is EXPLICITLY EMPTY (the empty-state rule above):
    -- the applied path stays EMPTY -- no configured schemas and no
    -- public fallback are appended, and unqualified access keeps
    -- failing exactly as before the migration, for every login of
    -- the role.
    IF NOT path_empty THEN
        sp_elems := prefix;
        FOREACH s IN ARRAY in_scope LOOP
            IF NOT sp_elems @> ARRAY[s] THEN
                sp_elems := array_append(sp_elems, s);
            END IF;
        END LOOP;
    ELSE
        sp_elems := ARRAY[]::text[];
    END IF;

    -- an empty element list writes the canonical empty value (''
    -- as a SQL string literal), which only the explicitly-empty
    -- case can produce -- every append path contains public
    SELECT COALESCE(string_agg(quote_ident(e), ','), quote_literal(''))
    INTO sp FROM unnest(sp_elems) AS e;
    -- the effective path: written to the login, whose connections
    -- apply it (the login-level setting is the ONLY applied
    -- search_path and wins over every broader default)
    BEGIN
        EXECUTE format('ALTER ROLE %I IN DATABASE %I SET search_path = %s',
                       user_name, db, sp);
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'cannot set search_path for %', user_name;
    END;

    -- the persistent store: the (possibly reduced) legacy prefix as
    -- quote_ident-joined names; an empty prefix is stored as the
    -- empty string (present, marking the capture done, with nothing
    -- to preserve). Written ONLY by runs that captured and by runs
    -- the store already governs (they may reduce it by the revoke
    -- delta): a run that did not capture must never INITIALIZE the
    -- store -- a second entry's new-login run used to write the
    -- empty store and make the later legacy-migration run of
    -- another login in the same role skip its capture entirely
    -- (regression: the old login silently resolved to the public
    -- twin after its migration)
    IF store_raw IS NOT NULL OR captured THEN
        SELECT COALESCE(string_agg(quote_ident(e), ','), quote_literal(''))
        INTO store_sp FROM unnest(prefix) AS e;
        BEGIN
            EXECUTE format('ALTER ROLE %I IN DATABASE %I SET search_path = %s',
                           role_name, db, store_sp);
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'cannot store the legacy search_path for %', role_name;
        END;
    END IF;
END $$;

COMMIT;

-- 4. database ownership: only when the executor IS the current
--    database owner (not a member of another managed role that took
--    ownership) and the target is NOT the admin database this job
--    started in AND not the database named postgres. Design
--    rationale: `database: postgres` (the instance's default/admin
--    database) allows migrating INSIDE this database -- the managed
--    application objects and schemas still transfer to the owner
--    role -- but the DATABASE itself never changes owner, wherever
--    the job started, because instance-level administration and
--    other jobs rely on that owner staying stable. The name-based
--    guard is independent of the admin secret's db.name: a job
--    started in a different database must not transfer the postgres
--    database either (the start-database guard alone does not
--    protect it, and the user name postgres is not the same as the
--    start database). A dedicated DAM-created application database
--    MAY belong to its owner role; on shared databases the first
--    owner role keeps the ownership so other roles' jobs do not
--    transfer it away.
--    Must stay outside the transaction: ALTER DATABASE cannot run in
--    a transaction block.
SELECT format('ALTER DATABASE %I OWNER TO %I', '{database_literal}', '{role_literal}')
FROM pg_database
WHERE datname = '{database_literal}'
  AND pg_get_userbyid(datdba) = current_user
  AND datname <> :'dam_admin_db'
  AND datname <> 'postgres';\gexec
