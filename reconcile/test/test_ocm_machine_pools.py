from typing import Mapping

from reconcile.gql_definitions.common.clusters import ClusterMachinePoolV1
from reconcile.ocm_machine_pools import (
    AbstractPool,
    DesiredMachinePool,
    DesiredStateList,
    MachinePool,
    calculate_diff,
)


def test_calculate_diff_create():
    current: Mapping[str, list[AbstractPool]] = {
        "cluster1": [],
    }
    desired = DesiredStateList(
        cluster_pools=[
            DesiredMachinePool(
                cluster_name="cluster1",
                hypershift=False,
                pools=[
                    ClusterMachinePoolV1(
                        id="pool1",
                        instance_type="m5.xlarge",
                        replicas=1,
                        labels=None,
                        taints=None,
                        subnet="subnet1",
                    )
                ],
            )
        ]
    )

    diff, error = calculate_diff(current, desired)
    assert len(diff) == 1
    assert diff[0].action == "create"
    assert not error


def test_calculate_diff_noop():
    current: Mapping[str, list[AbstractPool]] = {
        "cluster1": [
            MachinePool(
                id="pool1",
                instance_type="m5.xlarge",
                replicas=1,
                labels=None,
                taints=None,
                cluster="cluster1",
            )
        ]
    }
    desired = DesiredStateList(
        cluster_pools=[
            DesiredMachinePool(
                cluster_name="cluster1",
                hypershift=False,
                pools=[
                    ClusterMachinePoolV1(
                        id="pool1",
                        instance_type="m5.xlarge",
                        replicas=1,
                        labels=None,
                        taints=None,
                        subnet="subnet1",
                    )
                ],
            )
        ]
    )
    diff, error = calculate_diff(current, desired)
    assert len(diff) == 0
    assert not error


def test_calculate_diff_update():
    current: Mapping[str, list[AbstractPool]] = {
        "cluster1": [
            MachinePool(
                id="pool1",
                instance_type="m5.xlarge",
                replicas=2,
                labels=None,
                taints=None,
                cluster="cluster1",
            )
        ]
    }
    desired = DesiredStateList(
        cluster_pools=[
            DesiredMachinePool(
                cluster_name="cluster1",
                hypershift=False,
                pools=[
                    ClusterMachinePoolV1(
                        id="pool1",
                        instance_type="m5.xlarge",
                        replicas=1,
                        labels=None,
                        taints=None,
                        subnet="subnet1",
                    )
                ],
            )
        ]
    )

    diff, error = calculate_diff(current, desired)
    assert len(diff) == 1
    assert diff[0].action == "update"
    assert not error


def test_calculate_diff_delete():
    current: Mapping[str, list[AbstractPool]] = {
        "cluster1": [
            MachinePool(
                id="pool1",
                instance_type="m5.xlarge",
                replicas=2,
                labels=None,
                taints=None,
                cluster="cluster1",
            )
        ]
    }
    desired = DesiredStateList(
        cluster_pools=[
            DesiredMachinePool(cluster_name="cluster1", hypershift=False, pools=[])
        ]
    )

    diff, error = calculate_diff(current, desired)
    assert len(diff) == 1
    assert diff[0].action == "delete"
    assert not error
