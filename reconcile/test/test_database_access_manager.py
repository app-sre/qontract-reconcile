from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import ANY, MagicMock

import pytest

from reconcile.database_access_manager.integration import (
    DatabaseAccessManagerIntegration,
    DatabaseConnectionParameters,
    DBAMIntegrationParams,
    JobFailedError,
    _access_list,
    _build_script,
    _configuration_digest,
    _ensure_pull_secret,
    _generated_username,
    _merge_pending_config,
    _process_db_access,
    _render_sql,
    _resolve_username,
    _revoke_list,
    _schemas_csv,
    _script_configuration_digest,
    _validate_db_access,
    _validate_role_sharing,
)
from reconcile.database_access_manager.jobs import DatabaseAccessJob
from reconcile.gql_definitions.terraform_resources.database_access_manager import (
    DatabaseAccessAccessV1,
    DatabaseAccessV1,
    NamespaceV1,
)
from reconcile.utils.jobcontroller.models import JobStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture


STATE_KEY = "test-provisioner/test-db/test"
ADMIN_SECRET_NAME = "db-secret"
JOB_IMAGE = "quay.io/app-sre/yet-another-debug-container:latest"


@pytest.fixture
def db_access(gql_class_factory: Callable[..., DatabaseAccessV1]) -> DatabaseAccessV1:
    return gql_class_factory(
        DatabaseAccessV1,
        {
            "username": "test",
            "name": "test",
            "database": "test",
        },
    )


@pytest.fixture
def db_access_access(
    gql_class_factory: Callable[..., DatabaseAccessAccessV1],
) -> DatabaseAccessAccessV1:
    return gql_class_factory(
        DatabaseAccessAccessV1,
        {
            "grants": ["INSERT", "SELECT"],
            "target": {
                "dbschema": "foo",
            },
        },
    )


@pytest.fixture
def db_access_role(
    gql_class_factory: Callable[..., DatabaseAccessV1],
    db_access_access: DatabaseAccessAccessV1,
) -> DatabaseAccessV1:
    return gql_class_factory(
        DatabaseAccessV1,
        {
            "name": "test",
            "database": "postgres",
            "role": "cs_owner",
            "access": [db_access_access.model_dump(by_alias=True)],
        },
    )


@pytest.fixture
def db_access_namespace(gql_class_factory: Callable[..., NamespaceV1]) -> NamespaceV1:
    return gql_class_factory(
        NamespaceV1,
        {
            "name": "test-namespace",
            "cluster": {
                "name": "test-cluster",
            },
        },
    )


@pytest.fixture
def dbam_state() -> MagicMock:
    state = MagicMock()
    state.exists.return_value = False
    return state


@pytest.fixture
def vault_mock() -> MagicMock:
    return MagicMock()


@pytest.fixture
def secret_reader() -> MagicMock:
    reader = MagicMock()
    reader.read_all.return_value = {}
    return reader


def _render(template: str, **params: str) -> str:
    defaults = {
        "database": "test",
        "database_literal": "test",
        "username": "test",
        "username_literal": "test",
        "username_ident_literal": "test",
        "admin_user": "admin",
        "role": "cs_owner",
        "role_literal": "cs_owner",
        "schemas_csv": "",
        "access_list": "",
        "revoke_list": "",
    }
    defaults.update(params)
    return _render_sql(template, **defaults)


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


ADMIN_SECRET = {
    "data": {
        "db.host": _b64("localhost"),
        "db.port": _b64("5432"),
        "db.user": _b64("admin"),
        "db.password": _b64("adminpw"),  # notsecret
        "db.name": _b64("postgres"),
    }
}


@pytest.fixture
def oc() -> MagicMock:
    oc = MagicMock()

    def oc_get(
        namespace: str, kind: str, name: str, allow_not_found: bool = True
    ) -> dict | None:
        if name == ADMIN_SECRET_NAME:
            return ADMIN_SECRET
        return None

    oc.get.side_effect = oc_get
    return oc


@pytest.fixture
def dbam_controller(mocker: MockerFixture) -> MagicMock:
    controller = MagicMock()
    controller.get_job_status.return_value = JobStatus.SUCCESS
    mocker.patch(
        "reconcile.database_access_manager.integration.K8sJobController",
        return_value=controller,
    )
    return controller


@pytest.fixture
def oc_map(mocker: MockerFixture, oc: MagicMock) -> MagicMock:
    oc_map = MagicMock()
    oc_map.get_cluster.return_value = oc
    oc_map.__enter__.return_value = oc_map
    mocker.patch(
        "reconcile.database_access_manager.integration.OC_Map",
        return_value=oc_map,
    )
    return oc_map


def run_process(
    db_access: DatabaseAccessV1,
    state: MagicMock,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    namespace: NamespaceV1,
    dry_run: bool = False,
) -> None:
    _process_db_access(
        dry_run,
        state,
        STATE_KEY,
        db_access,
        namespace,
        ADMIN_SECRET_NAME,
        "postgres",
        secret_reader,
        "vault-out",
        vault_mock,
        JOB_IMAGE,
        None,
        None,
    )


def enqueued_job(controller: MagicMock) -> DatabaseAccessJob:
    return controller.enqueue_job.call_args[0][0]


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_validate_db_access_requires_username_without_role(
    db_access: DatabaseAccessV1,
) -> None:
    db_access.username = None
    with pytest.raises(ValueError, match="Username is required"):
        _validate_db_access(db_access)


def test_validate_db_access_role_mode_allows_missing_username(
    db_access_role: DatabaseAccessV1,
) -> None:
    _validate_db_access(db_access_role)


