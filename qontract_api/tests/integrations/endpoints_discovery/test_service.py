"""Tests for the endpoints-discovery reconciliation service."""

from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.kubernetes import Route
from qontract_utils.vcs.provider_protocol import (
    CreateMergeRequestInput,
    MergeRequestInfo,
)

from qontract_api.integrations.endpoints_discovery.domain import (
    AppInterfaceRepo,
    ClusterConnection,
    CurrentEndpoint,
    DesiredApp,
    NamespaceDesiredState,
)
from qontract_api.integrations.endpoints_discovery.mr import (
    LABEL,
    render_description,
    render_merge_request_content,
    render_title,
)
from qontract_api.integrations.endpoints_discovery.schemas import (
    AddEndpointAction,
    ChangeEndpointAction,
    DeleteEndpointAction,
    EndpointsDiscoveryReconcileRequest,
    MergeRequestStatus,
)
from qontract_api.integrations.endpoints_discovery.service import (
    EndpointsDiscoveryService,
)
from qontract_api.kubernetes.workspace_client import KubernetesWorkspaceClient
from qontract_api.models import Secret, TaskStatus
from qontract_api.vcs.vcs_workspace_client import VCSWorkspaceClient

CLUSTER_NAME = "cluster-1"
NAMESPACE_NAME = "ns-1"
APP_PATH = "/services/app-1/app.yml"
REPO_PATH = "data/services/app-1/app.yml"
PREFIX = f"endpoints-discovery/{CLUSTER_NAME}/{NAMESPACE_NAME}/"
MR_URL = "https://gitlab.example.com/group/app-interface/-/merge_requests/1"

TEMPLATE = """\
name: {{ endpoint_name }}
url: {{ route.url }}
"""


def _secret() -> Secret:
    return Secret(
        secret_manager_url="https://vault.example.org",
        path="cluster/token",
        field="token",
    )


def _cluster(
    cluster_name: str = CLUSTER_NAME,
    *,
    disabled_integrations: list[str] | None = None,
) -> ClusterConnection:
    return ClusterConnection(
        cluster_name=cluster_name,
        server_url=f"https://{cluster_name}:6443",
        automation_token=_secret(),
        disabled_integrations=disabled_integrations or [],
    )


def _namespace(
    name: str = NAMESPACE_NAME,
    *,
    cluster: ClusterConnection | None = None,
    labels: dict[str, str] | None = None,
    delete: bool = False,
    discover: bool = True,
) -> NamespaceDesiredState:
    return NamespaceDesiredState(
        name=name,
        labels=labels or {},
        delete=delete,
        discover=discover,
        cluster=cluster or _cluster(),
    )


def _app(
    *,
    end_points: list[CurrentEndpoint] | None = None,
    namespaces: list[NamespaceDesiredState] | None = None,
    labels: dict[str, str] | None = None,
) -> DesiredApp:
    return DesiredApp(
        name="app-1",
        path=APP_PATH,
        labels=labels or {},
        end_points=end_points or [],
        namespaces=namespaces if namespaces is not None else [_namespace()],
    )


def _request(
    apps: list[DesiredApp],
    *,
    dry_run: bool = True,
    auto_merge: bool = False,
) -> EndpointsDiscoveryReconcileRequest:
    return EndpointsDiscoveryReconcileRequest(
        dry_run=dry_run,
        auto_merge=auto_merge,
        endpoint_template=TEMPLATE,
        app_interface=AppInterfaceRepo(
            repo_url="https://gitlab.example.com/group/app-interface",
            token=_secret(),
        ),
        apps=apps,
    )


@pytest.fixture
def cluster_client() -> MagicMock:
    mock = MagicMock(spec=KubernetesWorkspaceClient)
    mock.list_routes.return_value = []
    mock.namespace_exists_uncached.return_value = True
    return mock


