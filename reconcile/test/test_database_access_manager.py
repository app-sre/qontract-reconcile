from collections import defaultdict
from typing import (
    Any,
    Callable,
    Optional,
)
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.database_access_manager import (
    DatabaseConnectionParameters,
    DBAMResource,
    JobFailedError,
    JobStatus,
    JobStatusCondition,
    PSQLScriptGenerator,
    _create_database_connection_parameter,
    _db_access_acccess_is_valid,
    _DBDonnections,
    _generate_password,
    _populate_resources,
    _process_db_access,
)
from reconcile.gql_definitions.terraform_resources.database_access_manager import (
    DatabaseAccessAccessGranteeV1,
    DatabaseAccessAccessV1,
    DatabaseAccessV1,
    NamespaceV1,
)
from reconcile.utils.openshift_resource import OpenshiftResource


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
def db_access_complete(
    db_access: DatabaseAccessV1, db_access_access: DatabaseAccessAccessV1
) -> DatabaseAccessV1:
    db_access.access = [db_access_access]
    return db_access


@pytest.fixture
def db_connection_parameter():
    return DatabaseConnectionParameters(
        host="localhost",
        port="5432",
        user="test",
        password="postgres",  # notsecret
        database="user",
    )


@pytest.fixture
def db_admin_connection_parameter():
    return DatabaseConnectionParameters(
        host="localhost",
        port="5432",
        user="admin",
        password="adminpw",  # notsecret
        database="test",
    )


@pytest.fixture
def db_secret_dict() -> dict[str, dict[str, str]]:
    return {
        "data": {
            "db.password": "aGR1aHNkZnVoc2Rm",  # notsecret
            "db.host": "bG9jYWxob3N0",
            "db.port": "NTQzMg==",
            "db.user": "dGVzdA==",
            "db.name": "dGVzdA==",
        }
    }


@pytest.fixture
def openshift_resource_secet() -> OpenshiftResource:
    return OpenshiftResource(
        body={
            "metadata": {"name": "test"},
            "kind": "secret",
            "data": {"password": "postgres"},
        },
        integration="TEST",
        integration_version="0.0.1",
    )


def _assert_create_script(script: str) -> None:
    assert 'CREATE DATABASE "test"' in script
    assert "REVOKE ALL ON DATABASE" in script
    assert 'CREATE ROLE "test"' in script
    assert 'ALTER ROLE "test" WITH LOGIN' in script
    assert 'GRANT CONNECT ON DATABASE "test" to "test"' in script
    assert "CREATE SCHEMA IF NOT EXISTS" in script
    assert 'GRANT "test" to "admin";' in script


def _assert_grant_access(script: str) -> None:
    assert 'GRANT INSERT,SELECT ON ALL TABLES IN SCHEMA "foo" TO "test"' in script


def _assert_delete_script(script: str) -> None:
    assert (
        '\n\\set ON_ERROR_STOP on\n\\c "test"\nREASSIGN OWNED BY "test" TO "admin";\nDROP ROLE IF EXISTS "test";\\gexec'
        in script
    )


def _assert_revoke_access(script: str) -> None:
    assert 'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA "foo" FROM "test";' in script


def test_generate_create_user(
    db_access: DatabaseAccessV1,
    db_connection_parameter: DatabaseConnectionParameters,
    db_admin_connection_parameter: DatabaseConnectionParameters,
) -> None:
    s = PSQLScriptGenerator(
        db_access=db_access,
        connection_parameter=db_connection_parameter,
        admin_connection_parameter=db_admin_connection_parameter,
        engine="postgres",
    )
    script = s._generate_create_user()
    _assert_create_script(script)


def test_generate_delete_user(
    db_access: DatabaseAccessV1,
    db_connection_parameter: DatabaseConnectionParameters,
    db_admin_connection_parameter: DatabaseConnectionParameters,
) -> None:
    s = PSQLScriptGenerator(
        db_access=db_access,
        connection_parameter=db_connection_parameter,
        admin_connection_parameter=db_admin_connection_parameter,
        engine="postgres",
    )
    script = s._generate_delete_user()
    _assert_delete_script(script)


def test_generate_access(
    db_access: DatabaseAccessV1,
    db_access_access: DatabaseAccessAccessV1,
    db_connection_parameter: DatabaseConnectionParameters,
    db_admin_connection_parameter: DatabaseConnectionParameters,
):
    db_access.access = [db_access_access]

    s = PSQLScriptGenerator(
        db_access=db_access,
        connection_parameter=db_connection_parameter,
        admin_connection_parameter=db_connection_parameter,
        engine="postgres",
    )
    script = s._generate_db_access()
    _assert_grant_access(script)


