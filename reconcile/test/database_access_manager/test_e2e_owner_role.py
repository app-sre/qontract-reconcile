"""End-to-end tests for the database-access-manager owner-role SQL templates.

These tests execute the rendered SQL templates against real PostgreSQL
containers (docker or podman) under the production-shaped
authentication policy of the shared fixtures: the fixture roles
(``postgres`` and the executor simulating the RDS master user) connect
without a password, every application login must authenticate with its
real password (scram-sha-256). Application connections therefore
always go through ``pg.login(...)``.

The module covers owner-role mode (``role`` set): a stable NOLOGIN role
owns the managed application objects, the application connects with a
swappable login that is a member of the role and automatically acts as
the role in new connections.

Run them explicitly:
    uv run pytest reconcile/test/database_access_manager/test_e2e_owner_role.py -v
"""

from __future__ import annotations

import dataclasses
import subprocess
import time
from typing import TYPE_CHECKING

import pytest

from reconcile.database_access_manager.integration import (
    JobFailedError,
    _generated_username,
    _job_name,
    _process_db_access,
    _resolve_username,
    _validate_role_sharing,
)
from reconcile.test.database_access_manager.conftest import (
    DB_PASSWORD,
    E2E_ADMIN_SECRET_NAME,
    E2E_JOB_IMAGE,
    E2E_STATE_KEY,
    EXECUTOR,
    PG_VERSIONS,
    DamJobHarness,
    _assert_owner,
    _create_database,
    _database_owner,
    _render_deprovision,
    _render_provision,
    build_script,
    make_db_access,
)
from reconcile.utils.secret_reader import SecretNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable
    from subprocess import CompletedProcess

    from reconcile.gql_definitions.terraform_resources.database_access_manager import (
        DatabaseAccessV1,
    )
    from reconcile.test.database_access_manager.conftest import PostgresContainer

# | ID  | Use case                                                                 | Observable guarantee                                                                                                                                                                                                                                                               | Test                                                                                                                                                                                                                        |
# | --- | ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
# | O01 | Move an existing app off the postgres login                              | The postgres database keeps its owner OID wherever the job started; the application tables change owner to the app role.                                                                                                                                                           | `test_migration_off_postgres_login`                                                                                                                                                                                         |
# | O02 | Empty access on an admin database                                        | The admin database never changes owner -- named postgres or differently, target or start database; no takeover without configuration.                                                                                                                                              | `test_empty_access_does_not_take_over_admin_database`                                                                                                                                                                       |
# | O03 | Fresh tenant with a dedicated database                                   | DAM creates DB, NOLOGIN owner role and login; the new DB belongs to the role; a fresh connection acts as the role (session_user/current_user).                                                                                                                                     | `test_dedicated_database_created_by_dam`                                                                                                                                                                                    |
# | O04 | The migrated app runs its next schema migration                          | Without SET ROLE: SELECT, INSERT, ALTER, CREATE INDEX/TABLE; routines usable; new tables belong to the app role.                                                                                                                                                                   | `test_migrated_app_runs_next_migration`                                                                                                                                                                                     |
# | O05 | App DDL in a schema DAM cannot take over                                 | Write access keeps CREATE (also after ALL -> SELECT,INSERT); provisioning needs no TEMP privilege on the target database.                                                                                                                                                          | `test_app_ddl_in_non_transferable_schema`                                                                                                                                                                                   |
# | O06 | DDL the executor cannot deliver                                          | Provisioning fails before commit on the missing schema CREATE with a specific error; no partially created logins or roles remain.                                                                                                                                                  | `test_provision_fails_when_executor_cannot_grant_create`                                                                                                                                                                    |
# | O07 | Application objects migrate, foreign and extension objects are protected | Every object type incl. a foreign table transfers to the role; outside-scope, third-party and extension members keep their owner.                                                                                                                                                  | `test_object_zoo_transferred_foreign_and_extension_protected`                                                                                                                                                               |
# | O08 | Two apps share one database in separate schemas                          | Both keep CONNECT; each reads only its own data with its own password.                                                                                                                                                                                                             | `test_two_apps_share_database_separate_schemas`                                                                                                                                                                             |
# | O09 | Explicit foreign read access, granted then revoked                       | Read works, write and CREATE do not; after the revoke the access and default privileges are gone; the foreign owner stays.                                                                                                                                                         | `test_foreign_read_access_granted_then_revoked`, `test_transient_grants_removed_with_schema`                                                                                                                                |
# | O10 | CONNECT when PUBLIC lacks it                                             | The login connects with its password; without grant option the job fails on the specific CONNECT error for app and database.                                                                                                                                                       | `test_connect_granted_when_public_lacks_it`, `test_provision_fails_when_executor_cannot_grant_connect`                                                                                                                      |
# | O11 | Re-provision, stale schema, deprovision, missing login                   | Repeats keep data, owners, privileges and the credential; both no-op removals succeed; the shared role keeps the data.                                                                                                                                                             | `test_reprovision_and_deprovision_convergence`                                                                                                                                                                              |
# | O12 | Provisioning under a concurrently held lock                              | The provision demonstrably waits in pg_locks; after release data and owners converge.                                                                                                                                                                                              | `test_concurrent_provision_waits_for_lock`                                                                                                                                                                                  |
# | O13 | Partial grants do not suffice                                            | A granted SELECT is not enough: missing table privileges or schema USAGE fail with their specific errors before commit; ALL verifies the version bundle incl. MAINTAIN (PG17+).                                                                                                    | `test_provision_fails_when_executor_can_grant_only_part_of_the_table_privileges`, `test_provision_fails_when_executor_cannot_grant_schema_usage`, `test_all_claim_checks_the_version_privilege_bundle`                      |
# | M01 | A legacy tenant adds only role                                           | Same login and password before/after; data, resolution and DDL stay usable; new objects belong to the role (9 variants: access lists, dash names, setting levels)., and a failed capture connection aborts before the switch so a retry captures the original resolution           | `test_legacy_tenant_adds_role_same_credentials`, `test_capture_failure_retry_preserves_resolution`                                                                                                                          |
# | M02 | The old app keeps writing during the migration                           | Both logins work in the transition; the follow-up run adopts late tables without password rotation or full revoke.                                                                                                                                                                 | `test_old_app_writes_during_migration`, `test_convergence_reenqueue_adopts_late_tables`                                                                                                                                     |
# | M03 | An application session opened before the migration keeps writing         | Late objects are adopted by the next unchanged run; the rotation login can ALTER them; deterministic barriers prove the session (incl. a provoked delayed start).                                                                                                                  | `test_open_legacy_session_late_objects_managed`                                                                                                                                                                             |
# | M04 | Implicit legacy schema not on the captured path                          | billing.late_orders transfers anyway; v2 alters it qualified; billing stays off the effective path.                                                                                                                                                                                | `test_open_legacy_session_late_objects_managed` (explicit-path-implicit-schema)                                                                                                                                             |
# | M05 | Credential rotation v1/v2 in the same role                               | Both credentials work in parallel with identical resolution; v1's open session ends on removal; the migrated tenant's v2 keeps marker and DDL schema after the legacy login is removed.                                                                                            | `test_rotation_keeps_unqualified_access`                                                                                                                                                                                    |
# | M06 | Second login vs. migration order                                         | In both orders the old login reads its marker immediately after the migration job, before any further reconcile; both converge identically.                                                                                                                                        | `test_second_login_order_with_legacy_migration`                                                                                                                                                                             |
# | M07 | Two fresh rotation entries share a new role                              | Exactly one shared role; no swapped credentials; a transient failed job converges on retry; nothing published before success.                                                                                                                                                      | `test_two_rotation_entries_share_fresh_role`                                                                                                                                                                                |
# | M08 | Transition window with a non-superuser old app                           | The new app reads/writes immediately and the old login works with the new objects (operations, both directions); late old objects adopt on the next run.                                                                                                                           | `test_old_app_writes_during_migration_non_superuser_executor`                                                                                                                                                               |
# | J01 | The tenant uses the credential DAM issued                                | Login with exactly the published record (user, db.name, password); a failed job publishes nothing new and the old credential keeps working.                                                                                                                                        | `test_generated_login_credential_end_to_end`                                                                                                                                                                                |
# | J02 | Credentials survive convergence and rotation                             | The old credential keeps working; the convergence re-enqueue reuses the vault secret via the production path; rotation adds a new login, not a password change.                                                                                                                    | `test_legacy_migration_keeps_credential_and_adopts_late_objects`, `test_job_credential_reuses_vault_secret_after_job_expiry`, `test_convergence_reenqueue_adopts_late_tables`, `test_two_rotation_entries_share_fresh_role` |
# | P01 | Default "$user", public resolution survives the role switch              | The shop marker before/after, after an unchanged rerun and with v2; unqualified creates land in the shop schema; the access order does not silently override the legacy path., also across a failed capture connection and its retry (the switch and the path activate atomically) | `test_legacy_tenant_adds_role_same_credentials`, `test_capture_failure_retry_preserves_resolution`                                                                                                                          |
# | P02 | Dash login names round-trip unquoted                                     | The shop-app marker survives migration, unchanged reruns and v2; no quote corruption in the stored path.                                                                                                                                                                           | `test_legacy_tenant_adds_role_same_credentials` (dash-login-name)                                                                                                                                                           |
# | P03 | Single-element search paths stay valid                                   | First run, second run and rotation deliver the original marker, never the public twin; a valid element is never treated as empty.                                                                                                                                                  | `test_single_element_search_path_keeps_original_marker`                                                                                                                                                                     |
# | P04 | Setting levels resolve by real precedence                                | login-in-db before login-wide before db-wide before server-wide/built-in, with markers exposing a wrong winner (incl. role-wide vs db-wide without a more specific override).                                                                                                      | `test_legacy_tenant_adds_role_same_credentials` (setting variants)                                                                                                                                                          |
# | P05 | Server-wide search_path default is captured                              | Without an override the public marker survives migration, rerun and rotation; a specific login override governs; the executor's private path never leaks.                                                                                                                          | `test_server_wide_search_path_default_is_captured`                                                                                                                                                                          |
# | P06 | DBA-set path values round-trip                                           | Single, quoted, $user, mixed-case, comma- and quote-containing names: the native resolution survives; a separator-containing name stays one name and unmanaged.                                                                                                                    | `test_dba_search_path_values_round_trip`                                                                                                                                                                                    |
# | P07 | Unusable and explicitly empty path entries                               | No invented objects or ownership from path tokens; qualified access keeps working; a previously failing unqualified query never unnoticed returns public data.                                                                                                                     | `test_unusable_and_empty_search_path_entries`                                                                                                                                                                               |
# | P08 | Intentional order changes apply and stay stable                          | The sales -> archive marker switch via the production renderer; stable on the unchanged rerun; the second login resolves identically.                                                                                                                                              | `test_search_path_stability`, `test_rotation_keeps_unqualified_access`                                                                                                                                                      |
# | P09 | Incidental role-owned schemas stay out                                   | An app-created archive never becomes the primary path or managed.                                                                                                                                                                                                                  | `test_search_path_stability`                                                                                                                                                                                                |
# | P10 | Removed schemas are not re-managed                                       | sales stays primary; post-removal admin tables stay admin-owned; the removed default ACLs stay revoked.                                                                                                                                                                            | `test_search_path_stability`                                                                                                                                                                                                |
# | P11 | Removed public is not re-managed as a path fallback                      | The admin table created after the removal stays admin-owned; configured sales stays managed; the DB owner OID is unchanged.                                                                                                                                                        | `test_removed_public_not_remanaged`                                                                                                                                                                                         |
# | P12 | Managed-but-off-path and on-path-but-unmanaged                           | billing stays outside the effective path yet its late table transfers and v2 alters it qualified; public stays a usable fallback without management.                                                                                                                               | `test_open_legacy_session_late_objects_managed`, `test_removed_public_not_remanaged`                                                                                                                                        |


# test passwords (annotated for the secret scanner; not secrets)
P07B_ROTATION_PASSWORD = "P07BRotation2"  # notsecret
P07C_ROTATION_PASSWORD = "P07CRotation2"  # notsecret
M6_SECOND_PASSWORD = "M6SecondPw2"  # notsecret
MIGRATED_V2_PASSWORD = "MigratedPw2"  # notsecret


# ─── helpers ──────────────────────────────────────────────────────────────


def _run_provision(
    pg: PostgresContainer,
    script: str,
    *,
    password: str = DB_PASSWORD,
    admin_user: str = EXECUTOR,
) -> CompletedProcess[str]:
    """Run a provision script as the given executor from the admin database."""
    result = pg.exec_psql(
        admin_user,
        "postgres",
        script,
        extra_args=["-v", f"db_user_password={password}"],
    )
    assert result.returncode == 0, f"provision failed: {result.stderr}"
    assert "ERROR" not in result.stderr, result.stderr
    return result


