from collections.abc import (
    Callable,
    Iterable,
)
from typing import (
    Mapping,
    Optional,
)
from unittest.mock import create_autospec

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.clusters import (
    ClusterMachinePoolV1,
    ClusterMachinePoolV1_ClusterSpecAutoScaleV1,
    ClusterV1,
)
from reconcile.ocm_machine_pools import (
    AbstractPool,
    AWSNodePool,
    DesiredMachinePool,
    InvalidUpdateError,
    MachinePool,
    MachinePoolAutoscaling,
    NodePool,
    PoolHandler,
    calculate_diff,
    run,
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

    def deletable(self) -> bool:
        return True


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
        autoscale=None,
        labels=None,
        taints=None,
        subnet="subnet1",
    )


@pytest.fixture
def ocm_mock():
    return create_autospec(OCM)


def test_diff__has_diff_autoscale(cluster_machine_pool: ClusterMachinePoolV1):
    pool = TestPool(id="pool1", cluster="cluster1")

    assert cluster_machine_pool.autoscale is None
    assert not pool._has_diff_autoscale(cluster_machine_pool)

    cluster_machine_pool.autoscale = ClusterMachinePoolV1_ClusterSpecAutoScaleV1(
        min_replicas=1, max_replicas=2
    )
    assert pool._has_diff_autoscale(cluster_machine_pool)

    cluster_machine_pool.autoscale = None
    pool.autoscaling = MachinePoolAutoscaling(min_replicas=1, max_replicas=2)
    assert pool._has_diff_autoscale(cluster_machine_pool)

    cluster_machine_pool.autoscale = ClusterMachinePoolV1_ClusterSpecAutoScaleV1(
        min_replicas=1, max_replicas=2
    )
    assert not pool._has_diff_autoscale(cluster_machine_pool)

    pool.autoscaling.max_replicas = 3
    assert pool._has_diff_autoscale(cluster_machine_pool)

    pool.autoscaling.max_replicas = 2
    assert not pool._has_diff_autoscale(cluster_machine_pool)

    pool.autoscaling.min_replicas = 0
    assert pool._has_diff_autoscale(cluster_machine_pool)


def test_calculate_diff_create():
    current: Mapping[str, list[AbstractPool]] = {
        "cluster1": [],
    }
    desired = {
        "cluster1": DesiredMachinePool(
            cluster_name="cluster1",
            hypershift=False,
            pools=[
                ClusterMachinePoolV1(
                    id="pool1",
                    instance_type="m5.xlarge",
                    autoscale=None,
                    replicas=1,
                    labels=None,
                    taints=None,
                    subnet="subnet1",
                )
            ],
        )
    }

    diff, error = calculate_diff(current, desired)
    assert len(diff) == 1
    assert diff[0].action == "create"
    assert not error


def test_calculate_diff_noop(current_with_pool):
    desired = {
        "cluster1": DesiredMachinePool(
            cluster_name="cluster1",
            hypershift=False,
            pools=[
                ClusterMachinePoolV1(
                    id="pool1",
                    instance_type="m5.xlarge",
                    replicas=2,
                    autoscale=None,
                    labels=None,
                    taints=None,
                    subnet="subnet1",
                )
            ],
        ),
    }
    diff, error = calculate_diff(current_with_pool, desired)
    assert len(diff) == 0
    assert not error


def test_calculate_diff_update(current_with_pool):
    desired = {
        "cluster1": DesiredMachinePool(
            cluster_name="cluster1",
            hypershift=False,
            pools=[
                ClusterMachinePoolV1(
                    id="pool1",
                    instance_type="m5.xlarge",
                    replicas=1,
                    autoscale=None,
                    labels=None,
                    taints=None,
                    subnet="subnet1",
                )
            ],
        ),
    }

    diff, error = calculate_diff(current_with_pool, desired)
    assert len(diff) == 1
    assert diff[0].action == "update"
    assert not error


@pytest.fixture
def current_with_2_pools() -> Mapping[str, list[AbstractPool]]:
    return {
        "cluster1": [
            MachinePool(
                id="pool1",
                instance_type="m5.xlarge",
                replicas=2,
                labels=None,
                taints=None,
                cluster="cluster1",
            ),
            MachinePool(
                id="workers",
                instance_type="m5.xlarge",
                replicas=2,
                labels=None,
                taints=None,
                cluster="cluster1",
            ),
        ]
    }


