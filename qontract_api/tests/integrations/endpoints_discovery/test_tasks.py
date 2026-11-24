"""Tests for endpoints-discovery Celery tasks."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from qontract_api.integrations.endpoints_discovery.domain import (
    AppInterfaceRepo,
    ClusterConnection,
    CurrentEndpoint,
    DesiredApp,
    NamespaceDesiredState,
)
from qontract_api.integrations.endpoints_discovery.schemas import (
    AddEndpointAction,
    EndpointsDiscoveryReconcileRequest,
    EndpointsDiscoveryTaskResult,
    MergeRequestStatus,
)
from qontract_api.integrations.endpoints_discovery.tasks import (
    _resolve_cluster_connections,
    generate_lock_key,
    reconcile_endpoints_discovery_task,
)
from qontract_api.kubernetes.cluster_client_map import ClusterConnectionParams
from qontract_api.models import Secret, TaskStatus

TASKS_MODULE = "qontract_api.integrations.endpoints_discovery.tasks"
MR_URL = "https://gitlab.example.com/group/app-interface/-/merge_requests/1"


def _secret(field: str | None = "token") -> Secret:
    return Secret(
        secret_manager_url="https://vault.example.org",
        path="cluster/token",
        field=field,
    )


def _cluster(
    cluster_name: str = "cluster-1", server_url: str = "https://cluster-1:6443"
) -> ClusterConnection:
    return ClusterConnection(
        cluster_name=cluster_name,
        server_url=server_url,
        automation_token=_secret(),
    )


def _app() -> DesiredApp:
    return DesiredApp(
        name="app-1",
        path="/services/app-1/app.yml",
        end_points=[CurrentEndpoint(name="manual", url="manual.example.com:443")],
        namespaces=[NamespaceDesiredState(name="ns-1", cluster=_cluster())],
    )


def _request(*, dry_run: bool = True) -> EndpointsDiscoveryReconcileRequest:
    return EndpointsDiscoveryReconcileRequest(
        endpoint_template="name: {{ endpoint_name }}\nurl: {{ route.url }}\n",
        app_interface=AppInterfaceRepo(
            repo_url="https://gitlab.example.com/group/app-interface",
            token=_secret(),
        ),
        apps=[_app()],
        dry_run=dry_run,
    )


def _action() -> AddEndpointAction:
    return AddEndpointAction(
        app_name="app-1",
        app_path="/services/app-1/app.yml",
        cluster="cluster-1",
        namespace="ns-1",
        endpoint_name="endpoints-discovery/cluster-1/ns-1/route-a",
        data={"name": "endpoints-discovery/cluster-1/ns-1/route-a"},
    )


def _task_func() -> Callable[..., EndpointsDiscoveryTaskResult]:
    return reconcile_endpoints_discovery_task.__wrapped__.__wrapped__


@pytest.fixture
def mock_self() -> MagicMock:
    mock = MagicMock()
    mock.request.id = "test-task-id"
    return mock


@contextmanager
def _task_env() -> Generator[SimpleNamespace]:
    """Patch the task's composition-root dependencies."""
    with (
        patch(f"{TASKS_MODULE}.get_cache") as get_cache,
        patch(f"{TASKS_MODULE}.get_secret_manager") as get_secret_manager,
        patch(f"{TASKS_MODULE}.create_vcs_workspace_client") as create_vcs,
        patch(f"{TASKS_MODULE}.ClusterClientMap") as cluster_map_cls,
        patch(f"{TASKS_MODULE}.EndpointsDiscoveryService") as service_cls,
        patch(f"{TASKS_MODULE}.get_event_manager") as get_event_manager,
    ):
        cache = MagicMock()
        get_cache.return_value = cache

        secret_manager = get_secret_manager.return_value
        secret_manager.read_all.return_value = {
            "server": "https://cluster-1:6443",
            "username": "automation",
            "token": "cluster-token",
        }
        secret_manager.read.return_value = "vcs-token"

        vcs_client = create_vcs.return_value
        cluster_map = cluster_map_cls.return_value.__enter__.return_value
        cluster_map.items.return_value = {"cluster-1": MagicMock()}

        event_manager = get_event_manager.return_value

        yield SimpleNamespace(
            cache=cache,
            secret_manager=secret_manager,
            create_vcs=create_vcs,
            vcs_client=vcs_client,
            cluster_map_cls=cluster_map_cls,
            cluster_map=cluster_map,
            service_cls=service_cls,
            service=service_cls.return_value,
            event_manager=event_manager,
        )


