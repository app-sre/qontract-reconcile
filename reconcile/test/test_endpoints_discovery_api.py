"""Tests for the endpoints-discovery-api client-side integration."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from qontract_api_client.schemas import (
    AddEndpointAction,
    ChangeEndpointAction,
    DeleteEndpointAction,
    EndpointsDiscoveryReconcileRequest,
    EndpointsDiscoveryTaskResponse,
    EndpointsDiscoveryTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError
from qontract_utils.vcs import Provider

from reconcile.endpoints_discovery_api import (
    QONTRACT_INTEGRATION,
    EndpointsDiscoveryApiIntegration,
    EndpointsDiscoveryApiIntegrationParams,
)
from reconcile.gql_definitions.endpoints_discovery_api.apps import (
    AppEndPointsV1,
    AppV1,
    NamespaceV1,
)
from reconcile.gql_definitions.fragments.oc_connection_cluster import (
    AutomationTokenEntryV1,
    DisableClusterAutomationsV1,
    OcConnectionCluster,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.typed_queries.vcs import Vcs

if TYPE_CHECKING:
    from collections.abc import Iterator

SECRET_MANAGER_URL = "https://vault.example.com"
REPO_URL = "https://gitlab.example.com/group/app-interface"


@pytest.fixture(autouse=True)
def patch_secret_manager_url() -> Iterator[None]:
    with patch.object(
        EndpointsDiscoveryApiIntegration,
        "secret_manager_url",
        new_callable=PropertyMock,
        return_value=SECRET_MANAGER_URL,
    ):
        yield


def make_integration(
    *,
    app_name: str | None = None,
    cluster_name: set[str] | None = None,
    internal: bool | None = None,
) -> EndpointsDiscoveryApiIntegration:
    return EndpointsDiscoveryApiIntegration(
        EndpointsDiscoveryApiIntegrationParams(
            app_name=app_name,
            cluster_name=cluster_name,
            internal=internal,
        )
    )


def make_vault_secret(
    path: str = "cluster/token", field: str = "token", version: int = 1
) -> VaultSecret:
    return VaultSecret(path=path, field=field, version=version, format=None, url=None)


def make_token_entry(
    secret: VaultSecret | None = None,
    *,
    active: bool | None = True,
    delete: bool | None = False,
) -> AutomationTokenEntryV1:
    return AutomationTokenEntryV1(
        name="token",
        namespace="app-sre",
        active=active,
        delete=delete,
        secret=secret,
    )


def make_cluster(
    name: str = "cluster-1",
    *,
    server_url: str = "https://cluster-1:6443",
    internal: bool | None = False,
    insecure: bool | None = None,
    token: VaultSecret | None = None,
    tokens: list[AutomationTokenEntryV1] | None = None,
    disabled: list[str] | None = None,
) -> OcConnectionCluster:
    return OcConnectionCluster(
        name=name,
        serverUrl=server_url,
        internal=internal,
        insecureSkipTLSVerify=insecure,
        automationToken=token,
        automationTokens=tokens,
        clusterAdminAutomationToken=None,
        clusterAdminAutomationTokens=None,
        disable=DisableClusterAutomationsV1(integrations=disabled)
        if disabled
        else None,
    )


def make_namespace(
    cluster: OcConnectionCluster,
    *,
    name: str = "ns-1",
    labels: dict | None = None,
    delete: bool | None = False,
) -> NamespaceV1:
    return NamespaceV1(
        name=name,
        labels=json.dumps(labels or {}),
        delete=delete,
        cluster=cluster,
    )


def make_app(
    *,
    name: str = "app-1",
    path: str = "/services/app-1/app.yml",
    labels: dict | None = None,
    end_points: list[AppEndPointsV1] | None = None,
    namespaces: list[NamespaceV1] | None = None,
) -> AppV1:
    return AppV1(
        path=path,
        name=name,
        labels=json.dumps(labels or {}),
        endPoints=end_points or [],
        namespaces=namespaces if namespaces is not None else [],
    )


def make_vcs_instance(url: str = "https://gitlab.example.com") -> Vcs:
    return Vcs(
        name="gitlab",
        url=url,
        token=make_vault_secret(path="app-sre/app-interface-token"),
        provider=Provider.GITLAB,
    )


# --- Basic integration surface ---


def test_name_property() -> None:
    assert make_integration().name == QONTRACT_INTEGRATION


def test_get_apps_parses_query_result() -> None:
    query_func = MagicMock(
        return_value={
            "apps": [
                {
                    "path": "/services/app-1/app.yml",
                    "name": "app-1",
                    "labels": None,
                    "endPoints": None,
                    "namespaces": None,
                }
            ]
        }
    )

    apps = make_integration().get_apps(query_func)

    assert [app.name for app in apps] == ["app-1"]


def test_get_apps_returns_empty_for_null_result() -> None:
    query_func = MagicMock(return_value={"apps": None})

    assert make_integration().get_apps(query_func) == []


# --- Desired state compilation ---


def test_compile_maps_app_and_namespace_fields() -> None:
    cluster = make_cluster(
        token=make_vault_secret(),
        insecure=True,
        disabled=["other-integration"],
    )
    app = make_app(
        labels={"app-label": "value"},
        end_points=[AppEndPointsV1(name="manual", url="manual.example.com:443")],
        namespaces=[make_namespace(cluster, labels={"ns-label": "value"})],
    )

    desired = make_integration().compile_desired_state(
        [app], cluster_names=None, internal=None
    )

    assert len(desired) == 1
    assert desired[0].name == "app-1"
    assert desired[0].path == "/services/app-1/app.yml"
    assert desired[0].labels == {"app-label": "value"}
    assert desired[0].end_points is not None
    assert desired[0].end_points[0].name == "manual"
    assert desired[0].end_points[0].url == "manual.example.com:443"

    namespace = (desired[0].namespaces or [])[0]
    assert namespace.name == "ns-1"
    assert namespace.labels == {"ns-label": "value"}
    assert namespace.discover is True
    assert namespace.cluster.cluster_name == "cluster-1"
    assert namespace.cluster.server_url == "https://cluster-1:6443"
    assert namespace.cluster.insecure_skip_tls_verify is True
    assert namespace.cluster.disabled_integrations == ["other-integration"]
    assert namespace.cluster.automation_token is not None
    assert namespace.cluster.automation_token.path == "cluster/token"
    assert namespace.cluster.automation_token.secret_manager_url == SECRET_MANAGER_URL


def test_compile_prefers_active_list_automation_token() -> None:
    active_secret = make_vault_secret(path="cluster/rotated")
    cluster = make_cluster(
        token=make_vault_secret(path="cluster/legacy"),
        tokens=[
            make_token_entry(make_vault_secret(path="cluster/inactive"), active=False),
            make_token_entry(active_secret),
            make_token_entry(make_vault_secret(path="cluster/deleted"), delete=True),
        ],
    )
    app = make_app(namespaces=[make_namespace(cluster)])

    desired = make_integration().compile_desired_state(
        [app], cluster_names=None, internal=None
    )

    token = (desired[0].namespaces or [])[0].cluster.automation_token
    assert token is not None
    assert token.path == "cluster/rotated"


def test_compile_falls_back_to_legacy_automation_token() -> None:
    cluster = make_cluster(
        token=make_vault_secret(path="cluster/legacy"),
        tokens=[make_token_entry(None)],
    )
    app = make_app(namespaces=[make_namespace(cluster)])

    desired = make_integration().compile_desired_state(
        [app], cluster_names=None, internal=None
    )

    token = (desired[0].namespaces or [])[0].cluster.automation_token
    assert token is not None
    assert token.path == "cluster/legacy"


@pytest.mark.parametrize(
    "disabled_name", ["endpoints-discovery", "endpoints-discovery-api"]
)
def test_compile_disables_cluster_for_either_integration_name(
    disabled_name: str,
) -> None:
    """A cluster disabled for the legacy integration is never discovered."""
    cluster = make_cluster(token=None, disabled=[disabled_name])
    app = make_app(namespaces=[make_namespace(cluster)])

    desired = make_integration().compile_desired_state(
        [app], cluster_names=None, internal=None
    )

    namespace = (desired[0].namespaces or [])[0]
    assert namespace.discover is False
    assert namespace.cluster.automation_token is None


def test_compile_does_not_discover_deleted_namespace() -> None:
    cluster = make_cluster(token=None)
    app = make_app(namespaces=[make_namespace(cluster, delete=True)])

    desired = make_integration().compile_desired_state(
        [app], cluster_names=None, internal=None
    )

    namespace = (desired[0].namespaces or [])[0]
    assert namespace.discover is False
    assert namespace.delete is True


def test_compile_keeps_filtered_namespaces_but_does_not_discover_them() -> None:
    cluster = make_cluster("cluster-2", token=None)
    app = make_app(namespaces=[make_namespace(cluster)])

    desired = make_integration(cluster_name={"cluster-1"}).compile_desired_state(
        [app], cluster_names={"cluster-1"}, internal=None
    )

    namespace = (desired[0].namespaces or [])[0]
    assert namespace.discover is False
    assert namespace.cluster.cluster_name == "cluster-2"


@pytest.mark.parametrize(
    ("internal", "cluster_internal", "expected"),
    [(True, True, True), (True, False, False), (False, True, False)],
)
def test_compile_filters_by_internal(
    internal: bool, cluster_internal: bool, expected: bool
) -> None:
    cluster = make_cluster(internal=cluster_internal, token=make_vault_secret())
    app = make_app(namespaces=[make_namespace(cluster)])

    desired = make_integration(internal=internal).compile_desired_state(
        [app], cluster_names=None, internal=internal
    )

    assert (desired[0].namespaces or [])[0].discover is expected


def test_compile_filters_by_app_name() -> None:
    cluster = make_cluster(token=make_vault_secret())
    apps = [
        make_app(name="app-1", namespaces=[make_namespace(cluster)]),
        make_app(name="app-2", namespaces=[make_namespace(cluster)]),
    ]

    desired = make_integration(app_name="app-2").compile_desired_state(
        apps, cluster_names=None, internal=None
    )

    assert [app.name for app in desired] == ["app-2"]


def test_compile_requires_token_only_for_discovered_namespaces() -> None:
    cluster = make_cluster(token=None)
    app = make_app(namespaces=[make_namespace(cluster)])

    with pytest.raises(IntegrationError, match="no automationToken"):
        make_integration().compile_desired_state(
            [app], cluster_names=None, internal=None
        )


def test_compile_repo_matches_vcs_instance_by_url_prefix() -> None:
    repo = make_integration().compile_app_interface_repo(
        REPO_URL, [make_vcs_instance()]
    )

    assert repo.repo_url == REPO_URL
    assert repo.target_branch == "master"
    assert repo.token.secret_manager_url == SECRET_MANAGER_URL
    assert repo.token.path == "app-sre/app-interface-token"


def test_compile_repo_raises_without_matching_instance() -> None:
    with pytest.raises(IntegrationError, match="no VCS instance"):
        make_integration().compile_app_interface_repo(
            REPO_URL, [make_vcs_instance("https://other.example.com")]
        )


# --- Request building ---


def test_build_request_sets_all_fields() -> None:
    cluster = make_cluster(token=make_vault_secret())
    desired = make_integration().compile_desired_state(
        [make_app(namespaces=[make_namespace(cluster)])],
        cluster_names=None,
        internal=None,
    )
    repo = make_integration().compile_app_interface_repo(
        REPO_URL, [make_vcs_instance()]
    )

    request = make_integration().build_request(
        apps=desired,
        endpoint_template="name: {{ endpoint_name }}\n",
        app_interface=repo,
        auto_merge=True,
        dry_run=False,
    )

    assert isinstance(request, EndpointsDiscoveryReconcileRequest)
    assert request.dry_run is False
    assert request.auto_merge is True
    assert request.endpoint_template == "name: {{ endpoint_name }}\n"
    assert request.app_interface.repo_url == REPO_URL
    assert request.apps[0].name == "app-1"


# --- async_run ---


def _gql_api(template: str = "name: {{ endpoint_name }}\n") -> MagicMock:
    api = MagicMock()
    api.query.return_value = {"apps": []}
    api.get_resource.return_value = {"content": template}
    return api


def test_async_run_returns_early_without_apps() -> None:
    integration = make_integration()
    with (
        patch("reconcile.endpoints_discovery_api.gql.get_api", return_value=_gql_api()),
        patch.object(integration, "get_apps", return_value=[]) as get_apps,
        patch(
            "reconcile.endpoints_discovery_api.endpoints_discovery",
            new_callable=AsyncMock,
        ) as api_call,
    ):
        asyncio.run(integration.async_run(dry_run=True))

    get_apps.assert_called_once()
    api_call.assert_not_awaited()


def test_async_run_returns_when_app_filter_matches_nothing() -> None:
    """An app-name filter that selects nothing skips the API call entirely."""
    integration = make_integration(app_name="other-app")
    apps = [
        make_app(
            name="app-1",
            namespaces=[make_namespace(make_cluster(token=make_vault_secret()))],
        )
    ]

    with (
        patch("reconcile.endpoints_discovery_api.gql.get_api", return_value=_gql_api()),
        patch.object(integration, "get_apps", return_value=apps),
        patch(
            "reconcile.endpoints_discovery_api.endpoints_discovery",
            new_callable=AsyncMock,
        ) as api_call,
    ):
        asyncio.run(integration.async_run(dry_run=True))

    api_call.assert_not_awaited()


def test_async_run_logs_change_and_delete_actions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Change and delete actions are logged individually."""
    integration = make_integration()
    cluster = make_cluster(token=make_vault_secret())
    apps = [make_app(namespaces=[make_namespace(cluster)])]
    response = EndpointsDiscoveryTaskResponse(
        id="task-id", status=TaskStatus.PENDING, status_url="http://status"
    )
    result = EndpointsDiscoveryTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[
            ChangeEndpointAction(
                app_name="app-1",
                app_path="/services/app-1/app.yml",
                cluster="cluster-1",
                namespace="ns-1",
                endpoint_name="endpoints-discovery/cluster-1/ns-1/route-a",
                data={},
            ),
            DeleteEndpointAction(
                app_name="app-1",
                app_path="/services/app-1/app.yml",
                endpoint_name="endpoints-discovery/cluster-1/ns-1/route-b",
            ),
            AddEndpointAction(
                app_name="app-1",
                app_path="/services/app-1/app.yml",
                cluster="cluster-1",
                namespace="ns-1",
                endpoint_name="endpoints-discovery/cluster-1/ns-1/route-c",
                data={},
            ),
        ],
        apps_with_changes=1,
    )

    with (
        patch("reconcile.endpoints_discovery_api.gql.get_api", return_value=_gql_api()),
        patch.object(integration, "get_apps", return_value=apps),
        patch(
            "reconcile.endpoints_discovery_api.get_app_interface_repo_url",
            return_value=REPO_URL,
        ),
        patch(
            "reconcile.endpoints_discovery_api.get_vcs_instances",
            return_value=[make_vcs_instance()],
        ),
        patch(
            "reconcile.endpoints_discovery_api.get_feature_toggle_state",
            return_value=False,
        ),
        patch(
            "reconcile.endpoints_discovery_api.endpoints_discovery",
            new_callable=AsyncMock,
            return_value=response,
        ),
        patch.object(
            integration,
            "poll_task_status",
            new_callable=AsyncMock,
            return_value=result,
        ),
        caplog.at_level(logging.INFO),
    ):
        asyncio.run(integration.async_run(dry_run=True))

    assert "change endpoint" in caplog.text
    assert "delete endpoint" in caplog.text