def test_validate_db_access_rejects_duplicate_schemas(
    db_access: DatabaseAccessV1,
    db_access_access: DatabaseAccessAccessV1,
) -> None:
    db_access.access = [db_access_access, db_access_access]
    with pytest.raises(ValueError, match="Duplicate schema"):
        _validate_db_access(db_access)


def test_validate_role_sharing_rejects_divergent_databases(
    db_access_role: DatabaseAccessV1,
    gql_class_factory: Callable[..., DatabaseAccessV1],
) -> None:
    other = gql_class_factory(
        DatabaseAccessV1,
        db_access_role.model_dump(by_alias=True)
        | {"name": "test-2", "database": "other"},
    )
    with pytest.raises(ValueError, match="different databases"):
        _validate_role_sharing([(db_access_role, "u1"), (other, "u2")])


def test_validate_role_sharing_rejects_divergent_access(
    db_access_role: DatabaseAccessV1,
    gql_class_factory: Callable[..., DatabaseAccessV1],
) -> None:
    divergent = gql_class_factory(
        DatabaseAccessV1,
        {
            "name": "test-2",
            "database": "postgres",
            "role": db_access_role.role,
            "access": [
                {
                    "grants": ["ALL"],
                    "target": {"dbschema": "foo"},
                }
            ],
        },
    )
    with pytest.raises(ValueError, match="different access"):
        _validate_role_sharing([(db_access_role, "u1"), (divergent, "u2")])


def test_validate_role_sharing_allows_rotation_entries(
    db_access_role: DatabaseAccessV1,
    gql_class_factory: Callable[..., DatabaseAccessV1],
) -> None:
    rotation = gql_class_factory(
        DatabaseAccessV1,
        db_access_role.model_dump(by_alias=True)
        | {"name": "test-2", "username": None, "delete": True},
    )
    # name, username and delete differ - that is the rotation flow -
    # database and access list are equivalent
    _validate_role_sharing([(db_access_role, "u1"), (rotation, "u2")])


def test_validate_role_sharing_ignores_access_order(
    db_access_role: DatabaseAccessV1,
    gql_class_factory: Callable[..., DatabaseAccessV1],
) -> None:
    reordered = gql_class_factory(
        DatabaseAccessV1,
        db_access_role.model_dump(by_alias=True)
        | {
            "name": "test-2",
            "access": [
                {
                    "grants": ["SELECT", "INSERT"],
                    "target": {"dbschema": "foo"},
                }
            ],
        },
    )
    _validate_role_sharing([(db_access_role, "u1"), (reordered, "u2")])


def test_generated_username() -> None:
    username = _generated_username("cs_owner", STATE_KEY)
    assert username.startswith("cs_owner_")
    assert len(username) <= 63
    assert re.fullmatch(r"[a-z_][a-z0-9_]*", username)
    # deterministic
    assert username == _generated_username("cs_owner", STATE_KEY)
    # different per entry (rotation)
    assert username != _generated_username("cs_owner", "other/key")


def test_generated_username_truncates_long_roles() -> None:
    role = "a" * 100
    username = _generated_username(role, STATE_KEY)
    assert len(username) <= 63


# ---------------------------------------------------------------------------
# list helpers
# ---------------------------------------------------------------------------


def test_access_list_and_schemas(
    db_access_role: DatabaseAccessV1, db_access_access: DatabaseAccessAccessV1
) -> None:
    db_access_role.access = [
        db_access_access,
        gql_class_factory_access("bar", ["SELECT"]),
    ]
    assert _access_list(db_access_role) == "foo|INSERT,SELECT;bar|SELECT"
    assert _schemas_csv(db_access_role) == "foo,bar"


def gql_class_factory_access(
    dbschema: str, grants: list[str]
) -> DatabaseAccessAccessV1:
    return DatabaseAccessAccessV1(
        grants=grants,
        target=gql_class_factory_target(dbschema),
    )


def gql_class_factory_target(dbschema: str) -> object:
    from reconcile.gql_definitions.terraform_resources.database_access_manager import (
        DatabaseAccessAccessGranteeV1,
    )

    return DatabaseAccessAccessGranteeV1(dbschema=dbschema)


@pytest.mark.parametrize(
    ("current_grants", "desired_grants", "expected"),
    [
        (None, ["SELECT"], ""),
        (["SELECT"], ["SELECT"], ""),
        (["SELECT", "INSERT"], ["SELECT"], "foo|INSERT"),
        (["SELECT"], ["SELECT", "INSERT"], ""),
        (["SELECT"], None, "foo|ALL"),
        (["ALL"], ["SELECT"], "foo|ALL"),
        (["ALL"], ["ALL"], ""),
        (["SELECT"], ["ALL"], ""),
    ],
)
def test_revoke_list(
    db_access: DatabaseAccessV1,
    gql_class_factory: Callable[..., DatabaseAccessV1],
    current_grants: list[str] | None,
    desired_grants: list[str] | None,
    expected: str,
) -> None:
    current = None
    if current_grants is not None:
        current = gql_class_factory(
            DatabaseAccessV1,
            {
                "username": "test",
                "name": "test",
                "database": "test",
                "access": [{"grants": current_grants, "target": {"dbschema": "foo"}}],
            },
        )
    # desired_grants None means the schema is no longer configured
    desired_access = (
        []
        if desired_grants is None
        else [{"grants": desired_grants, "target": {"dbschema": "foo"}}]
    )
    desired = gql_class_factory(
        DatabaseAccessV1,
        {
            "username": "test",
            "name": "test",
            "database": "test",
            "access": desired_access,
        },
    )
    assert _revoke_list(current, desired) == expected


