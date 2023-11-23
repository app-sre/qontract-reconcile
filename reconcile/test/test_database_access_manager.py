from collections import defaultdict
from typing import (
    Any,
    Callable,
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
    _generate_password,
    _populate_resources,
    _process_db_access,
)
from reconcile.gql_definitions.terraform_resources.database_access_manager import (
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
    gql_class_factory: Callable[..., DatabaseAccessAccessV1]
) -> DatabaseAccessAccessV1:
    return gql_class_factory(
        DatabaseAccessAccessV1,
        {
            "grants": ["insert", "select"],
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
    assert 'CREATE ROLE "test"  WITH LOGIN PASSWORD' in script
    assert "CREATE SCHEMA IF NOT EXISTS" in script


def _assert_grant_access(script: str) -> None:
    assert 'GRANT insert,select ON ALL TABLES IN SCHEMA "foo" TO "test"' in script


def test_generate_create_user(
    db_access: DatabaseAccessV1, db_connection_parameter: DatabaseConnectionParameters
) -> None:
    s = PSQLScriptGenerator(
        db_access=db_access,
        connection_parameter=db_connection_parameter,
        engine="postgres",
    )
    script = s._generate_create_user()
    _assert_create_script(script)


def test_generate_access(
    db_access: DatabaseAccessV1,
    db_access_access: DatabaseAccessAccessV1,
    db_connection_parameter: DatabaseConnectionParameters,
):
    db_access.access = [db_access_access]

    s = PSQLScriptGenerator(
        db_access=db_access,
        connection_parameter=db_connection_parameter,
        engine="postgres",
    )
    script = s._generate_db_access()
    _assert_grant_access(script)


def test_generate_complete(
    db_access_complete: DatabaseAccessV1,
    db_connection_parameter: DatabaseConnectionParameters,
):
    s = PSQLScriptGenerator(
        db_access=db_access_complete,
        connection_parameter=db_connection_parameter,
        engine="postgres",
    )
    script = s.generate_script()
    _assert_create_script(script)
    _assert_grant_access(script)


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
        database_connection=db_connection_parameter,
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
    assert p == DatabaseConnectionParameters(
        host="localhost",
        port="5432",
        user="test",
        password="hduhsdfuhsdf",
        database="test",
    )


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
    assert p == DatabaseConnectionParameters(
        host="localhost",
        port="5432",
        user="test",
        password=pw_generated,
        database="test",
    )


def test_generate_password():
    assert len(_generate_password()) == 32
    assert _generate_password() != _generate_password()


@pytest.fixture
def dbam_state(mocker: MockerFixture) -> MockerFixture:
    return mocker.patch("reconcile.database_access_manager.State", autospec=True)


@pytest.fixture
def dbam_process_mocks(
    openshift_resource_secet: OpenshiftResource, mocker: MockerFixture
) -> DBAMResource:
    expected_resource = DBAMResource(resource=openshift_resource_secet, clean_up=True)
    mocker.patch(
        "reconcile.database_access_manager._create_database_connection_parameter",
        return_value=db_connection_parameter,
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
):
    dbam_state.exists.return_value = False
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
):
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
        )


def test__process_db_access_state_diff(
    db_access: DatabaseAccessV1,
    dbam_state: MagicMock,
    db_access_namespace: NamespaceV1,
    dbam_process_mocks: DBAMResource,
    mocker: MockerFixture,
    ai_settings: dict[str, Any],
):
    dbam_state.get.return_value = {}
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


def test__process_db_access_state_exists_matched(
    db_access: DatabaseAccessV1,
    db_access_namespace: NamespaceV1,
    dbam_state: MagicMock,
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
    )
