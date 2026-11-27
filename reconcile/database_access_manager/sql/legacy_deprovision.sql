-- legacy deprovision mode: revoke the configured grants and remove
-- the login user.
-- rendered values: {database} {username} {username_literal} {admin_user} {access_list}
\set ON_ERROR_STOP on

-- connect to the target database FIRST: the revoke block and all
-- subsequent statements operate on database-local grants. Running
-- the revoke in the admin database (where the job starts) would
-- silently skip schemas that only exist in the target database.
\c "{database}"

-- a login that does not exist any more is a successful no-op
-- (psql conditionals: \if / \endif, not PL/pgSQL IF)
SELECT NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{username_literal}') AS dam_login_absent \gset
\if :dam_login_absent
\echo 'login {username_literal} does not exist, nothing to deprovision'
\quit
\endif

-- revoke the configured grants (in the TARGET database, after \c)
DO $$
DECLARE
    entry text;
BEGIN
    FOREACH entry IN ARRAY string_to_array('{access_list}', ';') LOOP
        IF entry <> '' AND EXISTS (
            SELECT 1 FROM pg_catalog.pg_namespace
            WHERE nspname = split_part(entry, '|', 1)
        ) THEN
            EXECUTE format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I FROM %I',
                           split_part(entry, '|', 1), '{username_literal}');
        END IF;
    END LOOP;
END $$;

-- cutoff: block new connections and terminate open sessions of the
-- departing login first, so no new objects can appear between the
-- reassignment and the role removal
ALTER ROLE "{username}" NOLOGIN;
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE usename = '{username_literal}'
  AND pid <> pg_backend_pid();

-- wait for the terminated sessions to actually exit:
-- pg_terminate_backend only signals them, cleanup must not start
-- while they can still commit. Works on all supported versions
-- (the two-argument pg_terminate_backend is PostgreSQL 14+).
DO $$
DECLARE
    remaining int;
    tries int := 0;
BEGIN
    LOOP
        -- the activity snapshot is cached within a transaction: a
        -- backend that exited during the sleep would stay visible
        -- otherwise and the loop would time out
        PERFORM pg_stat_clear_snapshot();
        SELECT count(*) INTO remaining
        FROM pg_stat_activity
        WHERE usename = '{username_literal}'
          AND pid <> pg_backend_pid();
        EXIT WHEN remaining = 0;
        tries := tries + 1;
        IF tries > 60 THEN
            RAISE EXCEPTION 'sessions of % did not terminate in time',
                '{username_literal}';
        END IF;
        PERFORM pg_sleep(0.5);
    END LOOP;
END $$;

REASSIGN OWNED BY "{username}" TO "{admin_user}";
DROP OWNED BY "{username}";
DROP ROLE IF EXISTS "{username}";\gexec
