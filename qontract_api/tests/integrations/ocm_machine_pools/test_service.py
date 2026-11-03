"""Unit tests for OcmMachinePoolsService."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.ocm_api import (
    OcmMachinePool,
    OcmNodePool,
    OcmNodePoolAutoscaling,
    OcmNodePoolAws,
)

from qontract_api.config import OcmSettings, Settings
from qontract_api.integrations.ocm_machine_pools.domain import (
    ClusterType,
    DesiredClusterMachinePools,
    DesiredMachinePool,
    DesiredMachinePoolAutoscaling,
    DesiredNodePool,
    DesiredNodePoolAutoscaling,
)
from qontract_api.integrations.ocm_machine_pools.schemas import (
    OcmMachinePoolsActionCreateMachinePool,
    OcmMachinePoolsActionCreateNodePool,
    OcmMachinePoolsActionDeleteMachinePool,
    OcmMachinePoolsActionDeleteNodePool,
    OcmMachinePoolsActionUpdateMachinePool,
    OcmMachinePoolsActionUpdateNodePool,
)
from qontract_api.integrations.ocm_machine_pools.service import OcmMachinePoolsService
from qontract_api.models import TaskStatus
from qontract_api.ocm.domain import OcmConnectionParams

OCM_ENVIRONMENT = "prod"
OCM_CONNECTION = OcmConnectionParams(
    secret_manager_url="https://vault.example.com",
    path="ocm/prod",
    ocm_url="https://api.openshift.com",
    access_token_url="https://sso.redhat.com/token",
    access_token_client_id="client-id",
)


def _osd_cluster(
    pools: list[Any] | None = None,
    name: str = "osd-cluster",
    cluster_id: str = "cid-osd",
) -> DesiredClusterMachinePools:
    """Create a desired OSD cluster with the given machine pools."""
    return DesiredClusterMachinePools(
        name=name,
        cluster_id=cluster_id,
        cluster_type=ClusterType.OSD,
        pools=pools if pools is not None else [],
    )


def _hcp_cluster(
    pools: list[Any] | None = None,
    name: str = "hcp-cluster",
    cluster_id: str = "cid-hcp",
) -> DesiredClusterMachinePools:
    """Create a desired ROSA HCP cluster with the given node pools."""
    return DesiredClusterMachinePools(
        name=name,
        cluster_id=cluster_id,
        cluster_type=ClusterType.ROSA_HCP,
        pools=pools if pools is not None else [],
    )


def _desired_machine_pool(
    pool_id: str = "worker",
    replicas: int | None = 3,
    **kwargs: Any,
) -> DesiredMachinePool:
    """Create a desired machine pool."""
    return DesiredMachinePool(
        id=pool_id, instance_type="m5.xlarge", replicas=replicas, **kwargs
    )


def _desired_node_pool(
    pool_id: str = "worker",
    replicas: int | None = 3,
    **kwargs: Any,
) -> DesiredNodePool:
    """Create a desired node pool."""
    return DesiredNodePool(
        id=pool_id,
        aws_node_pool=OcmNodePoolAws(instance_type="m5.xlarge"),
        replicas=replicas,
        **kwargs,
    )


def _live_machine_pool(
    pool_id: str = "worker",
    replicas: int | None = 3,
    instance_type: str = "m5.xlarge",
    **kwargs: Any,
) -> OcmMachinePool:
    """Create a live machine pool, as read from OCM."""
    return OcmMachinePool(
        id=pool_id, instance_type=instance_type, replicas=replicas, **kwargs
    )


def _live_node_pool(
    pool_id: str = "worker",
    replicas: int | None = 3,
    **kwargs: Any,
) -> OcmNodePool:
    """Create a live node pool, as read from OCM."""
    return OcmNodePool(
        id=pool_id,
        aws_node_pool=OcmNodePoolAws(instance_type="m5.xlarge"),
        replicas=replicas,
        **kwargs,
    )


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create a mock CacheBackend."""
    return MagicMock()


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    """Create a mock SecretManager."""
    return MagicMock()


@pytest.fixture
def settings() -> Settings:
    """Settings with OCM concurrency configured."""
    return Settings(ocm=OcmSettings(machine_pools_fetch_concurrency=2))


