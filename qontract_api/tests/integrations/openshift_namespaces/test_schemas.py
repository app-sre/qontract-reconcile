"""Tests for openshift-namespaces schemas."""

import pytest
from pydantic import ValidationError

from qontract_api.integrations.openshift_namespaces.domain import (
    ClusterNamespaces,
    DesiredNamespace,
)
from qontract_api.integrations.openshift_namespaces.schemas import (
    CreateNamespaceAction,
    DeleteNamespaceAction,
    NamespaceAction,
    OpenShiftNamespacesReconcileRequest,
    OpenShiftNamespacesTaskResponse,
    OpenShiftNamespacesTaskResult,
)
from qontract_api.models import Secret, TaskStatus


def _secret(path: str = "k8s/prod/token") -> Secret:
    return Secret(secret_manager_url="https://vault", path=path, field="token")


def _cluster(
    name: str = "prod-1",
    namespaces: list[DesiredNamespace] | None = None,
) -> ClusterNamespaces:
    return ClusterNamespaces(
        cluster_name=name,
        server_url="https://prod-1:6443",
        automation_token=_secret(),
        namespaces=namespaces or [],
    )


def test_create_action_frozen() -> None:
    action = CreateNamespaceAction(cluster="prod-1", namespace="app-a")
    with pytest.raises(ValidationError):
        action.namespace = "changed"  # type: ignore[misc]


def test_delete_action_frozen() -> None:
    action = DeleteNamespaceAction(cluster="prod-1", namespace="app-a")
    with pytest.raises(ValidationError):
        action.namespace = "changed"  # type: ignore[misc]


def test_create_action_type() -> None:
    action = CreateNamespaceAction(cluster="c", namespace="n")
    assert action.action_type == "create_namespace"


def test_delete_action_type() -> None:
    action = DeleteNamespaceAction(cluster="c", namespace="n")
    assert action.action_type == "delete_namespace"


def test_discriminated_union_create() -> None:
    data = {"action_type": "create_namespace", "cluster": "c", "namespace": "n"}
    from pydantic import TypeAdapter

    adapter: TypeAdapter[NamespaceAction] = TypeAdapter(NamespaceAction)
    action = adapter.validate_python(data)
    assert isinstance(action, CreateNamespaceAction)


def test_discriminated_union_delete() -> None:
    data = {"action_type": "delete_namespace", "cluster": "c", "namespace": "n"}
    from pydantic import TypeAdapter

    adapter: TypeAdapter[NamespaceAction] = TypeAdapter(NamespaceAction)
    action = adapter.validate_python(data)
    assert isinstance(action, DeleteNamespaceAction)


def test_request_frozen() -> None:
    req = OpenShiftNamespacesReconcileRequest(clusters=[_cluster()])
    with pytest.raises(ValidationError):
        req.dry_run = False  # type: ignore[misc]


def test_request_dry_run_defaults_true() -> None:
    req = OpenShiftNamespacesReconcileRequest(clusters=[])
    assert req.dry_run is True


def test_request_with_namespaces() -> None:
    ns = [DesiredNamespace(name="app-a"), DesiredNamespace(name="app-b", delete=True)]
    req = OpenShiftNamespacesReconcileRequest(
        clusters=[_cluster(namespaces=ns)],
        dry_run=False,
    )
    assert len(req.clusters) == 1
    assert len(req.clusters[0].namespaces) == 2
    assert req.clusters[0].namespaces[1].delete is True


def test_task_result_extends_base() -> None:
    result = OpenShiftNamespacesTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[CreateNamespaceAction(cluster="c", namespace="n")],
        applied_actions=[CreateNamespaceAction(cluster="c", namespace="n")],
        applied_count=1,
    )
    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert result.applied_count == 1


def test_task_result_empty_defaults() -> None:
    result = OpenShiftNamespacesTaskResult(status=TaskStatus.PENDING)
    assert result.actions == []
    assert result.applied_actions == []
    assert result.applied_count == 0
    assert result.errors == []


def test_task_response() -> None:
    resp = OpenShiftNamespacesTaskResponse(
        id="task-123",
        status=TaskStatus.PENDING,
        status_url="http://api/reconcile/task-123",
    )
    assert resp.id == "task-123"


def test_desired_namespace_defaults() -> None:
    ns = DesiredNamespace(name="app-a")
    assert ns.delete is False


def test_desired_namespace_delete() -> None:
    ns = DesiredNamespace(name="app-a", delete=True)
    assert ns.delete is True


def test_cluster_namespaces_has_secret_ref() -> None:
    cluster = _cluster()
    assert cluster.automation_token.path == "k8s/prod/token"
    assert cluster.automation_token.field == "token"


def test_action_serialization_roundtrip() -> None:
    action = CreateNamespaceAction(cluster="prod-1", namespace="app-a")
    data = action.model_dump()
    restored = CreateNamespaceAction.model_validate(data)
    assert restored == action