def test_calculate_diff_delete(current_with_2_pools):
    desired = {
        "cluster1": DesiredMachinePool(
            cluster_name="cluster1",
            hypershift=False,
            pools=[
                ClusterMachinePoolV1(
                    id="pool1",
                    instance_type="m5.xlarge",
                    replicas=2,
                    autoscale=None,
                    labels=None,
                    taints=None,
                    subnet="subnet1",
                )
            ],
        ),
    }

    diff, error = calculate_diff(current_with_2_pools, desired)
    assert len(diff) == 1
    assert diff[0].action == "delete"
    assert not error


def test_calculate_diff_delete_all_fail_validation(current_with_pool):
    desired = {
        "cluster1": DesiredMachinePool(
            cluster_name="cluster1",
            hypershift=False,
            pools=[],
        ),
    }

    diff, error = calculate_diff(current_with_pool, desired)
    assert len(diff) == 0
    assert len(error) == 1


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


def test_pool_machine_pool_has_new_auto_scale(machine_pool, cluster_machine_pool):
    machine_pool.replicas = None
    cluster_machine_pool.replicas = None
    assert not machine_pool.has_diff(cluster_machine_pool)
    cluster_machine_pool.autoscale = ClusterMachinePoolV1_ClusterSpecAutoScaleV1(
        min_replicas=1, max_replicas=2
    )
    assert machine_pool.has_diff(cluster_machine_pool)


def test_pool_node_pool_has_new_auto_scale(node_pool, cluster_machine_pool):
    node_pool.replicas = None
    cluster_machine_pool.replicas = None
    assert not node_pool.has_diff(cluster_machine_pool)
    cluster_machine_pool.autoscale = ClusterMachinePoolV1_ClusterSpecAutoScaleV1(
        min_replicas=1, max_replicas=2
    )
    assert node_pool.has_diff(cluster_machine_pool)


def test_pool_machine_pool_invalid_diff_instance_type(
    machine_pool, cluster_machine_pool
):
    cluster_machine_pool.instance_type = "foo"
    assert machine_pool.invalid_diff(cluster_machine_pool)


def test_machine_pool_update(machine_pool, ocm_mock):
    machine_pool.update(ocm=ocm_mock)

    ocm_mock.update_machine_pool.assert_called_once_with(
        "cluster1",
        {"id": "pool1", "replicas": 2, "cluster": "cluster1", "autoscaling": None},
    )

    machine_pool.labels = {"foo": "bar"}
    machine_pool.update(ocm=ocm_mock)
    ocm_mock.update_machine_pool.assert_called_with(
        "cluster1",
        {
            "id": "pool1",
            "replicas": 2,
            "cluster": "cluster1",
            "labels": {"foo": "bar"},
            "autoscaling": None,
        },
    )


def test_node_pool_update(node_pool, ocm_mock):
    node_pool.update(ocm=ocm_mock)

    ocm_mock.update_node_pool.assert_called_once_with(
        "cluster1",
        {"id": "pool1", "replicas": 2, "cluster": "cluster1", "autoscaling": None},
    )

    node_pool.labels = {"foo": "bar"}
    node_pool.update(ocm=ocm_mock)
    ocm_mock.update_node_pool.assert_called_with(
        "cluster1",
        {
            "id": "pool1",
            "replicas": 2,
            "cluster": "cluster1",
            "labels": {"foo": "bar"},
            "autoscaling": None,
        },
    )


def setup_mocks(
    mocker: MockerFixture,
    clusters: list[ClusterV1] | None = None,
    machine_pools: list[dict] | None = None,
    node_pools: list[dict] | None = None,
) -> dict:
    mocked_get_clusters = mocker.patch(
        "reconcile.ocm_machine_pools.get_clusters", return_value=clusters or []
    )
    mocked_ocm_map = mocker.patch("reconcile.ocm_machine_pools.OCMMap", autospec=True)
    mocked_ocm = mocked_ocm_map.return_value.get.return_value
    mocked_ocm.get_machine_pools.return_value = machine_pools or []
    mocked_ocm.get_node_pools.return_value = node_pools or []

    mocked_queries = mocker.patch("reconcile.ocm_machine_pools.queries")

    return {
        "get_clusters": mocked_get_clusters,
        "queries": mocked_queries,
        "OCMMap": mocked_ocm_map,
        "OCM": mocked_ocm,
    }


