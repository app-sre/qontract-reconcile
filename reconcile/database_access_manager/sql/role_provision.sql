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
-- authenticate even while the password is being rotated) and, concatenated
-- CLIENT-side by psql, in the conninfo of that application-login connection
-- itself (never as server-side SQL text)
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
-- carries one pointing at THIS entry's owner role, a legacy login
-- does not -- and neither does a DBA-set default pointing at an
-- UNRELATED role, which must not disable the capture). The effective
-- search_path VALUE itself is no longer reconstructed from the
-- catalogs here: PostgreSQL itself resolves the complete precedence
-- (the login's per-database setting, its role-wide setting, the
-- database-wide setting, the server-wide value, the built-in "$user",
-- public) when the application login connects, and the capture
-- observes exactly that on a real connection of the login -- a value
-- the executor's own search_path can neither mask nor corrupt.
SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles
               WHERE rolname = '{username_literal}') AS dam_login_existed \gset
SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_db_role_setting s
               JOIN pg_catalog.pg_database d ON d.oid = s.setdatabase
               CROSS JOIN LATERAL unnest(s.setconfig) AS cfg
               WHERE s.setrole = (SELECT oid FROM pg_catalog.pg_roles
                                  WHERE rolname = '{username_literal}')
                 AND d.datname = '{database_literal}'
                 AND cfg = 'role={role_literal}') AS dam_login_role_default \gset

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
--    intentional order change could never apply), the persistent
--    store is not initialized (a capture writes it). A login that
--    exists but currently lacks CONNECT on the database (a restricted
--    database -- PUBLIC revoked and the direct grant gone, e.g. after
--    another entry's legacy job) receives the executor's best-effort
--    direct GRANT before the capture decision below: when the
--    executor can grant (the normal case: it owns or administers the
--    database), the capture's application connection succeeds and the
--    login's legacy resolution is PRESERVED (regression: the capture
--    used to be skipped for a CONNECT-less login and the configured
--    order silently replaced its legacy path). When the executor
--    cannot grant (no grant option, not the database owner), the
--    GRANT only warns and the capture hop itself fails: the job
--    aborts BEFORE the transaction -- the same fail-closed contract
--    as section 3's CONNECT verification, without the silent
--    resolution flip a skipped capture would perform. The CASE (not a
--    bare AND) guards has_database_privilege: it errors on a
--    nonexistent role, and a fresh login may not exist.
--
--    Residual, deliberately accepted and narrowed by the
--    pre-transaction owner-role name check below: an in-transaction
--    failure AFTER this pre-grant still leaves the grant in place --
--    it is idempotent with the successful outcome (section 3 grants
--    CONNECT unconditionally and verifies the direct ACL entry), the
--    same residual class as the password pre-set below.

-- the OWNER-ROLE NAME CHECK, deliberately BEFORE the CONNECT
-- pre-grant below (and before every persistent change of this
-- script). A pre-existing LOGIN role with the owner-role name must
-- abort the job with the specific error while nothing has been
-- written yet: the condition used to be verified only by the
-- in-transaction duplicate handler of section 1, but the CONNECT
-- pre-grant and the password pre-set run in autocommit BEFORE that
-- transaction -- a job that later failed on the clash had already
-- persisted both. Catalog-only check (pg_roles): no grant, no
-- password write, no transaction.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles
               WHERE rolname = '{role_literal}' AND rolcanlogin) THEN
        RAISE EXCEPTION 'role % already exists as a LOGIN role: the owner role of a database_access entry must be a NOLOGIN group role',
            '{role_literal}';
    END IF;
END $$;

SELECT 'GRANT CONNECT ON DATABASE "{database}" TO "{username}"'
WHERE CASE WHEN EXISTS (SELECT 1 FROM pg_catalog.pg_roles
                        WHERE rolname = '{username_literal}')
           THEN NOT has_database_privilege('{username_literal}',
                                           '{database_literal}', 'CONNECT')
           ELSE false END;\gexec
SELECT (:'dam_login_existed'::boolean
        AND NOT :'dam_login_role_default'::boolean
        AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_db_role_setting rs
                        JOIN pg_catalog.pg_database d ON d.oid = rs.setdatabase
                        CROSS JOIN LATERAL unnest(rs.setconfig) AS cfg
                        WHERE rs.setrole = (SELECT oid FROM pg_catalog.pg_roles
                                            WHERE rolname = '{role_literal}')
                          AND d.datname = '{database_literal}'
                          AND cfg LIKE 'search_path=%')
       ) AS dam_capture \gset