# ---------------------------------------------------------------------------
# script rendering
# ---------------------------------------------------------------------------


def test_render_legacy_provision(db_access: DatabaseAccessV1) -> None:
    script = _render(
        "legacy_provision.sql",
        database="test",
        username="test",
        admin_user="admin",
        access_list="foo|SELECT,INSERT",
        revoke_list="",
    )
    assert 'CREATE DATABASE "test"' in script
    assert 'CREATE ROLE "test"' in script
    assert "PASSWORD :'db_user_password'" in script
    assert 'CREATE SCHEMA IF NOT EXISTS "test"' in script
    assert 'GRANT "test" to "admin";' in script
    assert "string_to_array('foo|SELECT,INSERT', ';')" in script


def test_render_role_provision() -> None:
    script = _render(
        "role_provision.sql",
        database="postgres",
        username="cs_app",
        admin_user="admin",
        role="cs_owner",
        schemas_csv="public",
        access_list="public|ALL",
        revoke_list="",
    )
    assert 'CREATE ROLE "cs_owner" NOLOGIN' in script
    assert "PASSWORD :'db_user_password'" in script
    assert "ALTER ROLE %I IN DATABASE %I SET role = %I" in script
    assert "pg_has_role(current_user, role_name, 'USAGE')" in script
    assert "ALTER STATISTICS %I.%I OWNER TO %I" in script
    assert "string_to_array('public|ALL', ';')" in script
    # the owner role is never dropped
    assert "DROP ROLE" not in script


def test_render_role_provision_verifies_schema_usage() -> None:
    script = _render(
        "role_provision.sql",
        database="postgres",
        username="cs_app",
        admin_user="admin",
        role="cs_owner",
        schemas_csv="foreign",
        access_list="foreign|SELECT",
        revoke_list="",
    )
    # a USAGE grant without grant option only warns and grants nothing:
    # the script must fail the transaction instead of committing an
    # inaccessible schema
    assert "has_schema_privilege(role_name, s, 'USAGE')" in script
    assert "RAISE EXCEPTION 'owner role % has no USAGE on schema %'" in script


def test_render_role_provision_empty_access() -> None:
    script = _render(
        "role_provision.sql",
        database="test",
        username="cs_app",
        admin_user="admin",
        role="cs_owner",
        schemas_csv="",
        access_list="",
        revoke_list="",
    )
    # no schema loops blow up on empty lists
    assert "string_to_array('', ',')" in script
    assert "string_to_array('', ';')" in script


def test_render_role_provision_grants_schema_usage() -> None:
    script = _render(
        "role_provision.sql",
        database="postgres",
        username="cs_app",
        admin_user="admin",
        role="cs_owner",
        schemas_csv="other",
        access_list="other|SELECT",
        revoke_list="foo|ALL",
    )
    # schemas owned by other roles need USAGE for the owner role to
    # reference objects in them, object grants alone are not enough
    assert "GRANT USAGE ON SCHEMA %I" in script
    assert "REVOKE USAGE ON SCHEMA %I" in script


def test_render_role_deprovision() -> None:
    script = _render(
        "role_deprovision.sql",
        database="test",
        username="cs_app",
        admin_user="admin",
    )
    assert 'REASSIGN OWNED BY "cs_app" TO "admin";' in script
    assert 'DROP OWNED BY "cs_app";' in script
    assert 'DROP ROLE IF EXISTS "cs_app"' in script
    # the shared owner role is never dropped
    assert "cs_owner" not in script


def test_render_legacy_deprovision() -> None:
    script = _render(
        "legacy_deprovision.sql",
        database="test",
        username="test",
        admin_user="admin",
        access_list="foo|SELECT",
    )
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I FROM %I" in script
    assert 'DROP ROLE IF EXISTS "test"' in script


# ---------------------------------------------------------------------------
# job model
# ---------------------------------------------------------------------------


def make_job(state_key: str = STATE_KEY) -> DatabaseAccessJob:
    return DatabaseAccessJob(
        state_key=state_key,
        job_image=JOB_IMAGE,
        script="\\set ON_ERROR_STOP on",
        admin_secret_name=ADMIN_SECRET_NAME,
        user_connection=DatabaseConnectionParameters(
            host="localhost",
            port="5432",
            user="test",
            password="testpw",  # notsecret
            database="test",
        ),
    )


def test_job_name_compliance() -> None:
    job = make_job("app-sre-clusters/service-integration-v4-clusters/service-db-access")
    assert len(job.name()) <= 63
    assert re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", job.name())
    assert job.name().startswith("dbam-")


def test_job_secret_data_and_scripts() -> None:
    job = make_job()
    assert set(job.secret_data()) == {
        "db.host",
        "db.port",
        "db.user",
        "db.password",
        "db.name",
    }
    assert set(job.scripts()) == {"script.sql"}


def test_job_spec() -> None:
    job = make_job()
    spec = job.job_spec()
    assert spec.template.spec is not None
    pod_spec = spec.template.spec
    assert pod_spec.automount_service_account_token is False
    assert spec.backoff_limit == 1
    assert spec.ttl_seconds_after_finished is not None
    assert pod_spec.containers
    container = pod_spec.containers[0]
    assert container.command == ["/usr/bin/psql"]
    assert container.args is not None
    assert "--file=/scripts/script.sql" in container.args
    # the user password comes from the job-bound secret
    assert container.env is not None
    user_pw_env = [e for e in container.env if e.name == "db_user_password"]
    assert len(user_pw_env) == 1
    assert user_pw_env[0].value_from is not None
    assert user_pw_env[0].value_from.secret_key_ref is not None
    assert user_pw_env[0].value_from.secret_key_ref.name == job.name()
    assert user_pw_env[0].value_from.secret_key_ref.key == "db.password"