def test_generate_revoke_access(
    db_access: DatabaseAccessV1,
    db_access_access: DatabaseAccessAccessV1,
    db_connection_parameter: DatabaseConnectionParameters,
    db_admin_connection_parameter: DatabaseConnectionParameters,
):
    db_access.access = [db_access_access]

    s = PSQLScriptGenerator(
        db_access=db_access,
        connection_parameter=db_connection_parameter,
        admin_connection_parameter=db_connection_parameter,
        engine="postgres",
    )
    script = s._generate_revoke_db_access()
    _assert_revoke_access(script)


@pytest.mark.parametrize(
    "current, expected",
    [
        (None, ""),
        (
            DatabaseAccessV1(
                username="test", name="test", database="test", delete=False, access=[]
            ),
            "",
        ),
        (
            DatabaseAccessV1(
                username="test",
                name="test",
                database="test",
                delete=False,
                access=[
                    DatabaseAccessAccessV1(
                        grants=["SELECT", "INSERT", "UPDATE"],
                        target=DatabaseAccessAccessGranteeV1(dbschema="foo"),
                    )
                ],
            ),
            'REVOKE UPDATE ON ALL TABLES IN SCHEMA "foo" FROM "test";',
        ),
        (
            DatabaseAccessV1(
                username="test",
                name="test",
                database="test",
                delete=False,
                access=[
                    DatabaseAccessAccessV1(
                        grants=["SELECT"],
                        target=DatabaseAccessAccessGranteeV1(dbschema="bar"),
                    )
                ],
            ),
            'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA "bar" FROM "test";',
        ),
    ],
)
def test_generate_revoke_changed(
    db_access_complete: DatabaseAccessV1,
    db_connection_parameter: DatabaseConnectionParameters,
    db_admin_connection_parameter: DatabaseConnectionParameters,
    expected: str,
    current: Optional[DatabaseAccessV1],
):
    s = PSQLScriptGenerator(
        db_access=db_access_complete,
        current_db_access=current,
        connection_parameter=db_connection_parameter,
        admin_connection_parameter=db_connection_parameter,
        engine="postgres",
    )
    script = s._generate_revoke_changed()
    assert script == expected


def test_generate_complete(
    db_access_complete: DatabaseAccessV1,
    db_connection_parameter: DatabaseConnectionParameters,
    db_admin_connection_parameter: DatabaseConnectionParameters,
):
    s = PSQLScriptGenerator(
        db_access=db_access_complete,
        connection_parameter=db_connection_parameter,
        admin_connection_parameter=db_admin_connection_parameter,
        engine="postgres",
    )
    script = s.generate_script()
    _assert_create_script(script)
    _assert_grant_access(script)


def test_generate_delete_complete(
    db_access_complete: DatabaseAccessV1,
    db_connection_parameter: DatabaseConnectionParameters,
    db_admin_connection_parameter: DatabaseConnectionParameters,
):
    db_access_complete.delete = True
    s = PSQLScriptGenerator(
        db_access=db_access_complete,
        connection_parameter=db_connection_parameter,
        admin_connection_parameter=db_admin_connection_parameter,
        engine="postgres",
    )
    script = s.generate_script()
    _assert_delete_script(script)
    _assert_revoke_access(script)


def test_db_access_acccess_is_valid(
    db_access_complete: DatabaseAccessV1, db_access_access: DatabaseAccessAccessV1
):
    assert db_access_complete.access
    assert _db_access_acccess_is_valid(db_access_complete)
    db_access_complete.access.append(db_access_access)
    assert not _db_access_acccess_is_valid(db_access_complete)


def test_job_completion():
    s = JobStatus(conditions=[])
    assert s.is_complete() is False

    s = JobStatus(conditions=[JobStatusCondition(type="Complete")])
    assert s.is_complete()
    assert s.has_errors() is False


def test_has_errors():
    s = JobStatus(conditions=[JobStatusCondition(type="Failed")])
    assert s.is_complete()
    assert s.has_errors()