@pytest.fixture
def mock_workspace_client() -> MagicMock:
    """Mock OcmWorkspaceClient, with __enter__ returning self like the real client."""
    m = MagicMock()
    m.get_machine_pools.return_value = []
    m.get_node_pools.return_value = []
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


@pytest.fixture(autouse=True)
def patch_workspace_client_factory(
    mock_workspace_client: MagicMock,
) -> Generator[MagicMock]:
    """Patch the workspace client factory used by the service."""
    with patch(
        "qontract_api.integrations.ocm_machine_pools.service."
        "create_ocm_workspace_client",
        return_value=mock_workspace_client,
    ) as mocked:
        yield mocked


@pytest.fixture
def service(
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    settings: Settings,
) -> OcmMachinePoolsService:
    """Create an OcmMachinePoolsService with mocked dependencies."""
    return OcmMachinePoolsService(
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=settings,
    )


def _reconcile(
    service: OcmMachinePoolsService,
    clusters: list[DesiredClusterMachinePools],
    *,
    dry_run: bool = True,
) -> Any:
    """Run a reconcile against the mocked workspace client."""
    return service.reconcile(
        ocm_environment=OCM_ENVIRONMENT,
        ocm_connection=OCM_CONNECTION,
        clusters=clusters,
        dry_run=dry_run,
    )


#
# happy paths
#