# ---------------------------------------------------------------------------
# integration flow
# ---------------------------------------------------------------------------


def test_process_state_exists_matched(
    db_access: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc_map: MagicMock,
) -> None:
    dbam_state.exists.side_effect = lambda key: key == STATE_KEY
    dbam_state.get.return_value = db_access.model_dump(by_alias=True)
    run_process(db_access, dbam_state, secret_reader, vault_mock, db_access_namespace)
    dbam_state.add.assert_not_called()
    dbam_controller.enqueue_job.assert_not_called()
    vault_mock.write.assert_not_called()


def test_process_legacy_provisions_job(
    db_access: DatabaseAccessV1,
    db_access_access: DatabaseAccessAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    oc_map: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
) -> None:
    db_access.access = [db_access_access]
    run_process(db_access, dbam_state, secret_reader, vault_mock, db_access_namespace)

    dbam_controller.enqueue_job.assert_called_once()
    job = enqueued_job(dbam_controller)
    assert 'CREATE ROLE "test"' in job.script
    assert job.user_connection.user == "test"
    assert job.user_connection.database == "test"

    vault_mock.write.assert_called_once()
    secret = vault_mock.write.call_args[0][0]
    assert secret["path"] == f"vault-out/database-access-manager/{STATE_KEY}"
    # pending marker (before the enqueue) and settled state (after)
    assert dbam_state.add.call_count == 2
    added_keys = [call.args[0] for call in dbam_state.add.call_args_list]
    assert added_keys == [f"{STATE_KEY}#pending", STATE_KEY]


def test_process_role_mode_generates_username(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
) -> None:
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )

    job = enqueued_job(dbam_controller)
    assert job.user_connection.user.startswith("cs_owner_")
    assert 'CREATE ROLE "cs_owner" NOLOGIN' in job.script
    # postgres as database is allowed in role mode
    assert job.user_connection.database == "postgres"


def test_process_postgres_db_without_role_raises(
    db_access: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    oc_map: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
) -> None:
    db_access.database = "postgres"
    with pytest.raises(ValueError, match="Can not use default database"):
        run_process(
            db_access, dbam_state, secret_reader, vault_mock, db_access_namespace
        )


def test_process_role_mode_reuses_vault_password(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
) -> None:
    secret_reader.read_all.return_value = {
        "db.host": "localhost",
        "db.port": "5432",
        "db.user": "cs_owner_abc",
        "db.password": "vaultpw",  # notsecret
        "db.name": "postgres",
    }
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )

    job = enqueued_job(dbam_controller)
    assert job.user_connection.password == "vaultpw"
    assert job.user_connection.user == "cs_owner_abc"


def test_process_role_mode_legacy_state_migrates(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
) -> None:
    # state written by the legacy implementation: no 'role' key
    dbam_state.exists.return_value = True
    dbam_state.get.return_value = {
        "username": "cs_app",
        "name": "test",
        "database": "postgres",
        "delete": False,
        "access": [],
    }
    # existing user with a vault secret keeps user and password
    db_access_role.username = "cs_app"
    secret_reader.read_all.return_value = {
        "db.host": "localhost",
        "db.port": "5432",
        "db.user": "cs_app",
        "db.password": "oldpw",  # notsecret
        "db.name": "postgres",
    }
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )

    job = enqueued_job(dbam_controller)
    assert job.user_connection.user == "cs_app"
    assert job.user_connection.password == "oldpw"
    assert "\\set ON_ERROR_STOP on" in job.script
    assert 'CREATE ROLE "cs_owner" NOLOGIN' in job.script


def test_process_pending_job_reuses_password(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc: MagicMock,
) -> None:
    pending_secret = {
        "data": {
            "db.host": _b64("localhost"),
            "db.port": _b64("5432"),
            "db.user": _b64("cs_owner_abc"),
            "db.password": _b64("pendingpw"),  # notsecret
            "db.name": _b64("postgres"),
        }
    }
    dbam_controller.get_job_status.return_value = JobStatus.IN_PROGRESS

    def oc_get(
        namespace: str, kind: str, name: str, allow_not_found: bool = True
    ) -> dict | None:
        if name == ADMIN_SECRET_NAME:
            return ADMIN_SECRET
        if name.startswith("dbam-"):
            return pending_secret
        return None

    oc.get.side_effect = oc_get
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )
    # job is running: no new job is enqueued, state is not updated
    dbam_controller.enqueue_job.assert_not_called()
    dbam_state.add.assert_not_called()


def test_process_job_error_raises(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
) -> None:
    dbam_controller.get_job_status.return_value = JobStatus.ERROR
    with pytest.raises(JobFailedError, match="failed"):
        run_process(
            db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
        )


@pytest.mark.parametrize("field", ["database", "username", "role"])
def test_process_value_error_immutable(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    field: str,
) -> None:
    dbam_state.exists.return_value = True
    dbam_state.get.return_value = db_access_role.model_dump(by_alias=True)
    if field == "database":
        db_access_role.database = "other"
    elif field == "username":
        db_access_role.username = "cs_app"
    else:
        db_access_role.role = "other_owner"
    with pytest.raises(ValueError, match="cannot be changed"):
        run_process(
            db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
        )


def test_process_dry_run_does_not_enqueue(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
) -> None:
    run_process(
        db_access_role,
        dbam_state,
        secret_reader,
        vault_mock,
        db_access_namespace,
        dry_run=True,
    )
    dbam_controller.enqueue_job.assert_not_called()
    dbam_state.add.assert_not_called()
    vault_mock.write.assert_not_called()


