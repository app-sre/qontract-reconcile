from typing import (
    Mapping,
    Optional,
)

import pytest

from reconcile.gql_definitions.common.clusters import ClusterMachinePoolV1
from reconcile.ocm_machine_pools import (
    AbstractPool,
    AWSNodePool,
    DesiredMachinePool,
    DesiredStateList,
    MachinePool,
    NodePool,
    PoolHandler,
    calculate_diff,
)
from reconcile.utils.ocm import OCM


class TestPool(AbstractPool):
    created = False
    deleted = False
    updated = False

    def create(self, ocm: OCM) -> None:
        self.created = True

    def delete(self, ocm: OCM) -> None:
        self.deleted = True

    def update(self, ocm: OCM) -> None:
        self.updated = True

    def has_diff(self, pool: ClusterMachinePoolV1) -> bool:
        return True

    def invalid_diff(self, pool: ClusterMachinePoolV1) -> Optional[str]:
        return None


@pytest.fixture
def test_pool() -> TestPool:
    return TestPool(
        id="pool1",
        replicas=2,
        labels=None,
        taints=None,
        cluster="cluster1",
    )


@pytest.fixture
def current_with_pool() -> Mapping[str, list[AbstractPool]]:
    return {
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


@pytest.fixture
def node_pool() -> NodePool:
    return NodePool(
        id="pool1",
        replicas=2,
        labels=None,
        taints=None,
        cluster="cluster1",
        subnet="subnet1",
        aws_node_pool=AWSNodePool(
            instance_type="m5.xlarge",
        ),
    )


@pytest.fixture
def machine_pool() -> MachinePool:
    return MachinePool(
        id="pool1",
        replicas=2,
        labels=None,
        taints=None,
        cluster="cluster1",
        subnet="subnet1",
        instance_type="m5.xlarge",
    )


@pytest.fixture
def cluster_machine_pool() -> ClusterMachinePoolV1:
    return ClusterMachinePoolV1(
        id="pool1",
        instance_type="m5.xlarge",
        replicas=1,
        labels=None,
        taints=None,
        subnet="subnet1",
    )


@pytest.fixture
def ocm_mock(mocker):
    return mocker.patch("reconcile.utils.ocm.OCM")


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


def test_calculate_diff_noop(current_with_pool):
    desired = DesiredStateList(
        cluster_pools=[
            DesiredMachinePool(
                cluster_name="cluster1",
                hypershift=False,
                pools=[
                    ClusterMachinePoolV1(
                        id="pool1",
                        instance_type="m5.xlarge",
                        replicas=2,
                        labels=None,
                        taints=None,
                        subnet="subnet1",
                    )
                ],
            )
        ]
    )
    diff, error = calculate_diff(current_with_pool, desired)
    assert len(diff) == 0
    assert not error


def test_calculate_diff_update(current_with_pool):
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

    diff, error = calculate_diff(current_with_pool, desired)
    assert len(diff) == 1
    assert diff[0].action == "update"
    assert not error


def test_calculate_diff_delete(current_with_pool):
    desired = DesiredStateList(
        cluster_pools=[
            DesiredMachinePool(cluster_name="cluster1", hypershift=False, pools=[])
        ]
    )

    diff, error = calculate_diff(current_with_pool, desired)
    assert len(diff) == 1
    assert diff[0].action == "delete"
    assert not error


def test_act_dry_run(test_pool, ocm_mock):
    handler = PoolHandler(action="create", pool=test_pool)
    handler.act(ocm=ocm_mock, dry_run=True)
    assert not test_pool.created
    assert not test_pool.deleted
    assert not test_pool.updated


def test_act_create(test_pool, ocm_mock):
    handler = PoolHandler(action="create", pool=test_pool)
    handler.act(ocm=ocm_mock, dry_run=False)
    assert test_pool.created


def test_act_update(test_pool, ocm_mock):
    handler = PoolHandler(action="update", pool=test_pool)
    handler.act(ocm=ocm_mock, dry_run=False)
    assert test_pool.updated


def test_act_delete(test_pool, ocm_mock):
    handler = PoolHandler(action="delete", pool=test_pool)
    handler.act(ocm=ocm_mock, dry_run=False)
    assert test_pool.deleted


def test_pool_node_pool_has_diff(node_pool, cluster_machine_pool):
    assert node_pool.has_diff(cluster_machine_pool)
    cluster_machine_pool.replicas = 2
    assert not node_pool.has_diff(cluster_machine_pool)


def test_pool_node_pool_invalid_diff_subnet(node_pool, cluster_machine_pool):
    cluster_machine_pool.subnet = "foo"
    assert node_pool.invalid_diff(cluster_machine_pool)


def test_pool_node_pool_invalid_diff_instance_type(node_pool, cluster_machine_pool):
    cluster_machine_pool.instance_type = "foo"
    assert node_pool.invalid_diff(cluster_machine_pool)


def test_pool_machine_pool_has_diff(machine_pool, cluster_machine_pool):
    assert machine_pool.has_diff(cluster_machine_pool)
    cluster_machine_pool.replicas = 2
    assert not machine_pool.has_diff(cluster_machine_pool)


def test_pool_machine_pool_invalid_diff_instance_type(
    machine_pool, cluster_machine_pool
):
    cluster_machine_pool.instance_type = "foo"
    assert machine_pool.invalid_diff(cluster_machine_pool)


def test_machine_pool_update(machine_pool, mocker):
    ocm = mocker.patch("reconcile.utils.ocm.OCM")
    machine_pool.update(ocm=ocm)

    assert ocm.update_machine_pool.call_count == 1
    ocm.update_machine_pool.assert_called_with(
        "cluster1", {"id": "pool1", "replicas": 2, "cluster": "cluster1"}
    )

    machine_pool.labels = {"foo": "bar"}
    machine_pool.update(ocm=ocm)
    ocm.update_machine_pool.assert_called_with(
        "cluster1",
        {"id": "pool1", "replicas": 2, "cluster": "cluster1", "labels": {"foo": "bar"}},
    )


def test_node_pool_update(node_pool, ocm_mock):
    node_pool.update(ocm=ocm_mock)

    assert ocm_mock.update_node_pool.call_count == 1
    ocm_mock.update_node_pool.assert_called_with(
        "cluster1", {"id": "pool1", "replicas": 2, "cluster": "cluster1"}
    )

    node_pool.labels = {"foo": "bar"}
    node_pool.update(ocm=ocm_mock)
    ocm_mock.update_node_pool.assert_called_with(
        "cluster1",
        {"id": "pool1", "replicas": 2, "cluster": "cluster1", "labels": {"foo": "bar"}},
    )
