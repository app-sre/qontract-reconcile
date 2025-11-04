from collections.abc import Callable
from unittest.mock import (
    MagicMock,
    create_autospec,
)

import pytest
from pytest_mock import MockerFixture

from reconcile import openshift_namespaces
from reconcile.gql_definitions.common.namespaces_minimal import NamespaceV1
from reconcile.utils.oc import OCCli
from reconcile.utils.oc_map import OCMap


@pytest.fixture
def namespace_builder(gql_class_factory: Callable) -> Callable[..., NamespaceV1]:
    def builder(
        name: str,
        cluster_name: str,
        delete: bool = False,
        managed_by_external: bool = False,
    ) -> NamespaceV1:
        return gql_class_factory(
            NamespaceV1,
            {
                "name": name,
                "cluster": {"name": cluster_name},
                "delete": delete,
                "managedByExternal": managed_by_external,
            },
        )

    return builder


def setup_mocks(
    mocker: MockerFixture,
    namespaces: list[NamespaceV1],
) -> dict[str, MagicMock]:
    get_namespaces_minimal = mocker.patch(
        "reconcile.openshift_namespaces.get_namespaces_minimal",
        return_value=namespaces,
    )
    get_app_interface_vault_settings = mocker.patch(
        "reconcile.openshift_namespaces.get_app_interface_vault_settings",
    )
    create_secret_reader = mocker.patch(
        "reconcile.openshift_namespaces.create_secret_reader",
    )
    oc = create_autospec(OCCli)
    oc_map = create_autospec(spec=OCMap)
    oc_map.get.return_value = oc
    init_oc_map_from_namespaces = mocker.patch(
        "reconcile.openshift_namespaces.init_oc_map_from_namespaces",
        return_value=oc_map,
    )
    return {
        "oc": oc,
        "oc_map": oc_map,
        "get_namespaces_minimal": get_namespaces_minimal,
        "get_app_interface_vault_settings": get_app_interface_vault_settings,
        "create_secret_reader": create_secret_reader,
        "init_oc_map_from_namespaces": init_oc_map_from_namespaces,
    }


@pytest.mark.parametrize("dry_run", [True, False])
def test_run(mocker: MockerFixture, dry_run: bool) -> None:
    mocks = setup_mocks(mocker, [])

    openshift_namespaces.run(dry_run, thread_pool_size=1)

    mocks["get_namespaces_minimal"].assert_called_once_with()
    mocks["get_app_interface_vault_settings"].assert_called_once_with()
    mocks["create_secret_reader"].assert_called_once_with(
        use_vault=mocks["get_app_interface_vault_settings"].return_value.vault
    )
    mocks["init_oc_map_from_namespaces"].assert_called_once_with(
        namespaces=[],
        integration="openshift-namespaces",
        secret_reader=mocks["create_secret_reader"].return_value,
        internal=None,
        use_jump_host=True,
        thread_pool_size=1,
        init_projects=True,
    )


def test_run_with_cluster_name(
    namespace_builder: Callable,
    mocker: MockerFixture,
) -> None:
    namespace = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
    )
    namespace_in_another_cluster = namespace_builder(
        name="another-namespace",
        cluster_name="another-cluster",
    )
    mocks = setup_mocks(mocker, [namespace, namespace_in_another_cluster])

    openshift_namespaces.run(False, thread_pool_size=1, cluster_name=["test-cluster"])

    mocks["oc"].project_exists.assert_called_once_with("test-namespace")


def test_run_with_namespace_name(
    namespace_builder: Callable,
    mocker: MockerFixture,
) -> None:
    namespace = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
    )
    another_namespace = namespace_builder(
        name="another-namespace",
        cluster_name="test-cluster",
    )
    mocks = setup_mocks(mocker, [namespace, another_namespace])

    openshift_namespaces.run(
        False, thread_pool_size=1, namespace_name=["test-namespace"]
    )

    mocks["oc"].project_exists.assert_called_once_with("test-namespace")