def test_integration_params() -> None:
    integration = DatabaseAccessManagerIntegration(
        DBAMIntegrationParams(
            vault_output_path="foo",
            job_image="quay.io/x",
        )
    )
    assert integration.name == "database-access-manager"


# ---------------------------------------------------------------------------
# review feedback fixes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template",
    [
        "legacy_provision.sql",
        "legacy_deprovision.sql",
        "role_provision.sql",
    ],
)
def test_template_foreach_target_is_scalar(template: str) -> None:
    content = (
        Path(__file__).parent.parent / "database_access_manager" / "sql" / template
    ).read_text()
    # FOREACH without SLICE requires a scalar target
    assert "entry text[];" not in content
    assert "entry text;" in content or "FOREACH" not in content


def test_provision_templates_are_transactional() -> None:
    for template in ["legacy_provision.sql", "role_provision.sql"]:
        content = (
            Path(__file__).parent.parent / "database_access_manager" / "sql" / template
        ).read_text()
        assert "BEGIN;" in content
        assert "COMMIT;" in content


def test_role_template_sets_password_on_every_run() -> None:
    script = _render(
        "role_provision.sql",
        database="test",
        username="cs_app",
        admin_user="admin",
        role="cs_owner",
        schemas_csv="",
        access_list="",
        revoke_list="",
    )
    assert "ALTER ROLE \"cs_app\" WITH LOGIN PASSWORD :'db_user_password'" in script


@pytest.mark.parametrize("template", ["role_deprovision.sql", "legacy_deprovision.sql"])
def test_deprovision_templates_cut_off_sessions(template: str) -> None:
    script = _render(
        template,
        database="test",
        username="cs_app",
        admin_user="admin",
        access_list="",
    )
    assert 'ALTER ROLE "cs_app" NOLOGIN;' in script
    assert "pg_terminate_backend" in script


def test_job_args_do_not_echo_errors() -> None:
    job = make_job()
    spec = job.job_spec()
    assert spec.template.spec is not None
    assert spec.template.spec.containers
    container = spec.template.spec.containers[0]
    assert container.args is not None
    assert "-b" not in container.args


def _job_secret_with_script(script: str) -> dict[str, dict[str, str]]:
    data = {
        "db.host": "localhost",
        "db.port": "5432",
        "db.user": "cs_owner_abc",
        "db.password": "jobpw",  # notsecret
        "db.name": "postgres",
        "script.sql": script,
    }
    return {"data": {k: _b64(v) for k, v in data.items()}}


def _desired_script(db_access_role: DatabaseAccessV1) -> str:
    return _build_script(
        db_access_role,
        None,
        _generated_username("cs_owner", STATE_KEY),
        "admin",
    )


def test_process_stale_job_is_replaced(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc: MagicMock,
) -> None:
    # a finished job from an older configuration must be replaced, even
    # when the state matches the current configuration (e.g. the
    # configuration was reverted while the job was in flight)
    dbam_state.exists.return_value = True
    dbam_state.get.return_value = db_access_role.model_dump(by_alias=True)
    oc.get.side_effect = lambda ns, kind, name, allow_not_found=True: (
        ADMIN_SECRET
        if name == ADMIN_SECRET_NAME
        else _job_secret_with_script("-- old script")
    )
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )
    dbam_controller.enqueue_job.assert_called_once()
    # the replacement revokes everything the stale job may have applied
    assert "foo|ALL" in enqueued_job(dbam_controller).script


def test_process_converged_job_settles(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc: MagicMock,
) -> None:
    # a finished job that ran the current script settles: no re-enqueue
    oc.get.side_effect = lambda ns, kind, name, allow_not_found=True: (
        ADMIN_SECRET
        if name == ADMIN_SECRET_NAME
        else _job_secret_with_script(_desired_script(db_access_role))
    )
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )
    dbam_controller.enqueue_job.assert_not_called()
    vault_mock.write.assert_called_once()
    secret = vault_mock.write.call_args[0][0]
    assert secret["path"] == f"vault-out/database-access-manager/{STATE_KEY}"
    assert secret["data"]["db.password"] == "jobpw"
    assert secret["data"]["db.user"] == "cs_owner_abc"
    dbam_state.add.assert_called_once()


def test_process_incomplete_job_is_repaired(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
) -> None:
    # a job stuck without its job-bound secret is removed so the next
    # reconcile can re-create it
    dbam_controller.get_job_status.return_value = JobStatus.IN_PROGRESS
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )
    dbam_controller.delete_job.assert_called_once()
    dbam_controller.enqueue_job.assert_not_called()


def test_process_failed_job_is_removed_and_raised(
    db_access_role: DatabaseAccessV1,
    oc_map: MagicMock,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
) -> None:
    dbam_controller.get_job_status.return_value = JobStatus.ERROR
    with pytest.raises(JobFailedError, match="failed"):
        run_process(
            db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
        )
    dbam_controller.delete_job.assert_called_once()


def test_pull_secret_uses_dockerconfigjson_type(mocker: MockerFixture) -> None:
    fetch = mocker.patch(
        "reconcile.database_access_manager.integration.orb.fetch_provider_vault_secret"
    )
    mocker.patch("reconcile.database_access_manager.integration.openshift_base.apply")
    result = _ensure_pull_secret(
        False,
        MagicMock(),
        "cluster",
        "namespace",
        MagicMock(),
        "vault-out",
        "vault/path",
        None,
    )
    assert result == "dbam-pull-secret"
    assert fetch.call_args.kwargs["type"] == "kubernetes.io/dockerconfigjson"