def test_populate_resources(
    mocker: MockerFixture,
    db_access: DatabaseAccessV1,
    db_connection_parameter: DatabaseConnectionParameters,
    db_admin_connection_parameter: DatabaseConnectionParameters,
    openshift_resource_secet: OpenshiftResource,
):
    mocker.patch(
        "reconcile.database_access_manager.orb.fetch_provider_vault_secret",
        return_value=openshift_resource_secet,
    )
    reources = _populate_resources(
        db_access=db_access,
        engine="postgres",
        image_repository="foo",
        pull_secret={
            "version": 1,
            "annotations": [],
            "type": "a",
            "labels": [],
            "path": "/foo/bar",
        },
        admin_secret_name="db-secret",
        resource_prefix="dbam-foo",
        settings={"foo": "bar"},
        user_connection=db_connection_parameter,
        admin_connection=db_admin_connection_parameter,
    )

    r_kinds = [r.resource.kind for r in reources]
    assert sorted(r_kinds) == ["Job", "Secret", "Secret", "ServiceAccount", "secret"]


def test__create_database_connection_parameter_user_exists(
    db_access: DatabaseAccessV1,
    db_secret_dict: dict[str, dict[str, str]],
    mocker: MockerFixture,
):
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.get.return_value = db_secret_dict
    p = _create_database_connection_parameter(
        db_access=db_access,
        namespace_name="foo",
        oc=oc,
        admin_secret_name="db-secret",
        user_secret_name="db-user-secret",
    )
    conn = DatabaseConnectionParameters(
        host="localhost",
        port="5432",
        user="test",
        password="hduhsdfuhsdf",
        database="test",
    )

    assert p["user"] == conn
    assert p["admin"] == conn
    assert oc.get.call_count == 2


def test__create_database_connection_parameter_user_missing(
    db_access: DatabaseAccessV1,
    db_secret_dict: dict[str, dict[str, str]],
    mocker: MockerFixture,
):
    pw_generated = "1N5j7oksB45l8w0RJD8qR0ENJP1yOAOs"  # notsecret
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.get.side_effect = [None, db_secret_dict]
    mocker.patch(
        "reconcile.database_access_manager._generate_password",
        return_value=pw_generated,
    )
    p = _create_database_connection_parameter(
        db_access=db_access,
        namespace_name="foo",
        oc=oc,
        admin_secret_name="db-secret",
        user_secret_name="db-user-secret",
    )
    conn = DatabaseConnectionParameters(
        host="localhost",
        port="5432",
        user="test",
        password=pw_generated,
        database="test",
    )

    admin_conn = conn.copy()
    admin_conn.password = "hduhsdfuhsdf"

    assert p["user"] == conn
    assert p["admin"] == admin_conn
    assert oc.get.call_count == 2


def test_generate_password():
    assert len(_generate_password()) == 32
    assert _generate_password() != _generate_password()


@pytest.fixture
def dbam_state(mocker: MockerFixture) -> MockerFixture:
    return mocker.patch("reconcile.database_access_manager.State", autospec=True)


@pytest.fixture
def vault_mock(mocker: MockerFixture) -> MockerFixture:
    return mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)


@pytest.fixture
def dbam_process_mocks(
    openshift_resource_secet: OpenshiftResource,
    mocker: MockerFixture,
    db_connection_parameter: DatabaseConnectionParameters,
    db_admin_connection_parameter: DatabaseConnectionParameters,
) -> DBAMResource:
    expected_resource = DBAMResource(resource=openshift_resource_secet, clean_up=True)
    mocker.patch(
        "reconcile.database_access_manager._create_database_connection_parameter",
        return_value=_DBDonnections(
            user=db_connection_parameter,
            admin=db_admin_connection_parameter,
        ),
    )
    mocker.patch(
        "reconcile.database_access_manager._populate_resources",
        return_value=[expected_resource],
    )
    return expected_resource


@pytest.fixture
def ai_settings() -> dict[str, Any]:
    d: dict[str, Any] = defaultdict(str)
    d["sqlQuery"] = {
        "imageRepository": {"foo": "bar"},
        "pullSecret": {"foo": "bar"},
    }
    return d


def test__process_db_access_job_pass(
    db_access: DatabaseAccessV1,
    db_access_namespace: NamespaceV1,
    dbam_state: MagicMock,
    dbam_process_mocks: DBAMResource,
    mocker: MockerFixture,
    ai_settings: dict[str, Any],
    vault_mock: MagicMock,
):
    dbam_state.exists.return_value = False
    dbam_state.get.return_value = db_access
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.get.return_value = {"status": {"conditions": [{"type": "Complete"}]}}

    oc_map = mocker.patch("reconcile.database_access_manager.OC_Map", autospec=True)
    oc_map.return_value.__enter__.return_value = oc_map
    oc_map.get_cluster.return_value = oc

    ob_delete = mocker.patch(
        "reconcile.database_access_manager.openshift_base.delete", autospec=True
    )

    _process_db_access(
        False,
        dbam_state,
        db_access,
        namespace=db_access_namespace,
        admin_secret_name="db-secret",
        engine="postgres",
        settings=ai_settings,
        vault_output_path="foo",
        vault_client=vault_mock,
    )

    vault_mock.write.assert_called_once_with(
        {
            "path": "foo/database-access-manager/test-cluster/test-namespace/test",
            "data": {
                "host": "localhost",
                "port": "5432",
                "user": "test",
                "password": "postgres",
                "database": "user",
            },
        },
        decode_base64=False,
    )

    assert ob_delete.call_count == 1
    ob_delete.assert_called_once_with(
        dry_run=False,
        oc_map=oc_map,
        cluster="test-cluster",
        namespace="test-namespace",
        resource_type="secret",
        name=dbam_process_mocks.resource.name,
        enable_deletion=True,
    )


