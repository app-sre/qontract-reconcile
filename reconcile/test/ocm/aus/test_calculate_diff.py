from datetime import datetime
from typing import (
    Optional,
    Tuple,
)
from unittest.mock import Mock

import pytest
from dateutil import parser
from pytest_mock import MockerFixture

from reconcile.aus import base
from reconcile.aus.base import (
    ClusterUpgradePolicy,
    ControlPlaneUpgradePolicy,
    NodePoolUpgradePolicy,
    UpgradePolicyHandler,
    _calculate_node_pool_diffs,
)
from reconcile.aus.cluster_version_data import (
    VersionData,
    VersionHistory,
    WorkloadHistory,
)
from reconcile.test.ocm.aus.fixtures import (
    build_cluster_upgrade_spec,
    build_organization_upgrade_spec,
    build_upgrade_policy,
)
from reconcile.test.ocm.fixtures import build_ocm_cluster
from reconcile.utils.ocm.base import OCMVersionGate
from reconcile.utils.ocm.clusters import OCMCluster
from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def cluster() -> OCMCluster:
    return build_ocm_cluster(
        name="cluster-1",
        version="4.12.17",
        available_upgrades=["4.12.19"],
    )


@pytest.fixture
def now(mocker: MockerFixture) -> datetime:
    d = parser.parse("2021-08-30T18:00:00.00000")
    datetime_mock = mocker.patch.object(base, "datetime", autospec=True)
    datetime_mock.utcnow.return_value = d
    return d


def build_version_data(
    check_in: datetime,
    version: str,
    workload: str,
    soak_days: int,
    reporting_clusters: Optional[list[str]] = None,
) -> VersionData:
    return VersionData(
        check_in=check_in,
        versions={
            version: VersionHistory(
                version=version,
                workloads={
                    workload: WorkloadHistory(
                        workload=workload,
                        soak_days=soak_days,
                        reporting=reporting_clusters
                        or ["a-cluster", "another-cluster"],
                    )
                },
            )
        },
    )


def test_calculate_diff_empty(ocm_api: OCMBaseClient) -> None:
    assert not base.calculate_diff(
        [], build_organization_upgrade_spec(specs=[]), ocm_api, VersionData()
    )


