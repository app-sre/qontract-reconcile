-- owner-role deprovision mode: remove the login user, keep the owner
-- role. The owner role is shared across rotation entries and is never
-- dropped by the integration.
-- rendered values: {database} {username} {admin_user}
\set ON_ERROR_STOP on

\c "{database}"

-- cutoff: block new connections and terminate open sessions of the
-- departing login first. Otherwise a session that still acts as the
-- login could create objects after the reassignment below, and
-- DROP OWNED would remove them.
ALTER ROLE "{username}" NOLOGIN;
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE usename = '{username}'
  AND pid <> pg_backend_pid();

-- reassign objects the user still owns (e.g. created before the
-- migration to the owner-role model), then revoke all its privileges.
-- DROP OWNED is the documented cleanup step after the reassignment,
-- without it DROP ROLE fails on remaining privileges.
REASSIGN OWNED BY "{username}" TO "{admin_user}";
DROP OWNED BY "{username}";
DROP ROLE IF EXISTS "{username}";\gexec