# --- Lock key ---


def test_generate_lock_key_is_constant() -> None:
    """Only one MR exists for all apps, so all live runs share one lock."""
    request = _request()

    assert generate_lock_key(MagicMock(), request) == "endpoints-discovery"
    assert generate_lock_key(MagicMock(), _request()) == "endpoints-discovery"


# --- Token resolution ---


def test_resolve_cluster_connections_success() -> None:
    """The token field is selected from the secret, after validating the server."""
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "server": "https://cluster-1:6443",
        "username": "automation",
        "token": "abc",
    }

    params, errors = _resolve_cluster_connections([_app()], secret_manager)

    assert errors == []
    assert params == [
        ClusterConnectionParams(
            cluster_name="cluster-1",
            server="https://cluster-1:6443",
            token="abc",
        )
    ]


def test_resolve_cluster_connections_deduplicates_clusters() -> None:
    """A cluster referenced by several apps is read once."""
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "server": "https://cluster-1:6443",
        "token": "abc",
    }

    _resolve_cluster_connections([_app(), _app()], secret_manager)

    secret_manager.read_all.assert_called_once()


def test_resolve_cluster_connections_skips_non_discover_namespaces() -> None:
    """Filtered namespaces need no connection, so their token is never read."""
    secret_manager = MagicMock()
    app = DesiredApp(
        name="app-1",
        path="/services/app-1/app.yml",
        namespaces=[
            NamespaceDesiredState(name="ns-1", cluster=_cluster(), discover=False)
        ],
    )

    params, errors = _resolve_cluster_connections([app], secret_manager)

    assert params == []
    assert errors == []
    secret_manager.read_all.assert_not_called()


def test_resolve_cluster_connections_skips_deleted_namespaces() -> None:
    """A deleted namespace needs no connection even when discover is true."""
    secret_manager = MagicMock()
    app = DesiredApp(
        name="app-1",
        path="/services/app-1/app.yml",
        namespaces=[
            NamespaceDesiredState(
                name="ns-1",
                cluster=ClusterConnection(
                    cluster_name="cluster-1",
                    server_url="https://cluster-1:6443",
                ),
                delete=True,
            )
        ],
    )

    params, errors = _resolve_cluster_connections([app], secret_manager)

    assert params == []
    assert errors == []
    secret_manager.read_all.assert_not_called()


def test_task_proceeds_when_only_deleted_namespaces_exist(
    mock_self: MagicMock,
) -> None:
    """A deleted namespace with discover left true does not fail the run."""
    request = EndpointsDiscoveryReconcileRequest(
        endpoint_template="name: {{ endpoint_name }}\n",
        app_interface=AppInterfaceRepo(
            repo_url="https://gitlab.example.com/group/app-interface",
            token=_secret(),
        ),
        apps=[
            DesiredApp(
                name="app-1",
                path="/services/app-1/app.yml",
                namespaces=[
                    NamespaceDesiredState(
                        name="ns-1",
                        cluster=ClusterConnection(
                            cluster_name="cluster-1",
                            server_url="https://cluster-1:6443",
                        ),
                        delete=True,
                    )
                ],
            )
        ],
    )

    with _task_env() as env:
        env.service.reconcile.return_value = EndpointsDiscoveryTaskResult(
            status=TaskStatus.SUCCESS
        )

        result = _task_func()(mock_self, request, dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    env.secret_manager.read_all.assert_not_called()
    env.service.reconcile.assert_called_once()


def test_resolve_cluster_connections_requires_a_token() -> None:
    """A discovered namespace on a tokenless cluster is a clear error."""
    secret_manager = MagicMock()
    app = DesiredApp(
        name="app-1",
        path="/services/app-1/app.yml",
        namespaces=[
            NamespaceDesiredState(
                name="ns-1",
                cluster=ClusterConnection(
                    cluster_name="cluster-1",
                    server_url="https://cluster-1:6443",
                ),
            )
        ],
    )

    params, errors = _resolve_cluster_connections([app], secret_manager)

    assert params == []
    assert errors
    assert "automationToken" in errors[0]
    secret_manager.read_all.assert_not_called()


def test_resolve_cluster_connections_server_mismatch_is_an_error() -> None:
    """A token naming another server must never be used for this cluster."""
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "server": "https://other-cluster:6443",
        "token": "abc",
    }

    params, errors = _resolve_cluster_connections([_app()], secret_manager)

    assert params == []
    assert len(errors) == 1
    assert "does not match" in errors[0]


