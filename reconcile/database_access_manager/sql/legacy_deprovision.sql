-- legacy deprovision mode: revoke the configured grants and remove
-- the login user.
-- rendered values: {database} {username} {username_literal} {admin_user} {access_list}
\set ON_ERROR_STOP on

DO $$
DECLARE
    entry text;
BEGIN
    FOREACH entry IN ARRAY string_to_array('{access_list}', ';') LOOP
        IF entry <> '' THEN
            EXECUTE format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I FROM %I',
                           split_part(entry, '|', 1), '{username}');
        END IF;
    END LOOP;
END $$;

\c "{database}"

-- cutoff: block new connections and terminate open sessions of the
-- departing login first, so no new objects can appear between the
-- reassignment and the role removal
ALTER ROLE "{username}" NOLOGIN;
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE usename = '{username_literal}'
  AND pid <> pg_backend_pid();

REASSIGN OWNED BY "{username}" TO "{admin_user}";
DROP ROLE IF EXISTS "{username}";\gexec
