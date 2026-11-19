-- legacy provision mode: the login user owns its own schema and gets
-- table level grants per the access list. Password is set on every run.
-- rendered values: {database} {database_literal} {username} {username_literal} {admin_user} {access_list} {revoke_list}
-- the user password is passed as the psql variable db_user_password via -v
\set ON_ERROR_STOP on

SELECT NOT EXISTS (SELECT FROM pg_database WHERE datname = '{database_literal}') AS dam_db_new \gset
SELECT 'CREATE DATABASE "{database}"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{database_literal}');\gexec
\if :dam_db_new
/* revoke only required for databases lower version 15
   this makes the behaviour compliant with postgres 15, writes are only allowed
   in the schema created for the role/user */
REVOKE ALL ON DATABASE "{database}" FROM public;
\endif

\c "{database}"

-- everything from here to the COMMIT is one transaction: a failing
-- grant rolls back the password change, so the vault credential that
-- is still published remains valid
BEGIN;

select 'CREATE ROLE "{username_ident_literal}"'
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{username_literal}');\gexec

ALTER ROLE "{username}" WITH LOGIN PASSWORD :'db_user_password' VALID UNTIL 'infinity';

GRANT CONNECT ON DATABASE "{database}" to "{username}";

-- rds specific, grant role to admin or create schema fails
GRANT "{username}" to "{admin_user}";
CREATE SCHEMA IF NOT EXISTS "{username}" AUTHORIZATION "{username}";

-- revoke grants that were removed from the configuration since the last run
DO $$
DECLARE
    entry text;
BEGIN
    FOREACH entry IN ARRAY string_to_array('{revoke_list}', ';') LOOP
        IF entry <> '' AND EXISTS (
            SELECT 1 FROM pg_catalog.pg_namespace
            WHERE nspname = split_part(entry, '|', 1)
        ) THEN
            EXECUTE format('REVOKE %s ON ALL TABLES IN SCHEMA %I FROM %I',
                           split_part(entry, '|', 2), split_part(entry, '|', 1),
                           '{username_literal}');
        END IF;
    END LOOP;
END $$;

-- apply the configured grants
DO $$
DECLARE
    entry text;
BEGIN
    FOREACH entry IN ARRAY string_to_array('{access_list}', ';') LOOP
        IF entry <> '' THEN
            EXECUTE format('GRANT %s ON ALL TABLES IN SCHEMA %I TO %I',
                           split_part(entry, '|', 2), split_part(entry, '|', 1),
                           '{username_literal}');
        END IF;
    END LOOP;
END $$;

COMMIT;