\if :dam_capture
-- the PASSWORD PRE-SET: the application-connection capture below
-- must authenticate as the login even when the password is being
-- rotated (no vault secret), so the job's password is set on the
-- login BEFORE the connection. It is idempotent when the vault
-- password is reused (the normal migration case: the legacy login
-- already carries it), and it needs exactly the privileges the
-- in-transaction password write of section 2 already requires (a
-- legacy-managed login carries the legacy template's grant to the
-- admin). The VALID UNTIL 'infinity' reset is CONDITIONAL, guarded on
-- the login being ACTUALLY expired (rolvaliduntil read from
-- pg_roles): an expired login (an instance password policy) would
-- otherwise fail the capture's authentication FOREVER -- the expiry
-- reset only comes with section 2's password write, which the failed
-- capture never reaches, so the job could never converge. A
-- NON-expired login (a policy-set future expiry) keeps its expiry
-- through the pre-set. Residual window, taken deliberately: a job
-- abort after this point leaves the DATABASE password ahead of the
-- vault until the next successful run -- the same staleness window
-- the previous post-commit failure mode had -- and a failed capture
-- on an ALREADY-EXPIRED login leaves password AND expiry changed
-- (that login was unusable anyway); a failed capture on a non-expired
-- login changes only the password. Both are strictly better than a
-- silent resolution flip.
ALTER ROLE "{username}" PASSWORD :'db_user_password';
SELECT 'ALTER ROLE "{username}" VALID UNTIL ''infinity'''
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_roles
              WHERE rolname = '{username_literal}'
                AND rolvaliduntil IS NOT NULL
                AND rolvaliduntil <= current_timestamp);\gexec
-- the application connection string of the observation hop is built
-- CLIENT-side: psql \set argument concatenation joins the quoted
-- literal and the db_user_password variable value into one conninfo
-- string that never reaches the SERVER as SQL text (with
-- log_statement = 'all', the SELECT that used to build it here wrote
-- the password to the server log as literal statement text). The
-- contract that makes the raw concatenation safe: the database and
-- username are psqlIdentifier-validated by app-interface (lowercase
-- alphanumerics and dashes) and DAM-generated passwords are
-- alphanumeric -- no conninfo quoting is ever needed. -reuse-
-- previous=on keeps the host and port of the current connection; the
-- user change of the hop makes psql drop the previous connection's
-- password (the hop back as the executor authenticates with the
-- job's PGPASSWORD or the local trust policy, never with the
-- application password). The ADMIN string is still built in SQL so
-- that every value is CONNINFO-ESCAPED (single-quoted, with
-- backslashes and single quotes backslash-escaped -- chr(92)/chr(39)
-- keep the template free of string-literal ambiguity): psql does
-- NOT interpolate :variables inside the double-quoted argument of a
-- \c command, but an UNQUOTED :dam_app_conninfo does interpolate,
-- as one conninfo argument. No secret is involved in it -- it is
-- built while still connected as the executor (current_user IS the
-- executor).
\set dam_app_conninfo 'dbname={database} user={username} password=' :db_user_password
SELECT 'dbname=' ||
       chr(39) || replace(replace('{database_literal}', chr(92), chr(92) || chr(92)), chr(39), chr(92) || chr(39)) || chr(39) ||
       ' user=' ||
       chr(39) || replace(replace(current_user::text, chr(92), chr(92) || chr(92)), chr(39), chr(92) || chr(39)) || chr(39)
       AS dam_admin_conninfo \gset
\c -reuse-previous=on :dam_app_conninfo
-- the observation: PostgreSQL's own resolution of the login's
-- effective search_path AND of the identity its session actually
-- acts as ($user resolves CURRENT_USER, not the login name: a DBA
-- startup role default like SET role = tenant makes the session act
-- as that role), as psql variables (they survive the hop back; a
-- session GUC would not). Nothing DAM writes exists yet: this is the
-- login's genuine pre-migration behavior. The probe is
-- pg_catalog-qualified: pg_catalog is only prepended IMPLICITLY while
-- the path does not name it, so a writable same-named function in a
-- schema the login's path lists BEFORE an explicit pg_catalog could
-- otherwise feed the capture a fabricated value. The bare current_user
-- keyword is reservation syntax and cannot be shadowed at all.
SELECT pg_catalog.current_setting('search_path') AS dam_observed_sp,
       current_user AS dam_observed_user,
       CASE WHEN EXISTS (SELECT 1 FROM pg_catalog.pg_namespace
                         WHERE nspname = current_user)
            THEN pg_catalog.has_schema_privilege(current_user, current_user, 'USAGE')
            ELSE false END AS dam_user_resolved \gset