def test__process_db_access_job_error(
    db_access: DatabaseAccessV1,
    dbam_state: MagicMock,
    db_access_namespace: NamespaceV1,
    dbam_process_mocks: DBAMResource,
    mocker: MockerFixture,
    ai_settings: dict[str, Any],
    vault_mock: MagicMock,
):
    dbam_state.exists.return_value = False
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.get.return_value = {"status": {"conditions": [{"type": "Failed"}]}}
    oc_map = mocker.patch("reconcile.database_access_manager.OC_Map", autospec=True)
    oc_map.return_value.__enter__.return_value = oc_map
    oc_map.get_cluster.return_value = oc

    with pytest.raises(JobFailedError):
        _process_db_access(
            False,
            dbam_state,
            db_access,
            namespace=db_access_namespace,
            admin_secret_name="db-secret",
            engine="postgres",
            settings=ai_settings,
            vault_output_path="foo",
            vault_client=vault_mock,
        )


def test__process_db_access_state_diff(
    db_access: DatabaseAccessV1,
    dbam_state: MagicMock,
    db_access_namespace: NamespaceV1,
    dbam_process_mocks: DBAMResource,
    mocker: MockerFixture,
    ai_settings: dict[str, Any],
    vault_mock: MagicMock,
):
    dba_current = db_access.dict(by_alias=True)
    dba_current["access"] = [{"grants": ["SELECT"], "target": {"dbschema": "test"}}]
    dbam_state.get.return_value = dba_current
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.get.return_value = False
    oc_map = mocker.patch("reconcile.database_access_manager.OC_Map", autospec=True)
    oc_map.return_value.__enter__.return_value = oc_map
    oc_map.get_cluster.return_value = oc

    ob_apply = mocker.patch(
        "reconcile.database_access_manager.openshift_base.apply", autospec=True
    )
    _process_db_access(
        False,
        dbam_state,
        db_access,
        namespace=db_access_namespace,
        admin_secret_name="db-secret",
        engine="postgres",
        settings=ai_settings,
        vault_output_path="foo",
        vault_client=vault_mock,
    )

    assert ob_apply.call_count == 1
    ob_apply.assert_called_once_with(
        dry_run=False,
        oc_map=oc_map,
        cluster="test-cluster",
        namespace="test-namespace",
        resource_type="secret",
        resource=dbam_process_mocks.resource,
        wait_for_namespace=False,
    )


@pytest.mark.parametrize("field", ["database", "username"])
def test__process_db_access_value_error_database(
    db_access: DatabaseAccessV1,
    dbam_state: MagicMock,
    db_access_namespace: NamespaceV1,
    dbam_process_mocks: DBAMResource,
    ai_settings: dict[str, Any],
    field: str,
    vault_mock: MagicMock,
):
    dba_current = db_access.dict(by_alias=True)
    dba_current[field] = "foo"
    dbam_state.get.return_value = dba_current

    with pytest.raises(ValueError):
        _process_db_access(
            False,
            dbam_state,
            db_access,
            namespace=db_access_namespace,
            admin_secret_name="db-secret",
            engine="postgres",
            settings=ai_settings,
            vault_output_path="foo",
            vault_client=vault_mock,
        )


def test__process_db_access_state_exists_matched(
    db_access: DatabaseAccessV1,
    db_access_namespace: NamespaceV1,
    dbam_state: MagicMock,
    vault_mock: MagicMock,
):
    dbam_state.exists.return_value = True
    dbam_state.get.return_value = db_access.dict(by_alias=True)
    # missing mocks would cause this to fail if not exit early
    _process_db_access(
        False,
        dbam_state,
        db_access,
        namespace=db_access_namespace,
        admin_secret_name="db-secret",
        engine="postgres",
        settings=defaultdict(str),
        vault_output_path="foo",
        vault_client=vault_mock,
    )
