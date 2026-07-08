"""Tests for openshift-namespaces-api client-side integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_api_client.schemas import (
    OpenShiftNamespacesTaskResponse,
    OpenShiftNamespacesTaskResult,
    TaskStatus,
)

from reconcile.openshift_namespaces_api import (
    QONTRACT_INTEGRATION,
    OpenShiftNamespacesIntegration,
    OpenShiftNamespacesIntegrationParams,
)

SECRET_MANAGER_URL = "https://vault.example.com"


class _TestableIntegration(OpenShiftNamespacesIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


@pytest.fixture
def integration() -> OpenShiftNamespacesIntegration:
    return _TestableIntegration(
        OpenShiftNamespacesIntegrationParams(
            cluster_names=None,
            namespace_name=None,
        )
    )


def test_integration_name(integration: OpenShiftNamespacesIntegration) -> None:
    assert integration.name == QONTRACT_INTEGRATION
    assert integration.name == "openshift-namespaces-api"


@pytest.mark.asyncio(loop_scope="function")
@patch(
    "reconcile.openshift_namespaces_api.openshift_namespaces_reconcile",
    new_callable=AsyncMock,
)
@patch("reconcile.openshift_namespaces_api.get_namespaces_minimal", return_value=[])
async def test_async_run_no_namespaces_returns_early(
    mock_get_ns: MagicMock,
    mock_reconcile: AsyncMock,
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """No namespaces → returns early, no API call."""
    await integration.async_run(dry_run=True)
    mock_reconcile.assert_not_called()


@pytest.mark.asyncio(loop_scope="function")
@patch(
    "reconcile.openshift_namespaces_api.openshift_namespaces_reconcile",
    new_callable=AsyncMock,
)
@patch("reconcile.openshift_namespaces_api.get_namespaces_minimal")
async def test_async_run_dry_run_polls_and_logs(
    mock_get_ns: MagicMock,
    mock_reconcile: AsyncMock,
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """Dry-run: sends request, polls task, logs actions."""
    ns = _make_ns_mock()
    mock_get_ns.return_value = [ns]

    mock_reconcile.return_value = OpenShiftNamespacesTaskResponse(
        id="task-1",
        status=TaskStatus.PENDING,
        status_url="http://api/reconcile/task-1",
    )

    mock_result = OpenShiftNamespacesTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[],
        applied_actions=[],
        applied_count=0,
        errors=[],
    )

    with patch.object(
        integration, "poll_task_status", new_callable=AsyncMock
    ) as mock_poll:
        mock_poll.return_value = mock_result
        await integration.async_run(dry_run=True)
        mock_poll.assert_called_once()
        mock_reconcile.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
@patch(
    "reconcile.openshift_namespaces_api.openshift_namespaces_reconcile",
    new_callable=AsyncMock,
)
@patch("reconcile.openshift_namespaces_api.get_namespaces_minimal")
async def test_async_run_non_dry_run_fires_and_forgets(
    mock_get_ns: MagicMock,
    mock_reconcile: AsyncMock,
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """Non-dry-run: sends request, returns immediately without polling."""
    ns = _make_ns_mock()
    mock_get_ns.return_value = [ns]

    mock_reconcile.return_value = OpenShiftNamespacesTaskResponse(
        id="task-1",
        status=TaskStatus.PENDING,
        status_url="http://api/reconcile/task-1",
    )

    with patch.object(
        integration, "poll_task_status", new_callable=AsyncMock
    ) as mock_poll:
        await integration.async_run(dry_run=False)
        mock_poll.assert_not_called()
        mock_reconcile.assert_called_once()


def test_params_cluster_filter() -> None:
    params = OpenShiftNamespacesIntegrationParams(
        cluster_names=frozenset({"prod-1"}), namespace_name=None
    )
    assert params.cluster_names == frozenset({"prod-1"})


def test_params_multiple_cluster_filter() -> None:
    params = OpenShiftNamespacesIntegrationParams(
        cluster_names=frozenset({"prod-1", "prod-2"}), namespace_name=None
    )
    assert params.cluster_names == frozenset({"prod-1", "prod-2"})


def test_params_namespace_filter() -> None:
    params = OpenShiftNamespacesIntegrationParams(
        cluster_names=None, namespace_name="app-a"
    )
    assert params.namespace_name == "app-a"


def _make_ns_mock(
    name: str = "app-a",
    cluster_name: str = "prod-1",
    delete: bool = False,
    disabled_integrations: list[str] | None = None,
    managed_by_external: bool | None = None,
    insecure_skip_tls_verify: bool | None = None,
) -> MagicMock:
    """Create a mock NamespaceV1 with cluster and disable info."""
    from reconcile.gql_definitions.common.namespaces_minimal import (
        DisableClusterAutomationsV1,
    )

    disable = (
        DisableClusterAutomationsV1(integrations=disabled_integrations)
        if disabled_integrations is not None
        else None
    )

    ns = MagicMock()
    ns.name = name
    ns.delete = delete
    ns.managed_by_external = managed_by_external
    ns.cluster.name = cluster_name
    ns.cluster.server_url = f"https://{cluster_name}:6443"
    ns.cluster.cluster_admin_automation_token.path = f"k8s/{cluster_name}/token"
    ns.cluster.cluster_admin_automation_token.field = "token"
    ns.cluster.cluster_admin_automation_token.version = None
    ns.cluster.insecure_skip_tls_verify = insecure_skip_tls_verify
    ns.cluster.disable = disable
    return ns


def test_disabled_upstream_name_filters_cluster(
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """Cluster with 'openshift-namespaces' disabled is skipped."""
    ns_enabled = _make_ns_mock(name="app-a", cluster_name="enabled-cluster")
    ns_disabled = _make_ns_mock(
        name="app-b",
        cluster_name="disabled-cluster",
        disabled_integrations=["openshift-namespaces"],
    )

    result = integration._apply_filters([ns_enabled, ns_disabled])
    assert len(result) == 1
    assert result[0].cluster.name == "enabled-cluster"


def test_disabled_api_name_filters_cluster(
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """Cluster with 'openshift-namespaces-api' disabled is also skipped."""
    ns = _make_ns_mock(
        disabled_integrations=["openshift-namespaces-api"],
    )

    result = integration._apply_filters([ns])
    assert len(result) == 0


def test_disabled_other_integration_passes(
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """Cluster with OTHER integration disabled still passes."""
    ns = _make_ns_mock(
        disabled_integrations=["some-other-integration"],
    )

    result = integration._apply_filters([ns])
    assert len(result) == 1


def test_disabled_none_passes(
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """Cluster with disable=None passes."""
    ns = _make_ns_mock()

    result = integration._apply_filters([ns])
    assert len(result) == 1


def test_managed_by_external_excluded(
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """Namespaces with managed_by_external=True are excluded."""
    ns_managed = _make_ns_mock(name="ext-ns", managed_by_external=True)
    ns_normal = _make_ns_mock(name="normal-ns", managed_by_external=None)

    result = integration._apply_filters([ns_managed, ns_normal])
    assert len(result) == 1
    assert result[0].name == "normal-ns"


def test_managed_by_external_false_included(
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """Namespaces with managed_by_external=False are included."""
    ns = _make_ns_mock(managed_by_external=False)

    result = integration._apply_filters([ns])
    assert len(result) == 1


def test_compile_desired_state_passes_insecure_skip_tls(
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """insecure_skip_tls_verify from cluster is passed to ClusterNamespaces."""
    ns = _make_ns_mock(insecure_skip_tls_verify=True)

    clusters = integration.compile_desired_state([ns])
    assert len(clusters) == 1
    assert clusters[0].insecure_skip_tls_verify is True


def test_compile_desired_state_defaults_insecure_skip_tls_false(
    integration: OpenShiftNamespacesIntegration,
) -> None:
    """insecure_skip_tls_verify defaults to False when not set on cluster."""
    ns = _make_ns_mock(insecure_skip_tls_verify=None)

    clusters = integration.compile_desired_state([ns])
    assert len(clusters) == 1
    assert clusters[0].insecure_skip_tls_verify is False