def test_run_no_action(mocker: MockerFixture) -> None:
    mocks = setup_mocks(mocker, clusters=[])

    run(False)

    mocks["get_clusters"].assert_called_once_with()
    mocks["OCMMap"].assert_not_called()


@pytest.fixture
def ocm_cluster_builder(
    gql_class_factory: Callable[..., ClusterV1],
) -> Callable[..., ClusterV1]:
    def builder(machine_pools: list[dict]) -> ClusterV1:
        return gql_class_factory(
            ClusterV1,
            {
                "name": "ocm-cluster",
                "auth": [],
                "ocm": {
                    "name": "ocm-name",
                    "environment": {
                        "accessTokenClientSecret": {},
                    },
                },
                "machinePools": machine_pools,
            },
        )

    return builder


@pytest.fixture
def default_worker_machine_pool() -> dict:
    return {
        "id": "worker",
        "instance_type": "m5.xlarge",
        "replicas": 2,
    }


@pytest.fixture
def ocm_cluster_with_default_machine_pool(
    ocm_cluster_builder: Callable[..., ClusterV1],
    default_worker_machine_pool: dict,
) -> ClusterV1:
    return ocm_cluster_builder([default_worker_machine_pool])


@pytest.fixture
def new_workers_machine_pool() -> dict:
    return {
        "id": "workers-new",
        "instance_type": "m5.2xlarge",
        "replicas": 3,
    }


@pytest.fixture
def ocm_cluster_with_default_and_new_machine_pools(
    ocm_cluster_builder: Callable[..., ClusterV1],
    default_worker_machine_pool: dict,
    new_workers_machine_pool: dict,
) -> ClusterV1:
    return ocm_cluster_builder(
        [
            default_worker_machine_pool,
            new_workers_machine_pool,
        ]
    )


@pytest.fixture
def expected_ocm_machine_pool_create_payload() -> dict:
    return {
        "autoscaling": None,
        "cluster": "ocm-cluster",
        "id": "workers-new",
        "instance_type": "m5.2xlarge",
        "labels": None,
        "replicas": 3,
        "taints": [],
    }


def test_run_create_machine_pool(
    mocker: MockerFixture,
    ocm_cluster_with_default_and_new_machine_pools: ClusterV1,
    default_worker_machine_pool: dict,
    expected_ocm_machine_pool_create_payload: dict,
) -> None:
    mocks = setup_mocks(
        mocker,
        clusters=[ocm_cluster_with_default_and_new_machine_pools],
        machine_pools=[default_worker_machine_pool],
    )

    run(False)

    mocks["OCM"].create_machine_pool.assert_called_once_with(
        ocm_cluster_with_default_and_new_machine_pools.name,
        expected_ocm_machine_pool_create_payload,
    )


@pytest.fixture
def existing_updated_default_machine_pool() -> dict:
    return {
        "id": "worker",
        "instance_type": "m5.xlarge",
        "replicas": 3,
    }


@pytest.fixture
def expected_ocm_machine_pool_update_payload() -> dict:
    return {
        "autoscaling": None,
        "cluster": "ocm-cluster",
        "id": "worker",
        "replicas": 2,
    }


def test_run_update_machine_pool(
    mocker: MockerFixture,
    ocm_cluster_with_default_machine_pool: ClusterV1,
    existing_updated_default_machine_pool: dict,
    expected_ocm_machine_pool_update_payload: dict,
) -> None:
    mocks = setup_mocks(
        mocker,
        clusters=[ocm_cluster_with_default_machine_pool],
        machine_pools=[existing_updated_default_machine_pool],
    )

    run(False)

    mocks["OCM"].update_machine_pool.assert_called_once_with(
        ocm_cluster_with_default_machine_pool.name,
        expected_ocm_machine_pool_update_payload,
    )


@pytest.fixture
def existing_default_machine_pool_with_different_instance_type() -> dict:
    return {
        "id": "worker",
        "instance_type": "m5.2xlarge",
        "replicas": 2,
    }