# ---------------------------------------------------------------------------
# review feedback round 3
# ---------------------------------------------------------------------------


def test_process_settled_job_publishes_password_with_matching_state(
    db_access_role: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc: MagicMock,
    oc_map: MagicMock,
) -> None:
    # a settled job must publish its credential even when the state
    # already matches: a replacement job may have run with a password
    # that vault does not have yet
    dbam_state.exists.return_value = True
    dbam_state.get.return_value = db_access_role.model_dump(by_alias=True)
    oc.get.side_effect = lambda ns, kind, name, allow_not_found=True: (
        ADMIN_SECRET
        if name == ADMIN_SECRET_NAME
        else _job_secret_with_script(_desired_script(db_access_role))
    )
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )
    dbam_controller.enqueue_job.assert_not_called()
    vault_mock.write.assert_called_once()
    assert vault_mock.write.call_args[0][0]["data"]["db.password"] == "jobpw"
    dbam_state.add.assert_called_once()


def test_configuration_digest_is_stable_across_revoke_deltas(
    db_access_role: DatabaseAccessV1,
    gql_class_factory: Callable[..., DatabaseAccessV1],
) -> None:
    # the rendered revoke delta changes once the desired state has been
    # applied -- the configuration digest must not
    current = gql_class_factory(
        DatabaseAccessV1,
        {
            "name": "test",
            "database": "postgres",
            "role": "cs_owner",
            "access": [{"grants": ["SELECT", "UPDATE"], "target": {"dbschema": "foo"}}],
        },
    )
    fresh = _build_script(db_access_role, None, "cs_app", "admin")
    converged = _build_script(db_access_role, current, "cs_app", "admin")
    assert fresh != converged  # different revoke deltas
    assert _script_configuration_digest(fresh) == _configuration_digest(db_access_role)
    assert _script_configuration_digest(converged) == _configuration_digest(
        db_access_role
    )


def test_script_without_digest_header_is_stale() -> None:
    assert _script_configuration_digest("-- old script") is None


def test_validate_username_must_differ_from_role(
    db_access_role: DatabaseAccessV1,
) -> None:
    db_access_role.username = "cs_owner"
    with pytest.raises(ValueError, match="must differ from the owner role"):
        _validate_db_access(db_access_role)


# ---------------------------------------------------------------------------
# review feedback round 5 (follow-ups on old threads + outside diff)
# ---------------------------------------------------------------------------


def test_revoke_list_includes_stale_only_schemas(
    db_access_role: DatabaseAccessV1,
    gql_class_factory: Callable[..., DatabaseAccessV1],
) -> None:
    # a stale job may have managed schemas that are no longer in the
    # desired configuration: those grants must be revoked too
    stale = gql_class_factory(
        DatabaseAccessV1,
        {
            "name": "test",
            "database": "postgres",
            "role": "cs_owner",
            "access": [{"grants": ["UPDATE"], "target": {"dbschema": "bar"}}],
        },
    )
    result = _revoke_list(None, db_access_role, revoke_all=True, stale_configs=[stale])
    # schemas are sorted for deterministic rendering
    assert result == "bar|ALL;foo|ALL"


def test_process_expired_job_with_pending_marker_re_runs(
    db_access_role: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc_map: MagicMock,
) -> None:
    # a job was enqueued but never observed (TTL expiry or removal
    # after a failure): the pending marker is the only record of what
    # it was going to apply, the entry must re-run with a full revoke
    dbam_state.exists.side_effect = lambda key: key == f"{STATE_KEY}#pending"
    dbam_state.get.return_value = db_access_role.model_dump(by_alias=True)
    dbam_controller.get_job_status.side_effect = [
        JobStatus.NOT_EXISTS,
        JobStatus.IN_PROGRESS,
    ]
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )
    dbam_controller.enqueue_job.assert_called_once()
    job = enqueued_job(dbam_controller)
    assert "foo|ALL" in job.script
    # the pending marker is re-written for the new job
    assert dbam_state.add.call_args_list[0].args[0] == f"{STATE_KEY}#pending"


def test_process_settle_removes_pending_marker(
    db_access_role: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc: MagicMock,
    oc_map: MagicMock,
) -> None:
    dbam_state.exists.side_effect = lambda key: key == f"{STATE_KEY}#pending"
    dbam_state.get.return_value = db_access_role.model_dump(by_alias=True)
    oc.get.side_effect = lambda ns, kind, name, allow_not_found=True: (
        ADMIN_SECRET
        if name == ADMIN_SECRET_NAME
        else _job_secret_with_script(_desired_script(db_access_role))
    )
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )
    dbam_state.rm.assert_called_once_with(f"{STATE_KEY}#pending")


@pytest.mark.parametrize(
    ("status", "match"),
    [
        (JobStatus.ERROR, "would be removed on a real run"),
    ],
)
def test_process_dry_run_does_not_delete_jobs(
    db_access_role: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc_map: MagicMock,
    status: JobStatus,
    match: str,
) -> None:
    dbam_controller.get_job_status.return_value = status
    with pytest.raises(JobFailedError, match=match):
        run_process(
            db_access_role,
            dbam_state,
            secret_reader,
            vault_mock,
            db_access_namespace,
            dry_run=True,
        )
    dbam_controller.delete_job.assert_not_called()