def test_resolve_cluster_connections_requires_a_field() -> None:
    """A secret without a field cannot identify its token entry."""
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "server": "https://cluster-1:6443",
        "token": "abc",
    }
    app = DesiredApp(
        name="app-1",
        path="/services/app-1/app.yml",
        namespaces=[
            NamespaceDesiredState(
                name="ns-1",
                cluster=ClusterConnection(
                    cluster_name="cluster-1",
                    server_url="https://cluster-1:6443",
                    automation_token=_secret(field=None),
                ),
            )
        ],
    )

    params, errors = _resolve_cluster_connections([app], secret_manager)

    assert params == []
    assert errors
    assert "field" in errors[0]


# --- Task body ---


def test_task_reconciles_and_returns_result(
    mock_self: MagicMock,
) -> None:
    """The task resolves secrets, builds clients, and delegates to the service."""
    request = _request(dry_run=False)
    expected = EndpointsDiscoveryTaskResult(status=TaskStatus.SUCCESS)

    with _task_env() as env:
        env.service.reconcile.return_value = expected

        result = _task_func()(mock_self, request, dry_run=False)

    assert result is expected
    env.create_vcs.assert_called_once()
    assert env.create_vcs.call_args.kwargs["repo_url"] == (
        "https://gitlab.example.com/group/app-interface"
    )
    assert env.create_vcs.call_args.kwargs["token"] == "vcs-token"
    env.service_cls.assert_called_once()
    assert env.service_cls.call_args.kwargs["cluster_clients"] == {
        "cluster-1": env.cluster_map.items.return_value["cluster-1"]
    }
    assert env.service_cls.call_args.kwargs["vcs_client"] is env.vcs_client
    env.service.reconcile.assert_called_once_with(request, dry_run=False)