\c -reuse-previous=on :dam_admin_conninfo
-- hand the observations to the settlement block inside the
-- transaction below: session GUCs in THIS executor session (set
-- after every reconnect, so no hop can lose them, and read by the
-- settlement DO block on the same backend). pg_catalog-qualified for
-- the same shadowing reason as the probe. dam_user_resolved records
-- whether "$user" actually RESOLVED in the capture session: the
-- observed identity held USAGE on its same-named schema. PostgreSQL
-- silently SKIPS a search-path schema the acting role has no USAGE
-- on during unqualified resolution, so a schema that merely EXISTS
-- must not enter the stored prefix first -- provisioning later
-- grants the owner role USAGE there and would silently flip the
-- resolution to that schema.
SELECT pg_catalog.set_config('dam.observed_sp', :'dam_observed_sp', false);
SELECT pg_catalog.set_config('dam.observed_user', :'dam_observed_user', false);
SELECT pg_catalog.set_config('dam.observed_user_resolved', :'dam_user_resolved', false);
\else
-- not a capture run (a fresh login, a login an earlier role-mode
-- run already manages, or a store that already governs the role):
-- no application connection and no password pre-set are needed, the
-- maintained path below is computed from the store or from the
-- configured order alone
\endif

-- 1. the owner role: NOLOGIN group role that owns everything.
--    A duplicate_object error is tolerated: two entries sharing this
--    role can run their first provisioning concurrently. The existing
--    role must be NOLOGIN: a pre-existing LOGIN role with the
--    owner-role name would silently receive the login's membership
--    below and act as a second application login -- a clear error
--    instead. That verification PRIMARILY runs pre-transaction now
--    (the owner-role name check before section 0's pre-grant); the
--    identical check here is the race guard for a LOGIN role created
--    between that check and this transaction, and keeps the handler
--    tolerant of NOLOGIN duplicates (concurrent first provisioning).
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
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles
               WHERE rolname = '{role_literal}' AND rolcanlogin) THEN
        RAISE EXCEPTION 'role % already exists as a LOGIN role: the owner role of a database_access entry must be a NOLOGIN group role',
            '{role_literal}';
    END IF;
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
    -- the membership probes: PG16+ role memberships carry separate
    -- SET and INHERIT options, and section 5 needs BOTH from the
    -- executor's wiring: the ownership transfers filter on USAGE
    -- (inheritance -- a membership granted WITH SET TRUE, INHERIT
    -- FALSE passes a SET-only probe while the transfers silently
    -- skip that role's objects, and ALTER DEFAULT PRIVILEGES FOR
    -- ROLE of 5i fails without the inherited membership), and the
    -- ALTER ... OWNER TO check of section 5 requires SET ("must be
    -- able to SET ROLE" -- the plain SET ROLE command is not the
    -- same, verified on a real instance). A membership missing
    -- either option is re-granted with INHERIT TRUE, SET TRUE: both
    -- options upgrade and the ADMIN option of an existing membership
    -- is preserved. Older versions have no SET option (set_probe is
    -- USAGE there, so the second check is the same probe twice) and
    -- keep the USAGE check alone.
    set_probe text := CASE WHEN current_setting('server_version_num')::int >= 160000
                           THEN 'SET' ELSE 'USAGE' END;
    s text;
BEGIN
    -- the executor must be able to SET ROLE to the owner role for
    -- every ownership transfer below, and to USE its privileges for
    -- the transfers and the default privileges. NOTE (PG16+): the
    -- automatic grant a role gets when creating another role has
    -- ADMIN but neither INHERIT nor SET, and a PRE-EXISTING
    -- membership can carry any option combination -- checking for
    -- membership (or for one option) alone is not enough here.
    IF NOT pg_has_role(current_user, role_name, set_probe)
       OR NOT pg_has_role(current_user, role_name, 'USAGE') THEN
        EXECUTE format('GRANT %I TO %I%s', role_name, current_user, set_opt);
    END IF;
    -- the executor must control the login user to transfer objects of
    -- a previously managed user and to set its role default
    IF NOT pg_has_role(current_user, user_name, set_probe)
       OR NOT pg_has_role(current_user, user_name, 'USAGE') THEN
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
    -- database, the credential would be published but rejected. The
    -- grant is UNCONDITIONAL and idempotent: a login whose CONNECT
    -- came from PUBLIC keeps none of its own and loses it the moment
    -- another entry's legacy job revokes PUBLIC on the same database
    -- -- a direct grant is the only one that survives that. The
    -- verification checks the login's own DIRECT ACL entry in
    -- pg_database.datacl (aclexplode), not the effective privilege:
    -- has_database_privilege includes PUBLIC, so a warning-grant from
    -- a grantless executor would pass the check while the login
    -- actually keeps CONNECT only via PUBLIC -- and gets locked out
    -- by that later revoke.
    BEGIN
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', db, user_name);
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE EXCEPTION 'login % has no CONNECT on database % and the executor cannot grant it',
            user_name, db;
    END;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_database d
        CROSS JOIN LATERAL pg_catalog.aclexplode(d.datacl) AS a
        WHERE d.datname = db
          AND a.grantee = (SELECT oid FROM pg_catalog.pg_roles
                           WHERE rolname = user_name)
          AND a.privilege_type = 'CONNECT'
    ) THEN
        RAISE EXCEPTION 'login % has no CONNECT on database % after explicit grant',
            user_name, db;
    END IF;