def test_process_dry_run_does_not_delete_incomplete_job(
    db_access_role: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc_map: MagicMock,
) -> None:
    dbam_controller.get_job_status.return_value = JobStatus.IN_PROGRESS
    # no job secret -> incomplete enqueue
    run_process(
        db_access_role,
        dbam_state,
        secret_reader,
        vault_mock,
        db_access_namespace,
        dry_run=True,
    )
    dbam_controller.delete_job.assert_not_called()


def test_role_template_tolerates_concurrent_unique_violation() -> None:
    script = _render("role_provision.sql")
    assert "WHEN duplicate_object OR unique_violation THEN" in script


def test_deprovision_templates_wait_for_session_exit() -> None:
    for template in ["role_deprovision.sql", "legacy_deprovision.sql"]:
        script = _render(template)
        assert "did not terminate in time" in script
        assert "PERFORM pg_sleep(0.5)" in script


def test_build_script_escapes_username_in_literals(
    db_access: DatabaseAccessV1,
    db_access_access: DatabaseAccessAccessV1,
) -> None:
    # bypasses schema validation on purpose: the escaping must hold
    # even for usernames the schema does not admit today
    db_access.username = "o'brien"
    db_access.access = [db_access_access]
    script = _build_script(db_access, None, "o'brien", "admin")
    # single quoted literals carry the literal-escaped name
    assert "o''brien" in script
    # identifiers inside outer string literals are double escaped
    # (identifier escaping first, then literal escaping)
    assert "CREATE ROLE \"o''brien\"" in script


# ---------------------------------------------------------------------------
# review feedback round 6 (previously missed inline comments)
# ---------------------------------------------------------------------------


def test_validate_role_sharing_rejects_username_role_collision(
    db_access_role: DatabaseAccessV1,
    db_access: DatabaseAccessV1,
) -> None:
    # entry B's username equals entry A's owner role: provisioning B
    # would grant LOGIN to A's owner role, deprovisioning B would
    # drop it
    db_access.username = "cs_owner"
    with pytest.raises(ValueError, match="equals a role of another entry"):
        _validate_role_sharing([
            (db_access_role, "cs_owner_abc"),
            (db_access, "cs_owner"),
        ])


def test_validate_role_sharing_allows_distinct_usernames(
    db_access_role: DatabaseAccessV1,
    db_access: DatabaseAccessV1,
) -> None:
    db_access.username = "cs_app"
    _validate_role_sharing([(db_access_role, "cs_owner_abc"), (db_access, "cs_app")])


def test_process_deletes_stale_secret_before_enqueue(
    db_access_role: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc: MagicMock,
    oc_map: MagicMock,
) -> None:
    # a replacement job must not read the previous run's secret data:
    # the old secret is removed before the enqueue
    stale_secret = _job_secret_with_script("-- old script")
    oc.get.side_effect = lambda ns, kind, name, allow_not_found=True: (
        ADMIN_SECRET if name == ADMIN_SECRET_NAME else stale_secret
    )
    dbam_controller.get_job_status.side_effect = [
        JobStatus.SUCCESS,
        JobStatus.IN_PROGRESS,
    ]
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )
    oc.delete.assert_called_once_with("test-namespace", "Secret", ANY)


# ---------------------------------------------------------------------------
# review feedback round 7
# ---------------------------------------------------------------------------


def test_merge_pending_config_preserves_stale_only_schemas(
    db_access_role: DatabaseAccessV1,
    gql_class_factory: Callable[..., DatabaseAccessV1],
) -> None:
    # the pending marker is overwritten with the union, so a failed
    # replacement cannot lose the revoke baseline of the previous job
    pending = gql_class_factory(
        DatabaseAccessV1,
        {
            "name": "test",
            "database": "postgres",
            "role": "cs_owner",
            "access": [{"grants": ["UPDATE"], "target": {"dbschema": "bar"}}],
        },
    )
    merged = _merge_pending_config(pending, db_access_role)
    schemas = {a.target.dbschema for a in merged.access or []}
    assert schemas == {"foo", "bar"}


def test_merge_pending_config_without_pending(
    db_access_role: DatabaseAccessV1,
) -> None:
    assert _merge_pending_config(None, db_access_role) == db_access_role


def test_process_database_change_with_pending_marker_rejected(
    db_access_role: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc_map: MagicMock,
) -> None:
    # the database is immutable against the pending marker too
    dbam_state.exists.side_effect = lambda key: key == f"{STATE_KEY}#pending"
    dbam_state.get.return_value = db_access_role.model_dump(by_alias=True)
    db_access_role.database = "otherdb"
    with pytest.raises(ValueError, match="Database name cannot be changed"):
        run_process(
            db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
        )


def test_resolve_username_explicit_and_generated(
    db_access: DatabaseAccessV1,
    db_access_role: DatabaseAccessV1,
) -> None:
    assert _resolve_username(db_access, STATE_KEY) == "test"
    assert _resolve_username(db_access_role, STATE_KEY).startswith("cs_owner_")


def test_validate_role_sharing_rejects_generated_username_collision(
    db_access_role: DatabaseAccessV1,
    gql_class_factory: Callable[..., DatabaseAccessV1],
) -> None:
    # entry B's owner role literally equals entry A's generated login
    colliding_role = gql_class_factory(
        DatabaseAccessV1,
        {
            "name": "other",
            "database": "postgres",
            "role": _generated_username("cs_owner", STATE_KEY),
            "access": [],
        },
    )
    with pytest.raises(ValueError, match="equals a role of another entry"):
        _validate_role_sharing([
            (db_access_role, _resolve_username(db_access_role, STATE_KEY)),
            (colliding_role, _resolve_username(colliding_role, "other/key")),
        ])