@pytest.fixture
def vcs_client() -> MagicMock:
    mock = MagicMock(spec=VCSWorkspaceClient)
    mock.list_open_merge_requests.return_value = []
    mock.get_file.return_value = "---\nname: app-1\n"
    mock.create_merge_request.return_value = MR_URL
    return mock


@pytest.fixture
def service(
    cluster_client: MagicMock, vcs_client: MagicMock
) -> EndpointsDiscoveryService:
    return EndpointsDiscoveryService(
        cluster_clients={CLUSTER_NAME: cluster_client},
        vcs_client=vcs_client,
    )


# --- Planning ---


def test_dry_run_plans_add_change_and_delete(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
    vcs_client: MagicMock,
) -> None:
    """Managed endpoints are diffed on URL; manual endpoints are ignored."""
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True),
        Route(name="route-b", host="b.example.com", tls=True),
    ]
    app = _app(
        end_points=[
            CurrentEndpoint(name=f"{PREFIX}route-b", url="b.example.com:80"),
            CurrentEndpoint(name=f"{PREFIX}route-c", url="c.example.com:80"),
            CurrentEndpoint(name="manual-endpoint", url="manual.example.com:443"),
        ]
    )

    result = service.reconcile(_request([app]), dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert result.apps_with_changes == 1
    assert result.mr_status is None
    assert result.mr_url is None
    assert result.applied_actions == []
    assert result.applied_count == 0
    assert result.errors == []

    assert {action.action_type for action in result.actions} == {
        "add_endpoint",
        "change_endpoint",
        "delete_endpoint",
    }
    add_action = next(
        action for action in result.actions if isinstance(action, AddEndpointAction)
    )
    assert add_action.endpoint_name == f"{PREFIX}route-a"
    assert add_action.data == {
        "name": f"{PREFIX}route-a",
        "url": "a.example.com:443",
    }
    change_action = next(
        action for action in result.actions if isinstance(action, ChangeEndpointAction)
    )
    assert change_action.endpoint_name == f"{PREFIX}route-b"
    assert change_action.data["url"] == "b.example.com:443"
    delete_action = next(
        action for action in result.actions if isinstance(action, DeleteEndpointAction)
    )
    assert delete_action.endpoint_name == f"{PREFIX}route-c"
    assert {action.app_name for action in result.actions} == {"app-1"}
    assert {action.app_path for action in result.actions} == {APP_PATH}
    assert {action.cluster for action in result.actions} == {CLUSTER_NAME}
    assert {action.namespace for action in result.actions} == {NAMESPACE_NAME}

    vcs_client.list_open_merge_requests.assert_not_called()
    vcs_client.create_merge_request.assert_not_called()


@pytest.mark.parametrize(
    "disabled_name", ["endpoints-discovery", "endpoints-discovery-api"]
)
def test_disabled_integration_is_skipped(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
    disabled_name: str,
) -> None:
    """Either the legacy or the API integration name disables a cluster."""
    app = _app(
        namespaces=[_namespace(cluster=_cluster(disabled_integrations=[disabled_name]))]
    )

    result = service.reconcile(_request([app]), dry_run=True)

    assert result.actions == []
    assert result.apps_with_changes == 0
    cluster_client.list_routes.assert_not_called()
    cluster_client.namespace_exists_uncached.assert_not_called()


def test_deleted_namespace_endpoints_are_deleted(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
) -> None:
    """Endpoints of a namespace marked delete are removed without discovery."""
    app = _app(
        end_points=[CurrentEndpoint(name=f"{PREFIX}route-a", url="a.example.com:80")],
        namespaces=[_namespace(delete=True)],
    )

    result = service.reconcile(_request([app]), dry_run=True)

    assert [action.action_type for action in result.actions] == ["delete_endpoint"]
    assert result.actions[0].cluster == CLUSTER_NAME
    assert result.actions[0].namespace == NAMESPACE_NAME
    cluster_client.list_routes.assert_not_called()


def test_endpoints_of_removed_namespace_are_deleted(
    service: EndpointsDiscoveryService,
) -> None:
    """Endpoints whose namespace left the app config are deleted."""
    app = _app(
        end_points=[
            CurrentEndpoint(
                name=f"endpoints-discovery/{CLUSTER_NAME}/ns-gone/route-a",
                url="a.example.com:80",
            )
        ],
        namespaces=[_namespace()],
    )

    result = service.reconcile(_request([app]), dry_run=True)

    assert [action.action_type for action in result.actions] == ["delete_endpoint"]
    assert result.actions[0].endpoint_name.endswith("/ns-gone/route-a")
    assert result.actions[0].cluster == CLUSTER_NAME
    assert result.actions[0].namespace == "ns-gone"


def test_filtered_namespace_endpoints_are_preserved(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
) -> None:
    """A namespace excluded from discovery must not lose its endpoints."""
    app = _app(
        end_points=[CurrentEndpoint(name=f"{PREFIX}route-a", url="a.example.com:80")],
        namespaces=[_namespace(discover=False)],
    )

    result = service.reconcile(_request([app]), dry_run=True)

    assert result.actions == []
    cluster_client.list_routes.assert_not_called()


def test_missing_namespace_deletes_managed_endpoints(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
) -> None:
    """A definitively absent namespace yields no routes, so endpoints are deleted."""
    cluster_client.namespace_exists_uncached.return_value = False
    app = _app(
        end_points=[CurrentEndpoint(name=f"{PREFIX}route-a", url="a.example.com:80")]
    )

    result = service.reconcile(_request([app]), dry_run=True)

    assert [action.action_type for action in result.actions] == ["delete_endpoint"]
    cluster_client.list_routes.assert_not_called()


def test_route_listing_error_fails_closed(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
) -> None:
    """An unreadable namespace must not produce deletions."""
    cluster_client.list_routes.side_effect = RuntimeError("forbidden")
    app = _app(
        end_points=[CurrentEndpoint(name=f"{PREFIX}route-a", url="a.example.com:80")]
    )

    result = service.reconcile(_request([app]), dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert result.apps_with_changes == 0
    assert len(result.errors) == 1
    assert NAMESPACE_NAME in result.errors[0]


def test_namespace_check_error_fails_closed(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
) -> None:
    """An error while checking namespace existence must not produce deletions."""
    cluster_client.namespace_exists_uncached.side_effect = RuntimeError("boom")
    app = _app(
        end_points=[CurrentEndpoint(name=f"{PREFIX}route-a", url="a.example.com:80")]
    )

    result = service.reconcile(_request([app]), dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert len(result.errors) == 1


def test_unexpected_planning_error_isolates_to_that_app(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
) -> None:
    """One app failing during planning does not discard the others."""
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True)
    ]
    healthy = _app()
    broken = _app().model_copy(update={"name": "app-2"})
    original = service._plan_app

    def _fail_for_app_2(app: DesiredApp, template: str) -> tuple[object, list[str]]:
        if app.name == "app-2":
            raise RuntimeError("boom")
        return original(app, template)

    with patch.object(service, "_plan_app", side_effect=_fail_for_app_2):
        result = service.reconcile(_request([healthy, broken]), dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert result.actions
    assert any("app-2" in error for error in result.errors)


def test_unexpected_merge_request_error_marks_result_failed(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
) -> None:
    """An unexpected apply failure is reported, not raised."""
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True)
    ]

    with patch.object(
        service, "_reconcile_merge_request", side_effect=RuntimeError("boom")
    ):
        result = service.reconcile(_request([_app()], dry_run=False), dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert result.mr_status == MergeRequestStatus.FAILED
    assert result.actions
    assert any(
        "merge request reconciliation failed" in error for error in result.errors
    )


def test_missing_cluster_client_is_an_error(vcs_client: MagicMock) -> None:
    """A cluster without a client fails closed."""
    service = EndpointsDiscoveryService(cluster_clients={}, vcs_client=vcs_client)

    result = service.reconcile(_request([_app()]), dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert "no client for cluster" in result.errors[0]


@pytest.mark.parametrize("label_source", ["app", "namespace"])
def test_ignored_routes_are_filtered(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
    label_source: str,
) -> None:
    """The ignore key uses the merged, pipe-joined route name."""
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True),
        Route(name="route-b", host="a.example.com", tls=True),
    ]
    ignore_key = "endpoints-discovery-route-a|route-b"
    app = _app(
        end_points=[
            CurrentEndpoint(name=f"{PREFIX}route-a|route-b", url="a.example.com:443")
        ],
        labels={ignore_key: "ignored"} if label_source == "app" else None,
        namespaces=[
            _namespace(
                labels={ignore_key: "ignored"} if label_source == "namespace" else None
            )
        ],
    )

    result = service.reconcile(_request([app]), dry_run=True)

    assert [action.action_type for action in result.actions] == ["delete_endpoint"]