def test_async_run_dry_run_polls_and_logs() -> None:
    integration = make_integration()
    cluster = make_cluster(token=make_vault_secret())
    apps = [make_app(namespaces=[make_namespace(cluster)])]
    response = EndpointsDiscoveryTaskResponse(
        id="task-id", status=TaskStatus.PENDING, status_url="http://status"
    )
    result = EndpointsDiscoveryTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[
            AddEndpointAction(
                app_name="app-1",
                app_path="/services/app-1/app.yml",
                cluster="cluster-1",
                namespace="ns-1",
                endpoint_name="endpoints-discovery/cluster-1/ns-1/route-a",
                data={},
            )
        ],
        apps_with_changes=1,
    )

    with (
        patch("reconcile.endpoints_discovery_api.gql.get_api", return_value=_gql_api()),
        patch.object(integration, "get_apps", return_value=apps),
        patch(
            "reconcile.endpoints_discovery_api.get_app_interface_repo_url",
            return_value=REPO_URL,
        ),
        patch(
            "reconcile.endpoints_discovery_api.get_vcs_instances",
            return_value=[make_vcs_instance()],
        ),
        patch(
            "reconcile.endpoints_discovery_api.get_feature_toggle_state",
            return_value=False,
        ) as toggle,
        patch(
            "reconcile.endpoints_discovery_api.endpoints_discovery",
            new_callable=AsyncMock,
            return_value=response,
        ) as api_call,
        patch.object(
            integration,
            "poll_task_status",
            new_callable=AsyncMock,
            return_value=result,
        ) as poll,
    ):
        asyncio.run(integration.async_run(dry_run=True))

    toggle.assert_called_once_with(
        "endpoints-discovery-allow-auto-merge-mrs", default=False
    )
    api_call.assert_awaited_once()
    assert api_call.await_args is not None
    request = api_call.await_args.args[0]
    assert request.dry_run is True
    assert request.auto_merge is False
    assert request.endpoint_template == "name: {{ endpoint_name }}\n"
    poll.assert_awaited_once()