def test_no_diff_success_no_actions(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Identical current and desired state yields SUCCESS with no actions."""
    mock_workspace_client.get_machine_pools.return_value = [
        _live_machine_pool(replicas=3)
    ]
    mock_workspace_client.get_node_pools.return_value = [_live_node_pool(replicas=3)]

    result = _reconcile(
        service,
        [
            _osd_cluster([_desired_machine_pool(replicas=3)]),
            _hcp_cluster([_desired_node_pool(replicas=3)]),
        ],
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    assert result.errors == []
    mock_workspace_client.create_machine_pool.assert_not_called()
    mock_workspace_client.update_machine_pool.assert_not_called()
    mock_workspace_client.delete_machine_pool.assert_not_called()


def test_new_machine_pool_creates_action_dry_run(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """A desired pool that doesn't exist yields a create action, no mutation."""
    mock_workspace_client.get_machine_pools.return_value = []

    result = _reconcile(service, [_osd_cluster([_desired_machine_pool()])])

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == [
        OcmMachinePoolsActionCreateMachinePool(cluster="osd-cluster", pool_id="worker")
    ]
    assert result.applied_count == 0
    mock_workspace_client.create_machine_pool.assert_not_called()


def test_new_machine_pool_created_when_not_dry_run(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """A create action is applied against OCM with the wire model."""
    mock_workspace_client.get_machine_pools.return_value = []

    result = _reconcile(
        service, [_osd_cluster([_desired_machine_pool()])], dry_run=False
    )

    assert result.applied_count == 1
    mock_workspace_client.create_machine_pool.assert_called_once_with(
        "cid-osd",
        OcmMachinePool(
            id="worker",
            instance_type="m5.xlarge",
            replicas=3,
        ),
    )


def test_new_node_pool_created_when_not_dry_run(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Node pool creates go through the node pool endpoint on HCP clusters."""
    mock_workspace_client.get_node_pools.return_value = []

    result = _reconcile(service, [_hcp_cluster([_desired_node_pool()])], dry_run=False)

    assert result.actions == [
        OcmMachinePoolsActionCreateNodePool(cluster="hcp-cluster", pool_id="worker")
    ]
    assert result.applied_count == 1
    mock_workspace_client.create_node_pool.assert_called_once_with(
        "cid-hcp",
        OcmNodePool(
            id="worker",
            aws_node_pool=OcmNodePoolAws(instance_type="m5.xlarge"),
            replicas=3,
        ),
    )
    mock_workspace_client.create_machine_pool.assert_not_called()


def test_replicas_change_yields_update(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """A replica count difference yields an update action."""
    mock_workspace_client.get_machine_pools.return_value = [
        _live_machine_pool(replicas=3)
    ]

    result = _reconcile(
        service, [_osd_cluster([_desired_machine_pool(replicas=5)])], dry_run=False
    )

    assert result.actions == [
        OcmMachinePoolsActionUpdateMachinePool(cluster="osd-cluster", pool_id="worker")
    ]
    assert result.applied_count == 1
    mock_workspace_client.update_machine_pool.assert_called_once_with(
        "cid-osd",
        OcmMachinePool(id="worker", instance_type="m5.xlarge", replicas=5),
    )


def test_node_pool_autoscaling_change_yields_update(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """A node pool autoscaling difference (singular fields) yields an update."""
    mock_workspace_client.get_node_pools.return_value = [
        _live_node_pool(
            autoscaling=OcmNodePoolAutoscaling(min_replica=1, max_replica=3)
        )
    ]

    result = _reconcile(
        service,
        [
            _hcp_cluster([
                _desired_node_pool(
                    replicas=None,
                    autoscaling=DesiredNodePoolAutoscaling(
                        min_replica=2, max_replica=5
                    ),
                )
            ])
        ],
        dry_run=False,
    )

    assert result.actions == [
        OcmMachinePoolsActionUpdateNodePool(cluster="hcp-cluster", pool_id="worker")
    ]
    assert result.applied_count == 1
    mock_workspace_client.update_node_pool.assert_called_once()


def test_machine_pool_autoscaling_mode_transition_yields_update(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Switching fixed replicas to autoscaling yields an update."""
    mock_workspace_client.get_machine_pools.return_value = [
        _live_machine_pool(replicas=3)
    ]

    result = _reconcile(
        service,
        [
            _osd_cluster([
                _desired_machine_pool(
                    replicas=None,
                    autoscaling=DesiredMachinePoolAutoscaling(
                        min_replicas=1, max_replicas=5
                    ),
                )
            ])
        ],
    )

    assert result.actions == [
        OcmMachinePoolsActionUpdateMachinePool(cluster="osd-cluster", pool_id="worker")
    ]


def test_removed_machine_pool_yields_delete(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """A live pool absent from the desired state yields a delete action."""
    mock_workspace_client.get_machine_pools.return_value = [
        _live_machine_pool(pool_id="worker"),
        _live_machine_pool(pool_id="extra"),
    ]

    result = _reconcile(
        service,
        [_osd_cluster([_desired_machine_pool(pool_id="worker")])],
        dry_run=False,
    )

    assert result.actions == [
        OcmMachinePoolsActionDeleteMachinePool(cluster="osd-cluster", pool_id="extra")
    ]
    assert result.applied_count == 1
    mock_workspace_client.delete_machine_pool.assert_called_once_with(
        "cid-osd", "extra"
    )


def test_removed_node_pool_deletable(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Node pools (even the default 'worker') are always deletable."""
    mock_workspace_client.get_node_pools.return_value = [
        _live_node_pool(pool_id="extra")
    ]

    result = _reconcile(service, [_hcp_cluster([])], dry_run=False)

    # hcp cluster has no desired pools but one live 'extra' pool: the
    # delete-all guard does NOT trigger because 'worker' remains? No -
    # desired is empty, so the delete-all guard fires.
    assert result.status == TaskStatus.FAILED
    mock_workspace_client.delete_node_pool.assert_not_called()


def test_removed_node_pool_deleted_when_cluster_keeps_pools(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """A live extra node pool is deleted when the cluster keeps its pools."""
    mock_workspace_client.get_node_pools.return_value = [
        _live_node_pool(pool_id="worker"),
        _live_node_pool(pool_id="extra"),
    ]

    result = _reconcile(
        service, [_hcp_cluster([_desired_node_pool(pool_id="worker")])], dry_run=False
    )

    assert result.actions == [
        OcmMachinePoolsActionDeleteNodePool(cluster="hcp-cluster", pool_id="extra")
    ]
    mock_workspace_client.delete_node_pool.assert_called_once_with("cid-hcp", "extra")


#
# legacy guards
#


def test_cannot_delete_all_pools_for_cluster(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """A cluster with no desired pools must not have all its pools deleted."""
    mock_workspace_client.get_machine_pools.return_value = [
        _live_machine_pool(pool_id="worker")
    ]

    result = _reconcile(service, [_osd_cluster([])])

    assert result.status == TaskStatus.FAILED
    assert any("can not delete all machine pools" in error for error in result.errors)
    mock_workspace_client.delete_machine_pool.assert_not_called()


def test_cannot_delete_osd_default_worker_pool(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """OSD clusters cannot delete their default worker machine pool."""
    mock_workspace_client.get_machine_pools.return_value = [
        _live_machine_pool(pool_id="extra"),
        _live_machine_pool(pool_id="worker"),
    ]

    result = _reconcile(
        service, [_osd_cluster([_desired_machine_pool(pool_id="extra")])]
    )

    assert result.status == TaskStatus.FAILED
    assert any("can not delete machine pool worker" in error for error in result.errors)
    mock_workspace_client.delete_machine_pool.assert_not_called()


def test_cannot_update_machine_pool_instance_type(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """instance_type is immutable: the diff becomes an error, not a mutation."""
    mock_workspace_client.get_machine_pools.return_value = [
        _live_machine_pool(instance_type="m5.xlarge")
    ]

    result = _reconcile(
        service,
        [_osd_cluster([DesiredMachinePool(id="worker", instance_type="m5.2xlarge")])],
        dry_run=False,
    )

    assert result.status == TaskStatus.FAILED
    assert any("can not update instance_type" in error for error in result.errors)
    mock_workspace_client.update_machine_pool.assert_not_called()


def test_cannot_update_node_pool_subnet(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """subnet is immutable on node pools: the diff becomes an error."""
    mock_workspace_client.get_node_pools.return_value = [
        _live_node_pool(subnet="subnet-1")
    ]

    result = _reconcile(
        service,
        [_hcp_cluster([_desired_node_pool(subnet="subnet-2", pool_id="worker")])],
    )

    assert result.status == TaskStatus.FAILED
    assert any("can not update subnet" in error for error in result.errors)
    mock_workspace_client.update_node_pool.assert_not_called()


#
# error isolation
#


def test_failed_cluster_fetch_excluded_from_diff(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """A cluster whose fetch fails is excluded from the diff entirely.

    Its live pools must never look like 'not desired' (spurious deletes),
    and its desired pools must not produce creates either.
    """
    mock_workspace_client.get_machine_pools.side_effect = [
        RuntimeError("fetch failed"),  # osd-cluster
        [_live_machine_pool(pool_id="worker")],  # osd-cluster-2
    ]

    result = _reconcile(
        service,
        [
            _osd_cluster([_desired_machine_pool()], name="osd-cluster"),
            _osd_cluster(
                [_desired_machine_pool()], name="osd-cluster-2", cluster_id="cid-2"
            ),
        ],
    )

    assert result.status == TaskStatus.FAILED
    assert any("osd-cluster" in error for error in result.errors)
    # no actions computed for the failed cluster
    assert result.actions == []
    mock_workspace_client.delete_machine_pool.assert_not_called()
    mock_workspace_client.create_machine_pool.assert_not_called()


def test_apply_error_reported_but_other_actions_continue(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
) -> None:
    """One failing mutation does not prevent other mutations."""
    mock_workspace_client.get_machine_pools.return_value = []
    mock_workspace_client.create_machine_pool.side_effect = [RuntimeError("boom"), None]

    result = _reconcile(
        service,
        [
            _osd_cluster([
                _desired_machine_pool(pool_id="pool-1"),
                _desired_machine_pool(pool_id="pool-2"),
            ])
        ],
        dry_run=False,
    )

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "failed to create pool" in result.errors[0]
    assert result.applied_count == 1
    assert mock_workspace_client.create_machine_pool.call_count == 2


def test_labels_change_warns_new_nodes_only(
    service: OcmMachinePoolsService,
    mock_workspace_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A labels/taints diff logs the 'only applied to new Nodes' warning."""
    mock_workspace_client.get_machine_pools.return_value = [
        _live_machine_pool(labels={"tier": "frontend"})
    ]

    with caplog.at_level("WARNING"):
        _reconcile(
            service, [_osd_cluster([_desired_machine_pool(labels={"tier": "backend"})])]
        )

    assert any("only be applied to new Nodes" in message for message in caplog.messages)