# --- Applying ---


def test_live_run_creates_merge_request(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
    vcs_client: MagicMock,
) -> None:
    """A changed app yields one update operation and one MR."""
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True)
    ]
    request = _request([_app()], dry_run=False)

    result = service.reconcile(request, dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.mr_status == MergeRequestStatus.CREATED
    assert result.mr_url == MR_URL
    assert result.applied_actions == result.actions
    assert result.applied_count == 1
    assert result.apps_with_changes == 1

    vcs_client.get_file.assert_called_once_with(REPO_PATH, ref="master")
    vcs_client.create_merge_request.assert_called_once()
    mr_input = vcs_client.create_merge_request.call_args[0][0]
    assert isinstance(mr_input, CreateMergeRequestInput)
    assert mr_input.title == render_title()
    assert mr_input.labels == [LABEL]
    assert mr_input.auto_merge is False
    assert mr_input.target_branch == "master"
    assert len(mr_input.file_operations) == 1
    file_op = mr_input.file_operations[0]
    assert file_op.path == REPO_PATH
    assert f"{PREFIX}route-a" in (file_op.content or "")
    assert (
        file_op.commit_message
        == "endpoints-discovery: update application endpoints for app-1"
    )
    assert mr_input.description.startswith("\nThis MR is triggered by app-interface's")


def test_live_run_existing_up_to_date_mr_is_a_noop(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
    vcs_client: MagicMock,
) -> None:
    """A matching hash means the open MR already contains this plan."""
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True)
    ]
    request = _request([_app()], dry_run=False)

    service.reconcile(request, dry_run=False)
    description = vcs_client.create_merge_request.call_args[0][0].description
    vcs_client.create_merge_request.reset_mock()
    vcs_client.list_open_merge_requests.return_value = [
        MergeRequestInfo(
            title=render_title(),
            description=description,
            web_url=MR_URL,
            labels=[LABEL],
        )
    ]

    result = service.reconcile(request, dry_run=False)

    assert result.mr_status == MergeRequestStatus.EXISTS
    assert result.mr_url == MR_URL
    assert result.applied_actions == []
    assert result.applied_count == 0
    vcs_client.create_merge_request.assert_not_called()