END $$;

-- 5. ownership transfer, grants and default privileges
DO $$
DECLARE
    role_name text := '{role_literal}';
    user_name text := '{username_literal}';
    -- the owner role's OID, resolved ONCE by exact text comparison
    -- with pg_roles.rolname: text::regrole parses its input as an
    -- UNQUOTED identifier (regrolein folds case), so a name that is
    -- not all-lowercase would resolve to a different or nonexistent
    -- role. Rendered role names are lowercase-only (the
    -- psqlIdentifier schema domain), which made a regrole cast a
    -- no-op there -- the OID comparison is exact for every name.
    role_oid oid := (SELECT oid FROM pg_catalog.pg_roles
                     WHERE rolname = role_name);
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
          AND n.nspowner <> role_oid
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
          AND n.nspowner <> role_oid
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
          AND c.relowner <> role_oid
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
          AND c.relowner <> role_oid
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
          AND s.stxowner <> role_oid
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
          AND p.proowner <> role_oid
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
          AND t.typowner <> role_oid
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
          AND c.relowner <> role_oid
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
          AND p.proowner <> role_oid
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
                    -- the transient CREATE grant (5a-bis) must not
                    -- outlive the schema's membership in the access
                    -- list
                    EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM %I',
                                   s, role_name);
                END IF;
                -- the default privileges (5i) must not outlive the
                -- schema's membership in the access list, on owned
                -- and foreign schemas alike: 5i grants the
                -- executor-to-owner direction for every managed
                -- schema, so a role-owned schema removed from the
                -- access list keeps granting the owner role access
                -- to new executor-created objects otherwise
                EXECUTE format(
                    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL PRIVILEGES ON TABLES FROM %I',
                    current_user, s, role_name);
                EXECUTE format(
                    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL PRIVILEGES ON SEQUENCES FROM %I',
                    current_user, s, role_name);
                EXECUTE format(
                    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL PRIVILEGES ON ROUTINES FROM %I',
                    current_user, s, role_name);
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
          AND n.nspowner <> role_oid
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
    observed_user text;
    user_resolved text;
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
    token_quoted boolean;
    s text;
    t text;
    sp text;
    store_sp text;