def test_async_run_live_does_not_poll() -> None:
    integration = make_integration()
    cluster = make_cluster(token=make_vault_secret())
    apps = [make_app(namespaces=[make_namespace(cluster)])]
    response = EndpointsDiscoveryTaskResponse(
        id="task-id", status=TaskStatus.PENDING, status_url="http://status"
    )

    with (
        patch("reconcile.endpoints_discovery_api.gql.get_api", return_value=_gql_api()),
        patch.object(integration, "get_apps", return_value=apps),
        patch(
            "reconcile.endpoints_discovery_api.get_app_interface_repo_url",
            return_value=REPO_URL,
        ),
        patch(
            "reconcile.endpoints_discovery_api.get_vcs_instances",
            return_value=[make_vcs_instance()],
        ),
        patch(
            "reconcile.endpoints_discovery_api.get_feature_toggle_state",
            return_value=True,
        ),
        patch(
            "reconcile.endpoints_discovery_api.endpoints_discovery",
            new_callable=AsyncMock,
            return_value=response,
        ) as api_call,
        patch.object(integration, "poll_task_status", new_callable=AsyncMock) as poll,
    ):
        asyncio.run(integration.async_run(dry_run=False))

    assert api_call.await_args is not None
    request = api_call.await_args.args[0]
    assert request.dry_run is False
    assert request.auto_merge is True
    poll.assert_not_awaited()