def test_role_template_clears_activity_snapshot() -> None:
    for template in ["role_deprovision.sql", "legacy_deprovision.sql"]:
        script = _render(template)
        assert "PERFORM pg_stat_clear_snapshot();" in script


def test_role_template_verifies_table_privileges() -> None:
    script = _render(
        "role_provision.sql", schemas_csv="foreign", access_list="foreign|SELECT"
    )
    assert "has_table_privilege" in script
    assert "check_privs" in script


def test_role_template_revokes_from_login_during_migration() -> None:
    script = _render("role_provision.sql", revoke_list="foo|ALL")
    # both the owner role and the login are revoke targets
    assert script.count("REVOKE %s ON ALL TABLES IN SCHEMA %I FROM %I") == 2
    assert "s, user_name);" in script


def test_role_template_double_escapes_create_role_literal() -> None:
    script = _render(
        "legacy_provision.sql", username="o'brien", username_ident_literal="o''brien"
    )
    assert "CREATE ROLE \"o''brien\"" in script


# ---------------------------------------------------------------------------
# review feedback round 8
# ---------------------------------------------------------------------------


def test_role_template_checks_each_privilege_individually() -> None:
    script = _render(
        "role_provision.sql", schemas_csv="s", access_list="s|SELECT,INSERT"
    )
    # has_table_privilege with a comma list is ANY semantics, not ALL
    assert "FOREACH g IN ARRAY string_to_array(check_privs, ',')" in script
    assert "check_privs text;" in script
    # MAINTAIN is version-gated for the ALL expansion
    assert "server_version_num')::int >= 170000" in script


def test_role_template_declares_user_name_in_acl_block() -> None:
    script = _render("role_provision.sql", revoke_list="foo|ALL")
    # the ACL DO block declares its own user_name (a PL/pgSQL DO
    # block has no access to the declarations of a preceding block)
    assert script.count("user_name text :=") >= 2
    # check_privs is assigned in the same block that uses it (the
    # ACL block, after the wiring block)
    acl_start = script.index("ownership transfer, grants and default privileges")
    assert "check_privs" not in script[:acl_start]
    assert "check_privs" in script[acl_start:]


def test_role_template_skips_revoke_for_missing_schemas() -> None:
    script = _render("role_provision.sql", revoke_list="gone|ALL")
    assert (
        "IF EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = s) THEN"
        in script
    )


def test_deprovision_templates_skip_missing_logins() -> None:
    for template in ["role_deprovision.sql", "legacy_deprovision.sql"]:
        script = _render(template)
        assert "nothing to deprovision" in script
        assert "\\return" in script


def test_process_pending_role_change_rejected(
    db_access_role: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc_map: MagicMock,
) -> None:
    dbam_state.exists.side_effect = lambda key: key == f"{STATE_KEY}#pending"
    dbam_state.get.return_value = db_access_role.model_dump(by_alias=True)
    # pin the username to the generated one so only the role change
    # triggers (the pending config has no explicit username either)
    db_access_role.username = _generated_username("cs_owner", STATE_KEY)
    db_access_role.role = "other_owner"
    with pytest.raises(ValueError, match="Role cannot be changed"):
        run_process(
            db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
        )


def test_process_pending_username_change_rejected(
    db_access_role: DatabaseAccessV1,
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc_map: MagicMock,
) -> None:
    dbam_state.exists.side_effect = lambda key: key == f"{STATE_KEY}#pending"
    dbam_state.get.return_value = db_access_role.model_dump(by_alias=True)
    db_access_role.username = "explicit_user"
    with pytest.raises(ValueError, match="Username cannot be changed"):
        run_process(
            db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
        )


def test_process_retry_after_failed_replacement_revokes_stale_schemas(
    db_access_role: DatabaseAccessV1,
    gql_class_factory: Callable[..., DatabaseAccessV1],
    dbam_state: MagicMock,
    dbam_controller: MagicMock,
    db_access_namespace: NamespaceV1,
    secret_reader: MagicMock,
    vault_mock: MagicMock,
    oc_map: MagicMock,
) -> None:
    # regression for the failed-replacement retry path: the pending
    # marker must still contain the stale-only schema (bar) after the
    # desired config (foo) was merged in, so the retry's script revokes
    # both schemas
    pending_with_bar = gql_class_factory(
        DatabaseAccessV1,
        {
            "name": "test",
            "database": "postgres",
            "role": "cs_owner",
            "access": [
                {"grants": ["UPDATE"], "target": {"dbschema": "bar"}},
            ],
        },
    )
    dbam_state.exists.side_effect = lambda key: key == f"{STATE_KEY}#pending"
    dbam_state.get.return_value = pending_with_bar.model_dump(by_alias=True)
    dbam_controller.get_job_status.return_value = JobStatus.ERROR
    with pytest.raises(JobFailedError):
        run_process(
            db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
        )
    # the next reconcile retries: the job was deleted, the pending
    # marker (now the merged union) drives the revoke baseline
    dbam_controller.get_job_status.side_effect = [
        JobStatus.NOT_EXISTS,
        JobStatus.IN_PROGRESS,
    ]
    run_process(
        db_access_role, dbam_state, secret_reader, vault_mock, db_access_namespace
    )
    # the retry re-enqueues with a full revoke over the union
    dbam_controller.enqueue_job.assert_called_once()
    job = enqueued_job(dbam_controller)
    assert "bar|ALL" in job.script
    assert "foo|ALL" in job.script
    # the pending marker written for the retry includes the union
    marker_value = dbam_state.add.call_args_list[0].kwargs.get("value")
    marker_schemas = {a["target"]["dbschema"] for a in marker_value["access"]}
    assert marker_schemas == {"foo", "bar"}