def test_run_update_machine_pool_error(
    mocker: MockerFixture,
    ocm_cluster_with_default_machine_pool: ClusterV1,
    existing_default_machine_pool_with_different_instance_type: dict,
) -> None:
    setup_mocks(
        mocker,
        clusters=[ocm_cluster_with_default_machine_pool],
        machine_pools=[existing_default_machine_pool_with_different_instance_type],
    )

    with pytest.raises(ExceptionGroup) as eg:
        run(False)

    assert len(eg.value.exceptions) == 1
    assert isinstance(eg.value.exceptions[0], InvalidUpdateError)


@pytest.fixture
def expected_ocm_machine_pool_delete_payload() -> dict:
    return {
        "autoscaling": None,
        "cluster": "ocm-cluster",
        "id": "workers-new",
        "instance_type": "m5.2xlarge",
        "labels": None,
        "replicas": 3,
        "taints": None,
    }


def test_run_delete_machine_pool(
    mocker: MockerFixture,
    ocm_cluster_with_default_machine_pool: ClusterV1,
    default_worker_machine_pool,
    new_workers_machine_pool: dict,
    expected_ocm_machine_pool_delete_payload: dict,
) -> None:
    mocks = setup_mocks(
        mocker,
        clusters=[ocm_cluster_with_default_machine_pool],
        machine_pools=[default_worker_machine_pool, new_workers_machine_pool],
    )

    run(False)

    mocks["OCM"].delete_machine_pool.assert_called_once_with(
        ocm_cluster_with_default_machine_pool.name,
        expected_ocm_machine_pool_delete_payload,
    )


@pytest.fixture
def ocm_cluster_without_machine_pools(
    ocm_cluster_builder: Callable[..., ClusterV1],
) -> ClusterV1:
    return ocm_cluster_builder([])


def test_run_delete_machine_pool_fail_validation(
    mocker: MockerFixture,
    ocm_cluster_without_machine_pools: ClusterV1,
    default_worker_machine_pool,
) -> None:
    setup_mocks(
        mocker,
        clusters=[ocm_cluster_without_machine_pools],
        machine_pools=[default_worker_machine_pool],
    )

    with pytest.raises(ExceptionGroup) as eg:
        run(False)

    assert len(eg.value.exceptions) == 1
    assert isinstance(eg.value.exceptions[0], InvalidUpdateError)


@pytest.fixture
def hypershift_cluster_builder(
    gql_class_factory: Callable[..., ClusterV1],
) -> Callable[..., ClusterV1]:
    def builder(machine_pools: Iterable[dict]) -> ClusterV1:
        return gql_class_factory(
            ClusterV1,
            {
                "name": "hypershift-cluster",
                "auth": [],
                "ocm": {
                    "name": "hypershift",
                    "environment": {
                        "accessTokenClientSecret": {},
                    },
                },
                "spec": {
                    "hypershift": True,
                },
                "machinePools": machine_pools,
            },
        )

    return builder


@pytest.fixture
def default_hypershift_worker_machine_pool() -> dict:
    return {
        "id": "workers",
        "instance_type": "m5.xlarge",
        "replicas": 2,
    }


@pytest.fixture
def hypershift_cluster(
    hypershift_cluster_builder: Callable[..., ClusterV1],
    default_hypershift_worker_machine_pool: dict,
) -> ClusterV1:
    return hypershift_cluster_builder([default_hypershift_worker_machine_pool])


@pytest.fixture
def expected_node_pool_create_payload() -> dict:
    return {
        "autoscaling": None,
        "aws_node_pool": {"instance_type": "m5.xlarge"},
        "cluster": "hypershift-cluster",
        "id": "workers",
        "labels": None,
        "replicas": 2,
        "subnet": None,
        "taints": [],
    }


def test_run_create_node_pool(
    mocker: MockerFixture,
    hypershift_cluster: ClusterV1,
    expected_node_pool_create_payload: dict,
) -> None:
    mocks = setup_mocks(mocker, clusters=[hypershift_cluster])

    run(False)

    mocks["OCM"].create_node_pool.assert_called_once_with(
        hypershift_cluster.name,
        expected_node_pool_create_payload,
    )


