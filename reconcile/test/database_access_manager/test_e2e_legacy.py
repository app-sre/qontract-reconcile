"""End-to-end tests for database-access-manager LEGACY mode.

Legacy mode (``role`` not set): the configured ``username`` is the
application login, owns its own schema named after the login and gets
the configured table-level grants. The target is always a dedicated
database (created or adopted by DAM, never the admin default
database) and a tenant stays in legacy mode from first to last step.

Every test executes the real SQL templates -- rendered through the
production renderer where grant changes are involved -- against a
real PostgreSQL container, and connects as the application login with
real password authentication wherever the user experience is asserted.

Run explicitly:
    uv run pytest reconcile/test/database_access_manager/test_e2e_legacy.py -v
"""

# | ID  | Use case                                                  | Observable guarantee                                                                                                                                      | Test                                              |
# | --- | --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
# | L01 | Provision a new dedicated database for a named login      | The app connects with its password, owns its schema (not the database); unrelated logins have no CONNECT or TEMP.                                         | `test_legacy_provision_new_database`              |
# | L02 | Adopt an existing dedicated database                      | Existing data and owners survive; the app connects; unrelated logins cannot connect and have no TEMP.                                                     | `test_legacy_adopt_existing_database`             |
# | L03 | The app works in its own schema without SET ROLE          | The login creates, fills and alters a table in its own schema; schema and table belong to the login; the database keeps its owner.                        | `test_legacy_own_schema_lifecycle`                |
# | L04 | Only the configured table grants are applied              | The login can SELECT and INSERT but not UPDATE the admin-owned table (table privilege error); the table keeps its owner.                                  | `test_legacy_configured_table_grants_only`        |
# | L05 | Grant changes through the production renderer             | The ALL -> SELECT -> SELECT,INSERT chain, schema removal and vanished schemas converge: lost privileges gone, new ones usable, nothing blocked.           | `test_legacy_grant_changes_via_renderer`          |
# | L06 | Re-run without a configuration change                     | App data, owners, grants and the working password survive the repeat run.                                                                                 | `test_legacy_own_schema_lifecycle`                |
# | L07 | A configuration change rotates the published password     | The newly published credential works; the previous password is rejected as an authentication failure.                                                     | `test_legacy_password_rotation_on_config_change`  |
# | L08 | A provisioning failure inside the transaction             | The old password keeps working and no new secret is published.                                                                                            | `test_legacy_failed_provision_keeps_old_password` |
# | L09 | Deprovision with an open session and the login's own data | The open session is terminated, new logins fail, the login-created table and committed data survive under admin ownership; the repeat removal is a no-op. | `test_legacy_own_schema_lifecycle`                |
# | L10 | Password authentication is enforced for app logins        | Only the correct password connects; wrong or missing passwords are rejected; only fixture roles keep trust.                                               | `test_legacy_password_auth_enforced`              |
# | L11 | A failed run on an adopted database                        | PUBLIC keeps CONNECT after a failed run (the revoke rolls back with the transaction); a successful run still revokes it and locks PUBLIC-connecting logins out.| `test_legacy_revoke_public_rolls_back_with_failed_run` |
# | L12 | Deprovision with a nonempty access list for an absent login | The missing-login guard runs BEFORE the revoke block: the deprovision is a successful no-op (nothing to deprovision) and the access list's schema keeps its objects.  | `test_legacy_deprovision_missing_login_nonempty_access` |

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from reconcile.database_access_manager.integration import JobFailedError
from reconcile.test.database_access_manager.conftest import (
    DB_PASSWORD,
    EXECUTOR,
    PG_VERSIONS,
    _create_database,
    _database_owner,
    _render_deprovision,
    _render_provision,
    build_script,
    make_db_access,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from subprocess import CompletedProcess

    from reconcile.test.database_access_manager.conftest import (
        DamJobHarness,
        PostgresContainer,
    )

INTRUDER_PASSWORD = "Intruder1"  # notsecret


def _run_script(
    pg: PostgresContainer, script: str, *, password: str | None = DB_PASSWORD
) -> CompletedProcess[str]:
    """Execute a rendered DAM script as the executor, like the real
    job does (the user password is passed as a psql variable)."""
    extra_args = ["-v", f"db_user_password={password}"] if password else None
    result = pg.exec_psql(EXECUTOR, "postgres", script, extra_args=extra_args)
    assert result.returncode == 0, f"DAM script failed: {result.stderr}"
    assert "ERROR" not in result.stderr
    return result


def _create_intruder(pg: PostgresContainer) -> None:
    """Create an unrelated instance login with a known password."""
    result = pg.exec_psql(
        "postgres",
        "postgres",
        f"CREATE ROLE intruder LOGIN PASSWORD '{INTRUDER_PASSWORD}';",
    )
    assert result.returncode == 0, f"creating the intruder failed: {result.stderr}"


def _assert_intruder_locked_out(pg: PostgresContainer, db: str) -> None:
    """The unrelated login has neither CONNECT nor TEMP on the
    dedicated legacy database.

    A real connection attempt with the intruder's CORRECT password
    must fail on the missing privilege, not on authentication."""
    assert (
        pg.query(
            EXECUTOR,
            db,
            f"SELECT has_database_privilege('intruder', '{db}', 'CONNECT')",
        )
        == "f"
    )
    assert (
        pg.query(
            EXECUTOR,
            db,
            f"SELECT has_database_privilege('intruder', '{db}', 'TEMP')",
        )
        == "f"
    )
    result = pg.login("intruder", INTRUDER_PASSWORD, db)
    assert result.returncode != 0, "unrelated login gained CONNECT via PUBLIC"
    stderr = result.stderr.lower()
    assert "permission denied" in stderr, (
        f"expected a permission error for the intruder, got: {result.stderr}"
    )
    assert "password authentication failed" not in stderr, result.stderr


def _schema_owner(pg: PostgresContainer, db: str, schema: str) -> str:
    return pg.query(
        EXECUTOR,
        db,
        f"SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
        f"WHERE nspname = '{schema}'",
    )


def _table_owner(pg: PostgresContainer, db: str, schema: str, table: str) -> str:
    return pg.query(
        EXECUTOR,
        db,
        f"SELECT pg_get_userbyid(relowner) FROM pg_class c "
        f"JOIN pg_namespace n ON n.oid = c.relnamespace "
        f"WHERE c.relname = '{table}' AND n.nspname = '{schema}'",
    )


def _wait_for_open_session(pg: PostgresContainer, db: str, user: str) -> None:
    """Wait until the background session of the login holds its
    ACCESS EXCLUSIVE lock, so the deprovision cannot finish without
    terminating the session."""
    lock_sql = (
        "SELECT count(*) FROM pg_locks l "
        "JOIN pg_class c ON c.oid = l.relation "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        f"WHERE l.mode = 'AccessExclusiveLock' AND l.granted "
        f"AND n.nspname = '{user}' AND c.relname = 'app_data'"
    )
    for _ in range(30):
        if pg.query("postgres", db, lock_sql) != "0":
            return
        time.sleep(1)
    pytest.fail(f"the open session of {user} never acquired its lock")


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_legacy_provision_new_database(postgres: PostgresContainer) -> None:
    """L01 — DAM creates the database, the login and its schema. The
    login owns the schema, not the database, and PUBLIC keeps nothing
    on the new database."""
    pg = postgres
    db = "legacy_new_db"
    _create_intruder(pg)

    _run_script(pg, _render_provision(db, "app_user"))

    # the executor that ran the job keeps the database
    assert _database_owner(pg, db) == EXECUTOR

    # the login connects with real password authentication
    result = pg.login("app_user", DB_PASSWORD, db)
    assert result.returncode == 0, result.stderr

    # the login owns its same-named schema
    assert _schema_owner(pg, db, "app_user") == "app_user"

    # an unrelated login has neither CONNECT nor TEMP via PUBLIC
    _assert_intruder_locked_out(pg, db)


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_legacy_adopt_existing_database(postgres: PostgresContainer) -> None:
    """L02 — an existing dedicated database is adopted. Its owner and
    data survive, the app login connects, and an unrelated login
    still cannot connect or use TEMP.

    Regression: PUBLIC must lose its privileges on the target
    database whether DAM created it or adopted it -- an adopted
    database is just as dedicated to a single login."""
    pg = postgres
    db = "legacy_adopt_db"
    _create_database(pg, db)
    setup = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE public.existing_data (id int); "
        "INSERT INTO public.existing_data VALUES (1), (2);",
    )
    assert setup.returncode == 0, setup.stderr
    _create_intruder(pg)

    owner_before = _database_owner(pg, db)
    rows_before = pg.query(EXECUTOR, db, "SELECT count(*) FROM public.existing_data")

    _run_script(pg, _render_provision(db, "app_user"))

    assert owner_before == EXECUTOR
    assert _database_owner(pg, db) == owner_before
    assert (
        pg.query(EXECUTOR, db, "SELECT count(*) FROM public.existing_data")
        == rows_before
    )
    assert _table_owner(pg, db, "public", "existing_data") == EXECUTOR

    result = pg.login("app_user", DB_PASSWORD, db)
    assert result.returncode == 0, result.stderr

    _assert_intruder_locked_out(pg, db)


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_legacy_own_schema_lifecycle(postgres: PostgresContainer) -> None:
    """L03, L06, L09 — the login works in its own schema
    without SET ROLE, a repeat run without a configuration change
    changes nothing, and the deprovision -- run twice -- terminates an
    open session of the login and keeps the login-created data under
    admin ownership."""
    pg = postgres
    db = "legacy_lifecycle_db"
    user = "app_user"

    _run_script(pg, _render_provision(db, user, access_list="public|SELECT"))
    owner_before = _database_owner(pg, db)
    assert owner_before == EXECUTOR

    # L03: the login creates, fills and alters a table in its own
    # schema -- no SET ROLE, real password authentication
    result = pg.login(
        user,
        DB_PASSWORD,
        db,
        "CREATE TABLE app_user.app_data (id int, note text); "
        "INSERT INTO app_user.app_data (id, note) VALUES (1, 'one'), (2, 'two'); "
        "ALTER TABLE app_user.app_data ADD COLUMN extra text;",
    )
    assert result.returncode == 0, result.stderr
    assert _schema_owner(pg, db, user) == user
    assert _table_owner(pg, db, user, "app_data") == user
    assert _database_owner(pg, db) == owner_before

    # an admin-owned table for the configured grant
    setup = pg.exec_psql(EXECUTOR, db, "CREATE TABLE public.admin_data (id int);")
    assert setup.returncode == 0, setup.stderr

    # L06: re-run without a configuration change
    _run_script(pg, _render_provision(db, user, access_list="public|SELECT"))
    assert pg.query(EXECUTOR, db, "SELECT count(*) FROM app_user.app_data") == "2"
    assert _schema_owner(pg, db, user) == user
    assert _table_owner(pg, db, user, "app_data") == user
    assert _database_owner(pg, db) == owner_before
    # the configured grant is intact after the repeat run and covers
    # the admin table created since the first run
    result = pg.login(user, DB_PASSWORD, db, "SELECT count(*) FROM public.admin_data;")
    assert result.returncode == 0, result.stderr
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT has_table_privilege('app_user', 'public.admin_data', 'SELECT')",
        )
        == "t"
    )
    # the password still works after the repeat run
    result = pg.login(user, DB_PASSWORD, db)
    assert result.returncode == 0, result.stderr

    # L08: deprovision while the login keeps a REAL session open with
    # an uncommitted insert and a lock on its own table. The trailing
    # newline matters: start_session keeps stdin open, and psql does
    # not execute a statement before its line is complete.
    session = pg.start_session(
        user,
        db,
        "BEGIN; "
        "INSERT INTO app_user.app_data (id, note) VALUES (3, 'open-session'); "
        "LOCK TABLE app_user.app_data; "
        "SELECT pg_sleep(60);\n",
        password=DB_PASSWORD,
    )
    try:
        _wait_for_open_session(pg, db, user)
        _run_script(pg, _render_deprovision(db, user), password=None)
        # the open session was terminated by the deprovision
        session.wait(timeout=30)
    finally:
        if session.poll() is None:
            session.kill()
        session.wait()

    # the login is gone and cannot connect any more
    assert (
        pg.query(
            EXECUTOR,
            db,
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = 'app_user')",
        )
        == "f"
    )
    denied = pg.login(user, DB_PASSWORD, db)
    assert denied.returncode != 0, "the removed login can still connect"
    assert user in denied.stderr, denied.stderr

    # the login-created table, its schema and its committed data
    # survive under admin ownership; the open session's uncommitted
    # insert is gone with the session
    assert _table_owner(pg, db, user, "app_data") == EXECUTOR
    assert _schema_owner(pg, db, user) == EXECUTOR
    assert pg.query(EXECUTOR, db, "SELECT count(*) FROM app_user.app_data") == "2"
    assert _database_owner(pg, db) == owner_before

    # L09: repeating the removal is a successful no-op
    repeat = _run_script(pg, _render_deprovision(db, user), password=None)
    assert "nothing to deprovision" in repeat.stdout, repeat.stdout
    assert pg.query(EXECUTOR, db, "SELECT count(*) FROM app_user.app_data") == "2"
    assert _table_owner(pg, db, user, "app_data") == EXECUTOR
    assert _database_owner(pg, db) == owner_before


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_legacy_configured_table_grants_only(postgres: PostgresContainer) -> None:
    """L04 — the login gets exactly the configured table grants on the
    admin-owned table -- reading and inserting work, an ungranted
    UPDATE fails with a table privilege error."""
    pg = postgres
    db = "legacy_table_grants_db"
    _create_database(pg, db)
    setup = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE public.managed (id int, note text); "
        "INSERT INTO public.managed VALUES (1, 'one');",
    )
    assert setup.returncode == 0, setup.stderr

    _run_script(
        pg, _render_provision(db, "app_user", access_list="public|SELECT,INSERT")
    )

    # the configured grants work with password authentication (the
    # public schema keeps USAGE for PUBLIC on every version)
    result = pg.login(
        "app_user", DB_PASSWORD, db, "SELECT count(*) FROM public.managed;"
    )
    assert result.returncode == 0, result.stderr
    result = pg.login(
        "app_user", DB_PASSWORD, db, "INSERT INTO public.managed VALUES (2, 'two');"
    )
    assert result.returncode == 0, result.stderr

    # UPDATE was not granted: a table privilege error
    result = pg.login(
        "app_user", DB_PASSWORD, db, "UPDATE public.managed SET note = 'x';"
    )
    assert result.returncode != 0, "UPDATE succeeded although it was not granted"
    assert "permission denied for table managed" in result.stderr, result.stderr

    # the admin-owned table does not change owner
    assert _table_owner(pg, db, "public", "managed") == EXECUTOR


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_legacy_grant_changes_via_renderer(postgres: PostgresContainer) -> None:
    """L05 — grant changes converge through the production renderer,
    so the revoke delta comes from ``_revoke_list``."""
    pg = postgres
    db = "legacy_renderer_db"
    user = "grant_user"
    _create_database(pg, db)
    setup = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE public.managed (id int); "
        "INSERT INTO public.managed VALUES (1), (2); "
        # a second schema for the removal step below
        "CREATE SCHEMA extra; "
        "CREATE TABLE extra.extra_data (id int); "
        "INSERT INTO extra.extra_data VALUES (7);",
    )
    assert setup.returncode == 0, setup.stderr

    # initial configuration: ALL on public
    all_grants = make_db_access(
        database=db, username=user, access=[("public", ("ALL",))]
    )
    _run_script(pg, build_script(all_grants))
    result = pg.login(user, DB_PASSWORD, db, "INSERT INTO public.managed VALUES (3);")
    assert result.returncode == 0, result.stderr
    result = pg.login(user, DB_PASSWORD, db, "UPDATE public.managed SET id = id;")
    assert result.returncode == 0, result.stderr

    # ALL -> SELECT: the production revoke delta must clear the whole
    # schema before the configured grant is applied
    select_only = make_db_access(
        database=db, username=user, access=[("public", ("SELECT",))]
    )
    _run_script(pg, build_script(select_only, all_grants))
    result = pg.login(user, DB_PASSWORD, db, "SELECT count(*) FROM public.managed;")
    assert result.returncode == 0, result.stderr
    # the lost privileges are REALLY gone for the login, with the
    # specific table privilege error (not just in the catalog)
    result = pg.login(user, DB_PASSWORD, db, "INSERT INTO public.managed VALUES (4);")
    assert result.returncode != 0, "INSERT survived the ALL -> SELECT change"
    assert "permission denied for table managed" in result.stderr, result.stderr
    result = pg.login(user, DB_PASSWORD, db, "UPDATE public.managed SET id = id;")
    assert result.returncode != 0, "UPDATE survived the ALL -> SELECT change"
    assert "permission denied for table managed" in result.stderr, result.stderr
    assert (
        pg.query(
            EXECUTOR,
            db,
            f"SELECT has_table_privilege('{user}', 'public.managed', 'UPDATE')",
        )
        == "f"
    ), "ALL left a leftover configured table privilege behind"

    # a newly configured grant becomes usable
    select_insert = make_db_access(
        database=db, username=user, access=[("public", ("SELECT", "INSERT"))]
    )
    _run_script(pg, build_script(select_insert, select_only))
    result = pg.login(user, DB_PASSWORD, db, "INSERT INTO public.managed VALUES (4);")
    assert result.returncode == 0, result.stderr

    # a schema REMOVED from the access list loses its grants: the
    # production revoke delta covers existing schemas too. The schema
    # USAGE is a test-setup prerequisite (legacy mode grants table
    # privileges only), kept through the removal so the assertion
    # fails on the TABLE privilege, not on the schema.
    setup = pg.exec_psql(EXECUTOR, db, f"GRANT USAGE ON SCHEMA extra TO {user};")
    assert setup.returncode == 0, setup.stderr
    with_extra = make_db_access(
        database=db,
        username=user,
        access=[("public", ("SELECT",)), ("extra", ("SELECT",))],
    )
    _run_script(pg, build_script(with_extra, select_insert))
    result = pg.login(user, DB_PASSWORD, db, "SELECT count(*) FROM extra.extra_data;")
    assert result.returncode == 0, result.stderr
    without_extra = make_db_access(
        database=db, username=user, access=[("public", ("SELECT",))]
    )
    script = build_script(without_extra, with_extra)
    assert "extra|ALL" in script, script
    _run_script(pg, script)
    result = pg.login(user, DB_PASSWORD, db, "SELECT count(*) FROM extra.extra_data;")
    assert result.returncode != 0, "SELECT on the removed schema survived"
    assert "permission denied for table extra_data" in result.stderr, result.stderr
    # the remaining configured grant still works after the removal
    result = pg.login(user, DB_PASSWORD, db, "SELECT count(*) FROM public.managed;")
    assert result.returncode == 0, result.stderr

    # a managed schema that no longer exists must not block the run:
    # the previous state claims gone_schema was managed, the database
    # disagrees (the revoke template guards with EXISTS)
    vanished_schema_state = make_db_access(
        database=db,
        username=user,
        access=[("gone_schema", ("SELECT",)), ("public", ("SELECT", "INSERT"))],
    )
    script = build_script(select_only, vanished_schema_state)
    assert "gone_schema|ALL" in script, script
    _run_script(pg, script)
    result = pg.login(user, DB_PASSWORD, db, "SELECT count(*) FROM public.managed;")
    assert result.returncode == 0, result.stderr
    result = pg.login(user, DB_PASSWORD, db, "INSERT INTO public.managed VALUES (5);")
    assert result.returncode != 0, "the removed INSERT grant survived"
    assert "permission denied for table managed" in result.stderr, result.stderr


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_legacy_password_rotation_on_config_change(
    postgres: PostgresContainer,
    dam_harness_factory: Callable[..., DamJobHarness],
) -> None:
    """L07 — L07a: a configuration change publishes a new password; the new
    credential works, the previous one is rejected."""
    pg = postgres
    harness = dam_harness_factory(pg)
    db = "legacy_rotate_db"

    initial = make_db_access(
        database="legacy_rotate_db",
        username="rot_user",
        access=[("public", ("SELECT",))],
    )
    harness.run(initial)
    first = harness.last_published_credential()
    result = pg.login(first.user, first.password, db)
    assert result.returncode == 0, result.stderr

    changed = make_db_access(
        database=db,
        username="rot_user",
        access=[("public", ("SELECT", "INSERT"))],
    )
    harness.run(changed)
    rotated = harness.last_published_credential()
    assert rotated.password != first.password

    result = pg.login(rotated.user, rotated.password, db)
    assert result.returncode == 0, result.stderr
    old = pg.login(first.user, first.password, db)
    assert old.returncode != 0, "the previous password still works after rotation"
    assert "password authentication failed" in old.stderr, old.stderr


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", ["16"], indirect=True)
def test_legacy_failed_provision_keeps_old_password(
    postgres: PostgresContainer,
    dam_harness_factory: Callable[..., DamJobHarness],
) -> None:
    """L08 — L07b: a provisioning failure inside the transaction (a grant
    on a nonexistent schema) rolls the password change back -- the
    old password keeps working and no new secret is published."""
    pg = postgres
    harness = dam_harness_factory(pg)
    db = "legacy_fail_db"

    initial = make_db_access(
        database=db, username="fail_user", access=[("public", ("SELECT",))]
    )
    harness.run(initial)
    published = harness.last_published_credential()
    result = pg.login(published.user, published.password, db)
    assert result.returncode == 0, result.stderr

    broken = make_db_access(
        database=db, username="fail_user", access=[("missing_schema", ("SELECT",))]
    )
    with pytest.raises(JobFailedError):
        harness.run(broken)

    # no new secret was published
    assert len(harness.vault_writes) == 1
    assert harness.last_published_credential().password == published.password

    # the old password still works: the transaction rolled back
    result = pg.login(published.user, published.password, db)
    assert result.returncode == 0, (
        "the old password stopped working after the failed provisioning"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_legacy_password_auth_enforced(postgres: PostgresContainer) -> None:
    """L10 — The mounted pg_hba.conf enforces scram-sha-256 for every role
    except the fixture roles: an app login only connects with its
    real password."""
    pg = postgres
    result = pg.exec_psql(
        "postgres",
        "postgres",
        "CREATE ROLE legacy_pw_user LOGIN PASSWORD 'Secret123';",
    )
    assert result.returncode == 0, result.stderr

    # the correct password connects
    result = pg.login("legacy_pw_user", "Secret123", "postgres")
    assert result.returncode == 0, result.stderr

    # a wrong password is rejected as an authentication failure
    result = pg.login("legacy_pw_user", "wrong-password", "postgres")
    assert result.returncode != 0
    assert "password authentication failed" in result.stderr, result.stderr

    # no password at all is rejected too
    result = pg.exec_psql("legacy_pw_user", "postgres", "SELECT 1;")
    assert result.returncode != 0

    # the fixture roles keep trust authentication
    result = pg.exec_psql(EXECUTOR, "postgres", "SELECT 1;")
    assert result.returncode == 0, result.stderr


REVOKE_RB_PASSWORD = "RbPubPw1"  # notsecret


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_legacy_deprovision_missing_login_nonempty_access(
    postgres: PostgresContainer,
) -> None:
    """L12 — Deprovisioning an absent login is a no-op even with a
    NONEMPTY access list.

    The L09 repeat removal and the render helper's default exercise
    the missing-login guard only with an empty access list. The guard
    must run BEFORE the revoke block: with a nonempty access list the
    revoke block would construct a ``REVOKE ALL ... FROM ghost_user``
    for the absent login (a "role does not exist" error), so a
    successful no-op proves the guard's position and not merely the
    guard's existence.
    """
    pg = postgres
    db = "legacy_missing_login_db"
    _create_database(pg, db)

    # an admin-owned table in the schema the access list names: had
    # the revoke block run, it would have errored on the absent login
    # -- after the no-op the table keeps its owner and data
    setup = pg.exec_psql(
        EXECUTOR,
        db,
        "CREATE TABLE public.kept (id int); INSERT INTO public.kept VALUES (1);",
    )
    assert setup.returncode == 0, setup.stderr

    result = _run_script(
        pg,
        _render_deprovision(db, "ghost_user", access_list="public|SELECT,INSERT"),
        password=None,
    )

    # the guard produced the no-op message and nothing behind it ran
    assert "nothing to deprovision" in result.stdout, result.stdout
    assert (
        pg.query(
            EXECUTOR,
            "postgres",
            "SELECT count(*) FROM pg_roles WHERE rolname = 'ghost_user'",
        )
        == "0"
    )
    assert _table_owner(pg, db, "public", "kept") == EXECUTOR
    assert pg.query(EXECUTOR, db, "SELECT count(*) FROM public.kept") == "1"


@pytest.mark.e2e
@pytest.mark.parametrize("postgres", PG_VERSIONS, indirect=True)
def test_legacy_revoke_public_rolls_back_with_failed_run(
    postgres: PostgresContainer,
) -> None:
    """L11 — A failed provisioning run must not lock an adopted
    database's PUBLIC-connecting logins out.

    The unconditional ``REVOKE ALL ON DATABASE ... FROM public`` used
    to run BEFORE the transaction: when a later statement inside the
    transaction failed, the direct ``GRANT CONNECT`` for the entry's
    login rolled back while the PUBLIC revoke persisted -- an existing
    login that connected via PUBLIC lost access to the database
    because a run FAILED. The revoke belongs INSIDE the transaction
    (REVOKE ON DATABASE is transactional, unlike CREATE DATABASE and
    ALTER DATABASE OWNER): a failed run leaves the database's ACL
    exactly as it was, and a successful run still revokes PUBLIC (the
    L01/L02 guarantee).
    """
    pg = postgres
    db = "legacy_revoke_rb_db"
    _create_database(pg, db)

    # an existing login whose CONNECT comes from PUBLIC alone (no
    # direct grant on the adopted database)
    result = pg.exec_psql(
        "postgres",
        "postgres",
        f"CREATE ROLE rb_pub_app LOGIN PASSWORD '{REVOKE_RB_PASSWORD}';",
    )
    assert result.returncode == 0, result.stderr
    result = pg.login("rb_pub_app", REVOKE_RB_PASSWORD, db)
    assert result.returncode == 0, result.stderr

    # a provisioning run that fails INSIDE the transaction: the access
    # list names a schema that does not exist
    broken = make_db_access(
        database=db, username="rb_user", access=[("missing_schema", ("SELECT",))]
    )
    failed = pg.exec_psql(
        EXECUTOR,
        "postgres",
        build_script(broken),
        extra_args=["-v", f"db_user_password={DB_PASSWORD}"],
    )
    assert failed.returncode != 0, "the broken provisioning run succeeded"
    assert "missing_schema" in failed.stderr, failed.stderr

    # the login that connected via PUBLIC keeps connecting: the PUBLIC
    # revoke rolled back with the failed transaction (regression: the
    # pre-transaction revoke persisted and locked the login out)
    result = pg.login("rb_pub_app", REVOKE_RB_PASSWORD, db)
    assert result.returncode == 0, (
        "the failed run locked a PUBLIC-connecting login out of the "
        f"adopted database: {result.stderr}"
    )

    # a later SUCCESSFUL run of the same entry still revokes PUBLIC:
    # the PUBLIC-connecting login is locked out by THAT run, and the
    # entry's own login connects with its direct grant
    fixed = make_db_access(
        database=db, username="rb_user", access=[("public", ("SELECT",))]
    )
    _run_script(pg, build_script(fixed, broken))
    result = pg.login("rb_pub_app", REVOKE_RB_PASSWORD, db)
    assert result.returncode != 0, "PUBLIC kept CONNECT after a successful run"
    assert "permission denied" in result.stderr, result.stderr
    result = pg.login("rb_user", DB_PASSWORD, db)
    assert result.returncode == 0, result.stderr