def test_task_fails_when_cluster_tokens_cannot_be_read(
    mock_self: MagicMock,
) -> None:
    """If no cluster token can be resolved, the run fails before any planning."""
    with _task_env() as env:
        env.secret_manager.read_all.side_effect = RuntimeError("denied")

        result = _task_func()(mock_self, _request(), dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert any("Failed to read token for cluster cluster-1" in e for e in result.errors)
    env.service.reconcile.assert_not_called()


def test_task_fails_when_repo_token_cannot_be_read(
    mock_self: MagicMock,
) -> None:
    """A missing App-Interface repository token fails the run."""
    with _task_env() as env:
        env.secret_manager.read_all.return_value = {
            "server": "https://cluster-1:6443",
            "token": "abc",
        }
        env.secret_manager.read.side_effect = RuntimeError("denied")

        result = _task_func()(mock_self, _request(), dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    env.service.reconcile.assert_not_called()


def test_task_reports_unexpected_service_error(mock_self: MagicMock) -> None:
    """An unexpected failure becomes a FAILED result, never an exception."""
    with _task_env() as env:
        env.service.reconcile.side_effect = RuntimeError("boom")

        result = _task_func()(mock_self, _request(), dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert any("Unexpected" in error for error in result.errors)


def test_task_fails_when_dependency_setup_fails(mock_self: MagicMock) -> None:
    """A broken cache or secret manager setup becomes a FAILED result."""
    with (
        patch(f"{TASKS_MODULE}.get_cache", side_effect=RuntimeError("no cache")),
        patch(f"{TASKS_MODULE}.get_secret_manager") as get_secret_manager,
    ):
        result = _task_func()(mock_self, _request(), dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert any("Unexpected" in error for error in result.errors)
    get_secret_manager.assert_not_called()


def test_task_reports_partial_cluster_token_failure(mock_self: MagicMock) -> None:
    """A cluster token failure fails the run without hiding the other cluster."""
    request = EndpointsDiscoveryReconcileRequest(
        endpoint_template="name: {{ endpoint_name }}\n",
        app_interface=AppInterfaceRepo(
            repo_url="https://gitlab.example.com/group/app-interface",
            token=_secret(),
        ),
        apps=[
            DesiredApp(
                name="app-1",
                path="/services/app-1/app.yml",
                namespaces=[
                    NamespaceDesiredState(name="ns-1", cluster=_cluster("cluster-1")),
                    NamespaceDesiredState(
                        name="ns-2",
                        cluster=_cluster(
                            "cluster-2", server_url="https://cluster-2:6443"
                        ),
                    ),
                ],
            )
        ],
    )

    with _task_env() as env:
        env.secret_manager.read_all.side_effect = [
            {"server": "https://cluster-1:6443", "token": "abc"},
            RuntimeError("denied"),
        ]
        env.service.reconcile.return_value = EndpointsDiscoveryTaskResult(
            status=TaskStatus.SUCCESS,
            apps_with_changes=1,
        )

        result = _task_func()(mock_self, request, dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert result.apps_with_changes == 1
    assert any(
        "Failed to read token for cluster cluster-2" in error for error in result.errors
    )


# --- Events ---


def test_task_publishes_action_and_merge_request_events(
    mock_self: MagicMock,
) -> None:
    """A successful live run publishes one event per applied action and the MR."""
    action = _action()
    with _task_env() as env:
        env.service.reconcile.return_value = EndpointsDiscoveryTaskResult(
            status=TaskStatus.SUCCESS,
            actions=[action],
            applied_actions=[action],
            applied_count=1,
            apps_with_changes=1,
            mr_status=MergeRequestStatus.CREATED,
            mr_url=MR_URL,
        )

        _task_func()(mock_self, _request(dry_run=False), dry_run=False)

    event_types = [
        call.args[0].type for call in env.event_manager.publish_event.call_args_list
    ]
    assert event_types == [
        "qontract-api.endpoints-discovery.add_endpoint",
        "qontract-api.endpoints-discovery.merge-request",
    ]


def test_task_publishes_error_events(mock_self: MagicMock) -> None:
    """Errors are published alongside action events."""
    with _task_env() as env:
        env.service.reconcile.return_value = EndpointsDiscoveryTaskResult(
            status=TaskStatus.FAILED,
            errors=["boom"],
        )

        _task_func()(mock_self, _request(dry_run=False), dry_run=False)

    event_types = [
        call.args[0].type for call in env.event_manager.publish_event.call_args_list
    ]
    assert event_types == ["qontract-api.endpoints-discovery.error"]


def test_task_swallows_event_publish_failure(mock_self: MagicMock) -> None:
    """A broken event manager never changes the task result."""
    with _task_env() as env:
        env.service.reconcile.return_value = EndpointsDiscoveryTaskResult(
            status=TaskStatus.SUCCESS,
            apps_with_changes=1,
            mr_status=MergeRequestStatus.CREATED,
            mr_url=MR_URL,
        )
        env.event_manager.publish_event.side_effect = RuntimeError("redis down")

        result = _task_func()(mock_self, _request(dry_run=False), dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.mr_status == MergeRequestStatus.CREATED


def test_task_does_not_publish_events_in_dry_run(mock_self: MagicMock) -> None:
    """Dry runs never publish events."""
    action = _action()
    with _task_env() as env:
        env.service.reconcile.return_value = EndpointsDiscoveryTaskResult(
            status=TaskStatus.SUCCESS,
            actions=[action],
            apps_with_changes=1,
        )

        _task_func()(mock_self, _request(), dry_run=True)

    env.event_manager.publish_event.assert_not_called()
