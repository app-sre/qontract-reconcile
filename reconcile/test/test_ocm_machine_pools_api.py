"""Tests for the ocm-machine-pools-api client-side integration."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from qontract_api_client.schemas import (
    OcmMachinePoolsActionCreateMachinePool,
    OcmMachinePoolsActionCreateNodePool,
    OcmMachinePoolsTaskResponse,
    OcmMachinePoolsTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.ocm_machine_pools_api.clusters import (
    ClusterMachinePoolV1,
    ClusterSpecV1,
    ClusterV1,
    OpenShiftClusterManagerV1,
    TaintV1,
)
from reconcile.ocm_machine_pools_api import (
    OcmMachinePoolsIntegration,
    OcmMachinePoolsIntegrationParams,
)

SECRET_MANAGER_URL = "https://vault.example.com"

# Module path for patching
_MOD = "reconcile.ocm_machine_pools_api"

OcmMachinePoolsAction = (
    OcmMachinePoolsActionCreateMachinePool | OcmMachinePoolsActionCreateNodePool
)


class _TestableIntegration(OcmMachinePoolsIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def make_integration() -> _TestableIntegration:
    return _TestableIntegration(OcmMachinePoolsIntegrationParams())


def make_pool(
    pool_id: str = "worker",
    instance_type: str = "m5.xlarge",
    replicas: int | None = 3,
    min_replicas: int | None = None,
    max_replicas: int | None = None,
    labels: dict[str, str] | None = None,
    subnet: str | None = None,
    taints: list[TaintV1] | None = None,
) -> ClusterMachinePoolV1:
    """Build a typed machine pool matching the GQL schema.

    labels arrives JSON-serialized (the GQL JSON scalar validates from a
    string and pydantic parses it), like a real gql response would.
    """
    return ClusterMachinePoolV1(
        id=pool_id,
        instance_type=instance_type,
        replicas=replicas,
        autoscale=(
            {"min_replicas": min_replicas, "max_replicas": max_replicas}
            if min_replicas is not None
            else None
        ),
        labels=json.dumps(labels) if labels is not None else None,
        subnet=subnet,
        taints=taints,
    )


def make_cluster(
    name: str = "my-cluster",
    *,
    spec_id: str = "cluster-1",
    product: str = "osd",
    hypershift: bool | None = False,
    pools: list[ClusterMachinePoolV1] | None = None,
    with_pools: bool = True,
    with_ocm: bool = True,
    ocm_env_name: str = "ocm-production",
    with_spec: bool = True,
) -> ClusterV1:
    """Build a typed ClusterV1 matching the GQL schema.

    with_pools=False builds a cluster whose machinePools are absent
    (None) - distinct from an empty pool list, which the compatibility
    filter treats as present.
    """
    ocm = None
    if with_ocm:
        ocm = OpenShiftClusterManagerV1(
            name=ocm_env_name,
            environment=OCMEnvironment(
                name=ocm_env_name,
                description=f"{ocm_env_name} env",
                labels=None,
                url="https://api.openshift.com",
                accessTokenClientId="client-id",
                accessTokenUrl="https://sso.redhat.com/token",
                accessTokenClientSecret=VaultSecret(
                    path="app-sre/creds/ocm",
                    field="client_secret",
                    version=None,
                    format=None,
                    url=None,
                ),
            ),
            accessTokenClientId=None,
            accessTokenUrl=None,
            accessTokenClientSecret=None,
        )
    return ClusterV1(
        name=name,
        spec=(
            ClusterSpecV1(id=spec_id, product=product, hypershift=hypershift)
            if with_spec
            else None
        ),
        machinePools=(
            (pools if pools is not None else [make_pool()]) if with_pools else None
        ),
        ocm=ocm,
        disable=None,
    )


def make_task_response(task_id: str = "task-123") -> OcmMachinePoolsTaskResponse:
    return OcmMachinePoolsTaskResponse(
        id=task_id, status=TaskStatus.PENDING, status_url=f"/tasks/{task_id}"
    )


def make_task_result(
    status: TaskStatus = TaskStatus.SUCCESS,
    actions: list[OcmMachinePoolsAction] | None = None,
    errors: list[str] | None = None,
) -> OcmMachinePoolsTaskResult:
    return OcmMachinePoolsTaskResult(
        status=status, actions=actions or [], errors=errors or []
    )


# ---------------------------------------------------------------------------
# async_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_polls_task_and_builds_machine_pool_request() -> None:
    """OSD clusters compile to the machine pool shape and are reconciled."""
    integration = make_integration()
    task_response = make_task_response()
    action = OcmMachinePoolsActionCreateMachinePool(
        cluster="my-cluster", pool_id="extra"
    )
    task_result = make_task_result(actions=[action])

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[make_cluster(product="osd", pools=[make_pool()])],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(return_value=task_response),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=task_result),
        ),
    ):
        await integration.async_run(dry_run=True)

        request = mock_reconcile.call_args.args[0]
        assert request.dry_run is True
        assert request.ocm_environment == "ocm-production"
        assert request.ocm_connection.ocm_url == "https://api.openshift.com"
        assert request.ocm_connection.secret_manager_url == SECRET_MANAGER_URL
        assert request.ocm_connection.access_token_client_id == "client-id"
        assert len(request.clusters) == 1
        assert request.clusters[0].name == "my-cluster"
        assert request.clusters[0].cluster_id == "cluster-1"
        assert request.clusters[0].cluster_type == "osd"
        pool = request.clusters[0].pools[0]
        assert pool.id == "worker"
        assert pool.instance_type == "m5.xlarge"
        assert pool.replicas == 3
        assert pool.autoscaling is None


@pytest.mark.asyncio
async def test_rosa_hcp_compiles_to_node_pool_shape() -> None:
    """rosa + hypershift clusters compile to node pools with singular autoscaling."""
    integration = make_integration()
    pool = make_pool(
        replicas=None,
        min_replicas=2,
        max_replicas=5,
        subnet="subnet-1",
        labels={"tier": "frontend"},
        taints=[TaintV1(key="dedicated", value="frontend", effect="NoSchedule")],
    )

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[make_cluster(product="rosa", hypershift=True, pools=[pool])],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(return_value=make_task_response()),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=make_task_result()),
        ),
    ):
        await integration.async_run(dry_run=True)

        request = mock_reconcile.call_args.args[0]
        assert request.clusters[0].cluster_type == "hypershift"
        node_pool = request.clusters[0].pools[0]
        assert node_pool.id == "worker"
        assert node_pool.aws_node_pool.instance_type == "m5.xlarge"
        assert node_pool.subnet == "subnet-1"
        assert node_pool.replicas is None
        assert node_pool.autoscaling is not None
        assert node_pool.autoscaling.min_replica == 2
        assert node_pool.autoscaling.max_replica == 5
        assert node_pool.labels == {"tier": "frontend"}
        assert node_pool.taints is not None
        assert node_pool.taints[0].key == "dedicated"


@pytest.mark.asyncio
async def test_rosa_classic_compiles_to_machine_pool_shape() -> None:
    """rosa without hypershift clusters compile to machine pools."""
    integration = make_integration()

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[make_cluster(product="rosa", hypershift=False)],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(return_value=make_task_response()),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=make_task_result()),
        ),
    ):
        await integration.async_run(dry_run=True)

        request = mock_reconcile.call_args.args[0]
        assert request.clusters[0].cluster_type == "rosa"
        assert request.clusters[0].pools[0].instance_type == "m5.xlarge"


@pytest.mark.asyncio
async def test_machine_pool_autoscaling_compiles_to_plural_fields() -> None:
    """Machine pool autoscaling keeps the plural field names."""
    integration = make_integration()
    pool = make_pool(replicas=None, min_replicas=1, max_replicas=4)

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[make_cluster(product="osd", pools=[pool])],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(return_value=make_task_response()),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=make_task_result()),
        ),
    ):
        await integration.async_run(dry_run=True)

        request = mock_reconcile.call_args.args[0]
        machine_pool = request.clusters[0].pools[0]
        assert machine_pool.autoscaling is not None
        assert machine_pool.autoscaling.min_replicas == 1
        assert machine_pool.autoscaling.max_replicas == 4


@pytest.mark.asyncio
async def test_unknown_product_raises() -> None:
    """An unrecognized cluster product fails the run."""
    integration = make_integration()

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[make_cluster(product="aro")],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        pytest.raises(IntegrationError, match="unknown cluster type"),
    ):
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_missing_spec_raises() -> None:
    """A cluster without spec fails the run."""
    integration = make_integration()

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[make_cluster(with_spec=False)],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        pytest.raises(IntegrationError, match="missing spec"),
    ):
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_filters_disabled_and_incompatible_clusters() -> None:
    """Each filter rejects its own cluster, independently of the others.

    All clusters except "disabled" are enabled, so "no-ocm" and
    "no-pools" can only be rejected by their compatibility predicates -
    and "no-pools" has machinePools absent (None), not an empty list.
    """
    integration = make_integration()

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[
                make_cluster(name="disabled"),
                make_cluster(name="no-ocm", with_ocm=False),
                make_cluster(name="no-pools", with_pools=False),
                make_cluster(name="enabled"),
            ],
        ),
        patch(
            f"{_MOD}.integration_is_enabled",
            side_effect=lambda integration, cluster: cluster.name != "disabled",
        ),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(return_value=make_task_response()),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=make_task_result()),
        ),
    ):
        await integration.async_run(dry_run=True)

        request = mock_reconcile.call_args.args[0]
        assert [c.name for c in request.clusters] == ["enabled"]


@pytest.mark.asyncio
async def test_non_dry_run_propagates_to_request() -> None:
    """dry_run=False must reach the request payload - a regression that
    hard-codes dry runs would otherwise turn every production run into
    a no-op."""
    integration = make_integration()

    with (
        patch(f"{_MOD}._get_clusters", return_value=[make_cluster()]),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(return_value=make_task_response()),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=make_task_result()),
        ),
    ):
        await integration.async_run(dry_run=False)

        request = mock_reconcile.call_args.args[0]
        assert request.dry_run is False


@pytest.mark.asyncio
async def test_one_request_per_ocm_environment() -> None:
    """Clusters are grouped by OCM environment, one request each."""
    integration = make_integration()

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[
                make_cluster(name="prod-1", ocm_env_name="ocm-production"),
                make_cluster(name="prod-2", ocm_env_name="ocm-production"),
                make_cluster(name="stage-1", ocm_env_name="ocm-stage"),
            ],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(return_value=make_task_response()),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=make_task_result()),
        ),
    ):
        await integration.async_run(dry_run=True)

        assert mock_reconcile.call_count == 2
        environments = {
            call.args[0].ocm_environment for call in mock_reconcile.call_args_list
        }
        assert environments == {"ocm-production", "ocm-stage"}
        for call in mock_reconcile.call_args_list:
            names = {c.name for c in call.args[0].clusters}
            if call.args[0].ocm_environment == "ocm-production":
                assert names == {"prod-1", "prod-2"}
            else:
                assert names == {"stage-1"}


@pytest.mark.asyncio
async def test_task_errors_raise() -> None:
    """Server-side errors are surfaced as IntegrationError."""
    integration = make_integration()

    with (
        patch(f"{_MOD}._get_clusters", return_value=[make_cluster()]),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(return_value=make_task_response()),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(
                return_value=make_task_result(status=TaskStatus.FAILED, errors=["boom"])
            ),
        ),
        pytest.raises(IntegrationError, match="1 error"),
    ):
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_task_timeout_raises() -> None:
    """A task that never completes raises instead of hanging silently."""
    integration = make_integration()

    with (
        patch(f"{_MOD}._get_clusters", return_value=[make_cluster()]),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(return_value=make_task_response()),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=make_task_result(status=TaskStatus.PENDING)),
        ),
        pytest.raises(IntegrationError, match="did not complete"),
    ):
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_no_clusters_is_a_noop() -> None:
    """No clusters in app-interface means no API calls."""
    integration = make_integration()

    with (
        patch(f"{_MOD}._get_clusters", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(),
        ) as mock_reconcile,
    ):
        await integration.async_run(dry_run=True)

        mock_reconcile.assert_not_called()


@pytest.mark.asyncio
async def test_cluster_without_spec_id_skipped() -> None:
    """A cluster missing spec.id is skipped with a warning."""
    integration = make_integration()

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[
                make_cluster(name="no-spec-id", spec_id=""),
                make_cluster(name="ok"),
            ],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}.reconcile_ocm_machine_pools",
            new=AsyncMock(return_value=make_task_response()),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=make_task_result()),
        ),
    ):
        await integration.async_run(dry_run=True)

        request = mock_reconcile.call_args.args[0]
        assert [c.name for c in request.clusters] == ["ok"]


def _connection_kwargs(cluster: ClusterV1) -> dict[str, Any]:
    """Extract the connection params the integration would build."""
    from reconcile.ocm_machine_pools_api import _build_ocm_connection

    connection = _build_ocm_connection(cluster, SECRET_MANAGER_URL)
    return connection.model_dump()


def test_connection_params_from_environment() -> None:
    """Connection params fall back to the OCM environment credentials."""
    cluster = make_cluster()
    kwargs = _connection_kwargs(cluster)
    assert kwargs["ocm_url"] == "https://api.openshift.com"
    assert kwargs["access_token_url"] == "https://sso.redhat.com/token"
    assert kwargs["access_token_client_id"] == "client-id"
    assert kwargs["path"] == "app-sre/creds/ocm"
    assert kwargs["secret_manager_url"] == SECRET_MANAGER_URL


def test_connection_params_cluster_overrides() -> None:
    """Cluster-level OCM credentials override the environment's."""
    cluster = make_cluster()
    assert cluster.ocm is not None
    cluster.ocm.access_token_client_id = "cluster-client-id"
    cluster.ocm.access_token_url = "https://cluster-sso.example.com/token"
    cluster.ocm.access_token_client_secret = VaultSecret(
        path="app-sre/creds/ocm/cluster",
        field="client_secret",
        version=None,
        format=None,
        url=None,
    )
    kwargs = _connection_kwargs(cluster)
    assert kwargs["access_token_client_id"] == "cluster-client-id"
    assert kwargs["access_token_url"] == "https://cluster-sso.example.com/token"
    assert kwargs["path"] == "app-sre/creds/ocm/cluster"


def test_connection_params_missing_credentials_raise() -> None:
    """Missing required OCM credentials fail loudly."""
    cluster = make_cluster()
    assert cluster.ocm is not None
    assert cluster.ocm.environment is not None
    # empty string is falsy - the credential is effectively missing
    cluster.ocm.environment.access_token_client_id = ""

    from reconcile.ocm_machine_pools_api import _build_ocm_connection

    with pytest.raises(IntegrationError, match="required OCM credentials"):
        _build_ocm_connection(cluster, SECRET_MANAGER_URL)