BEGIN
    -- the observations of the capture run (the session GUCs set in
    -- the section-0 \if branch; NULL on every other run). The search
    -- path and the identity the login's session acted as
    -- (current_user there -- a DBA startup role default like SET
    -- role = tenant makes the session act as that role). The reads
    -- are pg_catalog-qualified: the settlement must not be
    -- shadowable by a hostile function in the executor's path.
    observed := pg_catalog.current_setting('dam.observed_sp', true);
    observed_user := pg_catalog.current_setting('dam.observed_user', true);
    user_resolved := pg_catalog.current_setting('dam.observed_user_resolved', true);
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
    -- Token semantics, exactly like PostgreSQL's own resolution:
    -- a QUOTED token keeps its content EXACTLY (a trailing space or
    -- an embedded tab is part of the name -- btrim would silently
    -- change the resolution), an UNQUOTED token folds to lowercase
    -- ASCII-ONLY (PostgreSQL downcases identifiers ASCII-only and
    -- resolves unquoted path elements case-insensitively: a raw
    -- TENANT resolves the tenant schema, never "TENANT" -- and a raw
    -- TENÄNTX resolves tenÄntx, never the tenäntx a locale-aware
    -- lower() would produce), and
    -- whitespace never becomes part of an unquoted token (the
    -- [:space:] branch below precedes the append branch, so a tab is
    -- a separator or invalid syntax -- PostgreSQL itself rejects
    -- tabs inside unquoted list elements at the GUC level). From
    -- here on schema names are NAMES, never pre-formatted SQL
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
            token_quoted := false;
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
                    token_quoted := true;
                    i := i + 1;
                ELSIF ch = ',' THEN
                    -- a quoted token keeps its content EXACTLY, an
                    -- unquoted one folds ASCII-only to lowercase like
                    -- PostgreSQL's own identifier downcasing (never
                    -- locale-aware: lower() would fold Ä to ä in a
                    -- UTF-8 locale -- a name PostgreSQL itself never
                    -- resolves an unquoted token to)
                    t := CASE WHEN token_quoted THEN cur
                              ELSE translate(btrim(cur),
                                             'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                                             'abcdefghijklmnopqrstuvwxyz') END;
                    IF t = '' THEN
                        -- an empty element is invalid list syntax
                        tokens := NULL;
                        EXIT;
                    END IF;
                    tokens := array_append(tokens, t);
                    cur := '';
                    token_quoted := false;
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
                    -- the final element folds like the comma-separated
                    -- ones: quoted content EXACT, unquoted ASCII-only
                    t := CASE WHEN token_quoted THEN cur
                              ELSE translate(btrim(cur),
                                             'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                                             'abcdefghijklmnopqrstuvwxyz') END;
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
        -- resolution, parsed as names above. $user expands to the
        -- identity OBSERVED during the capture (current_user in the
        -- capture session -- a DBA startup role default like SET
        -- role = tenant makes the session act as that role, and
        -- PostgreSQL resolves $user against it), NOT the login name:
        -- the login-name substitution used to drop the tenant schema
        -- off the path and silently flip the unqualified resolution.
        -- The exists-filter applies to the substituted identity's
        -- token and to the login name alike: the token only stays
        -- while a schema of that name exists. When the login had no
        -- setting at all, the observation IS the built-in "$user",
        -- public -- this branch preserves it exactly like a DBA-set
        -- value.
        FOREACH t IN ARRAY tokens LOOP
            IF t = '$user' THEN
                -- an UNRESOLVED $user (the observed identity held no
                -- USAGE on its same-named schema, so PostgreSQL
                -- skipped it during resolution) must not enter the
                -- prefix: provisioning grants the owner role USAGE
                -- later, and a stored tenant-first path would then
                -- silently flip the unqualified resolution to that
                -- schema. Omit the token; the configured order
                -- decides.
                IF COALESCE(user_resolved, 'f') NOT IN ('t', 'true') THEN
                    CONTINUE;
                END IF;
                t := COALESCE(observed_user, user_name);
            END IF;
            IF t IN (user_name, observed_user)
               AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
                               WHERE n.nspname = t) THEN
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
    -- quote_ident-joined names. Written ONLY by runs that captured
    -- and by runs the store already governs (they may reduce it by
    -- the revoke delta): a run that did not capture must never
    -- INITIALIZE the store -- a second entry's new-login run used to
    -- write the empty store and make the later legacy-migration run
    -- of another login in the same role skip its capture entirely
    -- (regression: the old login silently resolved to the public
    -- twin after its migration). THREE outcomes: an explicitly empty
    -- resolution is PRESERVED as the canonical empty store (the
    -- empty-state rule above); a NON-empty prefix is stored as
    -- names; an EXHAUSTED prefix (every legacy entry left the
    -- configuration) RESETS the role's store setting entirely -- a
    -- present-but-empty store would read as an explicitly empty
    -- resolution on the next run and suppress every configured
    -- schema (regression: removing the last prefix schema made the
    -- next run apply an EMPTY path and the unqualified query failed
    -- with "relation does not exist"). After the reset, the next run
    -- recomputes from the maintained state -- no store, no capture,
    -- the configured order -- not from a phantom empty capture; a
    -- capture run whose entire prefix was revoked never initializes
    -- a store at all (resetting a nonexistent setting is a no-op).
    IF store_raw IS NOT NULL OR captured THEN
        IF path_empty THEN
            store_sp := quote_literal('');
        ELSIF cardinality(prefix) = 0 THEN
            store_sp := NULL;
        ELSE
            SELECT string_agg(quote_ident(e), ',')
            INTO store_sp FROM unnest(prefix) AS e;
        END IF;
        BEGIN
            IF store_sp IS NULL THEN
                EXECUTE format('ALTER ROLE %I IN DATABASE %I RESET search_path',
                               role_name, db);
            ELSE
                EXECUTE format('ALTER ROLE %I IN DATABASE %I SET search_path = %s',
                               role_name, db, store_sp);
            END IF;
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
