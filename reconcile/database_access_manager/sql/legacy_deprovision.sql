-- legacy deprovision mode: revoke the configured grants and remove
-- the login user.
-- rendered values: {database} {username} {admin_user} {access_list}
\set ON_ERROR_STOP on

DO $$
DECLARE
    entry text[];
BEGIN
    FOREACH entry IN ARRAY string_to_array('{access_list}', ';') LOOP
        IF entry <> '' THEN
            EXECUTE format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I FROM %I',
                           split_part(entry, '|', 1), '{username}');
        END IF;
    END LOOP;
END $$;

\c "{database}"

REASSIGN OWNED BY "{username}" TO "{admin_user}";
DROP ROLE IF EXISTS "{username}";\gexec