def test_live_run_outdated_mr_is_closed_without_replacement(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
    vcs_client: MagicMock,
) -> None:
    """A stale MR is closed, and no replacement opens in the same run."""
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True)
    ]
    vcs_client.list_open_merge_requests.return_value = [
        MergeRequestInfo(
            title=render_title(),
            description=render_description(plan_hash="deadbeef"),
            web_url="https://gitlab.example.com/mr/9",
            labels=[LABEL],
        )
    ]

    result = service.reconcile(_request([_app()], dry_run=False), dry_run=False)

    assert result.mr_status == MergeRequestStatus.CLOSED_OUTDATED
    vcs_client.close_merge_request.assert_called_once_with(
        "https://gitlab.example.com/mr/9",
        comment="Closing this MR because it's outdated.",
    )
    vcs_client.create_merge_request.assert_not_called()


@pytest.mark.parametrize(
    ("description", "has_conflicts"),
    [
        ("not machine readable", False),
        (render_description(plan_hash="x").replace("1.0.0", "0.9.0"), False),
        (
            render_description(plan_hash="x").replace(
                "integration: endpoints-discovery", "integration: other"
            ),
            False,
        ),
        (render_description(plan_hash="x"), True),
    ],
)
def test_live_run_invalid_or_conflicted_mr_is_closed_then_replaced(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
    vcs_client: MagicMock,
    description: str,
    has_conflicts: bool,
) -> None:
    """Malformed, mismatched or conflicted MRs are closed and replaced."""
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True)
    ]
    vcs_client.list_open_merge_requests.return_value = [
        MergeRequestInfo(
            title=render_title(),
            description=description,
            web_url="https://gitlab.example.com/mr/7",
            labels=[LABEL],
            has_conflicts=has_conflicts,
        )
    ]

    result = service.reconcile(_request([_app()], dry_run=False), dry_run=False)

    vcs_client.close_merge_request.assert_called_once()
    assert (
        "invalid or has conflicts"
        in (vcs_client.close_merge_request.call_args.kwargs["comment"])
    )
    assert result.mr_status == MergeRequestStatus.CREATED
    vcs_client.create_merge_request.assert_called_once()