def test_calculate_diff_create_cluster_upgrade_no_gates(
    ocm_api: OCMBaseClient,
    cluster: OCMCluster,
    now: datetime,
) -> None:
    workload = "wl"
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(workloads=[workload], soak_days=10),
            ),
        ],
    )
    diffs = base.calculate_diff(
        [],
        org_upgrade_spec,
        ocm_api,
        build_version_data(
            check_in=now,
            version=cluster.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert diffs == []


def test_calculate_diff_create_cluster_upgrade_all_gates_agreed(
    ocm_api: OCMBaseClient,
    cluster: OCMCluster,
    now: datetime,
    mocker: MockerFixture,
) -> None:
    get_version_gates_mock = mocker.patch("reconcile.aus.base.get_version_gates")
    get_version_gates_mock.return_value = [
        OCMVersionGate(**{
            "kind": "VersionGate",
            "id": "gate_id",
            "version_raw_id_prefix": "4.12",
            "label": "api.openshift.com/some-gate",
            "value": "4.12",
            "sts_only": False,
        })
    ]
    gates_to_agree_mock = mocker.patch("reconcile.aus.base.gates_to_agree")
    gates_to_agree_mock.return_value = []

    workload = "wl"
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(workloads=[workload], soak_days=10),
            ),
        ],
    )
    diffs = base.calculate_diff(
        [],
        org_upgrade_spec,
        ocm_api,
        build_version_data(
            check_in=now,
            version=cluster.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert diffs == [
        UpgradePolicyHandler(
            action="create",
            policy=ClusterUpgradePolicy(
                cluster=cluster,
                version="4.12.19",
                schedule_type="manual",
                next_run="2021-08-30T18:07:00Z",
            ),
            gates_to_agree=[],
        )
    ]


def test_calculate_diff_create_control_plane_upgrade_all_gates_agreed(
    ocm_api: OCMBaseClient, cluster: OCMCluster, now: datetime, mocker: MockerFixture
) -> None:
    get_version_gates_mock = mocker.patch("reconcile.aus.base.get_version_gates")
    get_version_gates_mock.return_value = [
        OCMVersionGate(**{
            "kind": "VersionGate",
            "id": "gate_id",
            "version_raw_id_prefix": "4.12",
            "label": "api.openshift.com/some-gate",
            "value": "4.12",
            "sts_only": False,
        })
    ]
    gates_to_agree_mock = mocker.patch("reconcile.aus.base.gates_to_agree")
    gates_to_agree_mock.return_value = []
    cnpd = mocker.patch("reconcile.aus.base._calculate_node_pool_diffs")
    cnpd.return_value = None
    workload = "wl"
    cluster.hypershift.enabled = True
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(workloads=[workload], soak_days=10),
            ),
        ],
    )
    diffs = base.calculate_diff(
        [],
        org_upgrade_spec,
        ocm_api,
        build_version_data(
            check_in=now,
            version=cluster.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert diffs == [
        UpgradePolicyHandler(
            action="create",
            policy=ControlPlaneUpgradePolicy(
                cluster=cluster,
                version="4.12.19",
                schedule_type="manual",
                next_run="2021-08-30T18:07:00Z",
            ),
            gates_to_agree=[],
        )
    ]


def test_calculate_diff_create_control_plane_upgrade_no_gates(
    ocm_api: OCMBaseClient, cluster: OCMCluster, now: datetime, mocker: MockerFixture
) -> None:
    cnpd = mocker.patch("reconcile.aus.base._calculate_node_pool_diffs")
    cnpd.return_value = None
    workload = "wl"
    cluster.hypershift.enabled = True
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(workloads=[workload], soak_days=10),
            ),
        ],
    )
    diffs = base.calculate_diff(
        [],
        org_upgrade_spec,
        ocm_api,
        build_version_data(
            check_in=now,
            version=cluster.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert diffs == []


def test_calculate_diff_create_control_plane_node_pool_only(
    ocm_api: OCMBaseClient, cluster: OCMCluster, now: datetime, mocker: MockerFixture
) -> None:
    expected = UpgradePolicyHandler(
        action="create",
        policy=NodePoolUpgradePolicy(
            cluster=cluster,
            version="4.12.19",
            schedule_type="manual",
            next_run="2021-08-30T18:06:00Z",
            node_pool="foo",
        ),
    )
    cnpd = mocker.patch("reconcile.aus.base._calculate_node_pool_diffs")
    cnpd.return_value = expected
    workload = "wl"
    cluster.hypershift.enabled = True
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(workloads=[workload], soak_days=10),
            ),
        ],
    )
    diffs = base.calculate_diff(
        [],
        org_upgrade_spec,
        ocm_api,
        build_version_data(
            check_in=now,
            version=cluster.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert diffs == [expected]


def test_calculate_diff_not_soaked(
    ocm_api: OCMBaseClient,
    cluster: OCMCluster,
    now: datetime,
) -> None:
    workload = "wl"
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(workloads=[workload], soak_days=12),
            ),
        ],
    )
    diffs = base.calculate_diff(
        [],
        org_upgrade_spec,
        ocm_api,
        build_version_data(
            check_in=now,
            version=cluster.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert not diffs


def test_calculate_diff_mutex_set(
    ocm_api: OCMBaseClient,
    cluster: OCMCluster,
    now: datetime,
) -> None:
    workload = "wl"
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(
                    workloads=[workload], soak_days=1, mutexes=["foo"]
                ),
            ),
        ],
    )
    diffs = base.calculate_diff(
        [
            NodePoolUpgradePolicy(
                cluster=cluster,
                schedule_type="manual",
                next_run="2021-08-30T18:06:00Z",
                version="4.12.19",
                node_pool="foo",
            )
        ],
        org_upgrade_spec,
        ocm_api,
        build_version_data(
            check_in=now,
            version=cluster.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert not diffs


@pytest.fixture
def node_pool_mocks(mocker: MockerFixture) -> Tuple[Mock, Mock, Mock]:
    return (
        mocker.patch("reconcile.aus.base.get_node_pools"),
        mocker.patch("reconcile.aus.base.get_version"),
        mocker.patch("reconcile.aus.base.get_node_pool_upgrade_policies"),
    )


def test__calculate_node_pool_diffs(
    ocm_api: OCMBaseClient,
    cluster: OCMCluster,
    now: datetime,
    node_pool_mocks: Tuple[Mock, Mock, Mock],
) -> None:
    node_pool_mocks[0].return_value = [
        {"id": "foo", "version": {"raw_id": "openshift-v4.12.19"}}
    ]
    node_pool_mocks[1].return_value = {"id": "4.12.19", "raw_id": "4.12.19"}
    node_pool_mocks[2].return_value = []

    cluster_upgrade_spec = build_cluster_upgrade_spec(name="cluster")
    created = _calculate_node_pool_diffs(ocm_api, cluster_upgrade_spec, now)
    assert created is not None
    assert isinstance(created.policy, NodePoolUpgradePolicy)
    assert created.policy.node_pool == "foo"
    assert cluster_upgrade_spec.current_version == "4.13.0"
    assert created.policy.version == "4.13.0"


def test__calculate_node_pool_diffs_multiple(
    ocm_api: OCMBaseClient,
    cluster: OCMCluster,
    now: datetime,
    node_pool_mocks: Tuple[Mock, Mock, Mock],
) -> None:
    node_pool_mocks[0].return_value = [
        {"id": "oof", "version": {"raw_id": "openshift-v4.12.19"}},
        {"id": "foo", "version": {"raw_id": "openshift-v4.12.19"}},
    ]
    node_pool_mocks[1].return_value = {"id": "4.12.19", "raw_id": "4.12.19"}
    node_pool_mocks[2].return_value = []

    cluster_upgrade_spec = build_cluster_upgrade_spec(name="cluster")
    created = _calculate_node_pool_diffs(ocm_api, cluster_upgrade_spec, now)
    assert created is not None
    assert isinstance(created.policy, NodePoolUpgradePolicy)
    assert created.policy.node_pool == "oof"
