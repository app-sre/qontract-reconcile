-- owner-role deprovision mode: remove the login user, keep the owner
-- role. The owner role is shared across rotation entries and is never
-- dropped by the integration.
-- rendered values: {database} {username} {username_literal} {admin_user}
\set ON_ERROR_STOP on

\c "{database}"

-- a login that does not exist any more is a successful no-op
-- (psql conditionals: \if / \endif, not PL/pgSQL IF)
SELECT NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{username_literal}') AS dam_login_absent \gset
\if :dam_login_absent
\echo 'login {username_literal} does not exist, nothing to deprovision'
\quit
\endif

-- cutoff: block new connections and terminate open sessions of the
-- departing login first. Otherwise a session that still acts as the
-- login could create objects after the reassignment below, and
-- DROP OWNED would remove them.
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

-- reassign objects the user still owns (e.g. created before the
-- migration to the owner-role model), then revoke all its privileges.
-- DROP OWNED is the documented cleanup step after the reassignment,
-- without it DROP ROLE fails on remaining privileges.
REASSIGN OWNED BY "{username}" TO "{admin_user}";
DROP OWNED BY "{username}";
DROP ROLE IF EXISTS "{username}";\gexec
