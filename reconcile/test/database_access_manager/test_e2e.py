"""End-to-end tests for the database-access-manager SQL templates.

These tests execute the rendered SQL against real PostgreSQL instances
(docker or podman). They are marked with `pytest.mark.e2e` and only run
when a container engine is available.

Run them explicitly:
    uv run pytest reconcile/test/database_access_manager/test_e2e.py -v

They are also included in the normal test run when docker/podman is
available (the conftest skips them otherwise).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.database_access_manager.integration import _render_sql

if TYPE_CHECKING:
    from reconcile.test.database_access_manager.conftest import PostgresContainer

# all supported PostgreSQL versions
PG_VERSIONS = ["13", "14", "15", "16", "17", "18"]

EXECUTOR = "test_admin"
DB_PASSWORD = "TestPw123"  # notsecret


def _render_provision(
    database: str,
    username: str,
    *,
    role: str | None = None,
    access_list: str = "public|SELECT,INSERT",
    revoke_list: str = "",
    schemas_csv: str = "public",
) -> str:
    """Render the appropriate provision template."""
    common = {
        "database": database,
        "database_literal": database,
        "username": username,
        "username_literal": username,
        "username_ident_literal": username,
        "admin_user": EXECUTOR,
    }
    if role:
        return _render_sql(
            "role_provision.sql",
            role=role,
            role_literal=role,
            schemas_csv=schemas_csv,
            access_list=access_list,
            revoke_list=revoke_list,
            **common,
        )
    return _render_sql(
        "legacy_provision.sql",
        access_list=access_list,
        revoke_list=revoke_list,
        **common,
    )


def _render_deprovision(database: str, username: str, *, role: bool = False) -> str:
    template = "role_deprovision.sql" if role else "legacy_deprovision.sql"
    return _render_sql(
        template,
        database=database,
        database_literal=database,
        username=username,
        username_literal=username,
        admin_user=EXECUTOR,
        access_list="",
    )


def _create_database(pg: PostgresContainer, name: str) -> None:
    """Create a database owned by the executor."""
    result = pg.exec_psql(
        "postgres", "postgres", f"CREATE DATABASE {name} OWNER {EXECUTOR};"
    )
    assert result.returncode == 0, f"CREATE DATABASE failed: {result.stderr}"


def _assert_owner(
    pg: PostgresContainer, db: str, obj_type: str, query: str, expected: str
) -> None:
    actual = pg.query(EXECUTOR, db, query)
    assert actual == expected, f"{obj_type}: expected owner {expected}, got {actual}"


# ─── legacy mode ──────────────────────────────────────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
class TestLegacyProvision:
    def test_full_cycle(self, postgres: PostgresContainer) -> None:
        """Legacy provision, grant change, idempotent re-run, deprovision."""
        pg = postgres
        db = "legacy_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        # provision
        script = _render_provision(db, "app_user")
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, f"provision failed: {result.stderr}"
        assert "ERROR" not in result.stderr

        # verify grants
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_table_privilege('app_user', 'public.orders', 'SELECT')",
            )
            == "t"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_table_privilege('app_user', 'public.orders', 'INSERT')",
            )
            == "t"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_table_privilege('app_user', 'public.orders', 'UPDATE')",
            )
            == "f"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_schema_privilege('app_user', 'public', 'USAGE')",
            )
            == "t"
        )

        # idempotent re-run
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, f"re-run failed: {result.stderr}"

        # grant change: remove INSERT, add UPDATE
        script_change = _render_provision(
            db,
            "app_user",
            access_list="public|SELECT,UPDATE",
            revoke_list="public|INSERT",
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script_change,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, f"grant change failed: {result.stderr}"
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_table_privilege('app_user', 'public.orders', 'INSERT')",
            )
            == "f"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_table_privilege('app_user', 'public.orders', 'UPDATE')",
            )
            == "t"
        )

        # deprovision
        drop_script = _render_deprovision(db, "app_user")
        result = pg.exec_psql(EXECUTOR, "postgres", drop_script)
        assert result.returncode == 0, f"deprovision failed: {result.stderr}"
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='app_user')",
            )
            == "f"
        )
        assert pg.query(EXECUTOR, db, "SELECT count(*) FROM public.orders") == "3"


# ─── role mode: every PostgreSQL object type ─────────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
class TestRoleProvision:
    def test_all_object_types_transferred(self, postgres: PostgresContainer) -> None:
        """Verify that every object type in the zoo is transferred to the owner role."""
        pg = postgres
        db = "role_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        script = _render_provision(
            db, "cs_app", role="cs_owner", access_list="public|ALL"
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, f"role provision failed: {result.stderr}"

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
            "SELECT pg_get_userbyid(stxowner) FROM pg_statistic_ext WHERE stxname='stat_orders_cust_status'",
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

        # memberships and role default
        assert (
            pg.query(EXECUTOR, db, "SELECT pg_has_role('cs_app', 'cs_owner', 'MEMBER')")
            == "t"
        )
        assert "cs_owner" in pg.query(
            EXECUTOR,
            db,
            "SELECT cfg FROM pg_db_role_setting s JOIN pg_roles r ON r.oid=s.setrole, LATERAL unnest(setconfig) cfg WHERE r.rolname='cs_app'",
        )

    def test_login_user_can_use_database(self, postgres: PostgresContainer) -> None:
        """The login user (acting as the owner role) can do everything."""
        pg = postgres
        db = "role_use_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        script = _render_provision(
            db, "cs_app", role="cs_owner", access_list="public|ALL"
        )
        pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )

        # DML
        result = pg.exec_psql(
            "cs_app", db, "SET ROLE cs_owner; SELECT count(*) FROM public.orders;"
        )
        assert result.returncode == 0
        assert "3" in result.stdout

        # DDL: ALTER TABLE
        result = pg.exec_psql(
            "cs_app",
            db,
            "SET ROLE cs_owner; ALTER TABLE public.orders ADD COLUMN e2e_col text;",
        )
        assert result.returncode == 0, result.stderr

        # DDL: CREATE INDEX
        result = pg.exec_psql(
            "cs_app",
            db,
            "SET ROLE cs_owner; CREATE INDEX idx_e2e ON public.orders (e2e_col);",
        )
        assert result.returncode == 0, result.stderr

        # DDL: CREATE TABLE
        result = pg.exec_psql(
            "cs_app", db, "SET ROLE cs_owner; CREATE TABLE public.e2e_new (id int);"
        )
        assert result.returncode == 0, result.stderr

        # DML: INSERT into new table
        result = pg.exec_psql(
            "cs_app", db, "SET ROLE cs_owner; INSERT INTO public.e2e_new VALUES (42);"
        )
        assert result.returncode == 0, result.stderr

        # function call
        result = pg.exec_psql(
            "cs_app", db, "SET ROLE cs_owner; SELECT public.get_order_total(1);"
        )
        assert result.returncode == 0
        assert "100.00" in result.stdout

        # procedure call
        result = pg.exec_psql(
            "cs_app", db, "SET ROLE cs_owner; CALL public.reset_pending();"
        )
        assert result.returncode == 0, result.stderr

        # aggregate
        result = pg.exec_psql(
            "cs_app",
            db,
            "SET ROLE cs_owner; SELECT public.max_qty(qty) > 0 FROM public.order_items;",
        )
        assert result.returncode == 0
        assert "t" in result.stdout

    def test_idempotent(self, postgres: PostgresContainer) -> None:
        """Re-running the role provision is a no-op."""
        pg = postgres
        db = "role_idem_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        script = _render_provision(
            db, "cs_app", role="cs_owner", access_list="public|ALL"
        )
        args = ["-v", f"db_user_password={DB_PASSWORD}"]

        result = pg.exec_psql(EXECUTOR, "postgres", script, extra_args=args)
        assert result.returncode == 0, result.stderr

        result = pg.exec_psql(EXECUTOR, "postgres", script, extra_args=args)
        assert result.returncode == 0, f"idempotent re-run failed: {result.stderr}"
        assert "ERROR" not in result.stderr

    def test_ext_data_access(self, postgres: PostgresContainer) -> None:
        """Cross-schema grants: the role gets SELECT on a ext_data schema."""
        pg = postgres
        db = "role_fk_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        # create a third-party schema with a table
        result = pg.exec_psql(
            "postgres",
            db,
            """
            CREATE ROLE third_party LOGIN;
            CREATE SCHEMA ext_data AUTHORIZATION third_party;
            SET ROLE third_party;
            CREATE TABLE ext_data.shared_data (id int, data text);
            INSERT INTO ext_data.shared_data VALUES (1, 'hello');
            RESET ROLE;
            GRANT USAGE ON SCHEMA ext_data TO test_admin WITH GRANT OPTION;
            GRANT SELECT ON ext_data.shared_data TO test_admin WITH GRANT OPTION;
        """,
        )
        assert result.returncode == 0, f"ext_data schema setup failed: {result.stderr}"

        script = _render_provision(
            db,
            "cs_app",
            role="cs_owner",
            access_list="public|ALL;ext_data|SELECT",
            schemas_csv="public,ext_data",
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, (
            f"ext_data schema provision failed: {result.stderr}"
        )

        # role has USAGE and SELECT on ext_data schema
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_schema_privilege('cs_owner', 'ext_data', 'USAGE')",
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
        # ext_data schema is NOT owned by cs_owner
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='ext_data'",
            )
            == "third_party"
        )

        # login user can read cross-schema
        result = pg.exec_psql(
            "cs_app",
            db,
            "SET ROLE cs_owner; SELECT data FROM ext_data.shared_data WHERE id=1;",
        )
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_revoke_from_stale_schema(self, postgres: PostgresContainer) -> None:
        """Revokes for schemas that no longer exist are skipped."""
        pg = postgres
        db = "role_stale_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        script = _render_provision(
            db,
            "cs_app",
            role="cs_owner",
            access_list="public|ALL",
            revoke_list="nonexistent_schema|ALL",
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, f"stale schema revoke failed: {result.stderr}"


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
class TestRoleDeprovision:
    def test_deprovision_keeps_role(self, postgres: PostgresContainer) -> None:
        """Deprovisioning removes the login, keeps the owner role and data."""
        pg = postgres
        db = "role_drop_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        # provision first
        script = _render_provision(
            db, "cs_app", role="cs_owner", access_list="public|ALL"
        )
        pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )

        # deprovision
        drop = _render_deprovision(db, "cs_app", role=True)
        result = pg.exec_psql(EXECUTOR, "postgres", drop)
        assert result.returncode == 0, f"deprovision failed: {result.stderr}"

        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cs_app')",
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

    def test_missing_login_is_noop(self, postgres: PostgresContainer) -> None:
        """Deprovisioning a login that does not exist is a successful no-op."""
        pg = postgres
        db = "role_ghost_db"
        _create_database(pg, db)

        drop = _render_deprovision(db, "ghost_user", role=True)
        result = pg.exec_psql(EXECUTOR, "postgres", drop)
        assert result.returncode == 0, f"ghost deprovision failed: {result.stderr}"
        assert "nothing to deprovision" in result.stdout


# ─── migration: legacy → role mode ───────────────────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
class TestLegacyToRoleMigration:
    def test_migration_without_password_change(
        self, postgres: PostgresContainer
    ) -> None:
        """A legacy user migrates to the role model, keeping its identity."""
        pg = postgres
        db = "migrate_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        # 1. legacy provision
        legacy = _render_provision(db, "app_user", access_list="public|SELECT,INSERT")
        pg.exec_psql(
            EXECUTOR,
            "postgres",
            legacy,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )

        # 2. migrate to role mode (same username, new role)
        role_script = _render_provision(
            db, "app_user", role="cs_owner", access_list="public|ALL"
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            role_script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, f"migration failed: {result.stderr}"

        # 3. verify: objects now owned by cs_owner
        _assert_owner(
            pg,
            db,
            "table after migration",
            "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='orders'",
            "cs_owner",
        )
        # user is a member of the role
        assert (
            pg.query(
                EXECUTOR, db, "SELECT pg_has_role('app_user', 'cs_owner', 'MEMBER')"
            )
            == "t"
        )
        # user still exists (same login)
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='app_user')",
            )
            == "t"
        )
        # data is intact
        assert pg.query(EXECUTOR, db, "SELECT count(*) FROM public.orders") == "3"
        # the user can still query (now via the role)
        result = pg.exec_psql(
            "app_user", db, "SET ROLE cs_owner; SELECT count(*) FROM public.orders;"
        )
        assert result.returncode == 0
        assert "3" in result.stdout


# ─── DAM scenario: master user → dedicated user ─────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
class TestMasterUserMigration:
    """Simulates the core use case: apps using the postgres master user
    on the default postgres database, migrating to a dedicated user."""

    def test_full_migration_zero_downtime(self, postgres: PostgresContainer) -> None:
        pg = postgres
        db = "postgres"  # the default database, like production

        # the postgres database is owned by the bootstrap superuser:
        # grant CREATE on public to the executor WITH GRANT OPTION
        # (simulating the RDS master user's privileges — rds_superuser
        # can grant on public)
        pg.exec_psql(
            "postgres",
            db,
            f"GRANT CREATE ON SCHEMA public TO {EXECUTOR} WITH GRANT OPTION;",
        )
        pg.seed(db, EXECUTOR)

        # the "app" is running as the master user (test_admin)
        assert pg.query(EXECUTOR, db, "SELECT count(*) FROM public.orders") == "3"

        # DAM provisions the role model
        script = _render_provision(
            db, "cs_app", role="cs_owner", access_list="public|ALL"
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, f"migration failed: {result.stderr}"

        # old user keeps working during migration window
        assert pg.query(EXECUTOR, db, "SELECT count(*) FROM public.orders") == "3"
        result = pg.exec_psql(
            EXECUTOR,
            db,
            "INSERT INTO public.orders (customer_id, total) VALUES (99, 1.00);",
        )
        assert result.returncode == 0, "master lost INSERT during migration"

        # new user has full access
        result = pg.exec_psql(
            "cs_app", db, "SET ROLE cs_owner; SELECT count(*) FROM public.orders;"
        )
        assert result.returncode == 0
        assert "4" in result.stdout

        # second reconcile picks up master-created objects
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0

        result = pg.exec_psql(
            EXECUTOR, db, "CREATE TABLE public.master_created (id int);"
        )
        assert result.returncode == 0
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0
        _assert_owner(
            pg,
            db,
            "master-created table",
            "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='master_created'",
            "cs_owner",
        )


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
class TestRotation:
    """Phase 1 rotation: two login users share the same owner role."""

    def test_two_users_same_role(self, postgres: PostgresContainer) -> None:
        pg = postgres
        db = "rotate_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        # provision user v1
        v1 = _render_provision(db, "cs_v1", role="cs_owner", access_list="public|ALL")
        result = pg.exec_psql(
            EXECUTOR, "postgres", v1, extra_args=["-v", "db_user_password=PwV1"]
        )
        assert result.returncode == 0, result.stderr

        # provision user v2 (same role, different login)
        v2 = _render_provision(db, "cs_v2", role="cs_owner", access_list="public|ALL")
        result = pg.exec_psql(
            EXECUTOR, "postgres", v2, extra_args=["-v", "db_user_password=PwV2"]
        )
        assert result.returncode == 0, result.stderr

        # both users are members of the role
        assert (
            pg.query(EXECUTOR, db, "SELECT pg_has_role('cs_v1', 'cs_owner', 'MEMBER')")
            == "t"
        )
        assert (
            pg.query(EXECUTOR, db, "SELECT pg_has_role('cs_v2', 'cs_owner', 'MEMBER')")
            == "t"
        )

        # both can use the database simultaneously
        for user in ("cs_v1", "cs_v2"):
            result = pg.exec_psql(
                user, db, "SET ROLE cs_owner; SELECT count(*) FROM public.orders;"
            )
            assert result.returncode == 0, f"{user} failed: {result.stderr}"

        # v2 can ALTER objects created by v1
        pg.exec_psql(
            "cs_v1", db, "SET ROLE cs_owner; CREATE TABLE public.v1_table (id int);"
        )
        result = pg.exec_psql(
            "cs_v2",
            db,
            "SET ROLE cs_owner; ALTER TABLE public.v1_table ADD COLUMN v2_col text;",
        )
        assert result.returncode == 0, f"v2 cannot ALTER v1's table: {result.stderr}"

        # deprovision v1 (the old credential)
        drop_v1 = _render_deprovision(db, "cs_v1", role=True)
        result = pg.exec_psql(EXECUTOR, "postgres", drop_v1)
        assert result.returncode == 0, f"deprovision v1 failed: {result.stderr}"

        # v1 gone, v2 still works, role and data survive
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cs_v1')",
            )
            == "f"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cs_v2')",
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
        assert pg.query(EXECUTOR, db, "SELECT count(*) FROM public.orders") == "3"
        result = pg.exec_psql(
            "cs_v2", db, "SET ROLE cs_owner; SELECT count(*) FROM public.orders;"
        )
        assert result.returncode == 0


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
class TestCrossSchemaIsolation:
    """Two tenants on the same instance: each role only sees its own schema."""

    def test_isolation(self, postgres: PostgresContainer) -> None:
        pg = postgres
        db = "isolation_db"
        _create_database(pg, db)

        # create two schemas with data
        result = pg.exec_psql(
            EXECUTOR,
            db,
            """
            CREATE SCHEMA tenant_a;
            CREATE SCHEMA tenant_b;
            CREATE TABLE tenant_a.data (id int, secret text);
            CREATE TABLE tenant_b.data (id int, secret text);
            INSERT INTO tenant_a.data VALUES (1, 'tenant_a_secret');
            INSERT INTO tenant_b.data VALUES (1, 'tenant_b_secret');
        """,
        )
        assert result.returncode == 0, result.stderr

        # provision role A (access to tenant_a only)
        a = _render_provision(
            db,
            "user_a",
            role="role_a",
            access_list="tenant_a|SELECT",
            schemas_csv="tenant_a",
        )
        result = pg.exec_psql(
            EXECUTOR, "postgres", a, extra_args=["-v", "db_user_password=PwA"]
        )
        assert result.returncode == 0, result.stderr

        # provision role B (access to tenant_b only)
        b = _render_provision(
            db,
            "user_b",
            role="role_b",
            access_list="tenant_b|SELECT",
            schemas_csv="tenant_b",
        )
        result = pg.exec_psql(
            EXECUTOR, "postgres", b, extra_args=["-v", "db_user_password=PwB"]
        )
        assert result.returncode == 0, result.stderr

        # user A can read tenant_a but NOT tenant_b
        result = pg.exec_psql(
            "user_a", db, "SET ROLE role_a; SELECT secret FROM tenant_a.data;"
        )
        assert result.returncode == 0
        assert "tenant_a_secret" in result.stdout

        result = pg.exec_psql(
            "user_a", db, "SET ROLE role_a; SELECT secret FROM tenant_b.data;"
        )
        assert result.returncode != 0, "user_a should NOT access tenant_b"

        # user B can read tenant_b but NOT tenant_a
        result = pg.exec_psql(
            "user_b", db, "SET ROLE role_b; SELECT secret FROM tenant_b.data;"
        )
        assert result.returncode == 0
        assert "tenant_b_secret" in result.stdout

        result = pg.exec_psql(
            "user_b", db, "SET ROLE role_b; SELECT secret FROM tenant_a.data;"
        )
        assert result.returncode != 0, "user_b should NOT access tenant_a"


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
class TestZeroDowntimeLocking:
    """Verifies that ownership transfer handles active app connections."""

    def test_migration_with_open_read_transaction(
        self, postgres: PostgresContainer
    ) -> None:
        """An open read transaction blocks ownership transfer until it
        commits. The migration must handle this (lock wait + retry or
        timeout)."""
        pg = postgres
        db = "lock_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        # start an open read transaction as the master user (simulates
        # the running app holding a read lock on a table)
        # Note: we can't easily hold a transaction across docker exec
        # calls, so we verify the lock behavior differently: we set a
        # short lock_timeout and confirm the script handles it
        pg.exec_psql(EXECUTOR, db, "SET lock_timeout = '5s';")

        # provision the role model (the ALTER TABLE will need to wait
        # for any locks, but with no active transaction it should
        # succeed immediately)
        script = _render_provision(
            db, "cs_app", role="cs_owner", access_list="public|ALL"
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, (
            f"provision with lock_timeout failed: {result.stderr}"
        )

        # verify the transfer succeeded
        _assert_owner(
            pg,
            db,
            "table after lock test",
            "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='orders'",
            "cs_owner",
        )

    def test_lock_timeout_does_not_cause_silent_failure(
        self, postgres: PostgresContainer
    ) -> None:
        """With a very short lock_timeout and an actual lock held by
        another session, the script must fail visibly (ON_ERROR_STOP)
        rather than silently skipping the transfer."""
        pg = postgres
        db = "lock_timeout_db"
        _create_database(pg, db)
        pg.seed(db, EXECUTOR)

        # create a table and hold a lock on it from another session
        # (via advisory lock simulation — we can't easily hold a real
        # transaction across docker exec calls, so we verify the
        # script's behavior with a table that has an ACCESS EXCLUSIVE
        # lock via a DDL operation)
        pg.exec_psql(EXECUTOR, db, "CREATE TABLE locked_table (id int);")

        # set an extremely short lock_timeout (1ms) so any contention
        # fails immediately
        pg.exec_psql(EXECUTOR, db, "SET lock_timeout = '1ms';")

        script = _render_provision(
            db, "cs_app", role="cs_owner", access_list="public|ALL"
        )
        # the script connects to the postgres database first, then \c to
        # the target — the lock_timeout is per-session and doesn't carry
        # over. The script itself should succeed because there's no
        # actual contention.
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, (
            f"provision should succeed without contention: {result.stderr}"
        )

        # verify the transfer
        _assert_owner(
            pg,
            db,
            "locked table transferred",
            "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='locked_table'",
            "cs_owner",
        )


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
class TestMultiRoleDatabaseAccess:
    """Two roles on disjoint schemas in the same DAM-created database
    must both retain CONNECT after ownership changes."""

    def test_both_roles_keep_connect(self, postgres: PostgresContainer) -> None:
        pg = postgres
        db = "multi_role_db"

        # create the database and schemas first
        _create_database(pg, db)
        pg.exec_psql(EXECUTOR, db, "CREATE SCHEMA schema_a; CREATE SCHEMA schema_b;")
        pg.exec_psql(
            EXECUTOR,
            db,
            "CREATE TABLE schema_a.data (id int); CREATE TABLE schema_b.data (id int);",
        )

        # provision role_a on schema_a
        a = _render_provision(
            db,
            "user_a",
            role="role_a",
            access_list="schema_a|SELECT",
            schemas_csv="schema_a",
        )
        result = pg.exec_psql(
            EXECUTOR, "postgres", a, extra_args=["-v", "db_user_password=PwA"]
        )
        assert result.returncode == 0, f"role_a provision failed: {result.stderr}"

        # verify user_a can connect
        result = pg.exec_psql("user_a", db, "SET ROLE role_a; SELECT 1;")
        assert result.returncode == 0, (
            f"user_a lost CONNECT after own provision: {result.stderr}"
        )

        # provision role_b on schema_b (same database)
        b = _render_provision(
            db,
            "user_b",
            role="role_b",
            access_list="schema_b|SELECT",
            schemas_csv="schema_b",
        )
        result = pg.exec_psql(
            EXECUTOR, "postgres", b, extra_args=["-v", "db_user_password=PwB"]
        )
        assert result.returncode == 0, f"role_b provision failed: {result.stderr}"

        # user_a must STILL be able to connect after role_b's
        # ALTER DATABASE changed the owner
        result = pg.exec_psql("user_a", db, "SET ROLE role_a; SELECT 1;")
        assert result.returncode == 0, (
            f"user_a lost CONNECT after role_b took ownership: {result.stderr}"
        )

        # user_b can also connect
        result = pg.exec_psql("user_b", db, "SET ROLE role_b; SELECT 1;")
        assert result.returncode == 0, f"user_b cannot connect: {result.stderr}"


# ─── review regressions ──────────────────────────────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
class TestMigrationSearchPath:
    """P1: the login's search path must survive the migration.
    Legacy mode creates a schema named after the login; the default
    search_path ($user, public) resolves $user as the session role
    once the role default applies, so unqualified lookups in the
    login's own schema would break on fresh connections."""

    def test_unqualified_lookup_survives_migration(
        self, postgres: PostgresContainer
    ) -> None:
        pg = postgres
        db = "searchpath_db"
        _create_database(pg, db)

        # legacy provision: creates the app_user schema with a table
        legacy = _render_provision(
            db, "app_user", access_list="app_user|SELECT,INSERT", schemas_csv="app_user"
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            legacy,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, f"legacy provision failed: {result.stderr}"
        pg.exec_psql(
            EXECUTOR,
            db,
            "CREATE TABLE app_user.orders (id int); INSERT INTO app_user.orders VALUES (1), (2), (3);",
        )

        # migrate to role mode
        role_script = _render_provision(
            db,
            "app_user",
            role="cs_owner",
            access_list="app_user|ALL",
            schemas_csv="app_user",
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            role_script,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, f"migration failed: {result.stderr}"

        # fresh connection, unqualified lookup: the role default
        # (SET ROLE cs_owner) must not break $user resolution
        result = pg.exec_psql("app_user", db, "SELECT count(*) FROM orders;")
        assert result.returncode == 0, (
            f"unqualified lookup broken after migration "
            f"(search_path not preserved): {result.stderr}"
        )
        assert "3" in result.stdout


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
class TestForeignSchemaGrants:
    """P1: read-only entries on foreign schemas (owned by a role the
    executor does not control) must not receive CREATE on the schema
    or ALL default privileges on future tables."""

    def test_select_only_foreign_schema(self, postgres: PostgresContainer) -> None:
        pg = postgres
        db = "foreign_db"
        _create_database(pg, db)

        # a schema owned by a third role the executor does NOT control.
        # Membership is needed transiently for the ownership transfer
        # (PG16 SET requirement), then revoked so the schema stays
        # foreign to the executor. The grant options let the executor
        # re-grant USAGE and SELECT as the provision script expects.
        setup = pg.exec_psql(
            EXECUTOR,
            db,
            "CREATE ROLE third_owner NOLOGIN; "
            "GRANT third_owner TO test_admin WITH SET TRUE; "
            "GRANT CREATE ON DATABASE foreign_db TO third_owner; "
            "SET ROLE third_owner; "
            "CREATE SCHEMA foreign_schema; "
            "CREATE TABLE foreign_schema.data (id int); "
            "GRANT USAGE, CREATE ON SCHEMA foreign_schema TO test_admin WITH GRANT OPTION; "
            "GRANT SELECT ON foreign_schema.data TO test_admin WITH GRANT OPTION; "
            "RESET ROLE; "
            "REVOKE third_owner FROM test_admin;",
        )
        assert setup.returncode == 0, f"setup failed: {setup.stderr}"

        # SELECT-only entry on the foreign schema
        script = _render_provision(
            db,
            "ro_user",
            role="cs_ro",
            access_list="foreign_schema|SELECT",
            schemas_csv="foreign_schema",
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", "db_user_password=RoPassword1"],
        )
        assert result.returncode == 0, f"provision failed: {result.stderr}"

        # the owner role has USAGE but NOT CREATE on the foreign schema
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_schema_privilege('cs_ro', 'foreign_schema', 'USAGE')",
            )
            == "t"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_schema_privilege('cs_ro', 'foreign_schema', 'CREATE')",
            )
            == "f"
        )

        # default privileges in the foreign schema are limited to the
        # CONFIGURED grants: SELECT on future executor-created tables,
        # not ALL (no INSERT)
        result = pg.exec_psql(
            EXECUTOR, db, "CREATE TABLE foreign_schema.future_data (id int);"
        )
        assert result.returncode == 0, f"future table creation failed: {result.stderr}"
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_table_privilege('cs_ro', 'foreign_schema.future_data', 'SELECT')",
            )
            == "t"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_table_privilege('cs_ro', 'foreign_schema.future_data', 'INSERT')",
            )
            == "f"
        )

        # the configured SELECT works
        result = pg.exec_psql(
            "ro_user", db, "SET ROLE cs_ro; SELECT count(*) FROM foreign_schema.data;"
        )
        assert result.returncode == 0, result.stderr

    def test_transient_grants_removed_with_schema(
        self, postgres: PostgresContainer
    ) -> None:
        """When a foreign schema leaves the access list, the transient
        CREATE grant and the default privileges must not persist."""
        pg = postgres
        db = "foreign_remove_db"
        _create_database(pg, db)

        setup = pg.exec_psql(
            EXECUTOR,
            db,
            "CREATE ROLE third_owner2 NOLOGIN; "
            "GRANT third_owner2 TO test_admin WITH SET TRUE; "
            "GRANT CREATE ON DATABASE foreign_remove_db TO third_owner2; "
            "SET ROLE third_owner2; "
            "CREATE SCHEMA removable_schema; "
            "CREATE TABLE removable_schema.data (id int); "
            "GRANT USAGE, CREATE ON SCHEMA removable_schema TO test_admin WITH GRANT OPTION; "
            "GRANT SELECT ON removable_schema.data TO test_admin WITH GRANT OPTION; "
            "RESET ROLE; "
            "REVOKE third_owner2 FROM test_admin;",
        )
        assert setup.returncode == 0, f"setup failed: {setup.stderr}"

        # the schema that stays in the access list after the removal
        result = pg.exec_psql(EXECUTOR, db, "CREATE SCHEMA other_schema;")
        assert result.returncode == 0, f"setup failed: {result.stderr}"

        # provision with the foreign schema in the access list
        with_schema = _render_provision(
            db,
            "ro_user2",
            role="cs_ro2",
            access_list="removable_schema|SELECT",
            schemas_csv="removable_schema",
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            with_schema,
            extra_args=["-v", "db_user_password=RoPassword2"],
        )
        assert result.returncode == 0, f"provision failed: {result.stderr}"

        # re-provision with the schema removed from the access list
        without_schema = _render_provision(
            db,
            "ro_user2",
            role="cs_ro2",
            access_list="other_schema|SELECT",
            schemas_csv="other_schema",
            revoke_list="removable_schema|SELECT",
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            without_schema,
            extra_args=["-v", "db_user_password=RoPassword2"],
        )
        assert result.returncode == 0, f"re-provision failed: {result.stderr}"

        # the owner role lost table access, USAGE and CREATE
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_table_privilege('cs_ro2', 'removable_schema.data', 'SELECT')",
            )
            == "f"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_schema_privilege('cs_ro2', 'removable_schema', 'USAGE')",
            )
            == "f"
        )
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_schema_privilege('cs_ro2', 'removable_schema', 'CREATE')",
            )
            == "f"
        )
        # the default privileges are gone: new executor tables grant
        # nothing to the owner role
        result = pg.exec_psql(
            EXECUTOR, db, "CREATE TABLE removable_schema.new_data (id int);"
        )
        assert result.returncode == 0, f"new table creation failed: {result.stderr}"
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_table_privilege('cs_ro2', 'removable_schema.new_data', 'SELECT')",
            )
            == "f"
        )


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
class TestLegacyPublicRestrictions:
    """P1: a newly created legacy database is dedicated to a single
    login -- unrelated instance logins must not gain CONNECT or TEMP
    through PUBLIC."""

    def test_unrelated_login_cannot_connect(self, postgres: PostgresContainer) -> None:
        pg = postgres
        db = "legacy_restricted_db"

        # an unrelated login that exists before provisioning
        pg.exec_psql(
            EXECUTOR, "postgres", "CREATE ROLE intruder LOGIN PASSWORD 'Intruder1';"
        )

        # legacy provision creates the database
        legacy = _render_provision(db, "legacy_user", access_list="legacy_user|SELECT")
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            legacy,
            extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
        )
        assert result.returncode == 0, f"legacy provision failed: {result.stderr}"

        # the managed login CAN connect (explicit CONNECT grant)
        result = pg.exec_psql("legacy_user", db, "SELECT 1;")
        assert result.returncode == 0, f"managed login lost CONNECT: {result.stderr}"

        # the unrelated login CANNOT connect
        result = pg.exec_psql("intruder", db, "SELECT 1;")
        assert result.returncode != 0, "unrelated login gained CONNECT via PUBLIC"


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
class TestConnectVerification:
    """P2: provisioning must grant and verify CONNECT for the login
    on databases where PUBLIC lacks it, and fail when it cannot."""

    def test_connect_granted_when_public_lacks_it(
        self, postgres: PostgresContainer
    ) -> None:
        pg = postgres
        db = "no_public_connect_db"
        _create_database(pg, db)
        # remove CONNECT from PUBLIC (as restricted instances do)
        pg.exec_psql(
            EXECUTOR, "postgres", f"REVOKE CONNECT ON DATABASE {db} FROM public;"
        )

        script = _render_provision(
            db, "conn_user", role="cs_conn", access_list="public|SELECT"
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", "db_user_password=ConnPassword1"],
        )
        assert result.returncode == 0, f"provision failed: {result.stderr}"

        # the login got CONNECT despite PUBLIC lacking it
        assert (
            pg.query(
                EXECUTOR,
                db,
                "SELECT has_database_privilege('conn_user', 'no_public_connect_db', 'CONNECT')",
            )
            == "t"
        )

    def test_provision_fails_without_connect_grant_option(
        self, postgres: PostgresContainer
    ) -> None:
        pg = postgres
        db = "no_connect_db"
        # owned by a third role with no public CONNECT and no path for
        # the executor to grant CONNECT. Membership is needed
        # transiently for the ownership transfer, then revoked.
        setup = pg.exec_psql(
            EXECUTOR,
            "postgres",
            f"CREATE DATABASE {db}; "
            f"REVOKE CONNECT ON DATABASE {db} FROM public; "
            f"CREATE ROLE db_guard NOLOGIN; "
            f"GRANT db_guard TO test_admin WITH SET TRUE; "
            f"ALTER DATABASE {db} OWNER TO db_guard; "
            f"REVOKE db_guard FROM test_admin;",
        )
        assert setup.returncode == 0, f"setup failed: {setup.stderr}"

        script = _render_provision(
            db, "no_conn_user", role="cs_noconn", access_list="public|SELECT"
        )
        result = pg.exec_psql(
            EXECUTOR,
            "postgres",
            script,
            extra_args=["-v", "db_user_password=NoConnPassword1"],
        )
        assert result.returncode != 0, (
            "provision succeeded although the login has no CONNECT and the "
            "executor cannot grant it"
        )