def test_create_namespace(
    namespace_builder: Callable,
    mocker: MockerFixture,
) -> None:
    namespace = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
    )
    mocks = setup_mocks(mocker, [namespace])
    mocks["oc"].project_exists.return_value = False

    openshift_namespaces.run(False, thread_pool_size=1)

    mocks["oc"].project_exists.assert_called_once_with("test-namespace")
    mocks["oc"].new_project.assert_called_once_with("test-namespace")
    mocks["oc"].delete_project.assert_not_called()


def test_no_op_when_namespace_exists(
    namespace_builder: Callable,
    mocker: MockerFixture,
) -> None:
    namespace = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
    )
    mocks = setup_mocks(mocker, [namespace])
    mocks["oc"].project_exists.return_value = True

    openshift_namespaces.run(False, thread_pool_size=1)

    mocks["oc"].project_exists.assert_called_once_with("test-namespace")
    mocks["oc"].new_project.assert_not_called()
    mocks["oc"].delete_project.assert_not_called()


def test_skip_create_managed_by_external_namespace(
    namespace_builder: Callable,
    mocker: MockerFixture,
) -> None:
    namespace = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
        managed_by_external=True,
    )
    mocks = setup_mocks(mocker, [namespace])
    mocks["oc"].project_exists.return_value = False

    openshift_namespaces.run(False, thread_pool_size=1)

    mocks["oc"].project_exists.assert_not_called()
    mocks["oc"].new_project.assert_not_called()
    mocks["oc"].delete_project.assert_not_called()


def test_delete_namespace(
    namespace_builder: Callable,
    mocker: MockerFixture,
) -> None:
    namespace = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
        delete=True,
    )
    mocks = setup_mocks(mocker, [namespace])
    mocks["oc"].project_exists.return_value = True

    openshift_namespaces.run(False, thread_pool_size=1)

    mocks["oc"].project_exists.assert_called_once_with("test-namespace")
    mocks["oc"].delete_project.assert_called_once_with("test-namespace")
    mocks["oc"].new_project.assert_not_called()


def test_no_op_when_namespace_already_deleted(
    namespace_builder: Callable,
    mocker: MockerFixture,
) -> None:
    namespace = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
        delete=True,
    )
    mocks = setup_mocks(mocker, [namespace])
    mocks["oc"].project_exists.return_value = False

    openshift_namespaces.run(False, thread_pool_size=1)

    mocks["oc"].project_exists.assert_called_once_with("test-namespace")
    mocks["oc"].new_project.assert_not_called()
    mocks["oc"].delete_project.assert_not_called()


def test_skip_delete_managed_by_external_namespace(
    namespace_builder: Callable,
    mocker: MockerFixture,
) -> None:
    namespace = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
        delete=True,
        managed_by_external=True,
    )
    mocks = setup_mocks(mocker, [namespace])
    mocks["oc"].project_exists.return_value = True

    openshift_namespaces.run(False, thread_pool_size=1)

    mocks["oc"].project_exists.assert_not_called()
    mocks["oc"].new_project.assert_not_called()
    mocks["oc"].delete_project.assert_not_called()


def test_duplicate_namespaces(
    namespace_builder: Callable,
    mocker: MockerFixture,
) -> None:
    namespace1 = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
    )
    namespace2 = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
    )
    setup_mocks(mocker, [namespace1, namespace2])

    with pytest.raises(ExceptionGroup) as e:
        openshift_namespaces.run(False, thread_pool_size=1)

    assert len(e.value.exceptions) == 1
    assert isinstance(
        e.value.exceptions[0], openshift_namespaces.NamespaceDuplicateError
    )
    assert "Found multiple definitions" in str(e.value.exceptions[0])


def test_error_handling(
    namespace_builder: Callable,
    mocker: MockerFixture,
) -> None:
    namespace = namespace_builder(
        name="test-namespace",
        cluster_name="test-cluster",
    )
    mocks = setup_mocks(mocker, [namespace])
    exception = Exception("Some error")
    mocks["oc"].project_exists.side_effect = exception

    with pytest.raises(ExceptionGroup) as e:
        openshift_namespaces.run(False, thread_pool_size=1)

    assert len(e.value.exceptions) == 1
    assert isinstance(e.value.exceptions[0], openshift_namespaces.NamespaceRuntimeError)
    assert "Some error" in str(e.value.exceptions[0])