@pytest.mark.parametrize(
    ("status", "errors"),
    [
        (TaskStatus.PENDING, []),
        (TaskStatus.FAILED, ["boom"]),
    ],
)
def test_async_run_raises_on_pending_or_errors(
    status: TaskStatus, errors: list[str]
) -> None:
    integration = make_integration()
    cluster = make_cluster(token=make_vault_secret())
    apps = [make_app(namespaces=[make_namespace(cluster)])]
    response = EndpointsDiscoveryTaskResponse(
        id="task-id", status=TaskStatus.PENDING, status_url="http://status"
    )
    result = EndpointsDiscoveryTaskResult(status=status, errors=errors)

    with (
        patch("reconcile.endpoints_discovery_api.gql.get_api", return_value=_gql_api()),
        patch.object(integration, "get_apps", return_value=apps),
        patch(
            "reconcile.endpoints_discovery_api.get_app_interface_repo_url",
            return_value=REPO_URL,
        ),
        patch(
            "reconcile.endpoints_discovery_api.get_vcs_instances",
            return_value=[make_vcs_instance()],
        ),
        patch(
            "reconcile.endpoints_discovery_api.get_feature_toggle_state",
            return_value=False,
        ),
        patch(
            "reconcile.endpoints_discovery_api.endpoints_discovery",
            new_callable=AsyncMock,
            return_value=response,
        ),
        patch.object(
            integration,
            "poll_task_status",
            new_callable=AsyncMock,
            return_value=result,
        ),
        pytest.raises(IntegrationError),
    ):
        asyncio.run(integration.async_run(dry_run=True))


def test_integration_name() -> None:
    assert QONTRACT_INTEGRATION == "endpoints-discovery-api"