@pytest.fixture
def existing_updated_hypershift_node_pools() -> list[dict]:
    return [
        {
            "id": "workers",
            "aws_node_pool": {"instance_type": "m5.xlarge"},
            "replicas": 3,
        }
    ]


@pytest.fixture
def expected_hypershift_node_pool_update_payload() -> dict:
    return {
        "autoscaling": None,
        "cluster": "hypershift-cluster",
        "id": "workers",
        "replicas": 2,
    }


def test_run_update_node_pool(
    mocker: MockerFixture,
    hypershift_cluster: ClusterV1,
    existing_updated_hypershift_node_pools: list[dict],
    expected_hypershift_node_pool_update_payload: dict,
) -> None:
    mocks = setup_mocks(
        mocker,
        clusters=[hypershift_cluster],
        node_pools=existing_updated_hypershift_node_pools,
    )

    run(False)

    mocks["OCM"].update_node_pool.assert_called_once_with(
        hypershift_cluster.name,
        expected_hypershift_node_pool_update_payload,
    )


@pytest.fixture
def non_default_hypershift_node_pool() -> dict:
    return {
        "id": "new-workers",
        "aws_node_pool": {"instance_type": "m5.xlarge"},
        "replicas": 3,
    }


@pytest.fixture
def existing_multiple_hypershift_node_pools() -> list[dict]:
    return [
        {
            "id": "workers",
            "aws_node_pool": {"instance_type": "m5.xlarge"},
            "replicas": 3,
        },
        {
            "id": "new-workers",
            "aws_node_pool": {"instance_type": "m5.xlarge"},
            "replicas": 3,
        },
    ]


@pytest.fixture
def expected_hypershift_node_pool_delete_payload() -> dict:
    return {
        "autoscaling": None,
        "cluster": "hypershift-cluster",
        "id": "new-workers",
        "aws_node_pool": {"instance_type": "m5.xlarge"},
        "labels": None,
        "replicas": 3,
        "subnet": None,
        "taints": None,
    }


def test_run_delete_node_pool(
    mocker: MockerFixture,
    hypershift_cluster: ClusterV1,
    existing_multiple_hypershift_node_pools: list[dict],
    expected_hypershift_node_pool_delete_payload: dict,
) -> None:
    mocks = setup_mocks(
        mocker,
        clusters=[hypershift_cluster],
        node_pools=existing_multiple_hypershift_node_pools,
    )

    run(False)

    mocks["OCM"].delete_node_pool.assert_called_once_with(
        hypershift_cluster.name,
        expected_hypershift_node_pool_delete_payload,
    )


@pytest.fixture
def non_default_hypershift_worker_machine_pool() -> dict:
    return {
        "id": "new-workers",
        "instance_type": "m5.xlarge",
        "replicas": 3,
    }


@pytest.fixture
def hypershift_cluster_without_default_worker_machine_pools(
    hypershift_cluster_builder: Callable[..., ClusterV1],
    non_default_hypershift_worker_machine_pool: dict,
) -> ClusterV1:
    return hypershift_cluster_builder([non_default_hypershift_worker_machine_pool])


@pytest.fixture
def existing_multiple_hypershift_node_pools_with_defaults() -> list[dict]:
    return [
        {
            "id": "workers",
            "aws_node_pool": {"instance_type": "m5.xlarge"},
            "replicas": 3,
        },
        {
            "id": "workers-1",
            "aws_node_pool": {"instance_type": "m5.xlarge"},
            "replicas": 3,
        },
        {
            "id": "new-workers",
            "aws_node_pool": {"instance_type": "m5.xlarge"},
            "replicas": 3,
        },
    ]


def test_run_delete_node_pool_skip_workers_ones(
    mocker: MockerFixture,
    hypershift_cluster_without_default_worker_machine_pools: ClusterV1,
    existing_multiple_hypershift_node_pools_with_defaults: list[dict],
) -> None:
    mocks = setup_mocks(
        mocker,
        clusters=[hypershift_cluster_without_default_worker_machine_pools],
        node_pools=existing_multiple_hypershift_node_pools_with_defaults,
    )

    run(False)

    mocks["OCM"].delete_node_pool.assert_not_called()
