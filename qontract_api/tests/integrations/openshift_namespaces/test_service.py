"""Tests for openshift-namespaces service."""

from unittest.mock import MagicMock

import pytest

from qontract_api.integrations.openshift_namespaces.domain import DesiredNamespace
from qontract_api.integrations.openshift_namespaces.schemas import (
    CreateNamespaceAction,
    DeleteNamespaceAction,
)
from qontract_api.integrations.openshift_namespaces.service import (
    OpenShiftNamespacesService,
)
from qontract_api.models import TaskStatus


@pytest.fixture
def service() -> OpenShiftNamespacesService:
    return OpenShiftNamespacesService()


@pytest.fixture
def mock_ws_client() -> MagicMock:
    return MagicMock()


def test_create_namespace_when_not_exists(
    service: OpenShiftNamespacesService,
    mock_ws_client: MagicMock,
) -> None:
    """Namespace doesn't exist → CreateNamespaceAction."""
    mock_ws_client.namespace_exists.return_value = False

    result = service.reconcile(
        cluster_clients={"prod-1": mock_ws_client},
        cluster_namespaces={"prod-1": [DesiredNamespace(name="app-a")]},
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], CreateNamespaceAction)
    assert result.actions[0].cluster == "prod-1"
    assert result.actions[0].namespace == "app-a"


def test_no_action_when_namespace_exists(
    service: OpenShiftNamespacesService,
    mock_ws_client: MagicMock,
) -> None:
    """Namespace already exists → no action."""
    mock_ws_client.namespace_exists.return_value = True

    result = service.reconcile(
        cluster_clients={"prod-1": mock_ws_client},
        cluster_namespaces={"prod-1": [DesiredNamespace(name="app-a")]},
    )

    assert result.actions == []


def test_delete_namespace_when_exists(
    service: OpenShiftNamespacesService,
    mock_ws_client: MagicMock,
) -> None:
    """Namespace marked for deletion and exists → DeleteNamespaceAction."""
    mock_ws_client.namespace_exists.return_value = True

    result = service.reconcile(
        cluster_clients={"prod-1": mock_ws_client},
        cluster_namespaces={"prod-1": [DesiredNamespace(name="old-ns", delete=True)]},
    )

    assert len(result.actions) == 1
    assert isinstance(result.actions[0], DeleteNamespaceAction)


def test_no_action_when_delete_not_exists(
    service: OpenShiftNamespacesService,
    mock_ws_client: MagicMock,
) -> None:
    """Namespace marked for deletion but doesn't exist → no action."""
    mock_ws_client.namespace_exists.return_value = False

    result = service.reconcile(
        cluster_clients={"prod-1": mock_ws_client},
        cluster_namespaces={"prod-1": [DesiredNamespace(name="gone", delete=True)]},
    )

    assert result.actions == []


def test_dry_run_calculates_but_does_not_execute(
    service: OpenShiftNamespacesService,
    mock_ws_client: MagicMock,
) -> None:
    """Dry run: actions calculated, nothing applied."""
    mock_ws_client.namespace_exists.return_value = False

    result = service.reconcile(
        cluster_clients={"prod-1": mock_ws_client},
        cluster_namespaces={"prod-1": [DesiredNamespace(name="app-a")]},
        dry_run=True,
    )

    assert len(result.actions) == 1
    assert result.applied_actions == []
    assert result.applied_count == 0
    mock_ws_client.create_namespace.assert_not_called()


def test_non_dry_run_executes_actions(
    service: OpenShiftNamespacesService,
    mock_ws_client: MagicMock,
) -> None:
    """Non-dry-run: actions are executed."""
    mock_ws_client.namespace_exists.return_value = False

    result = service.reconcile(
        cluster_clients={"prod-1": mock_ws_client},
        cluster_namespaces={"prod-1": [DesiredNamespace(name="app-a")]},
        dry_run=False,
    )

    assert len(result.applied_actions) == 1
    assert result.applied_count == 1
    mock_ws_client.create_namespace.assert_called_once_with("app-a")


def test_action_error_does_not_stop_others(
    service: OpenShiftNamespacesService,
    mock_ws_client: MagicMock,
) -> None:
    """Individual action failure doesn't stop remaining actions."""
    mock_ws_client.namespace_exists.return_value = False
    mock_ws_client.create_namespace.side_effect = [
        Exception("first fails"),
        MagicMock(),
    ]

    result = service.reconcile(
        cluster_clients={"prod-1": mock_ws_client},
        cluster_namespaces={
            "prod-1": [
                DesiredNamespace(name="fail-ns"),
                DesiredNamespace(name="ok-ns"),
            ]
        },
        dry_run=False,
    )

    assert len(result.actions) == 2
    assert len(result.applied_actions) == 1
    assert len(result.errors) == 1
    assert result.status == TaskStatus.FAILED


def test_empty_clusters(service: OpenShiftNamespacesService) -> None:
    """Empty cluster list → empty result."""
    result = service.reconcile(
        cluster_clients={},
        cluster_namespaces={},
    )

    assert result.actions == []
    assert result.status == TaskStatus.SUCCESS


def test_multiple_clusters(
    service: OpenShiftNamespacesService,
) -> None:
    """Actions from multiple clusters are collected."""
    ws1 = MagicMock()
    ws1.namespace_exists.return_value = False
    ws2 = MagicMock()
    ws2.namespace_exists.return_value = False

    result = service.reconcile(
        cluster_clients={"prod-1": ws1, "prod-2": ws2},
        cluster_namespaces={
            "prod-1": [DesiredNamespace(name="ns-a")],
            "prod-2": [DesiredNamespace(name="ns-b")],
        },
    )

    assert len(result.actions) == 2
    cluster_names = {a.cluster for a in result.actions}
    assert cluster_names == {"prod-1", "prod-2"}


def test_missing_client_for_cluster(
    service: OpenShiftNamespacesService,
) -> None:
    """Cluster without a client → error reported."""
    result = service.reconcile(
        cluster_clients={},
        cluster_namespaces={"unknown": [DesiredNamespace(name="ns")]},
    )

    assert len(result.errors) == 1
    assert "unknown" in result.errors[0]
    assert result.status == TaskStatus.FAILED


def test_mix_create_and_delete(
    service: OpenShiftNamespacesService,
    mock_ws_client: MagicMock,
) -> None:
    """Mix of creates and deletes in same cluster."""

    def exists_side_effect(name: str) -> bool:
        return name == "existing"

    mock_ws_client.namespace_exists.side_effect = exists_side_effect

    result = service.reconcile(
        cluster_clients={"prod-1": mock_ws_client},
        cluster_namespaces={
            "prod-1": [
                DesiredNamespace(name="new-ns"),
                DesiredNamespace(name="existing", delete=True),
            ]
        },
    )

    assert len(result.actions) == 2
    types = {type(a) for a in result.actions}
    assert types == {CreateNamespaceAction, DeleteNamespaceAction}
