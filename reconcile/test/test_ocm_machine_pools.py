from reconcile.gql_definitions.common.clusters import ClusterMachinePoolV1
from reconcile.ocm_machine_pools import (
    MachinePool,
    calculate_diff,
)


def test_calculate_diff_create():
    current = {
        "cluster1": [],
    }
    desired = {
        "cluster1": {
            "machine_pools": [
                ClusterMachinePoolV1(
                    id="pool1",
                    instance_type="m5.xlarge",
                    replicas=1,
                    labels=None,
                    taints=None,
                )
            ],
            "hypershift": False,
        },
    }

    diff, error = calculate_diff(current, desired)
    assert len(diff) == 1
    assert diff[0].action == "create"


def test_calculate_diff_noop():
    current = {
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
    desired = {
        "cluster1": {
            "machine_pools": [
                ClusterMachinePoolV1(
                    id="pool1",
                    instance_type="m5.xlarge",
                    replicas=1,
                    labels=None,
                    taints=None,
                )
            ],
            "hypershift": False,
        },
    }

    diff, error = calculate_diff(current, desired)
    assert len(diff) == 0


def test_calculate_diff_update():
    current = {
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
    desired = {
        "cluster1": {
            "machine_pools": [
                ClusterMachinePoolV1(
                    id="pool1",
                    instance_type="m5.xlarge",
                    replicas=1,
                    labels=None,
                    taints=None,
                )
            ],
            "hypershift": False,
        },
    }

    diff, error = calculate_diff(current, desired)
    assert len(diff) == 1
    assert diff[0].action == "update"


def test_calculate_diff_delete():
    current = {
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
    desired = {
        "cluster1": {
            "machine_pools": [],
            "hypershift": False,
        },
    }

    diff, error = calculate_diff(current, desired)
    assert len(diff) == 1
    assert diff[0].action == "delete"