def _wait_until(
    pg: PostgresContainer,
    database: str,
    sql: str,
    expected: str,
    *,
    what: str,
    timeout: float = 30.0,
) -> None:
    """Poll a query as the bootstrap superuser until it returns the expected value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pg.query("postgres", database, sql) == expected:
            return
        time.sleep(0.5)
    pytest.fail(f"timed out waiting for {what}")


def _qi(name: str) -> str:
    """Quote an identifier for hand-written test SQL (like quote_ident)."""
    return '"' + name.replace('"', '""') + '"'


def _assert_unqualified_marker(
    pg: PostgresContainer,
    db: str,
    user: str,
    password: str,
    expected: str,
    *,
    forbidden: tuple[str, ...] = (),
    where: str,
) -> None:
    """Read the false-table oracle on a real password connection.

    The ``orders`` table exists in at least two schemas with the same
    id but distinct ``note`` markers; the unqualified query must
    return EXACTLY the expected marker, and a forbidden marker winning
    is the failure this oracle exists to catch (never a mere
    "query still succeeds").
    """
    result = pg.login(user, password, db, "SELECT note FROM orders WHERE id = 1;")
    assert result.returncode == 0, f"{where}: {result.stderr}"
    assert expected in result.stdout, (
        f"{where}: expected {expected!r}, got {result.stdout}"
    )
    for marker in forbidden:
        assert marker not in result.stdout, (
            f"{where}: forbidden marker {marker!r} won: {result.stdout}"
        )


def _create_foreign_schema(
    pg: PostgresContainer, database: str, schema: str, owner: str, table: str
) -> None:
    """Create a schema owned by a third-party role the executor does not control.

    The setup runs as the bootstrap superuser and the executor never
    becomes a member of the owner, so the schema stays foreign to the
    executor on every PostgreSQL version. The executor receives USAGE
    and CREATE with grant option (like an RDS master user on a foreign
    schema) so the provision script can re-grant USAGE to the owner
    role, and the test can create future tables there for the
    default-privilege assertions.
    """
    result = pg.exec_psql(
        "postgres",
        database,
        f"CREATE ROLE {owner} LOGIN; "
        f"CREATE SCHEMA {schema} AUTHORIZATION {owner}; "
        f"SET ROLE {owner}; "
        f"CREATE TABLE {schema}.{table} (id int, data text); "
        f"INSERT INTO {schema}.{table} VALUES (1, 'hello'); "
        f"RESET ROLE; "
        f"GRANT USAGE, CREATE ON SCHEMA {schema} TO {EXECUTOR} WITH GRANT OPTION; "
        f"GRANT SELECT ON {schema}.{table} TO {EXECUTOR} WITH GRANT OPTION;",
    )
    assert result.returncode == 0, f"foreign schema setup failed: {result.stderr}"


def _run_harness_entry(
    harness: DamJobHarness, db_access: DatabaseAccessV1, state_key: str
) -> None:
    """Run one db-access entry through the production _process_db_access
    under its own state key.

    DamJobHarness.run models a single entry under the shared E2E state
    key. In production the entry name is part of the state key
    (provisioner/identifier/entry-name), so rotation entries sharing an
    owner role differ in the state key and therefore in their generated
    login names. The harness state, job controller, OpenShift client
    and vault double are shared here, exactly like one reconciliation
    of one RDS resource with several database_access entries.
    """
    _process_db_access(
        dry_run=False,
        state=harness.state,
        state_key=state_key,
        db_access=db_access,
        namespace=harness.namespace,
        admin_secret_name=E2E_ADMIN_SECRET_NAME,
        engine="postgres",
        secret_reader=harness.secret_reader,
        vault_output_path="vault-out",
        vault_client=harness.vault_client,
        job_image=E2E_JOB_IMAGE,
        pull_secret_path=None,
        pull_secret_version=None,
    )


def _serve_published_credentials(harness: DamJobHarness) -> None:
    """Serve the credentials DAM published to the vault double through
    the secret reader double.

    The production _vault_connection read-back then works like a real
    vault holding the existing app secret: a later job reuses the
    published password instead of a regenerated one.
    """

    def _read_all(secret: dict[str, str]) -> dict[str, str]:
        for write in harness.vault_writes:
            if write["path"] == secret["path"]:
                return dict(write["data"])
        raise SecretNotFoundError(f"no secret at {secret['path']}")

    harness.secret_reader.read_all.side_effect = _read_all


# ─── 1. migration off the postgres login ──────────────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_migration_off_postgres_login(postgres: PostgresContainer) -> None:
    """O01 — Move an existing app off the postgres login in database postgres.

    The executor is the postgres superuser itself -- the previous owner
    of both the application objects and the postgres database. The
    application objects transfer to the app role; the DATABASE itself
    must never change owner, wherever the job started: the start
    database guard only protects the database the job connected to, so
    a job started in a DIFFERENT database must not transfer the
    postgres database either (regression: the database named postgres
    used to change owner whenever the job did not start in it).
    """
    pg = postgres
    db = "postgres"

    pg.seed(db, "postgres")
    database_owner_before = _database_owner(pg, db)
    assert database_owner_before == "postgres"
    postgres_datdba = pg.query(
        "postgres",
        "postgres",
        "SELECT datdba FROM pg_database WHERE datname = 'postgres'",
    )

    script = _render_provision(
        db, "cs_app", role="cs_owner", access_list="public|ALL", admin_user="postgres"
    )
    _run_provision(pg, script, admin_user="postgres")

    # the database itself never changes owner
    assert _database_owner(pg, db) == database_owner_before

    # the application tables belong to the app role afterwards
    for table in ("orders", "order_items", "events", "v_open_orders", "custom_seq"):
        _assert_owner(
            pg,
            db,
            f"table {table}",
            f"SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='{table}'",
            "cs_owner",
        )

    # the new app connects with its password and reads the migrated data
    result = pg.login("cs_app", DB_PASSWORD, db, "SELECT count(*) FROM public.orders;")
    assert result.returncode == 0, result.stderr
    assert "3" in result.stdout

    # the same job started in a DIFFERENT database: the start-database
    # guard does not apply here, the database named postgres must stay
    # protected anyway
    _create_database(pg, "admin_connect", owner="postgres")
    result = pg.exec_psql(
        "postgres",
        "admin_connect",
        script,
        extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
    )
    assert result.returncode == 0, f"provision failed: {result.stderr}"
    assert "ERROR" not in result.stderr, result.stderr

    # the postgres database keeps its owner: the datdba OID is unchanged
    assert (
        pg.query(
            "postgres",
            "postgres",
            "SELECT datdba FROM pg_database WHERE datname = 'postgres'",
        )
        == postgres_datdba
    )

    # the migrated application table still belongs to the app role
    _assert_owner(
        pg,
        db,
        "migrated table",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='orders'",
        "cs_owner",
    )

    # and the app login keeps working on a fresh connection
    result = pg.login("cs_app", DB_PASSWORD, db, "SELECT count(*) FROM public.orders;")
    assert result.returncode == 0, result.stderr
    assert "3" in result.stdout


# ─── 2. the migrated app runs its next schema migration ───────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_migrated_app_runs_next_migration(postgres: PostgresContainer) -> None:
    """O04 — The migrated app runs its next schema migration.

    A fresh connection as the app login with its password, WITHOUT a
    manual SET ROLE (the per-database role default applies), can read,
    write, ALTER existing objects and CREATE new ones. The new table
    belongs to the app role.
    """
    pg = postgres
    db = "role_use_db"
    _create_database(pg, db)
    pg.seed(db, EXECUTOR)

    script = _render_provision(db, "cs_app", role="cs_owner", access_list="public|ALL")
    _run_provision(pg, script)

    # read
    result = pg.login("cs_app", DB_PASSWORD, db, "SELECT count(*) FROM public.orders;")
    assert result.returncode == 0, result.stderr
    assert "3" in result.stdout

    # write
    result = pg.login(
        "cs_app",
        DB_PASSWORD,
        db,
        "INSERT INTO public.orders (customer_id, total) VALUES (99, 1.00);",
    )
    assert result.returncode == 0, result.stderr

    # DDL: ALTER TABLE and CREATE INDEX on migrated objects
    result = pg.login(
        "cs_app",
        DB_PASSWORD,
        db,
        "ALTER TABLE public.orders ADD COLUMN e2e_col text;",
    )
    assert result.returncode == 0, result.stderr
    result = pg.login(
        "cs_app",
        DB_PASSWORD,
        db,
        "CREATE INDEX idx_e2e ON public.orders (e2e_col);",
    )
    assert result.returncode == 0, result.stderr

    # DDL: CREATE TABLE (the next migration's new table)
    result = pg.login(
        "cs_app", DB_PASSWORD, db, "CREATE TABLE public.e2e_new (id int);"
    )
    assert result.returncode == 0, result.stderr

    # DML on the new table
    result = pg.login(
        "cs_app", DB_PASSWORD, db, "INSERT INTO public.e2e_new VALUES (42);"
    )
    assert result.returncode == 0, result.stderr

    # the new table belongs to the app role
    _assert_owner(
        pg,
        db,
        "app-created table",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='e2e_new'",
        "cs_owner",
    )

    # migrated routines keep working: function, procedure, aggregate
    result = pg.login("cs_app", DB_PASSWORD, db, "SELECT public.get_order_total(1);")
    assert result.returncode == 0, result.stderr
    assert "100.00" in result.stdout
    result = pg.login("cs_app", DB_PASSWORD, db, "CALL public.reset_pending();")
    assert result.returncode == 0, result.stderr
    result = pg.login(
        "cs_app",
        DB_PASSWORD,
        db,
        "SELECT public.max_qty(qty) > 0 FROM public.order_items;",
    )
    assert result.returncode == 0, result.stderr
    assert "t" in result.stdout


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["15", "16", "17", "18"], indirect=True)
def test_app_ddl_in_non_transferable_schema(postgres: PostgresContainer) -> None:
    """O05 — App DDL when DAM can grant CREATE on public but cannot take over the schema.

    In the postgres database on PG15+ public is owned by
    pg_database_owner (the database owner), which the executor cannot
    transfer. The entry configures write access (public|ALL): the app
    role must keep CREATE so the application can run its next
    migration there (regression: the transient CREATE used to be
    revoked unconditionally). A later grant change on the same schema
    away from ALL (to SELECT,INSERT) must keep CREATE as well: the
    revoke delta strips the old grants together with CREATE, and the
    configured write access still requires DDL (regression: CREATE
    used to stay lost after the change).

    The executor holds exactly the privileges DAM needs (CONNECT,
    role management, CREATE on public with grant option) and nothing
    more: TEMP is revoked from PUBLIC on the database and never
    re-granted to the executor. Provisioning must not depend on the
    TEMP privilege -- an internal helper table must not abort a job
    whose real work is fully privileged (regression: the captured
    login context used to live in a TEMP table, which failed the job
    with "permission denied to create temporary tables"). Neither DAM
    nor this test grants TEMP as a workaround, and the executor still
    lacks TEMP after the runs.
    """
    pg = postgres
    db = "postgres"

    # rds_superuser-like: the executor may grant CREATE on public but
    # cannot become the database owner
    pg.exec_psql(
        "postgres",
        db,
        f"GRANT CREATE ON SCHEMA public TO {EXECUTOR} WITH GRANT OPTION;",
    )
    # a hardened database: TEMP revoked from PUBLIC, so the executor
    # (no direct grant either) holds no privilege beyond what DAM
    # needs -- asserted before the run so the red/green state of the
    # environment is proven, not assumed
    pg.exec_psql("postgres", db, "REVOKE TEMP ON DATABASE postgres FROM public;")
    assert (
        pg.query(
            EXECUTOR, db, f"SELECT has_database_privilege('{EXECUTOR}', '{db}', 'TEMP')"
        )
        == "f"
    )

    pg.seed(db, EXECUTOR)

    script = _render_provision(db, "cs_app", role="cs_owner", access_list="public|ALL")
    _run_provision(pg, script)

    # the schema stayed with pg_database_owner
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='public'",
        )
        == "pg_database_owner"
    )

    # provisioning worked without the TEMP privilege: the executor
    # still lacks it (no silent workaround grant anywhere in the
    # script) and the postgres database owner is unchanged
    assert (
        pg.query(
            EXECUTOR, db, f"SELECT has_database_privilege('{EXECUTOR}', '{db}', 'TEMP')"
        )
        == "f"
    )
    assert _database_owner(pg, db) == "postgres"

    # the app runs its next migration: CREATE TABLE without SET ROLE
    result = pg.login(
        "cs_app", DB_PASSWORD, db, "CREATE TABLE public.next_migration (id int);"
    )
    assert result.returncode == 0, result.stderr

    # and the new table belongs to the app role
    _assert_owner(
        pg,
        db,
        "app-created table",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='next_migration'",
        "cs_owner",
    )

    # the entry's grants change from ALL to SELECT,INSERT through the
    # production renderer: the computed revoke delta (public|ALL)
    # strips the old grants before the new ones are applied
    old_config = make_db_access(
        database=db, username="cs_app", role="cs_owner", access=[("public", ("ALL",))]
    )
    new_config = make_db_access(
        database=db,
        username="cs_app",
        role="cs_owner",
        access=[("public", ("SELECT", "INSERT"))],
    )
    change_script = build_script(new_config, old_config)
    _run_provision(pg, change_script)

    # the app still runs DDL there on a fresh password connection
    # without SET ROLE: the configured write access keeps CREATE on
    # the non-transferable schema
    result = pg.login(
        "cs_app", DB_PASSWORD, db, "CREATE TABLE public.after_change (id int);"
    )
    assert result.returncode == 0, result.stderr

    # and that table belongs to the app role as well
    _assert_owner(
        pg,
        db,
        "app-created table",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='after_change'",
        "cs_owner",
    )

    # the change run kept the hardened state too: no TEMP for the
    # executor, the postgres database owner unchanged
    assert (
        pg.query(
            EXECUTOR, db, f"SELECT has_database_privilege('{EXECUTOR}', '{db}', 'TEMP')"
        )
        == "f"
    )
    assert _database_owner(pg, db) == "postgres"


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["15", "16", "17", "18"], indirect=True)
def test_provision_fails_when_executor_cannot_grant_create(
    postgres: PostgresContainer,
) -> None:
    """O06 — Provisioning fails with the specific CREATE error when it cannot grant.

    The inverse of ``test_app_ddl_in_non_transferable_schema``: the
    entry configures write access (public|ALL) on the non-transferable
    public schema of the postgres database, but the executor has NO
    grant option for CREATE there. PostgreSQL only issues a WARNING
    ("no privileges were granted") for such a GRANT -- it never raises
    -- so the EXCEPTION tolerance of the 5j write-branch is not enough
    on its own. The script must verify the owner role's effective
    CREATE privilege before the commit and fail with the specific
    error naming the role, the schema and CREATE (regression: the job
    used to complete successfully although DAM had promised the
    application DDL in the migration schema and silently not delivered
    it). The public schema stays empty so no table transfer can end
    the job for a different reason.
    """
    pg = postgres
    db = "postgres"

    # sanity: the executor really lacks CREATE on public -- on PG15+
    # the schema belongs to pg_database_owner (the postgres database
    # is owned by the bootstrap superuser, not by the executor) and
    # the default PUBLIC grant is gone; the fixture only gives the
    # executor CREATEDB and CREATEROLE
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_schema_privilege('test_admin', 'public', 'CREATE')",
        )
        == "f"
    )

    script = _render_provision(db, "cs_app", role="cs_owner", access_list="public|ALL")
    result = pg.exec_psql(
        EXECUTOR,
        db,
        script,
        extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
    )

    # the script fails with EXACTLY the specific CREATE verification
    # error, not just any failure
    assert result.returncode != 0, (
        "provision succeeded although the owner role has no CREATE on "
        "public and the executor cannot grant it"
    )
    assert (
        "owner role cs_owner lacks CREATE on schema public "
        "required for DDL migrations -- the executor cannot grant it" in result.stderr
    ), result.stderr

    # the failure stemmed from the missing schema CREATE and rolled
    # the whole transaction back: NO partially created login or owner
    # role remains (roles are cluster-wide, checked in the catalog)
    assert (
        pg.query(
            EXECUTOR,
            "postgres",
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = 'cs_app')",
        )
        == "f"
    ), "the failed provision left the partially created login behind"
    assert (
        pg.query(
            EXECUTOR,
            "postgres",
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = 'cs_owner')",
        )
        == "f"
    ), "the failed provision left the partially created owner role behind"

    # the login really does not exist any more: a connection attempt
    # with its would-be password fails on the missing role
    denied = pg.login("cs_app", DB_PASSWORD, "postgres")
    assert denied.returncode != 0, "the rolled-back login still connects"
    assert "cs_app" in denied.stderr, denied.stderr


# ─── 3. the old app keeps writing during the migration ────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_old_app_writes_during_migration(postgres: PostgresContainer) -> None:
    """M02 — The old app keeps writing during the migration and creates late tables.

    Same constellation as the migration off the postgres login: the
    executor is the postgres superuser in database postgres. Old and
    new app work during the transition, late-created tables move to
    the app role on the next run, data and the database owner are
    unchanged.
    """
    pg = postgres
    db = "postgres"

    pg.seed(db, "postgres")
    database_owner_before = _database_owner(pg, db)

    script = _render_provision(
        db, "cs_app", role="cs_owner", access_list="public|ALL", admin_user="postgres"
    )
    _run_provision(pg, script, admin_user="postgres")

    # the old app (the postgres login) keeps working during the window
    assert pg.query("postgres", db, "SELECT count(*) FROM public.orders") == "3"
    result = pg.exec_psql(
        "postgres",
        db,
        "INSERT INTO public.orders (customer_id, total) VALUES (99, 1.00);",
    )
    assert result.returncode == 0, result.stderr

    # the new app has full access on a fresh password connection
    result = pg.login("cs_app", DB_PASSWORD, db, "SELECT count(*) FROM public.orders;")
    assert result.returncode == 0, result.stderr
    assert "4" in result.stdout

    # the old app creates a late table; the next DAM run picks it up
    result = pg.exec_psql(
        "postgres", db, "CREATE TABLE public.master_created (id int);"
    )
    assert result.returncode == 0, result.stderr
    _run_provision(pg, script, admin_user="postgres")
    _assert_owner(
        pg,
        db,
        "late-created table",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='master_created'",
        "cs_owner",
    )

    # data preserved, database owner unchanged
    assert pg.query("postgres", db, "SELECT count(*) FROM public.orders") == "4"
    assert _database_owner(pg, db) == database_owner_before


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_old_app_writes_during_migration_non_superuser_executor(
    postgres: PostgresContainer,
) -> None:
    """M08 — The old app keeps writing during the migration as a NON-SUPERUSER.

    The variant of ``test_old_app_writes_during_migration`` where the
    old app is not a superuser: it is the executor login itself
    (CREATEROLE/CREATEDB only), working in a MANAGED application
    schema -- so the grants DAM delivers are the only reason the old
    app keeps working, not superuser bypasses.

    Before the migration the old login creates a table WITH a
    sequence in the managed schema. The migration moves schema, table
    AND sequence to the owner role and grants the schema back to the
    executor (5a) plus reverse default privileges (5i). The NEW app
    (a fresh password connection, no SET ROLE) reads the old data and
    writes in the intended schema BEFORE the next reconcile, and the
    OLD login works with the NEW app's objects -- both directions are
    proven by operations, not by inspecting pg_default_acl. Objects
    the old app creates late are owned by the old login until the
    next run adopts them: only then does DDL requiring ownership work
    for the new app.
    """
    pg = postgres
    db = "old_app_managed_db"
    _create_database(pg, db)

    # the old app really is a non-superuser: only CREATEROLE/CREATEDB
    assert (
        pg.query(
            EXECUTOR,
            "postgres",
            "SELECT rolsuper FROM pg_roles WHERE rolname='test_admin'",
        )
        == "f"
    )

    # the old app (the executor login) works in the MANAGED
    # application schema: it creates a table WITH a sequence there
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE SCHEMA appschema; "
        "CREATE TABLE appschema.legacy_data (id serial PRIMARY KEY, payload text); "
        "INSERT INTO appschema.legacy_data (payload) "
        "VALUES ('old-app-row-1'), ('old-app-row-2');",
    )
    assert result.returncode == 0, result.stderr

    # the migration: a fresh DAM login joins a new owner role that
    # takes over the managed schema (the job runs as the executor,
    # the same non-superuser login the old app uses)
    script = _render_provision(
        db,
        "new_app",
        role="cs_old_owner",
        access_list="appschema|ALL",
        schemas_csv="appschema",
    )
    _run_provision(pg, script, password="NewAppPw1")

    # schema, table AND sequence moved to the owner role; the
    # dedicated database belongs to the owner role now
    _assert_owner(
        pg,
        db,
        "old table",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='legacy_data'",
        "cs_old_owner",
    )
    _assert_owner(
        pg,
        db,
        "old sequence",
        "SELECT pg_get_userbyid(relowner) FROM pg_class "
        "WHERE relname='legacy_data_id_seq'",
        "cs_old_owner",
    )
    _assert_owner(
        pg,
        db,
        "managed schema",
        "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='appschema'",
        "cs_old_owner",
    )
    assert _database_owner(pg, db) == "cs_old_owner"

    # the NEW app reads the old data and writes in the intended
    # schema BEFORE the next reconcile: the serial insert exercises
    # the migrated sequence, the unqualified insert proves the
    # search-path target is the managed schema
    result = pg.login(
        "new_app",
        "NewAppPw1",
        db,
        "SELECT payload FROM appschema.legacy_data WHERE id = 2;",
    )
    assert result.returncode == 0, result.stderr
    assert "old-app-row-2" in result.stdout
    result = pg.login(
        "new_app",
        "NewAppPw1",
        db,
        "INSERT INTO appschema.legacy_data (payload) VALUES ('new-app-row-3'); "
        "INSERT INTO legacy_data (payload) VALUES ('new-app-unqual'); "
        "CREATE TABLE appschema.new_app_table (id int, note text); "
        "INSERT INTO appschema.new_app_table VALUES (1, 'from-new-app');",
    )
    assert result.returncode == 0, result.stderr

    # the OLD login works with the NEW app's objects: the reverse
    # default privileges of the migration window deliver the access,
    # proven by operations on the new app's table
    result = pg.exec_psql(
        EXECUTOR, db, "INSERT INTO appschema.new_app_table VALUES (2, 'from-old-app');"
    )
    assert result.returncode == 0, result.stderr
    assert pg.query(EXECUTOR, db, "SELECT count(*) FROM appschema.new_app_table") == "2"
    # and it keeps writing the old table too -- through its membership
    # in the owner role, not through superuser rights
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "INSERT INTO appschema.legacy_data (payload) VALUES ('old-app-row-4');",
    )
    assert result.returncode == 0, result.stderr

    # the old app creates a LATE table with a sequence inside the
    # migration window: it belongs to the old login, not the role
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE appschema.late_old_table (id serial PRIMARY KEY, note text); "
        "INSERT INTO appschema.late_old_table (note) VALUES ('late-old');",
    )
    assert result.returncode == 0, result.stderr
    _assert_owner(
        pg,
        db,
        "late table before adoption",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='late_old_table'",
        EXECUTOR,
    )

    # the new app can USE the late table (the forward default
    # privileges of the migration window, sequence included) ...
    result = pg.login(
        "new_app",
        "NewAppPw1",
        db,
        "INSERT INTO appschema.late_old_table (note) VALUES ('new-app-late');",
    )
    assert result.returncode == 0, result.stderr
    # ... but DDL requiring ownership fails: the role does not own the
    # late objects yet
    result = pg.login(
        "new_app",
        "NewAppPw1",
        db,
        "ALTER TABLE appschema.late_old_table ADD COLUMN extra text;",
    )
    assert result.returncode != 0, "the new app could DDL a table it does not own"
    assert "must be owner" in result.stderr

    # the next run adopts the late objects into the owner role
    _run_provision(pg, script, password="NewAppPw1")
    _assert_owner(
        pg,
        db,
        "late table after adoption",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='late_old_table'",
        "cs_old_owner",
    )
    _assert_owner(
        pg,
        db,
        "late sequence after adoption",
        "SELECT pg_get_userbyid(relowner) FROM pg_class "
        "WHERE relname='late_old_table_id_seq'",
        "cs_old_owner",
    )

    # DDL requiring ownership works for the new app now, and all the
    # data survived the whole transition
    result = pg.login(
        "new_app",
        "NewAppPw1",
        db,
        "ALTER TABLE appschema.late_old_table ADD COLUMN extra text;",
    )
    assert result.returncode == 0, result.stderr
    assert (
        pg.query(EXECUTOR, db, "SELECT count(*) FROM appschema.late_old_table") == "2"
    )
    assert pg.query(EXECUTOR, db, "SELECT count(*) FROM appschema.legacy_data") == "5"


# ─── 4. an existing legacy tenant adds role ───────────────────────


@dataclasses.dataclass(frozen=True)
class _LegacySwitchSpec:
    """One legacy->role switch scenario of the parametrized matrix."""

    variant: str
    login: str
    role: str
    access: tuple[tuple[str, tuple[str, ...]], ...]
    app_table_schema: str
    app_marker: str
    expected_marker: str
    settings: tuple[str, ...] = ()
    create_qualified: bool = False
    public_twin: bool = True
    second_run: bool = False
    rotation_login: str | None = None
    rotation_password: str = ""
    post_switch_ddl: bool = False
    structural_checks: bool = False


_LEGACY_SWITCH_SPECS = [
    pytest.param(  # M01/P01
        _LegacySwitchSpec(
            variant="own-schema-in-access",
            login="app_user",
            role="cs_owner",
            access=(("app_user", ("SELECT", "INSERT")),),
            app_table_schema="app_user",
            app_marker="own-schema-data",
            expected_marker="own-schema-data",
            public_twin=False,
            structural_checks=True,
        ),
        id="own-schema-in-access",
    ),
    pytest.param(  # M01/P01
        _LegacySwitchSpec(
            variant="public-only-access",
            login="shop_app",
            role="shop_owner",
            access=(("public", ("SELECT", "INSERT")),),
            app_table_schema="shop_app",
            app_marker="shop-data",
            expected_marker="shop-data",
            public_twin=True,
            post_switch_ddl=True,
            second_run=True,
            rotation_login="shop_app2",
            rotation_password="ShopRotation2",
        ),
        id="public-only-access",
    ),
    pytest.param(  # M01/P01
        _LegacySwitchSpec(
            variant="public-and-own-schema",
            login="shop_app",
            role="shop_role",
            access=(
                ("public", ("SELECT", "INSERT")),
                ("shop_app", ("SELECT", "INSERT")),
            ),
            app_table_schema="shop_app",
            app_marker="shop-note",
            expected_marker="shop-note",
            rotation_login="shop_app2",
            rotation_password="ShopRotation2",
            post_switch_ddl=True,
        ),
        id="public-and-own-schema",
    ),
    pytest.param(  # P02/M01
        _LegacySwitchSpec(
            variant="dash-login-name",
            login="shop-app",
            role="dash_owner",
            access=(("public", ("SELECT", "INSERT")),),
            app_table_schema="shop-app",
            app_marker="shop-note",
            expected_marker="shop-note",
            second_run=True,
            rotation_login="shop-app2",
            rotation_password="DashRotation2",
        ),
        id="dash-login-name",
    ),
    pytest.param(  # P04
        _LegacySwitchSpec(
            variant="role-wide-setting",
            login="tenant_a",
            role="tenant_a_owner",
            access=(("public", ("SELECT", "INSERT")),),
            app_table_schema="tenant_a",
            app_marker="tenant-note",
            expected_marker="public-note",
            settings=("ALTER ROLE tenant_a SET search_path TO public, tenant_a;",),
            create_qualified=True,
        ),
        id="role-wide-setting",
    ),
    pytest.param(  # P04
        _LegacySwitchSpec(
            variant="database-wide-setting",
            login="tenant_b",
            role="tenant_b_owner",
            access=(("public", ("SELECT", "INSERT")),),
            app_table_schema="tenant_b",
            app_marker="tenant-note",
            expected_marker="public-note",
            settings=("ALTER DATABASE {db} SET search_path TO public, tenant_b;",),
            create_qualified=True,
        ),
        id="database-wide-setting",
    ),
    pytest.param(  # P04
        _LegacySwitchSpec(
            variant="login-in-db-precedence",
            login="tenant_c",
            role="tenant_c_owner",
            access=(("public", ("SELECT", "INSERT")),),
            app_table_schema="tenant_c",
            app_marker="tenant-note",
            expected_marker="public-note",
            settings=(
                "ALTER DATABASE {db} SET search_path TO tenant_c, public;",
                "ALTER ROLE tenant_c SET search_path TO tenant_c, public;",
                (
                    "ALTER ROLE tenant_c IN DATABASE {db} "
                    "SET search_path TO public, tenant_c;"
                ),
            ),
            create_qualified=True,
        ),
        id="login-in-db-precedence",
    ),
    pytest.param(  # P04
        _LegacySwitchSpec(
            variant="role-wide-beats-db-wide",
            login="tenant_d",
            role="tenant_d_owner",
            access=(("public", ("SELECT", "INSERT")),),
            app_table_schema="tenant_d",
            app_marker="tenant-note",
            expected_marker="tenant-note",
            settings=(
                "ALTER ROLE tenant_d SET search_path TO tenant_d, public;",
                "ALTER DATABASE {db} SET search_path TO public, tenant_d;",
            ),
            create_qualified=True,
        ),
        id="role-wide-beats-db-wide",
    ),
    pytest.param(  # P04
        _LegacySwitchSpec(
            variant="role-wide-public-beats-db-wide",
            login="tenant_e",
            role="tenant_e_owner",
            access=(("public", ("SELECT", "INSERT")),),
            app_table_schema="tenant_e",
            app_marker="tenant-note",
            expected_marker="public-note",
            settings=(
                "ALTER ROLE tenant_e SET search_path TO public, tenant_e;",
                "ALTER DATABASE {db} SET search_path TO tenant_e, public;",
            ),
            create_qualified=True,
        ),
        id="role-wide-public-beats-db-wide",
    ),
]


def _run_legacy_switch_scenario(pg: PostgresContainer, spec: _LegacySwitchSpec) -> None:
    """Drive one legacy->role switch scenario against a real container.

    The migration adds ONLY the role: username, database, grants and
    schema order stay identical by construction (the production
    renderer computes both scripts from the same access list, so the
    revoke delta between them is empty). The false-table oracle --
    the unqualified ``orders`` marker query -- is read on real
    password connections before and after the switch, and per the
    scenario's flags after further runs, post-switch DDL and a
    rotation login.
    """
    db = f"legacy_{spec.variant.replace('-', '_')}_db"
    _create_database(pg, db)

    if spec.public_twin:
        # the public twin table with uniquely distinct data
        result = pg.exec_psql(
            EXECUTOR,
            db,
            "CREATE TABLE public.orders (id int, note text); "
            "INSERT INTO public.orders VALUES (1, 'public-note');",
        )
        assert result.returncode == 0, result.stderr

    access: list[tuple[str, tuple[str, ...]]] = [
        (schema, grants) for schema, grants in spec.access
    ]
    legacy_config = make_db_access(database=db, username=spec.login, access=access)
    _run_provision(pg, build_script(legacy_config))

    # the app plants its marker table: unqualified DDL follows the
    # login's effective default (the own schema first), qualified DDL
    # when the effective default resolves elsewhere
    create_table = (
        f"CREATE TABLE {_qi(spec.app_table_schema)}.orders (id int, note text); "
        if spec.create_qualified
        else "CREATE TABLE orders (id int, note text); "
    )
    result = pg.login(
        spec.login,
        DB_PASSWORD,
        db,
        create_table + f"INSERT INTO orders VALUES (1, '{spec.app_marker}');",
    )
    assert result.returncode == 0, result.stderr

    # the DBA-set defaults, applied after the app planted its table
    for setting in spec.settings:
        result = pg.exec_psql(EXECUTOR, db, setting.format(db=db))
        assert result.returncode == 0, result.stderr

    # the false-table oracle's wrong-winner baits: every distinct
    # marker that exists in this scenario's database EXCEPT the
    # expected one (for the setting-level variants the expected
    # resolution IS the public twin, and the app's own-schema data is
    # the bait a wrong capture would deliver)
    bait_markers = {spec.app_marker}
    if spec.public_twin:
        bait_markers.add("public-note")
    forbidden = tuple(
        marker for marker in bait_markers if marker != spec.expected_marker
    )

    # BEFORE the switch: the same login and password work, unqualified
    _assert_unqualified_marker(
        pg,
        db,
        spec.login,
        DB_PASSWORD,
        spec.expected_marker,
        forbidden=forbidden,
        where="before the switch",
    )

    # migrate by ONLY adding role, through the production renderer:
    # the revoke delta is empty -- nothing but the role changed
    role_config = make_db_access(
        database=db, username=spec.login, role=spec.role, access=access
    )
    _run_provision(pg, build_script(role_config, legacy_config))

    # AFTER the switch: a FRESH password login without a manual
    # SET ROLE keeps resolving the same unqualified name
    _assert_unqualified_marker(
        pg,
        db,
        spec.login,
        DB_PASSWORD,
        spec.expected_marker,
        forbidden=forbidden,
        where="after the switch",
    )

    if spec.post_switch_ddl:
        # the app runs its usual migration there: ALTER the existing
        # table and CREATE a new one in the same schema (unqualified
        # DDL follows the search path, whose first entry is the
        # marker schema)
        result = pg.login(
            spec.login,
            DB_PASSWORD,
            db,
            "ALTER TABLE orders ADD COLUMN migrated_at text; "
            "CREATE TABLE migration_log (id int); "
            f"INSERT INTO orders (id, note, migrated_at) "
            f"VALUES (2, '{spec.app_marker}', 'now');",
        )
        assert result.returncode == 0, result.stderr
        # the new unqualified object lands in the marker schema ...
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT EXISTS (SELECT 1 FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = 'migration_log' "
                f"AND n.nspname = '{spec.app_table_schema}')",
            )
            == "t"
        )
        # ... and both tables belong to the owner role, data intact
        _assert_owner(
            pg,
            db,
            "new table in the marker schema",
            "SELECT pg_get_userbyid(relowner) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = 'migration_log' "
            f"AND n.nspname = '{spec.app_table_schema}'",
            spec.role,
        )
        _assert_owner(
            pg,
            db,
            "migrated table in the marker schema",
            "SELECT pg_get_userbyid(relowner) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = 'orders' "
            f"AND n.nspname = '{spec.app_table_schema}'",
            spec.role,
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                f"SELECT count(*) FROM {_qi(spec.app_table_schema)}.orders",
            )
            == "2"
        )

    if spec.structural_checks:
        # objects now owned by the owner role, membership intact,
        # login and data intact
        _assert_owner(
            pg,
            db,
            "table after migration",
            "SELECT pg_get_userbyid(relowner) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = 'orders' "
            f"AND n.nspname = '{spec.app_table_schema}'",
            spec.role,
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                f"SELECT pg_has_role('{spec.login}', '{spec.role}', 'MEMBER')",
            )
            == "t"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                f"SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{spec.login}')",
            )
            == "t"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                f"SELECT count(*) FROM {_qi(spec.app_table_schema)}.orders",
            )
            == "1"
        )

    if spec.second_run:
        _run_provision(pg, build_script(role_config))
        _assert_unqualified_marker(
            pg,
            db,
            spec.login,
            DB_PASSWORD,
            spec.expected_marker,
            forbidden=forbidden,
            where="after another unchanged run",
        )

    if spec.rotation_login:
        # rotation survival: a second login of the same role resolves
        # the same primary schema -- the resolution must not differ
        # just because the login name differs
        rotation_config = make_db_access(
            database=db, username=spec.rotation_login, role=spec.role, access=access
        )
        _run_provision(
            pg, build_script(rotation_config), password=spec.rotation_password
        )
        _assert_unqualified_marker(
            pg,
            db,
            spec.rotation_login,
            spec.rotation_password,
            spec.expected_marker,
            forbidden=forbidden,
            where="rotation login",
        )


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
@pytest.mark.parametrize("spec", _LEGACY_SWITCH_SPECS)
def test_legacy_tenant_adds_role_same_credentials(
    postgres: PostgresContainer, spec: _LegacySwitchSpec
) -> None:
    """M01, P01, P02, P04 — An existing legacy tenant adds role to its entry (parametrized matrix).

    The very same login and password work before and after the switch
    (real password authentication); after the switch unqualified
    lookups keep working without a manual SET ROLE. The grants, the
    schema order and the username stay IDENTICAL across every
    migration -- only the role is added (proved by construction: the
    production renderer renders both scripts from the same access
    list, and the revoke delta between them is empty).

    The matrix covers: an access list naming the login's schema
    explicitly; one naming ONLY public while the legacy app keeps its
    table in its own (auto-created) schema -- with the public decoy
    twin ENABLED, so the shop-marker oracle actually discriminates
    the resolution (unqualified ``orders`` must return the shop
    marker while ``public.orders`` exists with different data) --
    including the app's post-switch DDL, an unchanged rerun and a
    rotation login there; one naming public AND
    the login's own schema where both hold a same-named table with
    distinct data (the legacy default ``"$user", public`` resolves
    the login's schema FIRST) plus a rotation login; a DASH in the
    login name (a quoted element in the stored search-path value,
    asserted again after an unchanged rerun AND for a rotation login
    -- regression: the stored quoted element used to be quote_ident-ed
    again and the corrupted path resolved the public data); and the
    capture of the login's effective
    search-path DEFAULT following PostgreSQL's own precedence:
    login-in-database before the login's role-wide setting before
    the database-wide setting -- a role-wide default alone, a
    database-wide default alone, the three-level precedence case,
    and role-wide directly against database-wide WITHOUT a more
    specific override in both directions (regression area: the
    capture used to assume the built-in ``"$user", public`` default,
    and a more general default used to displace a more specific
    one).
    """
    _run_legacy_switch_scenario(postgres, spec)


# ─── 4a. single-element search_path values (P03) ──────────────────────────


@dataclasses.dataclass(frozen=True)
class _SingleElementSpec:
    """One single-element search_path variant of the capture matrix."""

    variant: str
    login: str
    role: str
    marker_schema: str
    setting_value: str


_SINGLE_ELEMENT_SPECS = [
    pytest.param(  # P03
        _SingleElementSpec(
            variant="ordinary",
            login="p03a_app",
            role="p03a_owner",
            marker_schema="single_app",
            setting_value="single_app",
        ),
        id="ordinary-schema",
    ),
    pytest.param(  # P03
        _SingleElementSpec(
            variant="quotable",
            login="p03b_app",
            role="p03b_owner",
            marker_schema="shop-app",
            setting_value='"shop-app"',
        ),
        id="quotable-schema",
    ),
]


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
@pytest.mark.parametrize("spec", _SINGLE_ELEMENT_SPECS)
def test_single_element_search_path_keeps_original_marker(
    postgres: PostgresContainer, spec: _SingleElementSpec
) -> None:
    """P03 — An explicit search_path of EXACTLY ONE schema survives the switch.

    A same-named ``orders`` table exists in public with different
    data. The legacy login's effective search_path is a single
    element -- once an ordinary schema name, once a quotable one --
    so the native resolution picks the marker schema, not public. The
    first run, a second unchanged run and a rotation login must all
    keep delivering the ORIGINAL marker (regression: a
    single-element value has no comma, and the stored-value parser
    only appended the final element when a comma had already produced
    a token -- a valid element was treated as empty because of the
    missing comma, the captured prefix degenerated to nothing, and
    the unqualified name resolved to the PUBLIC data).
    """
    pg = postgres
    db = f"p03_{spec.variant}_db"
    _create_database(pg, db)

    # the public twin table with uniquely distinct data, and the
    # marker schema the explicit single-element path names
    result = pg.exec_psql(
        EXECUTOR,
        db,
        f"CREATE SCHEMA {_qi(spec.marker_schema)}; "
        "CREATE TABLE public.orders (id int, note text); "
        "INSERT INTO public.orders VALUES (1, 'public-data');",
    )
    assert result.returncode == 0, result.stderr

    # the access list names public FIRST: with the captured prefix
    # lost, the configured order alone resolves the unqualified name
    # to the public twin -- exactly the wrong winner this test guards
    # against
    access: list[tuple[str, tuple[str, ...]]] = [
        ("public", ("SELECT", "INSERT")),
        (spec.marker_schema, ("SELECT", "INSERT")),
    ]
    legacy_config = make_db_access(database=db, username=spec.login, access=access)
    _run_provision(pg, build_script(legacy_config))

    # the DBA prepared the marker schema for the application login
    # (legacy mode grants only table privileges, never schema USAGE)
    result = pg.exec_psql(
        EXECUTOR,
        db,
        f"GRANT USAGE, CREATE ON SCHEMA {_qi(spec.marker_schema)} TO {spec.login};",
    )
    assert result.returncode == 0, result.stderr

    # the DBA-set explicit single-element search_path
    result = pg.exec_psql(
        EXECUTOR,
        db,
        f"ALTER ROLE {spec.login} IN DATABASE {db} "
        f"SET search_path TO {spec.setting_value};",
    )
    assert result.returncode == 0, result.stderr

    # the app plants its marker table with unqualified DDL: it lands
    # in the single schema on the path
    result = pg.login(
        spec.login,
        DB_PASSWORD,
        db,
        "CREATE TABLE orders (id int, note text); "
        f"INSERT INTO orders VALUES (1, '{spec.variant}-data');",
    )
    assert result.returncode == 0, result.stderr

    # BEFORE the switch: the native resolution picks the marker schema
    _assert_unqualified_marker(
        pg,
        db,
        spec.login,
        DB_PASSWORD,
        f"{spec.variant}-data",
        forbidden=("public-data",),
        where="before the switch",
    )

    # migrate by ONLY adding role: same username, same grants, the
    # same schema order -- through the production renderer
    role_config = make_db_access(
        database=db, username=spec.login, role=spec.role, access=access
    )
    _run_provision(pg, build_script(role_config, legacy_config))

    # AFTER the switch: the ORIGINAL marker, not the public one
    _assert_unqualified_marker(
        pg,
        db,
        spec.login,
        DB_PASSWORD,
        f"{spec.variant}-data",
        forbidden=("public-data",),
        where="after the switch",
    )

    # a second unchanged run: the stored prefix (again exactly one
    # element) round-trips as a name
    _run_provision(pg, build_script(role_config))
    _assert_unqualified_marker(
        pg,
        db,
        spec.login,
        DB_PASSWORD,
        f"{spec.variant}-data",
        forbidden=("public-data",),
        where="after a second run",
    )

    # rotation: a second login of the same role resolves the same
    # marker from the stored prefix
    rotation_config = make_db_access(
        database=db, username=spec.login + "2", role=spec.role, access=access
    )
    _run_provision(pg, build_script(rotation_config), password="P03Rotation2")
    _assert_unqualified_marker(
        pg,
        db,
        spec.login + "2",
        "P03Rotation2",
        f"{spec.variant}-data",
        forbidden=("public-data",),
        where="rotation login",
    )


# ─── 4a-bis. the instance-wide search_path default (P05) ──────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres_server_search_path", ["16"], indirect=True)
def test_server_wide_search_path_default_is_captured(
    postgres_server_search_path: PostgresContainer,
) -> None:
    """P05 — The instance-wide search_path default is captured, not guessed.

    The server itself was started with ``-c search_path=public`` (like
    an RDS parameter group setting the instance default); the app
    login has NO role or database override. ``public.orders`` and
    ``tenant_app.orders`` hold different data, and the login's own
    schema keeps a table from the time before the instance-wide
    setting existed. Without any override the native resolution is
    the PUBLIC marker -- before and after the migration, after a
    follow-up run and for a rotation login (regression: the capture
    chain ended at the database-wide setting and fell back to the
    hard-wired ``"$user", public`` built-in, which put the login's
    own schema first and delivered its historical data instead). A
    specific login-in-database override governs over the same server
    default, and the DAM executor's private search_path never leaks
    into the capture: the settlement observes the effective value on
    a real connection of the application login (PostgreSQL itself
    resolves every level), so the executor's own override -- a
    private path, or even an EXPLICITLY EMPTY one -- changes nothing
    about the observation, and the executor's personal settings are
    never modified by a DAM run.
    """
    pg = postgres_server_search_path
    db = "p05_server_default_db"
    _create_database(pg, db)

    # sanity: the server-wide default really is the command-line
    # public value in this database
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT source || '=' || setting FROM pg_settings "
            "WHERE name = 'search_path'",
        )
        == "command line=public"
    )

    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE SCHEMA tenant_app; "
        "CREATE TABLE public.orders (id int, note text); "
        "INSERT INTO public.orders VALUES (1, 'public-data'); "
        "CREATE TABLE tenant_app.orders (id int, note text); "
        "INSERT INTO tenant_app.orders VALUES (1, 'tenant-data');",
    )
    assert result.returncode == 0, result.stderr

    access: list[tuple[str, tuple[str, ...]]] = [
        ("public", ("SELECT", "INSERT")),
        ("tenant_app", ("SELECT", "INSERT")),
    ]
    legacy_config = make_db_access(database=db, username="p05_app", access=access)
    _run_provision(pg, build_script(legacy_config))

    # the app's own schema keeps its historical table from before the
    # instance-wide setting existed (created qualified back then)
    result = pg.login(
        "p05_app",
        DB_PASSWORD,
        db,
        "CREATE TABLE p05_app.orders (id int, note text); "
        "INSERT INTO p05_app.orders VALUES (1, 'own-history-data');",
    )
    assert result.returncode == 0, result.stderr

    # BEFORE the switch: no override -- the server default governs
    _assert_unqualified_marker(
        pg,
        db,
        "p05_app",
        DB_PASSWORD,
        "public-data",
        forbidden=("own-history-data",),
        where="before the switch",
    )

    # migrate by ONLY adding role
    role_config = make_db_access(
        database=db, username="p05_app", role="p05_owner", access=access
    )
    _run_provision(pg, build_script(role_config, legacy_config))

    # AFTER the switch: still the PUBLIC marker -- the server-wide
    # value was captured, not the "$user", public built-in
    _assert_unqualified_marker(
        pg,
        db,
        "p05_app",
        DB_PASSWORD,
        "public-data",
        forbidden=("own-history-data",),
        where="after the switch",
    )

    # a follow-up run and a rotation login keep the server default
    _run_provision(pg, build_script(role_config))
    _assert_unqualified_marker(
        pg,
        db,
        "p05_app",
        DB_PASSWORD,
        "public-data",
        forbidden=("own-history-data",),
        where="after a follow-up run",
    )
    rotation_config = make_db_access(
        database=db, username="p05_app2", role="p05_owner", access=access
    )
    _run_provision(pg, build_script(rotation_config), password="P05Rotation2")
    _assert_unqualified_marker(
        pg,
        db,
        "p05_app2",
        "P05Rotation2",
        "public-data",
        forbidden=("own-history-data",),
        where="rotation login",
    )

    # ── counter-probe: a specific login override governs over the ───
    # same server default
    override_legacy = make_db_access(database=db, username="p05b_app", access=access)
    _run_provision(pg, build_script(override_legacy))
    result = pg.exec_psql(
        EXECUTOR,
        db,
        f"ALTER ROLE p05b_app IN DATABASE {db} SET search_path TO tenant_app, public;",
    )
    assert result.returncode == 0, result.stderr

    # BEFORE: the override resolves the tenant data (the DBA also
    # prepared the schema: legacy mode grants only table privileges)
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "GRANT USAGE ON SCHEMA tenant_app TO p05b_app;",
    )
    assert result.returncode == 0, result.stderr
    _assert_unqualified_marker(
        pg,
        db,
        "p05b_app",
        DB_PASSWORD,
        "tenant-data",
        forbidden=("public-data",),
        where="override before the switch",
    )

    override_role = make_db_access(
        database=db, username="p05b_app", role="p05b_owner", access=access
    )
    _run_provision(pg, build_script(override_role, override_legacy))

    # AFTER: the override still governs over the server default
    _assert_unqualified_marker(
        pg,
        db,
        "p05b_app",
        DB_PASSWORD,
        "tenant-data",
        forbidden=("public-data",),
        where="override after the switch",
    )

    # ── the executor's private search_path never leaks ─────────────
    # The executor gets a role-wide path of its own with a marker
    # schema holding distinct data. From that moment the server-wide
    # value is NOT observable from the job session (pg_settings shows
    # the executor's own 'user' source). The settlement does not read
    # the value from the job session at all: it observes on an
    # application connection, so the app login's resolution keeps the
    # SERVER default -- and the executor's personal setting must
    # remain UNTOUCHED by the DAM run (byte for byte).
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE SCHEMA executor_private; "
        "CREATE TABLE executor_private.orders (id int, note text); "
        "INSERT INTO executor_private.orders VALUES (1, 'executor-data'); "
        "ALTER ROLE test_admin SET search_path TO executor_private, public;",
    )
    assert result.returncode == 0, result.stderr
    assert (
        pg.query(
            EXECUTOR, db, "SELECT source FROM pg_settings WHERE name = 'search_path'"
        )
        == "user"
    )

    private_legacy = make_db_access(database=db, username="p05c_app", access=access)
    _run_provision(pg, build_script(private_legacy))
    result = pg.login(
        "p05c_app",
        DB_PASSWORD,
        db,
        "CREATE TABLE p05c_app.orders (id int, note text); "
        "INSERT INTO p05c_app.orders VALUES (1, 'own-c-data');",
    )
    assert result.returncode == 0, result.stderr

    # BEFORE: the app login itself still has no override -- the
    # server default governs its sessions, whatever the executor's
    # own path is
    _assert_unqualified_marker(
        pg,
        db,
        "p05c_app",
        DB_PASSWORD,
        "public-data",
        forbidden=("own-c-data", "executor-data"),
        where="executor override before the switch",
    )

    # the executor's personal setting, recorded before the DAM run:
    # the run must never touch it, byte for byte
    executor_setting_sql = (
        "SELECT cfg FROM pg_db_role_setting s "
        "JOIN pg_roles r ON r.oid = s.setrole "
        "CROSS JOIN LATERAL unnest(s.setconfig) AS cfg "
        "WHERE r.rolname = 'test_admin' AND s.setdatabase = 0 "
        "AND cfg LIKE 'search_path=%'"
    )
    executor_setting_before = pg.query(EXECUTOR, db, executor_setting_sql)
    assert executor_setting_before == "search_path=executor_private, public"

    private_role = make_db_access(
        database=db, username="p05c_app", role="p05c_owner", access=access
    )
    _run_provision(pg, build_script(private_role, private_legacy))

    # AFTER: the SAME marker as before the switch -- the server-wide
    # value was observed on the application connection, not replaced
    # by the executor's private path or the "$user", public built-in
    _assert_unqualified_marker(
        pg,
        db,
        "p05c_app",
        DB_PASSWORD,
        "public-data",
        forbidden=("own-c-data", "executor-data"),
        where="executor override after the switch",
    )

    # untouched safety: the executor's personal setting survived the
    # DAM run byte for byte
    assert pg.query(EXECUTOR, db, executor_setting_sql) == executor_setting_before, (
        "the executor's private search_path setting was modified by the DAM run"
    )

    # ── the executor's EXPLICITLY EMPTY private search_path ────────
    # The corner that broke the previous capture mechanism: the
    # executor's own override is the EMPTY value, so the server-wide
    # default is masked AND the old unmask dance could not restore
    # what it had reset (ALTER ROLE ... SET search_path TO "" is a
    # zero-length delimited identifier -- the job failed and the
    # executor's setting stayed reset). The settlement never touches
    # the executor's settings: the capture observes on an application
    # connection, the migration SUCCEEDS, and the executor's
    # explicitly empty setting survives byte for byte.
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "ALTER ROLE test_admin SET search_path TO '';",
    )
    assert result.returncode == 0, result.stderr

    empty_executor_setting_sql = (
        "SELECT cfg FROM pg_db_role_setting s "
        "JOIN pg_roles r ON r.oid = s.setrole "
        "CROSS JOIN LATERAL unnest(s.setconfig) AS cfg "
        "WHERE r.rolname = 'test_admin' AND s.setdatabase = 0 "
        "AND cfg LIKE 'search_path=%'"
    )
    empty_executor_setting_before = pg.query(EXECUTOR, db, empty_executor_setting_sql)
    assert empty_executor_setting_before == 'search_path=""'

    empty_exec_legacy = make_db_access(database=db, username="p05d_app", access=access)
    _run_provision(pg, build_script(empty_exec_legacy))
    result = pg.login(
        "p05d_app",
        DB_PASSWORD,
        db,
        "CREATE TABLE p05d_app.orders (id int, note text); "
        "INSERT INTO p05d_app.orders VALUES (1, 'own-d-data');",
    )
    assert result.returncode == 0, result.stderr

    # BEFORE: no override on the app login -- the server default
    # governs its sessions, whatever the executor's own (empty) path
    # is
    _assert_unqualified_marker(
        pg,
        db,
        "p05d_app",
        DB_PASSWORD,
        "public-data",
        forbidden=("own-d-data",),
        where="empty executor override before the switch",
    )

    empty_exec_role = make_db_access(
        database=db, username="p05d_app", role="p05d_owner", access=access
    )
    _run_provision(pg, build_script(empty_exec_role, empty_exec_legacy))

    # AFTER: the SAME public marker, on a run that SUCCEEDED
    _assert_unqualified_marker(
        pg,
        db,
        "p05d_app",
        DB_PASSWORD,
        "public-data",
        forbidden=("own-d-data",),
        where="empty executor override after the switch",
    )

    # untouched safety: the executor's explicitly empty setting
    # survived the DAM run byte for byte
    assert pg.query(EXECUTOR, db, empty_executor_setting_sql) == (
        empty_executor_setting_before
    ), "the executor's explicitly empty search_path setting was modified by the DAM run"


# ─── 4a-ter. DBA-set search_path values round-trip as names (P06) ─────────


@dataclasses.dataclass(frozen=True)
class _DbaSearchPathSpec:
    """One DBA-set search_path value variant of the round-trip matrix."""

    variant: str
    login: str
    role: str
    setting_value: str
    marker_schema: str
    in_access_list: bool
    marker: str
    extra_bait: tuple[tuple[str, str], ...] = ()


_DBA_SEARCH_PATH_SPECS = [
    pytest.param(  # P06
        _DbaSearchPathSpec(
            variant="single-element",
            login="p06a_app",
            role="p06a_owner",
            setting_value="p06_solo",
            marker_schema="p06_solo",
            in_access_list=True,
            marker="solo-data",
        ),
        id="single-element",
    ),
    pytest.param(  # P06
        _DbaSearchPathSpec(
            variant="quoted-both-ends",
            login="p06b_app",
            role="p06b_owner",
            setting_value='"p06-alpha", "p06-beta"',
            marker_schema="p06-alpha",
            in_access_list=True,
            marker="alpha-data",
            extra_bait=(("p06-beta", "beta-data"),),
        ),
        id="quoted-both-ends",
    ),
    pytest.param(  # P06
        _DbaSearchPathSpec(
            variant="dollar-user",
            login="p06c_app",
            role="p06c_owner",
            setting_value='"$user", public',
            marker_schema="p06c_app",
            in_access_list=False,
            marker="own-data",
        ),
        id="dollar-user",
    ),
    pytest.param(  # P06
        _DbaSearchPathSpec(
            variant="mixed-case",
            login="p06d_app",
            role="p06d_owner",
            setting_value='"P06Mixed"',
            marker_schema="P06Mixed",
            in_access_list=True,
            marker="mixed-data",
        ),
        id="mixed-case",
    ),
    pytest.param(  # P06
        _DbaSearchPathSpec(
            variant="comma-in-name",
            login="p06e_app",
            role="p06e_owner",
            setting_value='"p06,weird"',
            marker_schema="p06,weird",
            in_access_list=False,
            marker="comma-data",
        ),
        id="comma-in-name",
    ),
    pytest.param(  # P06
        _DbaSearchPathSpec(
            variant="embedded-quote",
            login="p06f_app",
            role="p06f_owner",
            setting_value='"p06""q", public',
            marker_schema='p06"q',
            in_access_list=True,
            marker="quote-data",
        ),
        id="embedded-quote",
    ),
]


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
@pytest.mark.parametrize("spec", _DBA_SEARCH_PATH_SPECS)
def test_dba_search_path_values_round_trip(
    postgres: PostgresContainer, spec: _DbaSearchPathSpec
) -> None:
    """P06 — DBA-set search_path values round-trip as schema NAMES.

    The DBA sets the legacy login's per-database search_path to
    catalog values a DBA can legitimately write; the app plants a
    marker table in the schema the NATIVE login resolves to (the
    resolution a real pre-migration session observed, not a second
    implementation of the parser), with a public twin holding
    different data. After the migration and after a second run, the
    same unqualified query must keep delivering the same marker.

    Variants: exactly one element; multiple quoted elements (the
    value begins and ends with a quoted name); ``"$user"``; mixed
    case; an actually existing schema whose name contains a COMMA or
    an EMBEDDED QUOTE. A separator-containing name must stay ONE name
    (regression: the parser used to prefer the de-quoted whole value
    over the raw stored value, which split a comma-named schema into
    two bogus names and resolved the unqualified name to the PUBLIC
    data). The comma-named schema cannot be represented in the
    renderer's comma-separated schema list, so it stays outside the
    access list (PUBLIC grants) -- and DAM must not take it over from
    a path token.
    """
    pg = postgres
    db = f"p06_{spec.variant.replace('-', '_')}_db"
    _create_database(pg, db)

    setup = (
        "CREATE TABLE public.orders (id int, note text); "
        "INSERT INTO public.orders VALUES (1, 'public-data'); "
    )
    if spec.variant == "comma-in-name":
        # the marker table pre-exists (executor-owned, PUBLIC grants):
        # a schema name containing a comma cannot ride the renderer's
        # comma-separated schema list, so it never joins the access
        # list, and the app only reads it
        setup += (
            f"CREATE SCHEMA {_qi(spec.marker_schema)}; "
            f"CREATE TABLE {_qi(spec.marker_schema)}.orders (id int, note text); "
            f"INSERT INTO {_qi(spec.marker_schema)}.orders VALUES "
            f"(1, '{spec.marker}'); "
            f"GRANT USAGE ON SCHEMA {_qi(spec.marker_schema)} TO public; "
            f"GRANT SELECT ON {_qi(spec.marker_schema)}.orders TO public; "
        )
    elif spec.variant != "dollar-user":
        # the DBA-created marker schema (the $user variant uses the
        # login's own legacy schema)
        setup += f"CREATE SCHEMA {_qi(spec.marker_schema)}; "
    for bait_schema, _bait_marker in spec.extra_bait:
        setup += f"CREATE SCHEMA {_qi(bait_schema)}; "
    result = pg.exec_psql(EXECUTOR, db, setup)
    assert result.returncode == 0, result.stderr

    access: list[tuple[str, tuple[str, ...]]] = [("public", ("SELECT", "INSERT"))]
    if spec.in_access_list:
        access.append((spec.marker_schema, ("SELECT", "INSERT")))
    for bait_schema, _bait_marker in spec.extra_bait:
        access.append((bait_schema, ("SELECT", "INSERT")))

    legacy_config = make_db_access(database=db, username=spec.login, access=access)
    _run_provision(pg, build_script(legacy_config))

    # the DBA prepared the marker schemas for the application login
    # (legacy mode grants only table privileges, never schema USAGE);
    # the $user variant needs nothing (the login owns its own
    # schema), the comma variant only reads the PUBLIC-granted table
    if spec.variant not in {"dollar-user", "comma-in-name"}:
        grants = (
            f"GRANT USAGE, CREATE ON SCHEMA {_qi(spec.marker_schema)} TO {spec.login};"
        )
        for bait_schema, _bait_marker in spec.extra_bait:
            grants += (
                f" GRANT USAGE, CREATE ON SCHEMA {_qi(bait_schema)} TO {spec.login};"
            )
        result = pg.exec_psql(EXECUTOR, db, grants)
        assert result.returncode == 0, result.stderr

    # the DBA-set search_path value, exactly as a DBA would write it
    result = pg.exec_psql(
        EXECUTOR,
        db,
        f"ALTER ROLE {spec.login} IN DATABASE {db} "
        f"SET search_path TO {spec.setting_value};",
    )
    assert result.returncode == 0, result.stderr

    # the app plants its marker table where the NATIVE resolution
    # points (unqualified DDL follows the DBA-set path)
    if spec.variant != "comma-in-name":
        plant = (
            "CREATE TABLE orders (id int, note text); "
            f"INSERT INTO orders VALUES (1, '{spec.marker}'); "
        )
        for bait_schema, bait_marker in spec.extra_bait:
            plant += (
                f"CREATE TABLE {_qi(bait_schema)}.orders (id int, note text); "
                f"INSERT INTO {_qi(bait_schema)}.orders VALUES "
                f"(1, '{bait_marker}'); "
            )
        result = pg.login(spec.login, DB_PASSWORD, db, plant)
        assert result.returncode == 0, result.stderr

    forbidden = ("public-data", *(marker for _, marker in spec.extra_bait))

    # BEFORE the switch: the native login's own resolution
    _assert_unqualified_marker(
        pg,
        db,
        spec.login,
        DB_PASSWORD,
        spec.marker,
        forbidden=forbidden,
        where="before the switch",
    )

    # migrate by ONLY adding role, through the production renderer
    role_config = make_db_access(
        database=db, username=spec.login, role=spec.role, access=access
    )
    _run_provision(pg, build_script(role_config, legacy_config))

    # AFTER the switch: the same marker as the native resolution
    _assert_unqualified_marker(
        pg,
        db,
        spec.login,
        DB_PASSWORD,
        spec.marker,
        forbidden=forbidden,
        where="after the switch",
    )

    # a second run: the stored value round-trips as names
    _run_provision(pg, build_script(role_config))
    _assert_unqualified_marker(
        pg,
        db,
        spec.login,
        DB_PASSWORD,
        spec.marker,
        forbidden=forbidden,
        where="after a second run",
    )

    if spec.variant == "comma-in-name":
        # the path-token schema is not DAM-managed: it keeps its owner
        # (no ownership takeover from a search-path token)
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
                f"WHERE nspname = '{spec.marker_schema}'",
            )
            == EXECUTOR
        )


# ─── 4a-quater. unusable and explicitly empty path entries (P07) ──────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_unusable_and_empty_search_path_entries(
    postgres: PostgresContainer,
) -> None:
    """P07 — Unusable path entries stay reachable; an empty path never leaks public data.

    Main case: the explicit path contains a NONEXISTENT schema before
    a usable one (``ghost_schema, tenant_app``). The native login
    skips the unusable entry and reaches the marker in the usable
    schema; public holds a same-named table with different data. DAM
    must keep the marker reachable for the app and a rotation login
    (an unsafely processable value must not silently "succeed" by
    resolving to a DIFFERENT table) and must not invent objects or
    ownership takeovers from a path token: ghost_schema is never
    created, and the owner role takes over nothing outside the
    managed schemas.

    Negative control: an EXPLICITLY EMPTY search_path (different from
    no setting and from empty access). The native login's behavior is
    recorded first: qualified access to ``tenant_app.orders`` works,
    unqualified access fails. After the pure role switch qualified
    access must still work, and the previously-failing unqualified
    access must keep FAILING concretely: the tenant deliberately
    emptied its resolution, so no configured schema and no public
    fallback may be appended (the applied path stays empty). This
    must also hold when ``public`` IS the FIRST configured schema --
    the variant where the old blanket public fallback returned the
    granted public twin -- and for a ROTATION login: the empty state
    is a property of the ROLE's store (present-but-empty), so a
    second login of the same role inherits it and the unqualified
    query keeps failing, never silently resolving to public data
    (regression: the path construction checked only the CURRENT
    login's captured emptiness, so the rotation login's path was
    rebuilt from the configured order and delivered the public twin).
    """
    pg = postgres
    db = "p07_ghost_db"
    _create_database(pg, db)

    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE SCHEMA tenant_app; "
        "CREATE TABLE public.orders (id int, note text); "
        "INSERT INTO public.orders VALUES (1, 'public-data');",
    )
    assert result.returncode == 0, result.stderr

    access: list[tuple[str, tuple[str, ...]]] = [("tenant_app", ("SELECT", "INSERT"))]
    legacy_config = make_db_access(database=db, username="p07_app", access=access)
    _run_provision(pg, build_script(legacy_config))

    # the DBA prepared the marker schema for the application login
    # (legacy mode grants only table privileges, never schema USAGE)
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "GRANT USAGE, CREATE ON SCHEMA tenant_app TO p07_app;",
    )
    assert result.returncode == 0, result.stderr

    # the unusable entry BEFORE the usable one
    result = pg.exec_psql(
        EXECUTOR,
        db,
        f"ALTER ROLE p07_app IN DATABASE {db} "
        "SET search_path TO ghost_schema, tenant_app;",
    )
    assert result.returncode == 0, result.stderr

    # the app plants its marker table with unqualified DDL: the
    # nonexistent ghost_schema is skipped, tenant_app receives it
    result = pg.login(
        "p07_app",
        DB_PASSWORD,
        db,
        "CREATE TABLE orders (id int, note text); "
        "INSERT INTO orders VALUES (1, 'tenant-data');",
    )
    assert result.returncode == 0, result.stderr

    # BEFORE the switch: the usable schema's marker
    _assert_unqualified_marker(
        pg,
        db,
        "p07_app",
        DB_PASSWORD,
        "tenant-data",
        forbidden=("public-data",),
        where="before the switch",
    )

    role_config = make_db_access(
        database=db, username="p07_app", role="p07_owner", access=access
    )
    _run_provision(pg, build_script(role_config, legacy_config))

    # AFTER the switch: the SAME table, not the public twin
    _assert_unqualified_marker(
        pg,
        db,
        "p07_app",
        DB_PASSWORD,
        "tenant-data",
        forbidden=("public-data",),
        where="after the switch",
    )

    # DAM invented nothing from the path token: ghost_schema does not
    # exist, and the owner role owns nothing outside the managed
    # schemas (tenant_app, public and the login's own schema)
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ghost_schema')",
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT count(*) FROM pg_namespace "
            "WHERE nspowner = 'p07_owner'::regrole "
            "AND nspname NOT IN ('tenant_app', 'public', 'p07_app')",
        )
        == "0"
    )

    # a second run and a rotation login keep the marker reachable
    _run_provision(pg, build_script(role_config))
    _assert_unqualified_marker(
        pg,
        db,
        "p07_app",
        DB_PASSWORD,
        "tenant-data",
        forbidden=("public-data",),
        where="after a second run",
    )
    rotation_config = make_db_access(
        database=db, username="p07_app2", role="p07_owner", access=access
    )
    _run_provision(pg, build_script(rotation_config), password="P07Rotation2")
    _assert_unqualified_marker(
        pg,
        db,
        "p07_app2",
        "P07Rotation2",
        "tenant-data",
        forbidden=("public-data",),
        where="rotation login",
    )

    # ── negative control: an explicitly EMPTY search_path ──────────
    empty_db = "p07_empty_db"
    _create_database(pg, empty_db)

    result = pg.exec_psql(
        EXECUTOR,
        empty_db,
        "CREATE SCHEMA tenant_app; "
        "CREATE TABLE public.orders (id int, note text); "
        "INSERT INTO public.orders VALUES (1, 'public-data');",
    )
    assert result.returncode == 0, result.stderr

    empty_legacy = make_db_access(database=empty_db, username="p07b_app", access=access)
    _run_provision(pg, build_script(empty_legacy))

    # the DBA prepared the marker schema for the application login
    result = pg.exec_psql(
        EXECUTOR,
        empty_db,
        "GRANT USAGE, CREATE ON SCHEMA tenant_app TO p07b_app;",
    )
    assert result.returncode == 0, result.stderr

    result = pg.exec_psql(
        EXECUTOR,
        empty_db,
        f"ALTER ROLE p07b_app IN DATABASE {empty_db} SET search_path TO '';",
    )
    assert result.returncode == 0, result.stderr

    # the app plants its marker table QUALIFIED: with an empty path
    # the native login cannot use unqualified DDL at all
    result = pg.login(
        "p07b_app",
        DB_PASSWORD,
        empty_db,
        "CREATE TABLE tenant_app.orders (id int, note text); "
        "INSERT INTO tenant_app.orders VALUES (1, 'tenant-data');",
    )
    assert result.returncode == 0, result.stderr

    # the native login's behavior, recorded first: qualified access
    # works, unqualified access FAILS
    result = pg.login(
        "p07b_app",
        DB_PASSWORD,
        empty_db,
        "SELECT note FROM tenant_app.orders WHERE id = 1;",
    )
    assert result.returncode == 0, result.stderr
    assert "tenant-data" in result.stdout
    result = pg.login("p07b_app", DB_PASSWORD, empty_db, "SELECT note FROM orders;")
    assert result.returncode != 0, "the empty path must not resolve unqualified names"
    assert 'relation "orders" does not exist' in result.stderr

    # the pure role switch (identical inputs, only the role added)
    empty_role = make_db_access(
        database=empty_db, username="p07b_app", role="p07b_owner", access=access
    )
    _run_provision(pg, build_script(empty_role, empty_legacy))

    # qualified access still works after the switch
    result = pg.login(
        "p07b_app",
        DB_PASSWORD,
        empty_db,
        "SELECT note FROM tenant_app.orders WHERE id = 1;",
    )
    assert result.returncode == 0, result.stderr
    assert "tenant-data" in result.stdout

    # the previously-failing unqualified access keeps failing: the
    # tenant deliberately emptied its resolution, and DAM must not
    # silently resolve the name through the configured schemas or the
    # public fallback
    result = pg.login(
        "p07b_app", DB_PASSWORD, empty_db, "SELECT note FROM orders WHERE id = 1;"
    )
    assert result.returncode != 0, (
        "the empty search_path silently resolved the unqualified name"
    )
    assert 'relation "orders" does not exist' in result.stderr

    # rotation: a second login of the same role inherits the ROLE's
    # empty state from the present-but-empty store -- the unqualified
    # query keeps failing (never public data) and qualified access
    # works for the new credential
    empty_rotation = make_db_access(
        database=empty_db, username="p07b_app2", role="p07b_owner", access=access
    )
    _run_provision(pg, build_script(empty_rotation), password=P07B_ROTATION_PASSWORD)
    result = pg.login(
        "p07b_app2",
        P07B_ROTATION_PASSWORD,
        empty_db,
        "SELECT note FROM tenant_app.orders WHERE id = 1;",
    )
    assert result.returncode == 0, result.stderr
    assert "tenant-data" in result.stdout
    result = pg.login(
        "p07b_app2",
        P07B_ROTATION_PASSWORD,
        empty_db,
        "SELECT note FROM orders WHERE id = 1;",
    )
    assert result.returncode != 0, (
        "the role's empty search_path state was lost on rotation"
    )
    assert 'relation "orders" does not exist' in result.stderr
    assert "public-data" not in result.stdout

    # ── negative control, public FIRST: the explicitly empty path ──
    # must not silently resolve to public even when public IS the
    # FIRST configured schema (and therefore granted): the old blanket
    # public fallback returned the public twin here
    public_first_db = "p07_public_first_db"
    _create_database(pg, public_first_db)

    result = pg.exec_psql(
        EXECUTOR,
        public_first_db,
        "CREATE SCHEMA tenant_app; "
        "CREATE TABLE public.orders (id int, note text); "
        "INSERT INTO public.orders VALUES (1, 'public-data');",
    )
    assert result.returncode == 0, result.stderr

    public_first_access: list[tuple[str, tuple[str, ...]]] = [
        ("public", ("SELECT", "INSERT")),
        ("tenant_app", ("SELECT", "INSERT")),
    ]
    public_first_legacy = make_db_access(
        database=public_first_db, username="p07c_app", access=public_first_access
    )
    _run_provision(pg, build_script(public_first_legacy))

    # the DBA prepared the tenant schema for the application login
    # (legacy mode grants only table privileges, never schema USAGE)
    result = pg.exec_psql(
        EXECUTOR,
        public_first_db,
        "GRANT USAGE, CREATE ON SCHEMA tenant_app TO p07c_app;",
    )
    assert result.returncode == 0, result.stderr

    result = pg.exec_psql(
        EXECUTOR,
        public_first_db,
        f"ALTER ROLE p07c_app IN DATABASE {public_first_db} SET search_path TO '';",
    )
    assert result.returncode == 0, result.stderr

    # the app plants its marker table QUALIFIED: with an empty path
    # the native login cannot use unqualified DDL at all
    result = pg.login(
        "p07c_app",
        DB_PASSWORD,
        public_first_db,
        "CREATE TABLE tenant_app.orders (id int, note text); "
        "INSERT INTO tenant_app.orders VALUES (1, 'tenant-data');",
    )
    assert result.returncode == 0, result.stderr

    # the native login's behavior, recorded first: qualified access
    # works, unqualified access FAILS
    result = pg.login(
        "p07c_app",
        DB_PASSWORD,
        public_first_db,
        "SELECT note FROM tenant_app.orders WHERE id = 1;",
    )
    assert result.returncode == 0, result.stderr
    assert "tenant-data" in result.stdout
    result = pg.login(
        "p07c_app", DB_PASSWORD, public_first_db, "SELECT note FROM orders;"
    )
    assert result.returncode != 0, "the empty path must not resolve unqualified names"
    assert 'relation "orders" does not exist' in result.stderr

    # the pure role switch (identical inputs, only the role added)
    public_first_role = make_db_access(
        database=public_first_db,
        username="p07c_app",
        role="p07c_owner",
        access=public_first_access,
    )
    _run_provision(pg, build_script(public_first_role, public_first_legacy))

    # qualified access still works after the switch
    result = pg.login(
        "p07c_app",
        DB_PASSWORD,
        public_first_db,
        "SELECT note FROM tenant_app.orders WHERE id = 1;",
    )
    assert result.returncode == 0, result.stderr
    assert "tenant-data" in result.stdout

    # the applied search_path stays EMPTY (not even public is
    # appended -- the catalog keeps the canonical empty value) and the
    # previously-failing unqualified access keeps failing -- even
    # though public is the FIRST configured schema and its table is
    # fully granted to the owner role
    assert (
        pg.query(
            EXECUTOR,
            public_first_db,
            "SELECT cfg FROM pg_db_role_setting s "
            "JOIN pg_roles r ON r.oid = s.setrole "
            "JOIN pg_database d ON d.oid = s.setdatabase "
            "CROSS JOIN LATERAL unnest(s.setconfig) AS cfg "
            "WHERE r.rolname = 'p07c_app' "
            f"AND d.datname = '{public_first_db}' "
            "AND cfg LIKE 'search_path=%'",
        )
        == 'search_path=""'
    ), "the explicitly empty search_path was replaced by a non-empty path"
    result = pg.login(
        "p07c_app",
        DB_PASSWORD,
        public_first_db,
        "SELECT note FROM orders WHERE id = 1;",
    )
    assert result.returncode != 0, (
        "the empty search_path silently resolved to the public twin"
    )
    assert 'relation "orders" does not exist' in result.stderr
    assert "public-data" not in result.stdout

    # rotation with public FIRST: the second login of the role
    # inherits the ROLE's empty state -- the unqualified query keeps
    # failing instead of silently returning the fully granted public
    # twin, and qualified access works
    public_first_rotation = make_db_access(
        database=public_first_db,
        username="p07c_app2",
        role="p07c_owner",
        access=public_first_access,
    )
    _run_provision(
        pg, build_script(public_first_rotation), password=P07C_ROTATION_PASSWORD
    )
    result = pg.login(
        "p07c_app2",
        P07C_ROTATION_PASSWORD,
        public_first_db,
        "SELECT note FROM tenant_app.orders WHERE id = 1;",
    )
    assert result.returncode == 0, result.stderr
    assert "tenant-data" in result.stdout
    result = pg.login(
        "p07c_app2",
        P07C_ROTATION_PASSWORD,
        public_first_db,
        "SELECT note FROM orders WHERE id = 1;",
    )
    assert result.returncode != 0, (
        "the role's empty search_path state was lost on rotation "
        "and the unqualified query silently resolved to the public twin"
    )
    assert 'relation "orders" does not exist' in result.stderr
    assert "public-data" not in result.stdout


# ─── 4a-quinquies. second login vs. legacy-migration order (M06) ──────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
@pytest.mark.parametrize(
    "order",
    [
        pytest.param("migration-first", id="migration-first"),
        pytest.param("new-login-first", id="new-login-first"),
    ],
)
def test_second_login_order_with_legacy_migration(
    postgres: PostgresContainer, order: str
) -> None:
    """M06 — A second login of the role and the legacy migration converge in any order.

    A valid desired state: an existing legacy login gets ``role`` AND
    a second login gets the same role with the same explicit access
    list. Two fresh states force (a) the legacy-migration job first
    and (b) the NEW LOGIN first. The old marker is captured before
    the rollout; in BOTH orders, immediately after the
    legacy-migration job succeeds, a FRESH connection as the OLD
    login must read the same marker -- BEFORE any further reconcile.
    After convergence both logins read the same legacy data, and a
    follow-up run is stable (regression, order (b): the new-login run
    used to initialize the empty legacy-path store, so the later
    migration run skipped its capture and the old login silently
    resolved to the PUBLIC twin).
    """
    pg = postgres
    db = f"m6_{order.replace('-', '_')}_db"
    _create_database(pg, db)

    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE public.orders (id int, note text); "
        "INSERT INTO public.orders VALUES (1, 'public-data');",
    )
    assert result.returncode == 0, result.stderr

    access: list[tuple[str, tuple[str, ...]]] = [("public", ("SELECT", "INSERT"))]
    legacy_config = make_db_access(database=db, username="m6_app", access=access)
    _run_provision(pg, build_script(legacy_config))

    # the legacy app creates its marker table with unqualified DDL:
    # the default "$user", public path puts it in the login's own
    # schema
    result = pg.login(
        "m6_app",
        DB_PASSWORD,
        db,
        "CREATE TABLE orders (id int, note text); "
        "INSERT INTO orders VALUES (1, 'legacy-data');",
    )
    assert result.returncode == 0, result.stderr

    # the old marker, captured before the rollout
    _assert_unqualified_marker(
        pg,
        db,
        "m6_app",
        DB_PASSWORD,
        "legacy-data",
        forbidden=("public-data",),
        where="before the rollout",
    )

    # the desired state: the legacy login adds the role, and a second
    # login joins the same role with the same access list
    role_config = make_db_access(
        database=db, username="m6_app", role="m6_owner", access=access
    )
    second_config = make_db_access(
        database=db, username="m6_app2", role="m6_owner", access=access
    )

    if order == "migration-first":
        # (a) the legacy-migration job first: it captures and stores
        # the legacy prefix
        _run_provision(pg, build_script(role_config, legacy_config))
    else:
        # (b) the NEW LOGIN first: a run that creates its own login
        # must not initialize the legacy-path store
        _run_provision(pg, build_script(second_config), password=M6_SECOND_PASSWORD)
        _run_provision(pg, build_script(role_config, legacy_config))

    # immediately after the legacy-migration job succeeds, BEFORE any
    # further reconcile: a fresh connection as the OLD login reads
    # the same legacy marker
    _assert_unqualified_marker(
        pg,
        db,
        "m6_app",
        DB_PASSWORD,
        "legacy-data",
        forbidden=("public-data",),
        where="immediately after the migration",
    )

    # convergence: the second login's run adopts the stored legacy
    # prefix, then both logins read the same legacy data
    _run_provision(pg, build_script(second_config), password=M6_SECOND_PASSWORD)
    _assert_unqualified_marker(
        pg,
        db,
        "m6_app",
        DB_PASSWORD,
        "legacy-data",
        forbidden=("public-data",),
        where="after convergence (old login)",
    )
    _assert_unqualified_marker(
        pg,
        db,
        "m6_app2",
        M6_SECOND_PASSWORD,
        "legacy-data",
        forbidden=("public-data",),
        where="after convergence (second login)",
    )

    # a follow-up run of both entries is stable
    _run_provision(pg, build_script(role_config))
    _run_provision(pg, build_script(second_config), password=M6_SECOND_PASSWORD)
    _assert_unqualified_marker(
        pg,
        db,
        "m6_app",
        DB_PASSWORD,
        "legacy-data",
        forbidden=("public-data",),
        where="after a follow-up run (old login)",
    )
    _assert_unqualified_marker(
        pg,
        db,
        "m6_app2",
        M6_SECOND_PASSWORD,
        "legacy-data",
        forbidden=("public-data",),
        where="after a follow-up run (second login)",
    )


# ─── 4b. an open legacy session creates objects after the migration ───────


def _wait_for_table_row(
    pg: PostgresContainer,
    database: str,
    table: str,
    expected_count: str,
    *,
    what: str,
) -> None:
    """Deterministic barrier for a table another session creates.

    Phase one waits for the table to EXIST via ``to_regclass`` -- a
    system-function catalog lookup that performs no table access and
    therefore cannot abort with ``undefined_table`` while the writing
    session has not committed its CREATE TABLE yet (regression: a
    plain ``count(*)`` poll aborted the whole test on the very first
    poll, because ``pg.query`` fails the test on ANY SQL error -- a
    session whose start is merely slow took the test down). Phase two
    then polls the committed marker row. No sleep-and-hope: the wait
    is bounded by ``_wait_until``'s deadline, and unrelated SQL
    errors still fail the test.
    """
    _wait_until(
        pg,
        database,
        f"SELECT to_regclass('{table}') IS NOT NULL",
        "t",
        what=f"the table {table} to exist",
    )
    _wait_until(
        pg,
        database,
        f"SELECT count(*) FROM {table}",
        expected_count,
        what=what,
    )


@dataclasses.dataclass(frozen=True)
class _OpenLegacySessionSpec:
    """One variant of the open-legacy-session scenario (M03/M04/P12)."""

    variant: str
    login: str
    role: str
    rotation_login: str
    rotation_password: str
    # the login's pre-migration search_path setting, written by the
    # executor before the session opens (None: the built-in
    # "$user", public default)
    explicit_setting: str | None
    # the open session's first statements and the barrier's target:
    # a marker table in the login's own schema, created unqualified
    # (the built-in "$user" resolution puts it there) or explicitly
    # qualified (an explicit path that does not contain the schema)
    marker_sql: str
    marker_table: str
    # the late objects the still-open session creates after the
    # migration, the barrier's target, and how a rotation login
    # ALTERs the late table (unqualified where the schema is on the
    # path, explicitly qualified where it is not)
    late_sql: str
    late_table: str
    alter_table: str
    # the effective search_path of fresh logins after the migration
    # (SHOW search_path output): the captured prefix plus the
    # configured segment; the login's implicit own schema stays
    # OUTSIDE it in the explicit-path variant
    expected_path: str
    # the false-table oracle (M04/P12): the unqualified ``orders``
    # query on fresh logins must return the expected marker and never
    # the forbidden one (None: this variant has no oracle)
    expected_marker: str | None = None
    forbidden_marker: str | None = None
    # provoke a delayed session start (M03): the session's first
    # statement waits on a bounded pg_sleep(5) BEFORE creating the
    # marker table, so the marker cannot exist for at least five
    # seconds after the session starts -- the existence barrier must
    # actually wait through that window instead of failing
    delayed_start: bool = False


_OPEN_LEGACY_SESSION_SPECS = [
    pytest.param(  # M03
        _OpenLegacySessionSpec(
            variant="own-schema",
            login="late_app",
            role="late_owner",
            rotation_login="late_app2",
            rotation_password="LateRotation2",
            explicit_setting=None,
            marker_sql=(
                "CREATE TABLE session_marker (id int); "
                "INSERT INTO session_marker VALUES (1);\n"
            ),
            marker_table="late_app.session_marker",
            late_sql=(
                "CREATE TABLE late_orders (id int, note text); "
                "INSERT INTO late_orders VALUES (1, 'late-note');\n"
            ),
            late_table="late_app.late_orders",
            alter_table="late_orders",
            expected_path="late_app, public",
        ),
        id="own-schema",
    ),
    pytest.param(  # M03
        _OpenLegacySessionSpec(
            variant="own-schema-delayed-start",
            login="late_app",
            role="late_owner",
            rotation_login="late_app2",
            rotation_password="LateRotation2",
            explicit_setting=None,
            marker_sql=(
                "CREATE TABLE session_marker (id int); "
                "INSERT INTO session_marker VALUES (1);\n"
            ),
            marker_table="late_app.session_marker",
            late_sql=(
                "CREATE TABLE late_orders (id int, note text); "
                "INSERT INTO late_orders VALUES (1, 'late-note');\n"
            ),
            late_table="late_app.late_orders",
            alter_table="late_orders",
            expected_path="late_app, public",
            delayed_start=True,
        ),
        id="own-schema-delayed-start",
    ),
    pytest.param(  # M04/P12
        _OpenLegacySessionSpec(
            variant="explicit-path-implicit-schema",
            login="billing",
            role="billing_owner",
            rotation_login="billing2",
            rotation_password="BillingRot2",
            explicit_setting="ALTER ROLE billing SET search_path TO public, reporting;",
            marker_sql=(
                "CREATE TABLE billing.session_marker (id int); "
                "INSERT INTO billing.session_marker VALUES (1);\n"
            ),
            marker_table="billing.session_marker",
            late_sql=(
                "CREATE TABLE billing.late_orders (id int, note text); "
                "INSERT INTO billing.late_orders VALUES (1, 'late-note'); "
                "CREATE TABLE billing.orders (id int, note text); "
                "INSERT INTO billing.orders VALUES (1, 'billing-note');\n"
            ),
            late_table="billing.late_orders",
            alter_table="billing.late_orders",
            expected_path="public, reporting",
            expected_marker="public-note",
            forbidden_marker="billing-note",
        ),
        id="explicit-path-implicit-schema",
    ),
]


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
@pytest.mark.parametrize("spec", _OPEN_LEGACY_SESSION_SPECS)
def test_open_legacy_session_late_objects_managed(
    postgres: PostgresContainer, spec: _OpenLegacySessionSpec
) -> None:
    """M03, M04, P12 — Objects a still-open legacy session creates after the migration.

    Two REAL sessions around one migration (finding S2): a legacy
    tenant whose access list names ONLY public, so the login's
    implicit own schema (what legacy mode auto-creates next to the
    login) is not in the access list. An application session opened
    as the legacy login BEFORE the migration keeps running across it
    -- its backend predates the role default, so objects it creates
    are owned by the plain login. The migration itself adds ONLY the
    role: username, password, grants and schema order stay identical,
    through the production renderer. The still-open session then
    creates a late table and commits.

    Synchronization (M03): the open session's progress is observed
    through a deterministic two-phase barrier -- ``to_regclass``
    proves the table EXISTS (a system-function query, no table
    access, no undefined_table abort) before the committed marker row
    is polled. The open session's backend is proven by id and state
    in pg_stat_activity before and after the migration, and the
    objects it creates are proven owned by the PLAIN login (catalog
    OIDs) before adoption. The ``own-schema-delayed-start`` variant
    provokes a delayed start once deliberately: the session's first
    statement is a bounded ``pg_sleep(5)`` before the marker CREATE,
    so the barrier provably WAITS (against the previous count-only
    poll the very first poll aborted with undefined_table).

    Variants:

    - ``own-schema`` (M03): no explicit setting; the built-in
      "$user", public resolution puts the unqualified marker and
      late table into the login's own schema, which is ON the
      captured path. A DAM run with the UNCHANGED configuration must
      adopt the late table into the owner role, and a rotation login
      of the same role -- a fresh connection acting as the role via
      the role default, no manual SET ROLE anywhere -- must be able
      to ALTER the late table (regression: "must be owner of table
      late_orders").
    - ``own-schema-delayed-start`` (M03): the same flow with the
      provoked delayed start.
    - ``explicit-path-implicit-schema`` (M04, with P12's
      managed-but-not-on-the-path side): the captured path is the
      login's EXPLICIT setting ``public, reporting`` and does NOT
      contain the implicit schema ``billing``. The old session
      creates ``billing.late_orders`` (and the oracle twin
      ``billing.orders``) EXPLICITLY qualified after the migration.
      The late table MUST be adopted by the next unchanged run even
      though ``billing`` is not on the captured path (RED before the
      default-ACL memory: the continuation rule needed prefix
      membership); v2 can ``ALTER TABLE billing.late_orders``
      QUALIFIED; and ``billing`` must NOT move to the front of the
      search path -- fresh v1 and v2 connections keep it OUTSIDE the
      effective path entirely (the false-table oracle: the
      unqualified ``orders`` query returns the public marker, never
      the billing one). The executor-owned ``reporting`` path member
      DAM never manages keeps its owner.
    """
    pg = postgres
    db = f"legacy_open_{spec.variant.replace('-', '_')}_db"
    _create_database(pg, db)

    # the explicit-path variant's scenery: a second, realistic member
    # of the captured path (executor-owned, never managed) and the
    # false-table oracle's public twin
    setup = ""
    if spec.explicit_setting:
        setup += "CREATE SCHEMA reporting; "
    if spec.expected_marker:
        setup += (
            "CREATE TABLE public.orders (id int, note text); "
            "INSERT INTO public.orders VALUES (1, 'public-note'); "
        )
    if setup:
        result = pg.exec_psql(EXECUTOR, db, setup)
        assert result.returncode == 0, result.stderr

    # 1. legacy provision: the access list names ONLY public, the
    # login's implicit own schema is auto-created next to the login
    legacy_config = make_db_access(
        database=db, username=spec.login, access=[("public", ("SELECT", "INSERT"))]
    )
    _run_provision(pg, build_script(legacy_config))

    # the login's explicit pre-migration path (the captured setting
    # of the explicit-path variant)
    if spec.explicit_setting:
        result = pg.exec_psql(EXECUTOR, db, spec.explicit_setting)
        assert result.returncode == 0, result.stderr

    # 2. session A: a REAL application session of the legacy login
    # with its password, opened BEFORE the migration. It commits an
    # initial marker row (psql autocommit); the trailing newline
    # matters: psql only executes a statement once its line is
    # complete, and stdin stays open for the whole session. The
    # delayed-start variant provokes the bounded wait BEFORE the
    # marker CREATE (pg_sleep(5)): the existence barrier must wait
    # through it
    delayed_prefix = "SELECT pg_sleep(5); " if spec.delayed_start else ""
    session_a: subprocess.Popen[str] = pg.start_session(
        spec.login,
        db,
        delayed_prefix + spec.marker_sql,
        password=DB_PASSWORD,
    )
    try:
        # the session is provably connected: its committed marker row
        # is visible from the executor connection -- the
        # deterministic barrier (to_regclass first, then the row
        # count) replaces the abort-on-first-poll count query
        _wait_for_table_row(
            pg,
            db,
            spec.marker_table,
            "1",
            what="the open legacy session to commit its marker row",
        )

        # the open session's backend is proven by id and state: one
        # backend of the login exists, it is idle (its statements
        # committed), and its pid is recorded to prove the SAME
        # backend survives the migration
        _wait_until(
            pg,
            db,
            "SELECT count(*) FROM pg_stat_activity "
            f"WHERE usename = '{spec.login}' AND pid <> pg_backend_pid()",
            "1",
            what="the open legacy session's backend to appear",
        )
        session_pid = pg.query(
            "postgres",
            db,
            "SELECT pid FROM pg_stat_activity "
            f"WHERE usename = '{spec.login}' AND pid <> pg_backend_pid()",
        )
        assert session_pid, "no backend found for the open legacy session"
        assert (
            pg.query(
                "postgres",
                db,
                f"SELECT state FROM pg_stat_activity WHERE pid = {session_pid}",
            )
            == "idle"
        ), "the open legacy session is not idle after committing its marker"
        assert session_a.poll() is None, "the legacy session died before the migration"

        # 3. the migration in a SECOND session (the test's executor
        # connection): only the role is added, everything else
        # identical, through the production renderer
        role_config = make_db_access(
            database=db,
            username=spec.login,
            role=spec.role,
            access=[("public", ("SELECT", "INSERT"))],
        )
        _run_provision(pg, build_script(role_config, legacy_config))

        # the SAME backend (by pid) survived the migration and is
        # still idle: the session provably predates the role default
        assert (
            pg.query(
                "postgres",
                db,
                f"SELECT state FROM pg_stat_activity WHERE pid = {session_pid}",
            )
            == "idle"
        ), "the open legacy session did not survive the migration"

        # 4. session A -- still open, still the plain legacy login
        # WITHOUT the role default (it connected before the
        # migration) -- creates the late objects and commits; the
        # trailing newline and flush matter as above
        assert session_a.stdin is not None
        session_a.stdin.write(spec.late_sql)
        session_a.stdin.flush()
        _wait_for_table_row(
            pg,
            db,
            spec.late_table,
            "1",
            what="the open legacy session to commit its late table",
        )

        # the late table is owned by the PLAIN login (catalog OID
        # proof): the open session's backend predates the role
        # default, so it does not act as the owner role
        late_schema, _, late_name = spec.late_table.partition(".")
        _assert_owner(
            pg,
            db,
            "late table before adoption",
            "SELECT pg_get_userbyid(relowner) FROM pg_class "
            f"WHERE relname = '{late_name}' "
            f"AND relnamespace = '{late_schema}'::regnamespace",
            spec.login,
        )

        # 5. another DAM run with the UNCHANGED configuration must
        # adopt the late table into the owner role (regression: the
        # transferred implicit schema had left the managed set --
        # M03: the own-schema detection only triggered while the
        # schema was owned by the login; M04: the continuation rule
        # needed prefix membership, and the explicit path does not
        # contain the implicit schema)
        _run_provision(pg, build_script(role_config))
        _assert_owner(
            pg,
            db,
            "late table of the open legacy session",
            "SELECT pg_get_userbyid(relowner) FROM pg_class "
            f"WHERE relname = '{late_name}' "
            f"AND relnamespace = '{late_schema}'::regnamespace",
            spec.role,
        )

        # 6. the effective path of a FRESH connection of the original
        # login: the captured prefix plus the configured segment, and
        # the implicit own schema stays OUTSIDE it in the
        # explicit-path variant (P12: managed but not on the path)
        result = pg.login(spec.login, DB_PASSWORD, db, "SHOW search_path;")
        assert result.returncode == 0, result.stderr
        assert spec.expected_path in result.stdout, (
            f"v1 search path: expected {spec.expected_path!r}, got {result.stdout}"
        )
        if spec.expected_marker and spec.forbidden_marker:
            assert spec.login not in result.stdout, (
                f"the implicit schema {spec.login!r} moved into the "
                f"effective path: {result.stdout}"
            )
            # the false-table oracle: the unqualified name resolves to
            # the public twin, never to the implicit schema's table
            _assert_unqualified_marker(
                pg,
                db,
                spec.login,
                DB_PASSWORD,
                spec.expected_marker,
                forbidden=(spec.forbidden_marker,),
                where="fresh v1 connection after the migration",
            )

        # 7. a rotation login of the same role with the same access
        # list: its fresh connections act as the role via the role
        # default, without any manual SET ROLE, and ALTERing the late
        # table must succeed (regression: "must be owner of table
        # late_orders"); in the explicit-path variant the ALTER is
        # deliberately QUALIFIED -- the implicit schema is outside
        # the effective path, so only the qualified name reaches it
        rotation = _render_provision(
            db,
            spec.rotation_login,
            role=spec.role,
            access_list="public|SELECT,INSERT",
            schemas_csv="public",
        )
        _run_provision(pg, rotation, password=spec.rotation_password)
        result = pg.login(
            spec.rotation_login,
            spec.rotation_password,
            db,
            "SHOW search_path;",
        )
        assert result.returncode == 0, result.stderr
        assert spec.expected_path in result.stdout, (
            f"v2 search path: expected {spec.expected_path!r}, got {result.stdout}"
        )
        if spec.expected_marker and spec.forbidden_marker:
            assert spec.login not in result.stdout, (
                f"the implicit schema {spec.login!r} moved into the "
                f"effective path: {result.stdout}"
            )
            _assert_unqualified_marker(
                pg,
                db,
                spec.rotation_login,
                spec.rotation_password,
                spec.expected_marker,
                forbidden=(spec.forbidden_marker,),
                where="fresh v2 connection after the rotation",
            )
        result = pg.login(
            spec.rotation_login,
            spec.rotation_password,
            db,
            f"ALTER TABLE {spec.alter_table} ADD COLUMN rotated text;",
        )
        assert result.returncode == 0, result.stderr

        # 8. the explicit-path variant's path member DAM never
        # managed keeps its owner: a schema on the captured path is
        # order-only, never managed (no default-ACL row, no
        # ownership takeover)
        if spec.explicit_setting:
            assert (
                pg.query(
                    EXECUTOR,
                    db,
                    "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
                    "WHERE nspname = 'reporting'",
                )
                == EXECUTOR
            ), "the unmanaged path member reporting changed owner"
    finally:
        # 9. cleanup: end the still-open legacy session
        session_a.kill()
        session_a.wait(timeout=30)
        pg.terminate_sessions(spec.login)


# ─── 4c. a removed public must not be re-managed (P11) ─────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_removed_public_not_remanaged(postgres: PostgresContainer) -> None:
    """P09, P10, P11, P12 — A removed ``public`` must not be re-managed (P11, with P12's
    on-the-path-but-not-managed side).

    A migrated legacy tenant had ``public`` in the old path AND as a
    configured area; after the transfer ``public`` belongs to the app
    role. The configuration then changes ``public,sales`` to ``sales``
    through the production renderer (the revoke delta is computed
    from the old configuration). The ADMIN -- the DAM executor, like
    a master user -- creates a new table in ``public``, and DAM runs
    again with the UNCHANGED sales-only configuration.

    RED before the default-ACL memory: the admin table transferred
    to the app owner, because ``public`` is ALWAYS in the
    path-fallback scope (the configured segment appends it), so the
    revoke signal never dropped it from the captured prefix, and the
    prefix-intersect-role-owned rule kept managing it. Acceptance:

    - the admin table STAYS admin-owned: no restoration of
      MANAGEMENT for ``public`` merely because it is a legitimate
      search-path fallback;
    - no restoration of DEFAULT-ACLs for ``public`` (the
      removal-run's revokes stay revoked), while the configured
      ``sales`` keeps its default-ACL row and stays managed (a late
      table there is adopted);
    - the database owner is unchanged on the follow-up run;
    - P12 (on the path but not managed): ``public`` remains a USABLE
      fallback. The app's fresh connection still resolves unqualified
      names there first (the captured prefix keeps it on the path)
      and can create and read its marker placed ONLY there -- the
      marker belongs to the role through the app's own role default,
      not through any DAM transfer, and no default-ACL row appears
      for ``public`` while the table exists. The already-transferred
      pre-removal objects in ``public`` are NOT asserted unreadable:
      the removal run's revokes legitimately strip even the owner's
      privileges there.

    P09/P10 reproductions: an ordinary PostgreSQL default privilege
    the APP set (acting as the owner role) is not a management
    mandate. The app creates a NEVER-configURED role-owned schema
    with a default ACL, and re-sets a default ACL in the ALREADY
    REMOVED ``public``; admin tables placed in both must stay
    admin-owned after unchanged follow-up runs (the P09/P10 oracle).
    P12 checkpoint: after the removal, a fresh v2-style rotation
    login of the role keeps ``public`` as a usable fallback while
    the executor's post-removal table stays admin-owned.
    """
    pg = postgres
    db = "p11_public_removal_db"
    _create_database(pg, db)

    # the area that stays configured, with the false-table oracle's
    # other twin
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE SCHEMA sales; "
        "CREATE TABLE sales.orders (id int, note text); "
        "INSERT INTO sales.orders VALUES (1, 'sales-note');",
    )
    assert result.returncode == 0, result.stderr

    # the legacy tenant: public AND sales configured
    legacy_config = make_db_access(
        database=db,
        username="p11_app",
        access=[
            ("public", ("SELECT", "INSERT")),
            ("sales", ("SELECT", "INSERT")),
        ],
    )
    _run_provision(pg, build_script(legacy_config))

    # the login's explicit old path: public
    result = pg.exec_psql(EXECUTOR, db, "ALTER ROLE p11_app SET search_path TO public;")
    assert result.returncode == 0, result.stderr

    # the migration adds ONLY the role, through the production
    # renderer; after the transfer public belongs to the app role
    role_config = make_db_access(
        database=db,
        username="p11_app",
        role="p11_owner",
        access=[
            ("public", ("SELECT", "INSERT")),
            ("sales", ("SELECT", "INSERT")),
        ],
    )
    _run_provision(pg, build_script(role_config, legacy_config))
    _assert_owner(
        pg,
        db,
        "public schema after the transfer",
        "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'public'",
        "p11_owner",
    )

    # the configuration removes public (production renderer: the
    # revoke delta carries public|ALL)
    sales_only = make_db_access(
        database=db,
        username="p11_app",
        role="p11_owner",
        access=[("sales", ("SELECT", "INSERT"))],
    )
    _run_provision(pg, build_script(sales_only, role_config))

    # the ADMIN (the DAM executor) creates a new table in public --
    # and one in sales, to prove the configured area keeps adopting
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE public.admin_new (id int); "
        "CREATE TABLE sales.admin_sales (id int);",
    )
    assert result.returncode == 0, result.stderr

    # the app's fresh connection places its readable marker ONLY in
    # public: the captured prefix keeps public first on the path, so
    # the unqualified DDL lands there, and the table belongs to the
    # role through the app's own role default -- not through DAM
    result = pg.login(
        "p11_app",
        DB_PASSWORD,
        db,
        "CREATE TABLE orders (id int, note text); "
        "INSERT INTO orders VALUES (1, 'public-note');",
    )
    assert result.returncode == 0, result.stderr
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT n.nspname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = 'orders' AND c.relnamespace "
            "NOT IN ('sales'::regnamespace)",
        )
        == "public"
    ), "the app's unqualified DDL did not land in the public fallback"

    database_owner_before = _database_owner(pg, db)

    # DAM runs again with the UNCHANGED sales-only configuration
    _run_provision(pg, build_script(sales_only))

    # the admin table STAYS admin-owned: public is not re-managed
    # merely because it is a legitimate search-path fallback
    _assert_owner(
        pg,
        db,
        "admin table in the removed public",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = 'admin_new'",
        EXECUTOR,
    )
    # the configured area stays managed: the late table there is
    # adopted by the owner role
    _assert_owner(
        pg,
        db,
        "admin table in the configured sales",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = 'admin_sales'",
        "p11_owner",
    )
    # the app's fallback marker belongs to the role through the app's
    # own role default -- DAM did not need to (and did not) transfer
    # anything in public for it
    _assert_owner(
        pg,
        db,
        "app marker in the public fallback",
        "SELECT pg_get_userbyid(relowner) FROM pg_class "
        "WHERE relname = 'orders' "
        "AND relnamespace = 'public'::regnamespace",
        "p11_owner",
    )
    # no restoration of default-ACLs for public -- while the app's
    # table exists there; sales keeps its row
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT count(*) FROM pg_default_acl "
            "WHERE defaclrole = 'p11_owner'::regrole "
            "AND defaclnamespace = 'public'::regnamespace",
        )
        == "0"
    ), "default privileges were restored for the removed public"
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT count(*) FROM pg_default_acl "
            "WHERE defaclrole = 'p11_owner'::regrole "
            "AND defaclnamespace = 'sales'::regnamespace",
        )
        != "0"
    ), "the configured sales lost its default-ACL row"
    # the database owner is unchanged on the follow-up run
    assert _database_owner(pg, db) == database_owner_before

    # P12: public remains a usable fallback -- the app's fresh
    # connection reads the marker placed only there, and the
    # unqualified resolution keeps hitting it first (the sales twin
    # must not win)
    _assert_unqualified_marker(
        pg,
        db,
        "p11_app",
        DB_PASSWORD,
        "public-note",
        forbidden=("sales-note",),
        where="after the removal, fresh login",
    )

    # ── P09: an ordinary PostgreSQL default privilege is not a ──────
    # management mandate. The app (acting as the owner role, which
    # owns the schema from birth) creates a NEVER-CONFIGURED schema
    # and sets a default ACL there -- the exact catalog row DAM's own
    # 5i grants produce. An admin table placed there must NOT be
    # adopted by an unchanged follow-up run (the P09/P10 oracle: the
    # table's owner stays the executor)
    result = pg.login(
        "p11_app",
        DB_PASSWORD,
        db,
        "CREATE SCHEMA app_archive; "
        "GRANT USAGE, CREATE ON SCHEMA app_archive TO test_admin; "
        "ALTER DEFAULT PRIVILEGES IN SCHEMA app_archive "
        "GRANT SELECT ON TABLES TO public;",
    )
    assert result.returncode == 0, result.stderr
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT count(*) FROM pg_default_acl "
            "WHERE defaclrole = 'p11_owner'::regrole "
            "AND defaclnamespace = 'app_archive'::regnamespace",
        )
        != "0"
    ), "the app-set default ACL row is missing (setup incomplete)"
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE app_archive.admin_acl_probe (id int);",
    )
    assert result.returncode == 0, result.stderr

    _run_provision(pg, build_script(sales_only))
    _assert_owner(
        pg,
        db,
        "admin table in the never-configured app_archive",
        "SELECT pg_get_userbyid(relowner) FROM pg_class "
        "WHERE relname = 'admin_acl_probe'",
        EXECUTOR,
    )

    # ── P10: the same reproduction for an ALREADY-REMOVED schema: ──
    # the app re-sets a default ACL in the removed public (an
    # ordinary privilege, not a management signal), the executor
    # places another admin table there, and an unchanged follow-up
    # run must not adopt it either
    result = pg.login(
        "p11_app",
        DB_PASSWORD,
        db,
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO public;",
    )
    assert result.returncode == 0, result.stderr
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE public.admin_acl_probe2 (id int);",
    )
    assert result.returncode == 0, result.stderr

    _run_provision(pg, build_script(sales_only))
    _assert_owner(
        pg,
        db,
        "admin table in the removed public after an app-set default ACL",
        "SELECT pg_get_userbyid(relowner) FROM pg_class "
        "WHERE relname = 'admin_acl_probe2'",
        EXECUTOR,
    )

    # ── P12 checkpoint with a SECOND login: a v2-style rotation ────
    # login of the role (fresh connection, no state of its own) keeps
    # public as a usable fallback, while the executor's post-removal
    # table stays admin-owned
    rotation = _render_provision(
        db,
        "p11_app2",
        role="p11_owner",
        access_list="sales|SELECT,INSERT",
        schemas_csv="sales",
    )
    _run_provision(pg, rotation, password="P11Rotation2")
    _assert_unqualified_marker(
        pg,
        db,
        "p11_app2",
        "P11Rotation2",
        "public-note",
        forbidden=("sales-note",),
        where="after the removal, fresh v2 rotation login",
    )
    _assert_owner(
        pg,
        db,
        "admin table in the removed public after the v2 rotation run",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = 'admin_new'",
        EXECUTOR,
    )


# ─── 5. credential rotation v1/v2 in the same role ────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_rotation_keeps_unqualified_access(postgres: PostgresContainer) -> None:
    """M05, P08 — Credential rotation v1/v2 within the same owner role.

    The app schemas are deliberately NOT named after either login, so
    the login's search path must point at the managed schemas and not
    at the rotating login name (regression: after rotating from v1 to
    v2 the app could no longer find its tables without a schema
    prefix). Two managed schemas both contain a table named ``orders``
    with distinct data: v1 and v2 list the schemas in the SAME order,
    so the unqualified name must resolve to the SAME table (the first
    schema) and its SAME data for both logins -- not merely keep the
    query succeeding. An open v1 session is terminated by the
    deprovision; v2, the data, the owner role and the database owner
    survive.

    v1's positive connection is proven right before the deprovision
    cuts it off: a fresh password login reading the marker while the
    open session's backend is proven by pid and state in
    pg_stat_activity, and the terminated backend is proven gone
    afterwards.

    After EACH removal (v1 in the first scenario, the original legacy
    login in the second) the scenario runs one further DAM
    reconciliation of the v2 entry and only then verifies v2 again on
    a fresh password connection: the same marker, the same DDL target
    schema, and no fallback to public.

    A second scenario in the same container (a separate database)
    covers a MIGRATED tenant: a legacy tenant adds a role, rotates to
    a v2 login and REMOVES the original legacy login. v2 then still
    reads the same marker, creates unqualified tables in the same DDL
    target schema (the legacy login's own schema) and does not fall
    back to public.
    """
    pg = postgres
    db = "rotation_db"
    _create_database(pg, db)
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE SCHEMA sales; "
        "CREATE SCHEMA archive; "
        "CREATE TABLE sales.orders (id int, src text); "
        "INSERT INTO sales.orders VALUES (1, 'sales-data'), (2, 'sales-data-2'); "
        "CREATE TABLE archive.orders (id int, src text); "
        "INSERT INTO archive.orders VALUES (1, 'archive-data');",
    )
    assert result.returncode == 0, result.stderr

    # provision v1: both schemas, in the same order as v2 below
    v1 = _render_provision(
        db,
        "cs_v1",
        role="cs_owner",
        access_list="sales|ALL;archive|ALL",
        schemas_csv="sales,archive",
    )
    _run_provision(pg, v1, password="RotationPw1")

    # v1 resolves the unqualified name to the FIRST schema (sales)
    # and its data
    result = pg.login(
        "cs_v1", "RotationPw1", db, "SELECT src FROM orders WHERE id = 2;"
    )
    assert result.returncode == 0, result.stderr
    assert "sales-data-2" in result.stdout

    # v1 can read BOTH tables with qualified names
    result = pg.login(
        "cs_v1",
        "RotationPw1",
        db,
        "SELECT src FROM sales.orders WHERE id = 1; "
        "SELECT src FROM archive.orders WHERE id = 1;",
    )
    assert result.returncode == 0, result.stderr
    assert "sales-data" in result.stdout
    assert "archive-data" in result.stdout

    # v1's app creates a table (owned by the owner role via the role default)
    result = pg.login(
        "cs_v1", "RotationPw1", db, "CREATE TABLE sales.v1_table (id int);"
    )
    assert result.returncode == 0, result.stderr

    # rotate: v2 joins the same owner role with its own password and
    # the SAME schema order in its access list
    v2 = _render_provision(
        db,
        "cs_v2",
        role="cs_owner",
        access_list="sales|ALL;archive|ALL",
        schemas_csv="sales,archive",
    )
    _run_provision(pg, v2, password="RotationPw2")
    database_owner_after_provision = _database_owner(pg, db)

    # v2 resolves the SAME unqualified name to the SAME table and its
    # SAME data as v1
    result = pg.login(
        "cs_v2", "RotationPw2", db, "SELECT src FROM orders WHERE id = 2;"
    )
    assert result.returncode == 0, result.stderr
    assert "sales-data-2" in result.stdout

    # v2 can read BOTH tables with qualified names
    result = pg.login(
        "cs_v2",
        "RotationPw2",
        db,
        "SELECT src FROM sales.orders WHERE id = 1; "
        "SELECT src FROM archive.orders WHERE id = 1;",
    )
    assert result.returncode == 0, result.stderr
    assert "sales-data" in result.stdout
    assert "archive-data" in result.stdout

    # v2 can ALTER objects created by v1
    result = pg.login(
        "cs_v2",
        "RotationPw2",
        db,
        "ALTER TABLE sales.v1_table ADD COLUMN v2_col text;",
    )
    assert result.returncode == 0, result.stderr

    # v1's POSITIVE connection is proven unambiguously BEFORE the
    # deprovision terminates it: a fresh password login reading the
    # marker while v2 already exists. Rotation added a second usable
    # login -- it did not change v1's password
    result = pg.login(
        "cs_v1", "RotationPw1", db, "SELECT src FROM orders WHERE id = 2;"
    )
    assert result.returncode == 0, result.stderr
    assert "sales-data-2" in result.stdout

    # an open v1 session holds a transaction; the deprovision cuts it
    # off. The trailing newline matters: psql only executes a
    # statement once its line is complete, and stdin stays open for
    # the whole session
    v1_session: subprocess.Popen[str] = pg.start_session(
        "cs_v1",
        db,
        "BEGIN; SELECT count(*) FROM sales.orders; SELECT pg_sleep(60);\n",
        password="RotationPw1",
    )
    # the open session's backend is proven by id and state BEFORE the
    # deprovision terminates it: wait until the session actually runs
    # pg_sleep (earlier states are transitional), then record the
    # backend pid and verify the session is active inside its open
    # transaction. pg_stat_activity always exists, the poll never hits
    # an undefined table
    _wait_until(
        pg,
        db,
        "SELECT count(*) FROM pg_stat_activity WHERE usename = 'cs_v1' "
        "AND state = 'active' AND query LIKE '%pg_sleep%'",
        "1",
        what="the open v1 session to run pg_sleep",
    )
    v1_pid = pg.query(
        "postgres",
        db,
        "SELECT pid FROM pg_stat_activity WHERE usename = 'cs_v1' "
        "AND query LIKE '%pg_sleep%'",
    )
    assert v1_pid
    assert (
        pg.query(
            "postgres",
            db,
            f"SELECT state || '/' || (xact_start IS NOT NULL)::text "
            f"FROM pg_stat_activity WHERE pid = {v1_pid}",
        )
        == "active/true"
    )
    drop_v1 = _render_deprovision(db, "cs_v1", role=True)
    result = pg.exec_psql(EXECUTOR, "postgres", drop_v1)
    assert result.returncode == 0, f"deprovision v1 failed: {result.stderr}"

    # the session was terminated: without termination it would sit in
    # pg_sleep(60) far beyond this timeout
    try:
        v1_session.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        v1_session.kill()
        pytest.fail("the open v1 session survived the deprovision")

    # the terminated backend is really gone: the recorded pid no
    # longer appears in pg_stat_activity (the deprovision itself waits
    # for the terminated sessions to exit, so this is deterministic)
    _wait_until(
        pg,
        db,
        f"SELECT count(*) FROM pg_stat_activity WHERE pid = {v1_pid}",
        "0",
        what="the terminated v1 backend to disappear",
    )

    # new v1 logins fail: the credential is gone
    result = pg.login("cs_v1", "RotationPw1", db, "SELECT 1;")
    assert result.returncode != 0, "the rotated-out login still works"
    assert "password authentication failed" in result.stderr

    # one more DAM reconciliation of the v2 entry AFTER the removal
    # (the same production-rendered script the scenario uses): the
    # rotation is complete, and the next run must keep v2's world
    # intact instead of disturbing it
    _run_provision(pg, v2, password="RotationPw2")

    # v2 on a FRESH password connection after that reconcile: the
    # same marker, and unqualified DDL still targets the SAME schema
    # (sales), not a fallback elsewhere
    result = pg.login(
        "cs_v2", "RotationPw2", db, "SELECT src FROM orders WHERE id = 2;"
    )
    assert result.returncode == 0, result.stderr
    assert "sales-data-2" in result.stdout
    result = pg.login(
        "cs_v2", "RotationPw2", db, "CREATE TABLE v2_after_removal (id int);"
    )
    assert result.returncode == 0, result.stderr
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT n.nspname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = 'v2_after_removal'",
        )
        == "sales"
    ), "v2's unqualified DDL changed its target schema after the removal"

    # v2, the data, the owner role and the database owner survive
    assert (
        pg.query(
            EXECUTOR, db, "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cs_v1')"
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR, db, "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cs_v2')"
        )
        == "t"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cs_owner')",
        )
        == "t"
    )
    result = pg.login(
        "cs_v2", "RotationPw2", db, "SELECT src FROM orders WHERE id = 2;"
    )
    assert result.returncode == 0, result.stderr
    assert "sales-data-2" in result.stdout
    assert _database_owner(pg, db) == database_owner_after_provision

    # ── sub-scenario: a MIGRATED tenant rotates and drops its legacy ──
    # login. The tenant's DDL target is the legacy login's own schema
    # (what legacy mode auto-creates next to its login); a same-named
    # decoy table in public proves that v2 does not fall back to it.
    # The old→new transition goes through the production renderer, so
    # the revoke delta is computed from the real legacy configuration.
    mdb = "rotation_migrated_db"
    _create_database(pg, mdb)

    # the public decoy with uniquely distinct data
    result = pg.exec_psql(
        EXECUTOR,
        mdb,
        "CREATE TABLE public.orders (id int, src text); "
        "INSERT INTO public.orders VALUES (1, 'public-decoy');",
    )
    assert result.returncode == 0, result.stderr

    # the legacy tenant: the login owns its own schema
    legacy_config = make_db_access(
        database=mdb,
        username="legacy_app",
        access=[("legacy_app", ("SELECT", "INSERT"))],
    )
    _run_provision(pg, build_script(legacy_config))

    # the legacy app creates its marker table with unqualified DDL
    # (the legacy "$user", public path puts it in the login's schema)
    result = pg.login(
        "legacy_app",
        DB_PASSWORD,
        mdb,
        "CREATE TABLE orders (id int, src text); "
        "INSERT INTO orders VALUES (1, 'legacy-marker');",
    )
    assert result.returncode == 0, result.stderr
    result = pg.login(
        "legacy_app", DB_PASSWORD, mdb, "SELECT src FROM orders WHERE id = 1;"
    )
    assert result.returncode == 0, result.stderr
    assert "legacy-marker" in result.stdout

    # the migration adds ONLY the role (same username, same grants)
    role_config = make_db_access(
        database=mdb,
        username="legacy_app",
        role="cs_mig_owner",
        access=[("legacy_app", ("SELECT", "INSERT"))],
    )
    _run_provision(pg, build_script(role_config, legacy_config))

    # the same login and password still work after the migration
    result = pg.login(
        "legacy_app", DB_PASSWORD, mdb, "SELECT src FROM orders WHERE id = 1;"
    )
    assert result.returncode == 0, result.stderr
    assert "legacy-marker" in result.stdout

    # rotation: v2 joins the same owner role with its own password
    v2_script = _render_provision(
        mdb,
        "mig_v2",
        role="cs_mig_owner",
        access_list="legacy_app|SELECT,INSERT",
        schemas_csv="legacy_app",
    )
    _run_provision(pg, v2_script, password=MIGRATED_V2_PASSWORD)

    # v2 reads the SAME marker (not the public decoy) on a fresh
    # password connection without SET ROLE
    result = pg.login(
        "mig_v2", MIGRATED_V2_PASSWORD, mdb, "SELECT src FROM orders WHERE id = 1;"
    )
    assert result.returncode == 0, result.stderr
    assert "legacy-marker" in result.stdout

    # the original legacy login is REMOVED: the rotation is complete
    drop_legacy = _render_deprovision(mdb, "legacy_app", role=True)
    result = pg.exec_psql(EXECUTOR, "postgres", drop_legacy)
    assert result.returncode == 0, f"deprovision legacy_app failed: {result.stderr}"

    # one more DAM reconciliation of the v2 entry AFTER the removal of
    # the original legacy login (the production renderer): the
    # rotation is complete, and the next run must keep v2's resolution
    # and DDL target instead of disturbing them
    _run_provision(pg, v2_script, password=MIGRATED_V2_PASSWORD)

    # v2 still reads the same marker after the removal and that
    # reconcile -- on a fresh password connection, without falling
    # back to the public decoy
    result = pg.login(
        "mig_v2", MIGRATED_V2_PASSWORD, mdb, "SELECT src FROM orders WHERE id = 1;"
    )
    assert result.returncode == 0, result.stderr
    assert "legacy-marker" in result.stdout
    assert "public-decoy" not in result.stdout, (
        "v2 fell back to the public decoy after the legacy login was removed"
    )

    # v2 creates unqualified tables in the SAME DDL target schema ...
    result = pg.login(
        "mig_v2",
        MIGRATED_V2_PASSWORD,
        mdb,
        "CREATE TABLE rotation_new (id int); "
        "INSERT INTO rotation_new VALUES (5); "
        "ALTER TABLE orders ADD COLUMN v2_col text;",
    )
    assert result.returncode == 0, result.stderr
    # ... which is the legacy app schema, NOT public
    assert (
        pg.query(
            EXECUTOR,
            mdb,
            "SELECT n.nspname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = 'rotation_new'",
        )
        == "legacy_app"
    )
    _assert_owner(
        pg,
        mdb,
        "v2-created table",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='rotation_new'",
        "cs_mig_owner",
    )

    # the legacy login is gone, the shared role and the data survive
    result = pg.login("legacy_app", DB_PASSWORD, mdb, "SELECT 1;")
    assert result.returncode != 0, "the removed legacy login still works"
    assert "password authentication failed" in result.stderr
    assert (
        pg.query(
            EXECUTOR,
            mdb,
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='legacy_app')",
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR,
            mdb,
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cs_mig_owner')",
        )
        == "t"
    )
    assert pg.query(EXECUTOR, mdb, "SELECT count(*) FROM legacy_app.orders") == "1"


# ─── 5b. search-path stability across unchanged and removed schemas ───────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_search_path_stability(postgres: PostgresContainer) -> None:
    """P08, P09, P10 — The search path must not flip on unchanged or removed configuration.

    Ownership of a schema by the login or the owner role alone is never
    evidence that the schema belongs on the login's search path or in
    the managed set. Two regressions of that rule, one container with
    two steps:

    1. only ``sales`` is configured; the app (acting as the owner
       role) additionally creates ``archive`` with a table of the same
       name and distinct data. An UNCHANGED-configuration run must keep
       resolving the unqualified table name to the configured schema's
       data and must reproduce the login's stored search path byte for
       byte.
    2. ``archive`` is removed from a previously valid list
       ``sales, archive`` through the production renderer: the
       role-owned leftover must not displace the primary application
       table, and the schema must not become managed again (its
       removal-revoked default privileges stay revoked).

    A third step covers the INTENTIONAL order change for a pure
    role-mode tenant without legacy history: the CONFIGURED part of
    the path is derived from the CURRENT ordered desired state, so
    changing ``sales, archive`` to ``archive, sales`` through the
    production renderer must move the unqualified resolution to the
    archive data (regression: the configured segment used to keep its
    old position and the query kept returning the sales data), stay
    stable on a further unchanged run, and a second login of the same
    role must resolve the same data.
    """
    pg = postgres

    # ── step 1: the unchanged run ────────────────────────────────────
    db = "sp_stability_db"
    _create_database(pg, db)
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE SCHEMA sales; "
        "CREATE TABLE sales.orders (id int, src text); "
        "INSERT INTO sales.orders VALUES (1, 'sales-data');",
    )
    assert result.returncode == 0, result.stderr

    first = _render_provision(
        db, "cs_app", role="cs_owner", access_list="sales|ALL", schemas_csv="sales"
    )
    _run_provision(pg, first)

    # the app (its session acts as the owner role, which owns the
    # database after the provision) creates an additional schema with
    # a table of the same name: incidental role-owned schema ownership
    result = pg.login(
        "cs_app",
        DB_PASSWORD,
        db,
        "CREATE SCHEMA archive; "
        "CREATE TABLE archive.orders (id int, src text); "
        "INSERT INTO archive.orders VALUES (1, 'archive-data');",
    )
    assert result.returncode == 0, result.stderr

    # the unqualified name resolves to the configured schema's data
    result = pg.login("cs_app", DB_PASSWORD, db, "SELECT src FROM orders WHERE id = 1;")
    assert result.returncode == 0, result.stderr
    assert "sales-data" in result.stdout

    # an UNCHANGED-configuration run must reproduce the login's stored
    # per-database search-path setting byte for byte
    setting_sql = (
        "SELECT cfg FROM pg_db_role_setting s "
        "JOIN pg_roles r ON r.oid = s.setrole "
        "JOIN pg_database d ON d.oid = s.setdatabase "
        "CROSS JOIN LATERAL unnest(s.setconfig) AS cfg "
        f"WHERE r.rolname = 'cs_app' AND d.datname = '{db}' "
        "AND cfg LIKE 'search_path%'"
    )
    setting_before = pg.query(EXECUTOR, db, setting_sql)
    _run_provision(pg, first)
    assert pg.query(EXECUTOR, db, setting_sql) == setting_before

    # ... and the unqualified name still resolves to the same table
    result = pg.login("cs_app", DB_PASSWORD, db, "SELECT src FROM orders WHERE id = 1;")
    assert result.returncode == 0, result.stderr
    assert "sales-data" in result.stdout

    # ── step 2: the removed schema ───────────────────────────────────
    db2 = "sp_removal_db"
    _create_database(pg, db2)
    result = pg.exec_psql(
        EXECUTOR,
        db2,
        "CREATE SCHEMA sales; "
        "CREATE SCHEMA archive; "
        "CREATE TABLE sales.orders (id int, src text); "
        "INSERT INTO sales.orders VALUES (1, 'sales-data'); "
        "CREATE TABLE archive.orders (id int, src text); "
        "INSERT INTO archive.orders VALUES (1, 'archive-data');",
    )
    assert result.returncode == 0, result.stderr

    with_archive = make_db_access(
        database=db2,
        username="cs_app2",
        role="cs_owner2",
        access=[("sales", ("ALL",)), ("archive", ("ALL",))],
    )
    _run_provision(pg, build_script(with_archive))

    result = pg.login(
        "cs_app2", DB_PASSWORD, db2, "SELECT src FROM orders WHERE id = 1;"
    )
    assert result.returncode == 0, result.stderr
    assert "sales-data" in result.stdout

    # remove archive from the access list through the production
    # renderer (the revoke delta is computed from the old config)
    without_archive = make_db_access(
        database=db2,
        username="cs_app2",
        role="cs_owner2",
        access=[("sales", ("ALL",))],
    )
    _run_provision(pg, build_script(without_archive, with_archive))

    # the removed role-owned leftover does not displace the primary
    # application table
    result = pg.login(
        "cs_app2", DB_PASSWORD, db2, "SELECT src FROM orders WHERE id = 1;"
    )
    assert result.returncode == 0, result.stderr
    assert "sales-data" in result.stdout

    # the removed schema is not re-managed: the reverse-direction
    # default privileges the removal run revoked (5h) stay revoked --
    # a re-managed schema would get them re-granted by 5i. The schema
    # itself keeps its owner (a role-owned leftover).
    assert (
        pg.query(
            EXECUTOR,
            db2,
            "SELECT count(*) FROM pg_default_acl "
            "WHERE defaclrole = 'cs_owner2'::regrole "
            "AND defaclnamespace = 'archive'::regnamespace",
        )
        == "0"
    )
    assert (
        pg.query(
            EXECUTOR,
            db2,
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
            "WHERE nspname = 'archive'",
        )
        == "cs_owner2"
    )

    # ── step 3: the intentional order change ─────────────────────────
    # A pure role-mode tenant WITHOUT legacy history: the configured
    # segment of the path must follow the CURRENT ordered access list,
    # not the position the schemas happened to have when they first
    # entered the path.
    db3 = "sp_order_change_db"
    _create_database(pg, db3)
    result = pg.exec_psql(
        EXECUTOR,
        db3,
        "CREATE SCHEMA sales; "
        "CREATE SCHEMA archive; "
        "CREATE TABLE sales.orders (id int, src text); "
        "INSERT INTO sales.orders VALUES (1, 'sales-data'); "
        "CREATE TABLE archive.orders (id int, src text); "
        "INSERT INTO archive.orders VALUES (1, 'archive-data');",
    )
    assert result.returncode == 0, result.stderr

    sales_first = make_db_access(
        database=db3,
        username="cs_app3",
        role="cs_owner3",
        access=[("sales", ("ALL",)), ("archive", ("ALL",))],
    )
    _run_provision(pg, build_script(sales_first))

    # the initial order resolves the unqualified name to the sales data
    result = pg.login(
        "cs_app3", DB_PASSWORD, db3, "SELECT src FROM orders WHERE id = 1;"
    )
    assert result.returncode == 0, result.stderr
    assert "sales-data" in result.stdout

    # the real configuration change through the production renderer:
    # only the ORDER of the access entries changes (the revoke delta
    # is empty -- same schemas, same grants)
    archive_first = make_db_access(
        database=db3,
        username="cs_app3",
        role="cs_owner3",
        access=[("archive", ("ALL",)), ("sales", ("ALL",))],
    )
    _run_provision(pg, build_script(archive_first, sales_first))

    # the intentional order change applies: the ARCHIVE data now
    # (regression: the configured segment kept its old position and
    # the query kept returning the sales data)
    result = pg.login(
        "cs_app3", DB_PASSWORD, db3, "SELECT src FROM orders WHERE id = 1;"
    )
    assert result.returncode == 0, result.stderr
    assert "archive-data" in result.stdout
    assert "sales-data" not in result.stdout

    # a further UNCHANGED run keeps the resolution stable
    _run_provision(pg, build_script(archive_first))
    result = pg.login(
        "cs_app3", DB_PASSWORD, db3, "SELECT src FROM orders WHERE id = 1;"
    )
    assert result.returncode == 0, result.stderr
    assert "archive-data" in result.stdout
    assert "sales-data" not in result.stdout

    # the rule spans rotation logins: a second login of the same role
    # resolves the same data
    second_login = _render_provision(
        db3,
        "cs_app4",
        role="cs_owner3",
        access_list="archive|ALL;sales|ALL",
        schemas_csv="archive,sales",
    )
    _run_provision(pg, second_login, password="OrderChange2")
    result = pg.login(
        "cs_app4", "OrderChange2", db3, "SELECT src FROM orders WHERE id = 1;"
    )
    assert result.returncode == 0, result.stderr
    assert "archive-data" in result.stdout
    assert "sales-data" not in result.stdout


# ─── 6. fresh tenant with a dedicated database ────────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_dedicated_database_created_by_dam(postgres: PostgresContainer) -> None:
    """O03 — A fresh tenant with empty access and a not-yet-existing database.

    DAM creates the dedicated database itself; a newly created
    dedicated application database belongs to its owner role, and the
    login actually works with its password. The owner role is NOLOGIN
    (a pure group role in the catalog), and a fresh connection of the
    login acts as the owner role through the role default: the
    session_user is the login while the current_user is the owner
    role. The instance's postgres database is untouched.
    """
    pg = postgres

    # the admin database's owner before the run (OID comparison below)
    postgres_datdba = pg.query(
        EXECUTOR,
        "postgres",
        "SELECT datdba FROM pg_database WHERE datname = 'postgres'",
    )

    script = _render_provision(
        "dedicated_db", "cs_app", role="cs_owner", access_list="", schemas_csv=""
    )
    _run_provision(pg, script)

    # the database was created and belongs to its owner role
    assert _database_owner(pg, "dedicated_db") == "cs_owner"

    # the owner role exists and is a pure NOLOGIN group role
    assert (
        pg.query(
            EXECUTOR,
            "postgres",
            "SELECT rolcanlogin FROM pg_roles WHERE rolname = 'cs_owner'",
        )
        == "f"
    )

    # the login actually connects with its password and, on the fresh
    # connection, acts as the owner role: the session user stays the
    # login while the current user is the owner role (the role default
    # in action, no manual SET ROLE anywhere)
    result = pg.login(
        "cs_app",
        DB_PASSWORD,
        "dedicated_db",
        "SELECT session_user || ':' || current_user;",
    )
    assert result.returncode == 0, result.stderr
    assert "cs_app:cs_owner" in result.stdout, result.stdout

    # the postgres database keeps its owner (the datdba OID is unchanged)
    assert (
        pg.query(
            EXECUTOR,
            "postgres",
            "SELECT datdba FROM pg_database WHERE datname = 'postgres'",
        )
        == postgres_datdba
    )
    assert _database_owner(pg, "postgres") == "postgres"


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_empty_access_does_not_take_over_admin_database(
    postgres: PostgresContainer,
) -> None:
    """O02 — An entry with empty access on the existing admin database.

    The admin database must never change owner -- not even when the
    executor (here: the postgres superuser) owns it (regression: it
    used to transfer the postgres database to the app role).

    A second scenario targets a DIFFERENTLY-NAMED admin database that
    the executor owns and that is simultaneously the START database of
    the job (the job connects to it) and its TARGET: only the
    start-database guard protects it there, and it must hold. With an
    empty access list nothing is managed, so a foreign application
    object in the target database keeps its owner too, and a fresh
    login of the entry works.
    """
    pg = postgres

    assert _database_owner(pg, "postgres") == "postgres"

    script = _render_provision(
        "postgres",
        "cs_app",
        role="cs_owner",
        access_list="",
        schemas_csv="",
        admin_user="postgres",
    )
    _run_provision(pg, script, admin_user="postgres")

    # the admin database keeps its owner
    assert _database_owner(pg, "postgres") == "postgres"

    # the login itself works
    result = pg.login("cs_app", DB_PASSWORD, "postgres", "SELECT 1;")
    assert result.returncode == 0, result.stderr

    # ── second scenario: a differently-named admin START database that
    # is simultaneously the TARGET and owned by the executor
    db = "admin_ops_db"
    _create_database(pg, db)

    # a foreign application object in the target database: a
    # third-party role owns a schema and a table there (the table is
    # created AS that role, so it is genuinely third-party owned)
    setup = pg.exec_psql(
        "postgres",
        db,
        "CREATE ROLE ops_dba LOGIN; "
        "CREATE SCHEMA ops_schema AUTHORIZATION ops_dba; "
        "SET ROLE ops_dba; "
        "CREATE TABLE ops_schema.app_data (id int); "
        "RESET ROLE;",
    )
    assert setup.returncode == 0, f"foreign object setup failed: {setup.stderr}"

    datdba_before = pg.query(
        "postgres", "postgres", f"SELECT datdba FROM pg_database WHERE datname = '{db}'"
    )
    assert _database_owner(pg, db) == EXECUTOR
    ops_schema_owner_oid = pg.query(
        EXECUTOR,
        db,
        "SELECT nspowner FROM pg_namespace WHERE nspname = 'ops_schema'",
    )
    app_data_owner_oid = pg.query(
        EXECUTOR,
        db,
        "SELECT relowner FROM pg_class WHERE relname = 'app_data'",
    )

    # empty access again, but the job STARTS in the differently-named
    # admin database and targets it
    target_script = _render_provision(
        db, "ops_app", role="ops_owner", access_list="", schemas_csv=""
    )
    result = pg.exec_psql(
        EXECUTOR,
        db,
        target_script,
        extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
    )
    assert result.returncode == 0, f"provision failed: {result.stderr}"
    assert "ERROR" not in result.stderr, result.stderr

    # the start database keeps its owner: the datdba OID is unchanged
    # (the start-database guard, not the postgres-name guard)
    assert _database_owner(pg, db) == EXECUTOR
    assert (
        pg.query(
            "postgres",
            "postgres",
            f"SELECT datdba FROM pg_database WHERE datname = '{db}'",
        )
        == datdba_before
    )

    # no takeover of foreign app objects without configuration: the
    # third-party schema and table keep their owner (OID comparison)
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT nspowner FROM pg_namespace WHERE nspname = 'ops_schema'",
        )
        == ops_schema_owner_oid
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT relowner FROM pg_class WHERE relname = 'app_data'",
        )
        == app_data_owner_oid
    )

    # a fresh login of the entry works (real password authentication)
    result = pg.login("ops_app", DB_PASSWORD, db, "SELECT 1;")
    assert result.returncode == 0, result.stderr


# ─── 7. object transfer with foreign and extension objects ────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_object_zoo_transferred_foreign_and_extension_protected(
    postgres: PostgresContainer,
) -> None:
    """O07 — Application objects migrate; foreign ownership and extension members are protected.

    Every object type of the seeded zoo transfers to the owner role. A
    representative object outside the configured schemas and a REAL
    extension member inside a checked schema (pg_trgm, trusted since
    PG13, its functions live in public) keep their owner.
    """
    pg = postgres
    db = "zoo_db"
    _create_database(pg, db)
    pg.seed(db, EXECUTOR)

    # a representative object OUTSIDE the configured schemas
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE SCHEMA unmanaged; CREATE TABLE unmanaged.other_data (id int);",
    )
    assert result.returncode == 0, result.stderr

    # a real extension member inside the checked schema
    result = pg.exec_psql(EXECUTOR, db, "CREATE EXTENSION pg_trgm;")
    assert result.returncode == 0, result.stderr
    extension_member_owner = pg.query(
        EXECUTOR,
        db,
        "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname='show_trgm'",
    )

    # a LOCAL catalog-capable FOREIGN TABLE representative in the
    # managed schema (no external database access ever happens: the
    # table is never queried). postgres_fdw is NOT a trusted extension
    # on ANY supported version (verified against the upstream control
    # files of PG13-18: no trusted flag), so the non-superuser
    # executor cannot install it -- like on a real managed instance,
    # the extension is installed once by the superuser, which hands
    # the executor USAGE on the foreign data wrapper. The executor
    # then owns the loopback SERVER and the FOREIGN TABLE itself,
    # exactly like the other seeded relations.
    result = pg.exec_psql(
        "postgres",
        db,
        "CREATE EXTENSION postgres_fdw; "
        f"GRANT USAGE ON FOREIGN DATA WRAPPER postgres_fdw TO {EXECUTOR};",
    )
    assert result.returncode == 0, f"postgres_fdw setup failed: {result.stderr}"
    result = pg.exec_psql(
        EXECUTOR,
        db,
        f"CREATE SERVER fdw_loopback FOREIGN DATA WRAPPER postgres_fdw "
        f"OPTIONS (dbname '{db}'); "
        "CREATE FOREIGN TABLE public.fdw_orders (id int, data text) "
        "SERVER fdw_loopback;",
    )
    assert result.returncode == 0, f"foreign table setup failed: {result.stderr}"
    fdw_extension_member_owner = pg.query(
        EXECUTOR,
        db,
        "SELECT pg_get_userbyid(proowner) FROM pg_proc "
        "WHERE proname='postgres_fdw_validator'",
    )

    script = _render_provision(db, "cs_app", role="cs_owner", access_list="public|ALL")
    _run_provision(pg, script)

    # every table (regular, partitioned, partitions, unlogged)
    for table in (
        "orders",
        "order_items",
        "events",
        "events_2026_01",
        "events_2026_02",
        "audit_log",
    ):
        _assert_owner(
            pg,
            db,
            f"table {table}",
            f"SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='{table}'",
            "cs_owner",
        )

    # views and matviews
    for view in ("v_open_orders", "mv_order_totals"):
        _assert_owner(
            pg,
            db,
            f"view {view}",
            f"SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='{view}'",
            "cs_owner",
        )

    # the foreign table transfers like the other relations (it is
    # never queried -- no external database access)
    _assert_owner(
        pg,
        db,
        "foreign table fdw_orders",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='fdw_orders'",
        "cs_owner",
    )

    # sequences
    _assert_owner(
        pg,
        db,
        "sequence custom_seq",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='custom_seq'",
        "cs_owner",
    )

    # statistics
    _assert_owner(
        pg,
        db,
        "statistics",
        "SELECT pg_get_userbyid(stxowner) FROM pg_statistic_ext "
        "WHERE stxname='stat_orders_cust_status'",
        "cs_owner",
    )

    # functions, procedures, aggregates
    for func in (
        "get_order_total",
        "top_customers",
        "next_custom_seq",
        "max_qty",
        "reset_pending",
        "audit_insert",
    ):
        _assert_owner(
            pg,
            db,
            f"function {func}",
            f"SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname='{func}'",
            "cs_owner",
        )

    # types (enum, composite, domain, range)
    for typ in ("order_status", "address", "positive_int", "order_range"):
        _assert_owner(
            pg,
            db,
            f"type {typ}",
            f"SELECT pg_get_userbyid(typowner) FROM pg_type WHERE typname='{typ}'",
            "cs_owner",
        )

    # schema: on PG15+ public is owned by pg_database_owner (i.e. the
    # database owner, transferred to cs_owner). On PG13/14 public is
    # owned by the bootstrap superuser and is NOT transferred.
    if int(pg.version) >= 15:
        _assert_owner(
            pg,
            db,
            "schema public",
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='public'",
            "cs_owner",
        )

    # the extension member inside the checked schema is NOT transferred
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname='show_trgm'",
        )
        == extension_member_owner
    )

    # the postgres_fdw extension members in the checked schema keep
    # their owner too (a second real extension, installed by the
    # superuser)
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT pg_get_userbyid(proowner) FROM pg_proc "
            "WHERE proname='postgres_fdw_validator'",
        )
        == fdw_extension_member_owner
    )

    # the object outside the configured schemas keeps its owner
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='other_data'",
        )
        == EXECUTOR
    )

    # memberships and role default
    assert (
        pg.query(EXECUTOR, db, "SELECT pg_has_role('cs_app', 'cs_owner', 'MEMBER')")
        == "t"
    )
    assert "cs_owner" in pg.query(
        EXECUTOR,
        db,
        "SELECT cfg FROM pg_db_role_setting s JOIN pg_roles r ON r.oid=s.setrole, "
        "LATERAL unnest(setconfig) cfg WHERE r.rolname='cs_app'",
    )


# ─── 8. two apps share one database in separate schemas ───────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_two_apps_share_database_separate_schemas(
    postgres: PostgresContainer,
) -> None:
    """O08 — Two applications share one database in separate schemas.

    Both apps are provisioned first; their fresh connections (password
    auth) are only opened afterwards. Each reads its own data (the
    per-login search path resolves the unqualified table) and cannot
    read the other's schema; both keep CONNECT.
    """
    pg = postgres
    db = "shared_db"
    _create_database(pg, db)
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE SCHEMA tenant_a; CREATE SCHEMA tenant_b; "
        "CREATE TABLE tenant_a.data (id int, secret text); "
        "CREATE TABLE tenant_b.data (id int, secret text); "
        "INSERT INTO tenant_a.data VALUES (1, 'tenant_a_secret'); "
        "INSERT INTO tenant_b.data VALUES (1, 'tenant_b_secret');",
    )
    assert result.returncode == 0, result.stderr

    a = _render_provision(
        db,
        "user_a",
        role="role_a",
        access_list="tenant_a|SELECT",
        schemas_csv="tenant_a",
    )
    _run_provision(pg, a, password="SharedPwA")

    b = _render_provision(
        db,
        "user_b",
        role="role_b",
        access_list="tenant_b|SELECT",
        schemas_csv="tenant_b",
    )
    _run_provision(pg, b, password="SharedPwB")

    # both apps connect with their passwords after the second provisioning
    result = pg.login("user_a", "SharedPwA", db, "SELECT 1;")
    assert result.returncode == 0, result.stderr
    result = pg.login("user_b", "SharedPwB", db, "SELECT 1;")
    assert result.returncode == 0, result.stderr

    # each reads its own data (unqualified, per-login search path)
    result = pg.login("user_a", "SharedPwA", db, "SELECT secret FROM data;")
    assert result.returncode == 0, result.stderr
    assert "tenant_a_secret" in result.stdout
    result = pg.login("user_b", "SharedPwB", db, "SELECT secret FROM data;")
    assert result.returncode == 0, result.stderr
    assert "tenant_b_secret" in result.stdout

    # neither can read the other's schema
    result = pg.login("user_a", "SharedPwA", db, "SELECT secret FROM tenant_b.data;")
    assert result.returncode != 0, "user_a must not access tenant_b"
    assert "permission denied for schema tenant_b" in result.stderr
    result = pg.login("user_b", "SharedPwB", db, "SELECT secret FROM tenant_a.data;")
    assert result.returncode != 0, "user_b must not access tenant_a"
    assert "permission denied for schema tenant_a" in result.stderr


# ─── 9. explicit foreign read access, granted then revoked ────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_foreign_read_access_granted_then_revoked(
    postgres: PostgresContainer,
) -> None:
    """O09 — Explicit foreign read access, granted and then revoked.

    The owner role gets read-only access to a schema owned by a
    third-party role: the reader can read but not write and not create
    objects, the foreign ownership is preserved and the default
    privileges are limited to the configured SELECT. After the revoke
    the access is gone.
    """
    pg = postgres
    db = "foreign_access_db"
    _create_database(pg, db)
    pg.seed(db, EXECUTOR)
    _create_foreign_schema(
        pg, db, schema="ext_data", owner="third_party", table="shared_data"
    )

    with_access = _render_provision(
        db,
        "cs_app",
        role="cs_owner",
        access_list="public|ALL;ext_data|SELECT",
        schemas_csv="public,ext_data",
    )
    _run_provision(pg, with_access)

    # the owner role has USAGE and SELECT, but no CREATE, on the foreign schema
    assert (
        pg.query(
            EXECUTOR, db, "SELECT has_schema_privilege('cs_owner', 'ext_data', 'USAGE')"
        )
        == "t"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_table_privilege('cs_owner', 'ext_data.shared_data', 'SELECT')",
        )
        == "t"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_schema_privilege('cs_owner', 'ext_data', 'CREATE')",
        )
        == "f"
    )

    # the foreign schema keeps its owner
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
            "WHERE nspname='ext_data'",
        )
        == "third_party"
    )

    # the reader can read cross-schema on a fresh password connection
    result = pg.login(
        "cs_app", DB_PASSWORD, db, "SELECT data FROM ext_data.shared_data WHERE id=1;"
    )
    assert result.returncode == 0, result.stderr
    assert "hello" in result.stdout

    # ... cannot write ...
    result = pg.login(
        "cs_app",
        DB_PASSWORD,
        db,
        "INSERT INTO ext_data.shared_data VALUES (2, 'nope');",
    )
    assert result.returncode != 0, "the reader must not write to the foreign schema"
    assert "permission denied for table shared_data" in result.stderr

    # ... and cannot create objects there
    result = pg.login("cs_app", DB_PASSWORD, db, "CREATE TABLE ext_data.evil (id int);")
    assert result.returncode != 0, (
        "the reader must not create objects in the foreign schema"
    )
    assert "permission denied for schema ext_data" in result.stderr

    # default privileges in the foreign schema are limited to the
    # configured read access: future executor-created tables grant
    # SELECT, not INSERT -- and keep their owner
    result = pg.exec_psql(EXECUTOR, db, "CREATE TABLE ext_data.future_data (id int);")
    assert result.returncode == 0, result.stderr
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_table_privilege('cs_owner', 'ext_data.future_data', 'SELECT')",
        )
        == "t"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_table_privilege('cs_owner', 'ext_data.future_data', 'INSERT')",
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT pg_get_userbyid(relowner) FROM pg_class "
            "WHERE relname='future_data'",
        )
        == EXECUTOR
    )

    # revoke: the foreign schema leaves the access list
    without_access = _render_provision(
        db,
        "cs_app",
        role="cs_owner",
        access_list="public|ALL",
        schemas_csv="public",
        revoke_list="ext_data|SELECT",
    )
    _run_provision(pg, without_access)

    # the access is gone
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_table_privilege('cs_owner', 'ext_data.shared_data', 'SELECT')",
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR, db, "SELECT has_schema_privilege('cs_owner', 'ext_data', 'USAGE')"
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_schema_privilege('cs_owner', 'ext_data', 'CREATE')",
        )
        == "f"
    )

    # the default privileges are gone too: new executor tables grant nothing
    result = pg.exec_psql(EXECUTOR, db, "CREATE TABLE ext_data.after_revoke (id int);")
    assert result.returncode == 0, result.stderr
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_table_privilege('cs_owner', 'ext_data.after_revoke', 'SELECT')",
        )
        == "f"
    )

    # the foreign schema still keeps its owner
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
            "WHERE nspname='ext_data'",
        )
        == "third_party"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_transient_grants_removed_with_schema(
    postgres: PostgresContainer,
) -> None:
    """O09 — When a foreign schema leaves the access list, no transient grants persist.

    The transient CREATE grant and the default privileges must not
    outlive the schema's membership in the access list.
    """
    pg = postgres
    db = "transient_db"
    _create_database(pg, db)
    _create_foreign_schema(
        pg, db, schema="removable_schema", owner="third_owner", table="data"
    )

    # the schema that stays in the access list after the removal
    result = pg.exec_psql(EXECUTOR, db, "CREATE SCHEMA other_schema;")
    assert result.returncode == 0, result.stderr

    # provision with the foreign schema in the access list
    with_schema = _render_provision(
        db,
        "ro_user",
        role="cs_ro",
        access_list="removable_schema|SELECT",
        schemas_csv="removable_schema",
    )
    _run_provision(pg, with_schema, password="RoPassword1")

    # re-provision with the schema removed from the access list
    without_schema = _render_provision(
        db,
        "ro_user",
        role="cs_ro",
        access_list="other_schema|SELECT",
        schemas_csv="other_schema",
        revoke_list="removable_schema|SELECT",
    )
    _run_provision(pg, without_schema, password="RoPassword1")

    # the owner role lost table access, USAGE and CREATE
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_table_privilege('cs_ro', 'removable_schema.data', 'SELECT')",
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_schema_privilege('cs_ro', 'removable_schema', 'USAGE')",
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_schema_privilege('cs_ro', 'removable_schema', 'CREATE')",
        )
        == "f"
    )
    # the default privileges are gone: new executor tables grant
    # nothing to the owner role
    result = pg.exec_psql(
        EXECUTOR, db, "CREATE TABLE removable_schema.new_data (id int);"
    )
    assert result.returncode == 0, result.stderr
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_table_privilege('cs_ro', 'removable_schema.new_data', 'SELECT')",
        )
        == "f"
    )


# ─── 9b. partial-grant negatives: runtime counter-probes ──────────────────


def _assert_role_rolled_back(pg: PostgresContainer, *roles: str) -> None:
    """A failed provision must leave none of the created roles behind.

    Roles are cluster-wide: the catalog check runs from the admin
    database against the instance-wide pg_roles.
    """
    for role in roles:
        assert (
            pg.query(
                EXECUTOR,
                "postgres",
                f"SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = '{role}')",
            )
            == "f"
        ), f"the failed provision left the partially created role {role} behind"


def _run_provision_expecting_failure(
    pg: PostgresContainer, script: str, *, password: str
) -> CompletedProcess[str]:
    """Execute a provision script that must fail before the commit."""
    result = pg.exec_psql(
        EXECUTOR,
        "postgres",
        script,
        extra_args=["-v", f"db_user_password={password}"],
    )
    assert result.returncode != 0, "the partial-grant provision unexpectedly succeeded"
    return result


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_provision_fails_when_executor_can_grant_only_part_of_the_table_privileges(
    postgres: PostgresContainer,
) -> None:
    """O13 — A partially deliverable table grant fails the job before the commit.

    The executor can pass on only PART of the requested table
    privileges: it holds the grant option for USAGE on the foreign
    schema and for SELECT on its table, but not for INSERT.
    PostgreSQL only issues a WARNING for the INSERT part of the
    ``GRANT SELECT, INSERT`` ("not all privileges were granted") and
    grants the SELECT -- which must NOT suffice: the job fails inside
    the transaction with the specific missing TABLE privilege (INSERT),
    distinguishable from the schema-CREATE and DB-CONNECT errors, and
    the rolled-back run leaves neither the login nor the owner role
    behind. This is the runtime counter-probe for the per-privilege
    verification of the 5h grant loop (each privilege is checked
    individually via has_table_privilege -- an "at least one
    privilege" check would let the job succeed here).
    """
    pg = postgres
    db = "partial_grant_db"
    _create_database(pg, db)

    # a foreign schema whose owner passes the executor USAGE with
    # grant option, but only the SELECT grant option on the table
    setup = pg.exec_psql(
        "postgres",
        db,
        "CREATE ROLE partial_owner LOGIN; "
        "CREATE SCHEMA partial_schema AUTHORIZATION partial_owner; "
        "CREATE TABLE partial_schema.shared (id int); "
        f"GRANT USAGE ON SCHEMA partial_schema TO {EXECUTOR} WITH GRANT OPTION; "
        f"GRANT SELECT ON partial_schema.shared TO {EXECUTOR} WITH GRANT OPTION;",
    )
    assert setup.returncode == 0, f"partial-grant setup failed: {setup.stderr}"

    # the entry requests SELECT,INSERT -- the executor can deliver
    # only the SELECT half
    script = _render_provision(
        db,
        "cs_part",
        role="cs_part_owner",
        access_list="partial_schema|SELECT,INSERT",
        schemas_csv="partial_schema",
    )
    result = _run_provision_expecting_failure(pg, script, password="PartialPw1")

    # the failure is EXACTLY the missing TABLE privilege, not a
    # PostgreSQL warning slipping through, not the schema-CREATE error
    # and not the DB-CONNECT error
    assert (
        "owner role cs_part_owner lacks INSERT on partial_schema.shared"
        in result.stderr
    ), result.stderr
    assert "lacks CREATE on schema" not in result.stderr, result.stderr
    assert "has no CONNECT on database" not in result.stderr, result.stderr

    # the transaction rolled back: no partially created roles remain
    _assert_role_rolled_back(pg, "cs_part", "cs_part_owner")


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_provision_fails_when_executor_cannot_grant_schema_usage(
    postgres: PostgresContainer,
) -> None:
    """O13 — An undeliverable schema USAGE fails the job before the commit.

    The executor CAN grant the requested table privileges (it holds
    both grant options) but NOT the schema USAGE: it has USAGE on the
    foreign schema without grant option, and PUBLIC holds nothing
    there. The ``GRANT USAGE`` only produces a warning and grants
    nothing, so the job must fail with the specific schema-USAGE error
    -- distinguishable from the missing TABLE privilege, the
    schema-CREATE error and the DB-CONNECT error -- and the
    rolled-back run leaves no partially created roles behind.
    """
    pg = postgres
    db = "no_usage_grant_db"
    _create_database(pg, db)

    # a foreign schema the executor may USE but not grant USAGE on;
    # the table privileges it may pass on in full. A probe role with
    # no grants of its own proves PUBLIC holds nothing there either.
    setup = pg.exec_psql(
        "postgres",
        db,
        "CREATE ROLE no_usage_owner LOGIN; "
        "CREATE ROLE usage_probe NOLOGIN; "
        "CREATE SCHEMA no_usage_schema AUTHORIZATION no_usage_owner; "
        "CREATE TABLE no_usage_schema.shared (id int); "
        f"GRANT USAGE ON SCHEMA no_usage_schema TO {EXECUTOR}; "
        "REVOKE ALL ON SCHEMA no_usage_schema FROM public; "
        f"GRANT SELECT, INSERT ON no_usage_schema.shared "
        f"TO {EXECUTOR} WITH GRANT OPTION;",
    )
    assert setup.returncode == 0, f"no-usage setup failed: {setup.stderr}"

    # the owner role does not get USAGE via PUBLIC either: a role with
    # no grants of its own has none on the schema
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_schema_privilege('usage_probe', 'no_usage_schema', 'USAGE')",
        )
        == "f"
    )

    script = _render_provision(
        db,
        "cs_usage",
        role="cs_usage_owner",
        access_list="no_usage_schema|SELECT,INSERT",
        schemas_csv="no_usage_schema",
    )
    result = _run_provision_expecting_failure(pg, script, password="NoUsagePw1")

    # the failure is EXACTLY the missing schema USAGE -- the table
    # privileges were deliverable, so a check that only verified them
    # would have let the job commit
    assert (
        "owner role cs_usage_owner has no USAGE on schema no_usage_schema"
        in result.stderr
    ), result.stderr
    assert "lacks INSERT on" not in result.stderr, result.stderr
    assert "lacks CREATE on schema" not in result.stderr, result.stderr
    assert "has no CONNECT on database" not in result.stderr, result.stderr

    # the transaction rolled back: no partially created roles remain
    _assert_role_rolled_back(pg, "cs_usage", "cs_usage_owner")


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16", "17", "18"], indirect=True)
def test_all_claim_checks_the_version_privilege_bundle(
    postgres: PostgresContainer,
) -> None:
    """O13 — An ALL claim verifies the version-appropriate full privilege bundle.

    The executor holds the grant option for every table privilege of
    its PostgreSQL version on the foreign table (and for USAGE and
    CREATE on the schema), so a ``GRANT ALL`` can deliver the complete
    bundle. On PG16 that is the 7-privilege bundle and the job
    SUCCEEDS -- proving the verification never demands MAINTAIN (or
    any other privilege) the version does not have. On PG17+ the
    MAINTAIN privilege exists but the executor cannot pass it on: the
    job must fail with the specific missing MAINTAIN privilege,
    proving the ALL expansion of the verification includes MAINTAIN
    from PG17 on.
    """
    pg = postgres
    db = "all_bundle_db"
    _create_database(pg, db)

    # every table privilege that exists on all tested versions, with
    # grant option -- MAINTAIN deliberately absent (it only exists
    # from PG17 on anyway)
    setup = pg.exec_psql(
        "postgres",
        db,
        "CREATE ROLE bundle_owner LOGIN; "
        "CREATE SCHEMA bundle_schema AUTHORIZATION bundle_owner; "
        "CREATE TABLE bundle_schema.bundle_data (id int); "
        f"GRANT USAGE, CREATE ON SCHEMA bundle_schema TO {EXECUTOR} "
        "WITH GRANT OPTION; "
        f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
        f"ON bundle_schema.bundle_data TO {EXECUTOR} WITH GRANT OPTION;",
    )
    assert setup.returncode == 0, f"bundle setup failed: {setup.stderr}"

    script = _render_provision(
        db,
        "cs_bundle",
        role="cs_bundle_owner",
        access_list="bundle_schema|ALL",
        schemas_csv="bundle_schema",
    )
    result = pg.exec_psql(
        EXECUTOR,
        "postgres",
        script,
        extra_args=["-v", "db_user_password=BundlePw1"],
    )

    if int(pg.version) >= 17:
        # MAINTAIN exists on this version and the executor cannot
        # deliver it: the job fails with the specific privilege
        assert result.returncode != 0, (
            "provision succeeded although the owner role lacks MAINTAIN "
            "and the executor cannot grant it"
        )
        assert (
            "owner role cs_bundle_owner lacks MAINTAIN "
            "on bundle_schema.bundle_data" in result.stderr
        ), result.stderr
        _assert_role_rolled_back(pg, "cs_bundle", "cs_bundle_owner")
        return

    # on PG16 the executor can deliver the complete version bundle:
    # the job succeeds and the owner role ends up with EVERY privilege
    # of the bundle (individually, not as an "at least one" check)
    assert result.returncode == 0, f"provision failed: {result.stderr}"
    assert "ERROR" not in result.stderr, result.stderr
    for privilege in (
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "REFERENCES",
        "TRIGGER",
    ):
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_table_privilege('cs_bundle_owner', "
                f"'bundle_schema.bundle_data', '{privilege}')",
            )
            == "t"
        ), f"the owner role lacks {privilege} after the ALL grant"

    # and the delivered access is real for the application login
    result = pg.login(
        "cs_bundle",
        "BundlePw1",
        db,
        "SELECT count(*) FROM bundle_schema.bundle_data;",
    )
    assert result.returncode == 0, result.stderr


# ─── 11. re-provision, stale schema, deprovision, missing login ───────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_reprovision_and_deprovision_convergence(
    postgres: PostgresContainer,
) -> None:
    """O11 — Re-provision, stale schema, deprovision and missing login converge.

    After a repeat run, data, owners AND privileges are still correct
    (not just the exit code) and the credentials still work; the
    deprovision keeps the owner role and the data; repeating the
    removal of an already-removed login succeeds; deprovisioning a
    login that never existed is a successful no-op.
    """
    pg = postgres
    db = "converge_db"
    _create_database(pg, db)
    pg.seed(db, EXECUTOR)

    # the revoke list references a schema that does not exist (stale
    # pending configuration): the run must skip it, not fail
    script = _render_provision(
        db,
        "cs_app",
        role="cs_owner",
        access_list="public|ALL",
        revoke_list="nonexistent_schema|ALL",
    )
    _run_provision(pg, script)

    # the repeat run is a no-op
    result = _run_provision(pg, script)
    assert "ERROR" not in result.stderr

    # data, owners and privileges are still correct after the repeat run
    assert pg.query(EXECUTOR, db, "SELECT count(*) FROM public.orders") == "3"
    _assert_owner(
        pg,
        db,
        "table orders",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='orders'",
        "cs_owner",
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_table_privilege('cs_owner', 'public.orders', 'SELECT')",
        )
        == "t"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_table_privilege('cs_owner', 'public.orders', 'INSERT')",
        )
        == "t"
    )
    assert (
        pg.query(
            EXECUTOR, db, "SELECT has_schema_privilege('cs_owner', 'public', 'USAGE')"
        )
        == "t"
    )

    # the credentials still work (real password authentication)
    result = pg.login("cs_app", DB_PASSWORD, db, "SELECT count(*) FROM public.orders;")
    assert result.returncode == 0, result.stderr
    assert "3" in result.stdout

    # deprovision: the login goes, the owner role and the data stay
    drop = _render_deprovision(db, "cs_app", role=True)
    result = pg.exec_psql(EXECUTOR, "postgres", drop)
    assert result.returncode == 0, f"deprovision failed: {result.stderr}"
    assert (
        pg.query(
            EXECUTOR, db, "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cs_app')"
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cs_owner')",
        )
        == "t"
    )
    assert pg.query(EXECUTOR, db, "SELECT count(*) FROM public.orders") == "3"
    _assert_owner(
        pg,
        db,
        "table orders after deprovision",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='orders'",
        "cs_owner",
    )

    # repeating the removal of the already-removed login succeeds
    result = pg.exec_psql(EXECUTOR, "postgres", drop)
    assert result.returncode == 0, f"repeat deprovision failed: {result.stderr}"
    assert "nothing to deprovision" in result.stdout

    # deprovisioning a login that never existed is a successful no-op
    ghost = _render_deprovision(db, "ghost_user", role=True)
    result = pg.exec_psql(EXECUTOR, "postgres", ghost)
    assert result.returncode == 0, f"ghost deprovision failed: {result.stderr}"
    assert "nothing to deprovision" in result.stdout


# ─── 12. provisioning under a concurrently held lock ───────────────────────


_LOCK_HOLDER_SQL = (
    "SELECT l.pid FROM pg_locks l "
    "WHERE l.relation = 'public.orders'::regclass "
    "AND l.mode = 'AccessExclusiveLock' AND l.granted"
)
_LOCK_WAITER_SQL = (
    "SELECT count(*) FROM pg_locks l "
    "WHERE l.relation = 'public.orders'::regclass "
    "AND l.mode = 'AccessExclusiveLock' AND NOT l.granted"
)


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_concurrent_provision_waits_for_lock(postgres: PostgresContainer) -> None:
    """O12 — Concurrent provisioning waits for a held lock instead of failing silently.

    Session A (the executor, simulating the old app) holds an ACCESS
    EXCLUSIVE lock on a managed table. Session B (the provision
    script) must demonstrably WAIT (verified via pg_locks from a third
    connection), then complete correctly once the lock is released.
    """
    pg = postgres
    db = "lock_contention_db"
    _create_database(pg, db)
    pg.seed(db, EXECUTOR)

    script = _render_provision(db, "cs_app", role="cs_owner", access_list="public|ALL")

    # session A: the old app holds the lock in an open transaction.
    # The trailing newline matters: psql only executes a statement
    # once its line is complete, and stdin stays open for the whole
    # session
    session_a: subprocess.Popen[str] = pg.start_session(
        EXECUTOR,
        db,
        "BEGIN; LOCK TABLE public.orders IN ACCESS EXCLUSIVE MODE; "
        "SELECT pg_sleep(60);\n",
    )

    # wait (bounded) until session A actually holds the lock
    holder_pid = ""
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if pid := pg.query("postgres", db, _LOCK_HOLDER_SQL):
            holder_pid = pid
            break
        time.sleep(0.5)
    if not holder_pid:
        session_a.kill()
        pytest.fail("session A never acquired the lock on public.orders")

    # session B: DAM provisions concurrently
    session_b: subprocess.Popen[str] = pg.start_session(
        EXECUTOR,
        "postgres",
        script,
        extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
    )

    # B demonstrably waits: its ungranted lock request is visible from
    # a third connection, and B is still running (no silent failure)
    _wait_until(
        pg,
        db,
        _LOCK_WAITER_SQL,
        "1",
        what="the provision to wait for the lock on public.orders",
    )
    assert session_b.poll() is None, "the provision failed while waiting for the lock"

    # release A: terminate exactly the blocking backend (a blanket
    # terminate_sessions(EXECUTOR) would also kill the provisioning
    # session, which runs as the executor too)
    result = pg.exec_psql("postgres", db, f"SELECT pg_terminate_backend({holder_pid});")
    assert result.returncode == 0, result.stderr

    # session A exits with its terminated backend
    try:
        session_a.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        session_a.kill()
        pytest.fail("session A did not exit after its backend was terminated")

    # B finishes (bounded) and succeeds: no silent failure
    try:
        _stdout, stderr = session_b.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        session_b.kill()
        pytest.fail("the provision did not finish after the lock was released")
    assert session_b.returncode == 0, f"provision failed: {stderr}"
    assert "ERROR" not in stderr, stderr

    # data and owners converged afterwards
    assert pg.query(EXECUTOR, db, "SELECT count(*) FROM public.orders") == "3"
    _assert_owner(
        pg,
        db,
        "table orders",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='orders'",
        "cs_owner",
    )


# ─── 13. CONNECT without PUBLIC ───────────────────────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_connect_granted_when_public_lacks_it(postgres: PostgresContainer) -> None:
    """O10 — The login gets and uses CONNECT when PUBLIC lacks it.

    Restricted instances revoke CONNECT from PUBLIC; the provision
    script must grant CONNECT to the login, and the login must
    actually log in with its password.
    """
    pg = postgres
    db = "no_public_connect_db"
    _create_database(pg, db)
    result = pg.exec_psql(
        EXECUTOR, "postgres", f"REVOKE CONNECT ON DATABASE {db} FROM public;"
    )
    assert result.returncode == 0, result.stderr

    script = _render_provision(
        db, "conn_user", role="cs_conn", access_list="public|SELECT"
    )
    _run_provision(pg, script, password="ConnPassword1")

    # the login got CONNECT despite PUBLIC lacking it
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_database_privilege('conn_user', "
            "'no_public_connect_db', 'CONNECT')",
        )
        == "t"
    )

    # the app login actually logs in with its password
    result = pg.login("conn_user", "ConnPassword1", db, "SELECT 1;")
    assert result.returncode == 0, result.stderr


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_provision_fails_when_executor_cannot_grant_connect(
    postgres: PostgresContainer,
) -> None:
    """O10 — Provisioning fails with the specific CONNECT error when it cannot grant.

    The executor can PROVABLY connect to the database (a direct
    CONNECT grant without grant option) but is unable to grant CONNECT
    to the app login. The script must fail with the specific CONNECT
    verification error naming the login and the database -- not with
    an arbitrary failure.

    Note on the exact message: PostgreSQL only issues a WARNING when a
    non-owner grants CONNECT on a database ("no privileges were
    granted"), so the GRANT itself never raises insufficient_privilege
    here and the check fails through its post-grant verification arm:
    "login ... has no CONNECT on database ... after explicit grant".
    Both arms are the same section-3 CONNECT verification.
    """
    pg = postgres
    db = "no_connect_db"

    # the database is owned by a guard role the executor is not a
    # member of; PUBLIC loses CONNECT; the executor keeps a direct
    # CONNECT grant WITHOUT grant option
    setup = pg.exec_psql(
        "postgres",
        "postgres",
        f"CREATE DATABASE {db}; "
        f"REVOKE CONNECT ON DATABASE {db} FROM public; "
        "CREATE ROLE db_guard NOLOGIN; "
        "GRANT db_guard TO test_admin WITH SET TRUE; "
        f"ALTER DATABASE {db} OWNER TO db_guard; "
        "REVOKE db_guard FROM test_admin; "
        f"GRANT CONNECT ON DATABASE {db} TO test_admin;",
    )
    assert setup.returncode == 0, f"setup failed: {setup.stderr}"

    # the executor can provably connect to the database
    result = pg.exec_psql(EXECUTOR, db, "SELECT 1;")
    assert result.returncode == 0, f"executor lost CONNECT: {result.stderr}"

    script = _render_provision(
        db, "no_conn_user", role="cs_noconn", access_list="public|SELECT"
    )
    result = pg.exec_psql(
        EXECUTOR,
        "postgres",
        script,
        extra_args=["-v", "db_user_password=NoConnPassword1"],
    )

    # the script fails with EXACTLY the specific CONNECT verification
    # error, not just any failure
    assert result.returncode != 0, (
        "provision succeeded although the login has no CONNECT and the "
        "executor cannot grant it"
    )
    assert (
        "login no_conn_user has no CONNECT on database no_connect_db "
        "after explicit grant" in result.stderr
    ), result.stderr


# ─── 14. the tenant uses the credential DAM issued ────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_generated_login_credential_end_to_end(
    postgres: PostgresContainer,
    dam_harness_factory: Callable[..., DamJobHarness],
) -> None:
    """J01 — the tenant uses the credential DAM issued, with a GENERATED login.

    The entry has no username: DAM resolves the login name from the
    owner role and the state key, and one harness run already
    executes the job when DAM polls its status and settles it. The
    tenant then logs in with EXACTLY the published app record -- user,
    db.name and password: the login goes through the published
    db.name, not a separately computed database, and the password
    authentication is real (the mounted pg_hba.conf enforces scram
    for non-fixture roles). Separately from the login, the published
    record's HOST and PORT are compared against the expected harness
    admin-connection endpoint: they must be the transport coordinates
    the job actually used. A later job error (an access entry on a
    nonexistent schema) publishes no new secret: the failed job's
    transaction rolls its password change back, so the published
    credential keeps working.

    Fake-infrastructure boundary: the Kubernetes job controller, the
    OpenShift client (admin secret and job-bound secrets), the
    integration state and vault are local test doubles; the
    PostgreSQL instance, the rendered SQL, the decision logic in
    _process_db_access, the generated passwords and the password
    logins are real.
    """
    pg = postgres
    harness = dam_harness_factory(pg)
    db = "generated_login_db"

    db_access = make_db_access(
        database=db,
        role="cs_owner",
        access=[("public", ("ALL",))],
    )
    harness.run(db_access)

    # the job ran for real: DAM created the database and it belongs
    # to the owner role
    assert _database_owner(pg, db) == "cs_owner"

    # the login follows DAM's deterministic generated-username scheme
    login = _generated_username("cs_owner", E2E_STATE_KEY)
    job = harness.enqueued_jobs[-1]
    assert job.user_connection.user == login
    assert job.user_connection.database == db
    assert login.startswith("cs_owner_")
    assert (
        pg.query(
            EXECUTOR,
            "postgres",
            f"SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{login}')",
        )
        == "t"
    )

    # the settlement published exactly the credential the job used ...
    credential = harness.last_published_credential()
    assert credential.user == login
    assert credential.password == job.user_connection.password
    assert credential.database == db
    # ... and the tenant logs in with EXACTLY that published record:
    # user, password and db.name (not a separately computed database)
    result = pg.login(credential.user, credential.password, credential.database)
    assert result.returncode == 0, result.stderr

    # SEPARATE from the login itself: the published record's transport
    # coordinates are the ones the job actually used. The published
    # credential's and the job's user connection's host and port equal
    # the harness admin-connection endpoint -- the admin secret's
    # db.host/db.port (localhost/5432) the job connected through
    assert credential.host == "localhost"
    assert credential.port == "5432"
    assert job.user_connection.host == "localhost"
    assert job.user_connection.port == "5432"

    # a job error publishes no new app secret: a grant on a
    # nonexistent schema fails the replacement job inside its
    # transaction
    broken = make_db_access(
        database=db,
        role="cs_owner",
        access=[("public", ("ALL",)), ("missing_schema", ("SELECT",))],
    )
    with pytest.raises(JobFailedError):
        harness.run(broken)
    assert len(harness.vault_writes) == 1

    # the failed job rolled back: the published credential still works
    result = pg.login(credential.user, credential.password, credential.database)
    assert result.returncode == 0, (
        "the published credential stopped working after the failed job"
    )


# ─── 11 (job path). convergence re-enqueue adopts late tables ────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_convergence_reenqueue_adopts_late_tables(
    postgres: PostgresContainer,
    dam_harness_factory: Callable[..., DamJobHarness],
) -> None:
    """M02, J02 — Objects the old app created after the migration are adopted by
    the next DAM run without rotating the credential.

    The executor is the postgres superuser, so the old app (the
    postgres login) keeps writing during the migration window, like
    in the migration off the postgres login. After the first
    provisioning settles, the next run settles again and re-enqueues
    the convergence job REUSING the settled credential (no rotation)
    and without the full revoke a stale job would get -- the
    state-transition regression of the unit suite, here against real
    PostgreSQL. The convergence job adopts the late-created table
    into the owner role and the data survives.
    """
    pg = postgres
    harness = dam_harness_factory(pg, admin_user="postgres")
    db = "postgres"
    pg.seed(db, "postgres")

    db_access = make_db_access(
        database=db,
        role="cs_owner",
        access=[("public", ("SELECT", "INSERT"))],
    )
    harness.run(db_access)

    # the provisioning ran for real: the seeded tables moved to the
    # owner role and the credential was published
    _assert_owner(
        pg,
        db,
        "seeded table",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='orders'",
        "cs_owner",
    )
    credential = harness.last_published_credential()

    # the old app (the postgres login) creates a table AFTER the
    # provisioning, inside the migration window
    result = pg.exec_psql(
        "postgres",
        db,
        "CREATE TABLE public.late_table (id int); "
        "INSERT INTO public.late_table VALUES (42);",
    )
    assert result.returncode == 0, result.stderr

    # the next DAM run settles and re-enqueues the convergence job
    harness.run(db_access)
    assert len(harness.enqueued_jobs) == 2
    convergence_job = harness.enqueued_jobs[-1]
    # the settled credential is reused: the password never rotates
    assert convergence_job.user_connection.password == credential.password
    assert len({c.password for c in harness.published_credentials()}) == 1
    # a settled job that ran the current configuration is not stale:
    # the convergence script carries the configured grants ...
    assert "public|SELECT,INSERT" in convergence_job.script
    # ... but no full revoke of the managed schema
    assert "public|ALL" not in convergence_job.script

    # the convergence job executed against the container and succeeded
    job_result = harness.last_job_result
    assert job_result is not None, "the convergence job did not run"
    assert job_result.returncode == 0, job_result.stderr

    # the late table was adopted by the owner role, data intact
    _assert_owner(
        pg,
        db,
        "late-created table",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='late_table'",
        "cs_owner",
    )
    assert pg.query("postgres", db, "SELECT count(*) FROM public.late_table") == "1"

    # the login still works with the SAME published password, and the
    # admin database keeps its owner
    result = pg.login(
        credential.user,
        credential.password,
        db,
        "SELECT count(*) FROM public.late_table;",
    )
    assert result.returncode == 0, result.stderr
    assert "1" in result.stdout
    assert _database_owner(pg, db) == "postgres"


# ─── 15 (job path). two rotation entries share one fresh role ─────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_two_rotation_entries_share_fresh_role(
    postgres: PostgresContainer,
    dam_harness_factory: Callable[..., DamJobHarness],
) -> None:
    """M07, J02 — Two NEW rotation entries share one not-yet-existing role.

    Both entries have no username (generated logins), no legacy
    history and the same database; they list exactly the same access
    (the production _validate_role_sharing requirement for sharing a
    role) and differ only in the entry name -- which is part of the
    state key, so each entry resolves its own generated login. Both
    logins work, exactly ONE shared owner role exists, and no
    credentials are swapped: each published credential authenticates
    its own user and fails for the other's password. Rotation adds a
    NEW LOGIN -- both credentials are usable in parallel, and neither
    published login loses its password because of the other entry.

    The proven boundary is the JOB-STATE overlap, not SQL-transaction
    concurrency: the harness holds A's converging job IN_PROGRESS in
    the simulated job controller (enqueued but not yet executed)
    while entry B is reconciled and B's job executes for real,
    creating the shared role -- the race the duplicate-object
    tolerance in the SQL exists for. B's credential publishes while
    A's job is observably still in progress; A's job then completes
    against the role B already created, and both credentials work
    with exactly one shared role. The two PostgreSQL transactions
    themselves still run sequentially (B's job has finished before
    A's job starts); actually concurrent SQL execution under a held
    lock is covered by test_concurrent_provision_waits_for_lock
    (O12) instead.

    A transient failed job (the first attempt against a broken
    configuration naming a nonexistent schema) publishes nothing; the
    next reconciliation observes the failed job, removes it and
    surfaces the error again (the production ERROR handling), and the
    retry after that converges.

    Fake-infrastructure boundary: the Kubernetes job controller, the
    OpenShift client (admin secret and job-bound secrets), the
    integration state and vault are local test doubles (one shared
    harness state, one state key per entry, exactly like one
    reconciliation of one RDS resource with two database_access
    entries); the PostgreSQL instance, the rendered SQL, the decision
    logic in _process_db_access, the generated passwords and the
    password logins are real.
    """
    pg = postgres
    harness = dam_harness_factory(pg)
    db = "rotation_two_entries_db"
    key_a = "e2e-provisioner/e2e-rds/rotation-a"
    key_b = "e2e-provisioner/e2e-rds/rotation-b"

    # the managed schema exists before the runs, owned by the executor
    _create_database(pg, db)
    result = pg.exec_psql(EXECUTOR, db, "CREATE SCHEMA sharedschema;")
    assert result.returncode == 0, result.stderr

    # the harness controller double does not implement delete_job:
    # model the production behavior -- a deleted job no longer exists
    # (neither in the status cache nor among the runnable enqueued
    # jobs) -- so the retry after the transient failure converges
    def _delete_job(job_name: str) -> None:
        harness._job_status.pop(job_name, None)
        harness.enqueued_jobs[:] = [
            j for j in harness.enqueued_jobs if j.name() != job_name
        ]

    harness.controller.delete_job.side_effect = _delete_job

    valid_a = make_db_access(
        database=db,
        role="cs_shared",
        access=[("sharedschema", ("ALL",))],
        name="rotation-a",
    )
    valid_b = make_db_access(
        database=db,
        role="cs_shared",
        access=[("sharedschema", ("ALL",))],
        name="rotation-b",
    )

    # the shared-role configuration passes the production validation:
    # equal access lists (also in order), the same database, distinct
    # resolved logins
    _validate_role_sharing([
        (valid_a, _resolve_username(valid_a, key_a)),
        (valid_b, _resolve_username(valid_b, key_b)),
    ])

    # the first attempt of entry A runs against a broken configuration
    # (an access entry on a nonexistent schema): the job fails inside
    # its transaction and publishes nothing
    broken_a = make_db_access(
        database=db,
        role="cs_shared",
        access=[("sharedschema", ("ALL",)), ("missing_schema", ("SELECT",))],
        name="rotation-a",
    )
    with pytest.raises(JobFailedError):
        _run_harness_entry(harness, broken_a, key_a)
    assert harness.vault_writes == []
    assert harness.last_job_result is not None
    assert harness.last_job_result.returncode != 0

    # the next reconciliation observes the failed job, removes it and
    # surfaces the error again -- the production ERROR handling before
    # a retry can be enqueued. Still nothing published
    with pytest.raises(JobFailedError):
        _run_harness_entry(harness, valid_a, key_a)
    assert harness.vault_writes == []

    # the proven-overlap phase: the normal retry of entry A converges
    # only up to its enqueued job, which is held IN_PROGRESS -- not
    # yet executed -- while entry B is reconciled against the same
    # not-yet-existing role. This is the barrier the sequential flow
    # cannot prove: B's reconciliation demonstrably happens while
    # A's job is still in progress
    job_a_name = _job_name(key_a, E2E_JOB_IMAGE, E2E_ADMIN_SECRET_NAME, None)
    harness.hold_job(job_a_name)
    _run_harness_entry(harness, valid_a, key_a)

    # the barrier is observable: A's job is IN_PROGRESS, nothing has
    # been published and the shared role does not exist yet -- A's
    # job, the only thing that could have created it so far, has not
    # executed
    assert harness.job_in_progress(job_a_name), "A's job is not in progress"
    assert harness.vault_writes == []
    assert (
        pg.query(
            EXECUTOR, db, "SELECT count(*) FROM pg_roles WHERE rolname='cs_shared'"
        )
        == "0"
    ), "the shared role exists although A's held job never executed"

    # entry B is reconciled WHILE A's job is still in progress: B's
    # job executes for real, CREATES the shared role (the race the
    # duplicate-object tolerance exists for) and publishes B's
    # credential -- a second generated login with its own password
    # (rotation produces a new login, not a password change on the
    # old one)
    _run_harness_entry(harness, valid_b, key_b)
    assert harness.job_in_progress(job_a_name), (
        "entry B was reconciled only after A's job had finished"
    )
    assert len(harness.vault_writes) == 1
    credential_b = harness.last_published_credential()
    login_a = _generated_username("cs_shared", key_a)
    login_b = _generated_username("cs_shared", key_b)
    assert login_a != login_b
    assert credential_b.user == login_b
    assert credential_b.database == db
    result = pg.login(login_b, credential_b.password, db)
    assert result.returncode == 0, result.stderr
    assert (
        pg.query(
            EXECUTOR, db, "SELECT count(*) FROM pg_roles WHERE rolname='cs_shared'"
        )
        == "1"
    ), "B's job did not create the shared role while A's job was held"

    # A's job completes: its CREATE ROLE hits the duplicate-object
    # tolerance (B created the shared role first), and A's credential
    # is published only now
    harness.release_job(job_a_name)
    _run_harness_entry(harness, valid_a, key_a)
    assert not harness.job_in_progress(job_a_name), "A's job never completed"
    credential_a = next(c for c in harness.published_credentials() if c.user == login_a)
    assert credential_a.database == db
    assert credential_a.password != credential_b.password
    published_users = [c.user for c in harness.published_credentials()]
    assert set(published_users) == {login_a, login_b}
    result = pg.login(login_a, credential_a.password, db)
    assert result.returncode == 0, result.stderr

    # exactly ONE shared owner role exists (NOLOGIN), with exactly the
    # two rotation logins next to it
    assert (
        pg.query(
            EXECUTOR, db, "SELECT count(*) FROM pg_roles WHERE rolname='cs_shared'"
        )
        == "1"
    )
    assert (
        pg.query(
            EXECUTOR, db, "SELECT rolcanlogin FROM pg_roles WHERE rolname='cs_shared'"
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'cs_shared%'",
        )
        == "3"
    )

    # no swapped credentials: each published credential logs in as its
    # own user, and the other entry's password fails for it
    result = pg.login(login_a, credential_a.password, db)
    assert result.returncode == 0, result.stderr
    result = pg.login(login_b, credential_b.password, db)
    assert result.returncode == 0, result.stderr
    result = pg.login(login_a, credential_b.password, db)
    assert result.returncode != 0, "entry A's login accepted entry B's password"
    assert "password authentication failed" in result.stderr
    result = pg.login(login_b, credential_a.password, db)
    assert result.returncode != 0, "entry B's login accepted entry A's password"
    assert "password authentication failed" in result.stderr

    # neither published login loses its password because of the other
    # entry: a convergence run of entry A leaves both credentials
    # working, each with exactly one distinct password ever published
    _run_harness_entry(harness, valid_a, key_a)
    passwords_by_user: dict[str, set[str]] = {}
    for published in harness.published_credentials():
        passwords_by_user.setdefault(published.user, set()).add(published.password)
    assert set(passwords_by_user) == {login_a, login_b}
    assert len(passwords_by_user[login_a]) == 1
    assert len(passwords_by_user[login_b]) == 1
    result = pg.login(login_a, credential_a.password, db)
    assert result.returncode == 0, result.stderr
    result = pg.login(login_b, credential_b.password, db)
    assert result.returncode == 0, result.stderr


# ─── 16 (job path). a legacy migration keeps the published credential ─────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_legacy_migration_keeps_credential_and_adopts_late_objects(
    postgres: PostgresContainer,
    dam_harness_factory: Callable[..., DamJobHarness],
) -> None:
    """J02 — A migrated tenant keeps its DAM app secret across the migration.

    A legacy tenant that already has a DAM app secret adds a role to
    its entry (the opt-in migration to the owner-role model): the real
    login with the OLD credential works before and after the
    migration, and the production job path reuses the password from
    the existing app secret (the vault read-back in _process_db_access)
    instead of generating a new one -- no password rotation ever
    happens. After convergence the SAME credential still works and a
    late object created by the old app during the migration window is
    adopted by the next run.

    Fake-infrastructure boundary: the Kubernetes job controller, the
    OpenShift client, the integration state and vault are local test
    doubles; the vault double serves the published app secret back
    through the secret reader double so the production _vault_connection
    read-back is exercised. PostgreSQL, the rendered SQL, the decision
    logic and the password logins are real.
    """
    pg = postgres
    harness = dam_harness_factory(pg)
    db = "legacy_credential_db"

    legacy_config = make_db_access(
        database=db,
        username="legacy_app",
        access=[("legacy_app", ("SELECT", "INSERT"))],
    )
    harness.run(legacy_config)

    # the OLD credential: published by the settlement, working on a
    # real password login BEFORE the migration
    credential = harness.last_published_credential()
    assert credential.user == "legacy_app"
    assert credential.database == db
    result = pg.login(credential.user, credential.password, credential.database)
    assert result.returncode == 0, result.stderr

    # the legacy app creates its table on its own password connection
    result = pg.login(
        credential.user,
        credential.password,
        credential.database,
        "CREATE TABLE orders (id int, src text); "
        "INSERT INTO orders VALUES (1, 'legacy-data');",
    )
    assert result.returncode == 0, result.stderr

    # the vault double serves the published app secret back, so the
    # migration run goes through the production vault read-back
    _serve_published_credentials(harness)

    # the migration adds ONLY the role: same username, same grants
    role_config = make_db_access(
        database=db,
        username="legacy_app",
        role="cs_mig_owner",
        access=[("legacy_app", ("SELECT", "INSERT"))],
    )
    harness.run(role_config)

    # the job reused the password from the existing app secret
    migration_job = harness.enqueued_jobs[-1]
    assert migration_job.user_connection.user == "legacy_app"
    assert migration_job.user_connection.password == credential.password
    # no password rotation ever happened
    assert len({c.password for c in harness.published_credentials()}) == 1

    # the SAME credential still works after the migration (real login,
    # no SET ROLE: the role default applies)
    result = pg.login(
        credential.user,
        credential.password,
        credential.database,
        "SELECT src FROM orders WHERE id = 1;",
    )
    assert result.returncode == 0, result.stderr
    assert "legacy-data" in result.stdout

    # a late object created by the old app (the executor login, like
    # the master user writing during the migration window)
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE legacy_app.late_table (id int); "
        "INSERT INTO legacy_app.late_table VALUES (7);",
    )
    assert result.returncode == 0, result.stderr

    # the next run settles and re-enqueues the convergence job, which
    # adopts the late object into the owner role
    harness.run(role_config)
    _assert_owner(
        pg,
        db,
        "late table",
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='late_table'",
        "cs_mig_owner",
    )

    # and the SAME credential reads the adopted table
    result = pg.login(
        credential.user,
        credential.password,
        credential.database,
        "SELECT count(*) FROM legacy_app.late_table;",
    )
    assert result.returncode == 0, result.stderr
    assert "1" in result.stdout


# ─── 17 (job path). an expired job reuses the vault password ──────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_job_credential_reuses_vault_secret_after_job_expiry(
    postgres: PostgresContainer,
    dam_harness_factory: Callable[..., DamJobHarness],
) -> None:
    """J02 — A job after the previous one expired reuses the vault password.

    The convergence-credential reuse of an existing entry has two
    production sources: the settled job's bound secret (proven by
    ``test_convergence_reenqueue_adopts_late_tables``) and the
    existing app secret in vault (the _vault_connection read-back).
    This case proves the second one through the production path: the
    job and its bound secret are gone (TTL expiry), the configuration
    changes, and the newly enqueued job must carry the password read
    back from the published app secret -- not a regenerated one. The
    M01-style SQL tests can deliberately receive the same password;
    only the job path proves where the password comes from.

    Fake-infrastructure boundary: the Kubernetes job controller, the
    OpenShift client, the integration state and vault are local test
    doubles; the job TTL expiry is modeled by removing the job and its
    bound secret from the harness. The vault double serves the
    published app secret back through the secret reader double.
    PostgreSQL, the rendered SQL, the decision logic and the password
    logins are real.
    """
    pg = postgres
    harness = dam_harness_factory(pg)
    db = "vault_reuse_db"

    # the managed schema exists before the runs, owned by the executor
    _create_database(pg, db)
    result = pg.exec_psql(EXECUTOR, db, "CREATE SCHEMA reuse_schema;")
    assert result.returncode == 0, result.stderr

    db_access = make_db_access(
        database=db,
        role="cs_reuse",
        access=[("reuse_schema", ("SELECT", "INSERT"))],
    )
    harness.run(db_access)

    # the credential was published and works on a real password login
    credential = harness.last_published_credential()
    assert credential.database == db
    result = pg.login(credential.user, credential.password, credential.database)
    assert result.returncode == 0, result.stderr

    # the vault double serves the published app secret back
    _serve_published_credentials(harness)

    # the job TTL-expired: it and its bound secret are gone, the
    # published app secret is the only remaining source of the password
    job_name = harness.enqueued_jobs[-1].name()
    harness._job_status.pop(job_name, None)
    harness._job_secrets.pop(job_name, None)

    # a grant change with the job gone enqueues a new job whose
    # credential can only come from the vault read-back
    changed = make_db_access(
        database=db,
        role="cs_reuse",
        access=[("reuse_schema", ("SELECT", "INSERT", "UPDATE"))],
    )
    harness.run(changed)

    changed_job = harness.enqueued_jobs[-1]
    assert changed_job.user_connection.user == credential.user
    assert changed_job.user_connection.password == credential.password, (
        "the new job did not reuse the password from the existing app secret"
    )
    # the changed job ran for real and succeeded
    job_result = harness.last_job_result
    assert job_result is not None, "the changed job did not run"
    assert job_result.returncode == 0, job_result.stderr

    # exactly one password was ever published for the entry ...
    assert len({c.password for c in harness.published_credentials()}) == 1
    # ... the grant change was applied ...
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_schema_privilege('cs_reuse', 'reuse_schema', 'USAGE')",
        )
        == "t"
    )
    # ... and the tenant still logs in with the unchanged credential
    result = pg.login(credential.user, credential.password, credential.database)
    assert result.returncode == 0, result.stderr


# ─── 19. a failed capture connection aborts before the switch ─────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_capture_failure_retry_preserves_resolution(
    postgres: PostgresContainer,
) -> None:
    """M01, P01 — A failed capture connection aborts before the switch; the retry captures.

    The retry corner of the search-path capture: the observation used
    to run POST-commit, so a failing application connection aborted
    the job AFTER the transaction had already made the role default
    permanent. The retry then classified the login as already
    role-managed, skipped the capture and converged on the configured
    order -- the SAME job reported SUCCESS while the unqualified
    ``orders`` query silently flipped from the shop marker to the
    public decoy (the reviewer's reproduction).

    The capture now runs BEFORE the transaction: the application
    connection of the capture cannot open a session here (the login's
    connection limit is 0, standing in for a pg_hba rule or an
    instance that rejects the app login -- the DAM job's own executor
    connection is unaffected, and the injection survives the script's
    own in-transaction WITH LOGIN), the job aborts VISIBLY with
    nothing persisted but the password pre-set, and the login keeps
    its old resolution behavior (no per-database role default, no
    path change). After app access is restored, the SAME job re-run
    with the same password reports SUCCESS, captures the legacy
    prefix into the store and delivers the SAME shop marker on a
    fresh password connection.
    """
    pg = postgres
    db = "capture_retry_db"
    _create_database(pg, db)

    # the public decoy with uniquely distinct data
    result = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE public.orders (id int, note text); "
        "INSERT INTO public.orders VALUES (1, 'public-note');",
    )
    assert result.returncode == 0, result.stderr

    access: list[tuple[str, tuple[str, ...]]] = [("public", ("SELECT", "INSERT"))]
    legacy_config = make_db_access(database=db, username="shop_app", access=access)
    _run_provision(pg, build_script(legacy_config))

    # the app plants its marker table in its own (auto-created) schema
    result = pg.login(
        "shop_app",
        DB_PASSWORD,
        db,
        "CREATE TABLE orders (id int, note text); "
        "INSERT INTO orders VALUES (1, 'shop-note');",
    )
    assert result.returncode == 0, result.stderr

    # BEFORE the migration: the login's default "$user", public
    # resolution delivers the shop marker
    _assert_unqualified_marker(
        pg,
        db,
        "shop_app",
        DB_PASSWORD,
        "shop-note",
        forbidden=("public-note",),
        where="before the migration",
    )

    # the migration adds ONLY the role: same username, same grants,
    # same order (the production renderer leaves the revoke delta
    # empty) -- the SAME script is the retried job below
    role_config = make_db_access(
        database=db, username="shop_app", role="shop_owner", access=access
    )
    script = build_script(role_config, legacy_config)

    # the application connection cannot open new sessions; the DAM
    # job's own executor connection is unaffected. CONNECTION LIMIT 0
    # is the injection that survives the script's own in-transaction
    # ALTER ROLE ... WITH LOGIN (which would undo NOLOGIN), so the
    # capture connection fails on the current post-commit placement
    # exactly like on the fixed pre-transaction one
    result = pg.exec_psql(EXECUTOR, db, "ALTER ROLE shop_app CONNECTION LIMIT 0;")
    assert result.returncode == 0, result.stderr

    # the first attempt aborts VISIBLY, on exactly the application
    # connection of the capture
    result = pg.exec_psql(
        EXECUTOR,
        db,
        script,
        extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
    )
    assert result.returncode != 0, (
        "the migration succeeded although the app login cannot connect"
    )
    assert "too many connections for role" in result.stderr, result.stderr

    # the abort left NOTHING persistent: the login has NO per-database
    # role default and NO search_path setting -- its old behavior is
    # intact, so a retry is still capture-eligible (regression: the
    # role default used to be committed already when the post-commit
    # capture failed, and the retry skipped the capture)
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT count(*) FROM pg_db_role_setting s "
            "JOIN pg_roles r ON r.oid = s.setrole "
            "JOIN pg_database d ON d.oid = s.setdatabase "
            "CROSS JOIN LATERAL unnest(s.setconfig) AS cfg "
            "WHERE r.rolname = 'shop_app' AND d.datname = 'capture_retry_db' "
            "AND (cfg LIKE 'role=%' OR cfg LIKE 'search_path=%')",
        )
        == "0"
    ), "the aborted attempt left the login role-managed or re-pathed"

    # app access restored
    result = pg.exec_psql(EXECUTOR, db, "ALTER ROLE shop_app CONNECTION LIMIT -1;")
    assert result.returncode == 0, result.stderr

    # the SAME job re-run (same password) reports SUCCESS
    _run_provision(pg, script)

    # the retry CAPTURED: the store (the owner role's per-database
    # search_path setting) holds the legacy prefix, with the shop
    # schema as its head ...
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT cfg FROM pg_db_role_setting s "
            "JOIN pg_roles r ON r.oid = s.setrole "
            "JOIN pg_database d ON d.oid = s.setdatabase "
            "CROSS JOIN LATERAL unnest(s.setconfig) AS cfg "
            "WHERE r.rolname = 'shop_owner' AND d.datname = 'capture_retry_db' "
            "AND cfg LIKE 'search_path=%'",
        )
        == "search_path=shop_app, public"
    ), "the retry did not capture the legacy prefix into the store"

    # ... and the applied path (the login's per-database setting)
    # resolves the shop schema first (PostgreSQL normalizes the
    # stored value: unquoted plain names, ", " separators)
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT cfg FROM pg_db_role_setting s "
            "JOIN pg_roles r ON r.oid = s.setrole "
            "JOIN pg_database d ON d.oid = s.setdatabase "
            "CROSS JOIN LATERAL unnest(s.setconfig) AS cfg "
            "WHERE r.rolname = 'shop_app' AND d.datname = 'capture_retry_db' "
            "AND cfg LIKE 'search_path=%'",
        )
        == "search_path=shop_app, public"
    ), "the retry did not apply the captured path to the login"

    # the same unqualified query on a FRESH password connection
    # returns the SAME shop marker (regression: the retry used to
    # converge on the configured order and deliver the public decoy)
    _assert_unqualified_marker(
        pg,
        db,
        "shop_app",
        DB_PASSWORD,
        "shop-note",
        forbidden=("public-note",),
        where="after the retried migration",
    )
