"""Unit tests for the ocm_machine_pools domain models."""

import pytest
from pydantic import ValidationError
from qontract_utils.ocm_api import OcmNodePoolAws

from qontract_api.integrations.ocm_machine_pools.domain import (
    ClusterType,
    DesiredClusterMachinePools,
    DesiredMachinePool,
    DesiredMachinePoolAutoscaling,
    DesiredNodePool,
    DesiredNodePoolAutoscaling,
)


def test_cluster_type_values() -> None:
    """Cluster type values match the legacy integration's product mapping."""
    assert ClusterType.OSD.value == "osd"
    assert ClusterType.ROSA_CLASSIC.value == "rosa"
    assert ClusterType.ROSA_HCP.value == "hypershift"


def test_machine_pool_autoscaling_rejects_max_below_min() -> None:
    """max_replicas must be greater than or equal to min_replicas."""
    with pytest.raises(ValidationError, match="max_replicas must be greater"):
        DesiredMachinePoolAutoscaling(min_replicas=5, max_replicas=2)


def test_machine_pool_autoscaling_allows_equal_bounds() -> None:
    """Legacy parity: min == max is a valid (if odd) autoscaling config."""
    assert DesiredMachinePoolAutoscaling(min_replicas=3, max_replicas=3) is not None


def test_machine_pool_autoscaling_string_bounds_coerced() -> None:
    """String bounds are coerced before comparison, not compared lexicographically.

    min="2", max="10" is valid (2 < 10) even though "2" > "10" as strings;
    min="10", max="2" is invalid. Comparing raw values would get both wrong
    and mixed types would raise a TypeError (500) instead of a 422.
    """
    assert DesiredMachinePoolAutoscaling(
        min_replicas="2",
        max_replicas="10",
    ) == DesiredMachinePoolAutoscaling(min_replicas=2, max_replicas=10)

    with pytest.raises(ValidationError, match="max_replicas must be greater"):
        DesiredMachinePoolAutoscaling(
            min_replicas="10",
            max_replicas="2",
        )


def test_node_pool_autoscaling_string_bounds_coerced() -> None:
    """Node pool (singular) bounds are coerced before comparison too."""
    with pytest.raises(ValidationError, match="max_replica must be greater"):
        DesiredNodePoolAutoscaling(
            min_replica="10",
            max_replica="2",
        )


def test_node_pool_autoscaling_rejects_max_below_min() -> None:
    """max_replica must be greater than or equal to min_replica (singular HCP fields)."""
    with pytest.raises(ValidationError, match="max_replica must be greater"):
        DesiredNodePoolAutoscaling(min_replica=5, max_replica=2)


def test_machine_pool_rejects_autoscaling_with_replicas() -> None:
    """autoscaling and replicas are mutually exclusive."""
    with pytest.raises(ValidationError, match="mutually exclusive"):
        DesiredMachinePool(
            id="worker",
            instance_type="m5.xlarge",
            replicas=3,
            autoscaling=DesiredMachinePoolAutoscaling(min_replicas=1, max_replicas=5),
        )


def test_node_pool_rejects_autoscaling_with_replicas() -> None:
    """autoscaling and replicas are mutually exclusive on node pools too."""
    with pytest.raises(ValidationError, match="mutually exclusive"):
        DesiredNodePool(
            id="worker",
            aws_node_pool=OcmNodePoolAws(instance_type="m5.xlarge"),
            replicas=3,
            autoscaling=DesiredNodePoolAutoscaling(min_replica=1, max_replica=5),
        )


def test_machine_pool_rejects_autoscaling_with_zero_replicas() -> None:
    """replicas=0 is falsy but still present - it must be rejected too."""
    with pytest.raises(ValidationError, match="mutually exclusive"):
        DesiredMachinePool(
            id="worker",
            instance_type="m5.xlarge",
            replicas=0,
            autoscaling=DesiredMachinePoolAutoscaling(min_replicas=1, max_replicas=5),
        )


def test_machine_pool_allows_autoscaling_without_replicas() -> None:
    """An autoscaled pool without a fixed replica count is valid."""
    pool = DesiredMachinePool(
        id="worker",
        instance_type="m5.xlarge",
        autoscaling=DesiredMachinePoolAutoscaling(min_replicas=1, max_replicas=5),
    )
    assert pool.replicas is None
    assert pool.autoscaling is not None


def test_cluster_rejects_node_pool_on_osd_cluster() -> None:
    """Pool shape must match the cluster type."""
    with pytest.raises(ValidationError, match="declares a node pool"):
        DesiredClusterMachinePools(
            name="osd-cluster",
            cluster_id="cid-1",
            cluster_type=ClusterType.OSD,
            pools=[
                DesiredNodePool(
                    id="worker",
                    aws_node_pool=OcmNodePoolAws(instance_type="m5.xlarge"),
                )
            ],
        )


def test_cluster_rejects_machine_pool_on_hcp_cluster() -> None:
    """Pool shape must match the cluster type."""
    with pytest.raises(ValidationError, match="declares a machine pool"):
        DesiredClusterMachinePools(
            name="hcp-cluster",
            cluster_id="cid-1",
            cluster_type=ClusterType.ROSA_HCP,
            pools=[DesiredMachinePool(id="worker", instance_type="m5.xlarge")],
        )


def test_cluster_accepts_matching_pool_shapes() -> None:
    """Matching pool shapes validate fine on both cluster types."""
    osd = DesiredClusterMachinePools(
        name="osd-cluster",
        cluster_id="cid-1",
        cluster_type=ClusterType.OSD,
        pools=[DesiredMachinePool(id="worker", instance_type="m5.xlarge")],
    )
    hcp = DesiredClusterMachinePools(
        name="hcp-cluster",
        cluster_id="cid-2",
        cluster_type=ClusterType.ROSA_HCP,
        pools=[
            DesiredNodePool(
                id="worker",
                aws_node_pool=OcmNodePoolAws(instance_type="m5.xlarge"),
            )
        ],
    )
    assert osd.pools[0].id == "worker"
    assert hcp.pools[0].id == "worker"


def test_models_are_frozen() -> None:
    """Domain models are immutable."""
    pool = DesiredMachinePool(id="worker", instance_type="m5.xlarge")
    with pytest.raises(ValidationError, match="frozen"):
        pool.id = "other"  # type: ignore[misc]