def test_live_run_missing_app_file_fails_closed(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
    vcs_client: MagicMock,
) -> None:
    """A file that cannot be read produces an error, never a partial MR."""
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True)
    ]
    vcs_client.get_file.return_value = None

    result = service.reconcile(_request([_app()], dry_run=False), dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert result.mr_status == MergeRequestStatus.FAILED
    assert result.applied_actions == []
    assert result.errors
    vcs_client.create_merge_request.assert_not_called()


def test_live_run_unchanged_content_creates_no_mr(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
    vcs_client: MagicMock,
) -> None:
    """A change rendering to the same content produces no commit and no MR.

    This happens when the branch is ahead of App-Interface: GraphQL still
    reports the old URL, so a change is planned, but the file already holds
    the rendered endpoint.
    """
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True)
    ]
    endpoint_name = f"{PREFIX}route-a"
    current_content = render_merge_request_content(
        current_content="---\nname: app-1\n",
        endpoints_to_add=[{"name": endpoint_name, "url": "a.example.com:443"}],
        endpoints_to_change={},
        endpoints_to_delete=[],
    )
    vcs_client.get_file.return_value = current_content
    app = _app(end_points=[CurrentEndpoint(name=endpoint_name, url="a.example.com:80")])

    result = service.reconcile(_request([app], dry_run=False), dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.mr_status == MergeRequestStatus.NOT_NEEDED
    assert result.applied_actions == []
    vcs_client.create_merge_request.assert_not_called()


def test_live_run_without_changes_is_not_needed(
    service: EndpointsDiscoveryService,
    vcs_client: MagicMock,
) -> None:
    """An empty plan never touches the repository."""
    result = service.reconcile(_request([_app()], dry_run=False), dry_run=False)

    assert result.mr_status == MergeRequestStatus.NOT_NEEDED
    assert result.apps_with_changes == 0
    vcs_client.list_open_merge_requests.assert_not_called()
    vcs_client.get_file.assert_not_called()
    vcs_client.create_merge_request.assert_not_called()


def test_auto_merge_is_propagated(
    service: EndpointsDiscoveryService,
    cluster_client: MagicMock,
    vcs_client: MagicMock,
) -> None:
    """The client-resolved auto-merge flag reaches the merge request input."""
    cluster_client.list_routes.return_value = [
        Route(name="route-a", host="a.example.com", tls=True)
    ]

    service.reconcile(_request([_app()], dry_run=False, auto_merge=True), dry_run=False)

    mr_input = vcs_client.create_merge_request.call_args[0][0]
    assert mr_input.auto_merge is True
