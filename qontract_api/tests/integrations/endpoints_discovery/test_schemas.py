"""Tests for endpoints-discovery API schemas."""

import pytest
from pydantic import TypeAdapter, ValidationError

from qontract_api.integrations.endpoints_discovery.domain import (
    AppInterfaceRepo,
    ClusterConnection,
    CurrentEndpoint,
    DesiredApp,
    NamespaceDesiredState,
)
from qontract_api.integrations.endpoints_discovery.schemas import (
    AddEndpointAction,
    ChangeEndpointAction,
    DeleteEndpointAction,
    EndpointAction,
    EndpointsDiscoveryReconcileRequest,
    EndpointsDiscoveryTaskResult,
    MergeRequestStatus,
)
from qontract_api.models import Secret, TaskStatus


def _secret() -> Secret:
    return Secret(
        secret_manager_url="https://vault.example.org",
        path="cluster/token",
        field="token",
    )


def _request() -> EndpointsDiscoveryReconcileRequest:
    cluster = ClusterConnection(
        cluster_name="cluster-1",
        server_url="https://cluster-1:6443",
        automation_token=_secret(),
    )
    app = DesiredApp(
        name="app-1",
        path="/services/app-1/app.yml",
        end_points=[CurrentEndpoint(name="manual", url="manual.example.com:443")],
        namespaces=[
            NamespaceDesiredState(name="ns-1", cluster=cluster),
        ],
    )
    return EndpointsDiscoveryReconcileRequest(
        endpoint_template="name: {{ endpoint_name }}\nurl: {{ route.url }}\n",
        app_interface=AppInterfaceRepo(
            repo_url="https://gitlab.example.com/group/app-interface",
            token=_secret(),
        ),
        apps=[app],
    )


def test_request_dry_run_defaults_to_true() -> None:
    """The request defaults to dry-run."""
    assert _request().dry_run is True


def test_request_frozen() -> None:
    """The request is immutable."""
    request = _request()
    with pytest.raises(ValidationError):
        request.dry_run = False  # type: ignore[misc]


def test_request_requires_endpoint_template() -> None:
    """The endpoint template is required so the server never guesses a default."""
    with pytest.raises(ValidationError):
        EndpointsDiscoveryReconcileRequest(  # type: ignore[call-arg]
            app_interface=AppInterfaceRepo(
                repo_url="https://gitlab.example.com/group/app-interface",
                token=_secret(),
            ),
            apps=[],
        )


def test_action_union_discriminates_add() -> None:
    """The action union deserializes an add action."""
    action = TypeAdapter(EndpointAction).validate_python({
        "action_type": "add_endpoint",
        "app_name": "app-1",
        "app_path": "/services/app-1/app.yml",
        "cluster": "cluster-1",
        "namespace": "ns-1",
        "endpoint_name": "endpoints-discovery/cluster-1/ns-1/route-a",
        "data": {"name": "endpoints-discovery/cluster-1/ns-1/route-a"},
    })

    assert isinstance(action, AddEndpointAction)
    assert action.endpoint_name == "endpoints-discovery/cluster-1/ns-1/route-a"


def test_action_union_discriminates_change() -> None:
    """The action union deserializes a change action."""
    action = TypeAdapter(EndpointAction).validate_python({
        "action_type": "change_endpoint",
        "app_name": "app-1",
        "app_path": "/services/app-1/app.yml",
        "cluster": "cluster-1",
        "namespace": "ns-1",
        "endpoint_name": "endpoints-discovery/cluster-1/ns-1/route-a",
        "data": {"name": "endpoints-discovery/cluster-1/ns-1/route-a"},
    })

    assert isinstance(action, ChangeEndpointAction)


def test_action_union_discriminates_delete() -> None:
    """The action union deserializes a delete action without rendered data."""
    action = TypeAdapter(EndpointAction).validate_python({
        "action_type": "delete_endpoint",
        "app_name": "app-1",
        "app_path": "/services/app-1/app.yml",
        "endpoint_name": "endpoints-discovery/cluster-1/ns-gone/route-a",
    })

    assert isinstance(action, DeleteEndpointAction)
    assert action.cluster is None
    assert action.namespace is None


def test_action_frozen() -> None:
    """Actions are immutable."""
    action = DeleteEndpointAction(
        app_name="app-1",
        app_path="/services/app-1/app.yml",
        endpoint_name="endpoints-discovery/cluster-1/ns-1/route-a",
    )
    with pytest.raises(ValidationError):
        action.app_name = "other"  # type: ignore[misc]


def test_task_result_defaults() -> None:
    """The task result starts empty, with no merge request outcome."""
    result = EndpointsDiscoveryTaskResult(status=TaskStatus.SUCCESS)

    assert result.actions == []
    assert result.applied_actions == []
    assert result.applied_count == 0
    assert result.apps_with_changes == 0
    assert result.mr_status is None
    assert result.mr_url is None
    assert result.errors == []


def test_task_result_carries_mr_outcome() -> None:
    """The task result records the merge request outcome separately from actions."""
    result = EndpointsDiscoveryTaskResult(
        status=TaskStatus.SUCCESS,
        apps_with_changes=2,
        mr_status=MergeRequestStatus.CREATED,
        mr_url="https://gitlab.example.com/group/app-interface/-/merge_requests/1",
    )

    assert result.mr_status == "created"
    assert result.apps_with_changes == 2


def test_merge_request_status_values() -> None:
    """The merge request status enum covers every lifecycle outcome."""
    assert {status.value for status in MergeRequestStatus} == {
        "created",
        "exists",
        "closed_outdated",
        "not_needed",
        "failed",
    }
