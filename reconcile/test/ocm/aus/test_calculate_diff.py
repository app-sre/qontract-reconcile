from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile.aus import base
from reconcile.aus.base import (
    ClusterUpgradePolicy,
    ControlPlaneUpgradePolicy,
    NodePoolUpgradePolicy,
    UpgradePolicyHandler,
    _calculate_node_pool_diffs,  # noqa: PLC2701
)
from reconcile.aus.cluster_version_data import (
    VersionData,
    VersionHistory,
    WorkloadHistory,
)
from reconcile.aus.models import NodePoolSpec
from reconcile.test.ocm.aus.fixtures import (
    build_cluster_health,
    build_cluster_upgrade_spec,
    build_organization,
    build_organization_upgrade_spec,
    build_upgrade_policy,
)
from reconcile.test.ocm.fixtures import build_label, build_ocm_cluster
from reconcile.utils.ocm.base import OCMVersionGate, build_label_container
from reconcile.utils.ocm.clusters import OCMCluster
from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def version_gate_mocks(mocker: MockerFixture) -> tuple[Mock, Mock]:
    return (
        mocker.patch("reconcile.aus.base.get_version_gates"),
        mocker.patch("reconcile.aus.base.get_version_agreement"),
    )


@pytest.fixture
def cluster() -> OCMCluster:
    return build_ocm_cluster(
        name="cluster-1",
        version="4.12.17",
        available_upgrades=["4.12.19"],
    )


NODE_POOL_SPECS = [
    NodePoolSpec(id="np-1", version="4.12.16"),
    NodePoolSpec(id="np-2", version="4.12.16"),
]


@pytest.fixture
def cluster_hypershift(
    version_gate_mocks: tuple[Mock, Mock],
    version_gate_4_12_ocp: OCMVersionGate,
) -> OCMCluster:
    version_gate_mocks[0].return_value = [version_gate_4_12_ocp]
    version_gate_mocks[0].return_value = [
        {
            "id": f"{version_gate_4_12_ocp.id}-agreement",
            "version_gate": version_gate_4_12_ocp.model_dump(by_alias=True),
        }
    ]

    return build_ocm_cluster(
        name="cluster-2",
        version="4.12.17",
        available_upgrades=["4.12.19"],
        hypershift=True,
    )


@pytest.fixture
def now(mocker: MockerFixture) -> datetime:
    d = datetime(2021, 8, 30, 18, 0, 0, 0, tzinfo=UTC)
    mocker.patch.object(base, "utc_now", return_value=d)
    return d


def build_version_data(
    check_in: datetime,
    version: str,
    workload: str,
    soak_days: int,
    reporting_clusters: list[str] | None = None,
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
    mocker: MockerFixture,
) -> None:
    get_version_agreement_mock = mocker.patch(
        "reconcile.aus.base.get_version_agreement"
    )
    get_version_agreement_mock.return_value = []
    workload = "wl"
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(workloads=[workload], soak_days=10),
                build_cluster_health(),
                [],
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
                organization_id="org-1-id",
                cluster=cluster,
                version="4.12.19",
                cluster_labels=build_label_container([
                    build_label(
                        key="sre-capabilities.aus.version-gate-approvals",
                        value="api.openshift.com/gate-ocp,api.openshift.com/gate-sts",
                    )
                ]),
                schedule_type="manual",
                next_run="2021-08-30T18:07:00Z",
            ),
        )
    ]


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
    get_version_agreement_mock = mocker.patch(
        "reconcile.aus.base.get_version_agreement"
    )
    get_version_agreement_mock.return_value = []

    workload = "wl"
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(workloads=[workload], soak_days=10),
                build_cluster_health(),
                [],
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
                organization_id="org-1-id",
                cluster_labels=build_label_container([
                    build_label(
                        key="sre-capabilities.aus.version-gate-approvals",
                        value="api.openshift.com/gate-ocp,api.openshift.com/gate-sts",
                    )
                ]),
                cluster=cluster,
                version="4.12.19",
                schedule_type="manual",
                next_run="2021-08-30T18:07:00Z",
            ),
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
    get_version_agreement_mock = mocker.patch(
        "reconcile.aus.base.get_version_agreement"
    )
    get_version_agreement_mock.return_value = []
    cnpd = mocker.patch("reconcile.aus.base._calculate_node_pool_diffs")
    cnpd.return_value = None
    workload = "wl"
    cluster.hypershift.enabled = True
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(workloads=[workload], soak_days=10),
                build_cluster_health(),
                [],
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
        )
    ]


def test_calculate_diff_create_control_plane_upgrade_no_gates(
    ocm_api: OCMBaseClient, cluster: OCMCluster, now: datetime, mocker: MockerFixture
) -> None:
    get_version_agreement_mock = mocker.patch(
        "reconcile.aus.base.get_version_agreement"
    )
    get_version_agreement_mock.return_value = []
    cnpd = mocker.patch("reconcile.aus.base._calculate_node_pool_diffs")
    cnpd.return_value = None
    workload = "wl"
    cluster.hypershift.enabled = True
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(workloads=[workload], soak_days=10),
                build_cluster_health(),
                [],
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
        )
    ]


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
                build_cluster_health(),
                [],
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
                build_cluster_health(),
                [],
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


@pytest.mark.parametrize(
    "cluster_2_mutexes, expected_upgrade",
    [
        (["foo"], 0),
        (["bar"], 1),
        ([], 1),
        (None, 1),
    ],
)
def test_calculate_diff_mutex_set(
    ocm_api: OCMBaseClient,
    cluster: OCMCluster,
    cluster_hypershift: OCMCluster,
    now: datetime,
    cluster_2_mutexes: list[str],
    expected_upgrade: int,
) -> None:
    workload = "wl"
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(
                    workloads=[workload], soak_days=1, mutexes=["foo"]
                ),
                build_cluster_health(),
                [],
            ),
            (
                cluster_hypershift,
                build_upgrade_policy(
                    workloads=[workload], soak_days=1, mutexes=cluster_2_mutexes
                ),
                build_cluster_health(),
                NODE_POOL_SPECS,
            ),
        ],
    )
    diffs = base.calculate_diff(
        [
            ClusterUpgradePolicy(
                organization_id="1",
                cluster_labels=build_label_container([
                    build_label(
                        key="sre-capabilities.aus.version-gate-approvals",
                        value="api.openshift.com/gate-ocp,api.openshift.com/gate-sts",
                    )
                ]),
                cluster=cluster,
                schedule_type="manual",
                next_run="2021-08-30T18:06:00Z",
                version="4.12.19",
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
    assert len(diffs) == expected_upgrade


def test_calculate_diff_implicit_mutex_set(
    ocm_api: OCMBaseClient,
    cluster_hypershift: OCMCluster,
    now: datetime,
) -> None:
    """
    This tests that the implicit mutex set by the cluster is respected.
    This prevents multiple node pool upgrades to happen for the same cluster.
    """
    workload = "wl"
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster_hypershift,
                build_upgrade_policy(
                    workloads=[workload],
                    soak_days=1,
                    mutexes=None,
                ),
                build_cluster_health(),
                [],
            ),
        ],
    )
    diffs = base.calculate_diff(
        [
            NodePoolUpgradePolicy(
                cluster=cluster_hypershift,
                schedule_type="manual",
                next_run="2021-08-30T18:06:00Z",
                version="4.12.19",
                node_pool="np-1",
            )
        ],
        org_upgrade_spec,
        ocm_api,
        build_version_data(
            check_in=now,
            version=cluster_hypershift.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert not diffs


@pytest.mark.parametrize(
    "max_parallel_upgrades, total_cluster_count, ongoing_cluster_upgrades, expected_skip",
    [
        # max_parallel_upgrades not set, only the mutex counts, we skip if there is at least one ongoing upgrade
        (None, 5, 0, False),
        (None, 5, 1, True),
        (None, 5, 4, True),
        ("1", 5, 0, False),  # 0 ongoing upgrade over 5 clusters, allow a new one
        ("1", 5, 1, True),  # 1 ongoing upgrade over 5 clusters, skip a new one
        ("1", 5, 2, True),  # 2 ongoing upgrades over 5 clusters, skip a new one
        ("2", 5, 0, False),  # 0 ongoing upgrade over 5 clusters, allow a new one
        ("2", 5, 1, False),  # 1 ongoing upgrade over 5 clusters, allow a new one
        ("2", 5, 2, True),  # 2 ongoing upgrades over 5 clusters, skip a new one
        ("2", 5, 3, True),  # 3 ongoing upgrades over 5 clusters, skip a new one
        ("2%", 5, 1, True),  # 1 ongoing upgrade over 5 clusters, skip a new one
        ("33%", 5, 0, False),  # 0 ongoing upgrade over 5 clusters, allow a new one
        ("33%", 5, 1, False),  # 1 ongoing upgrade over 5 clusters, allow a new one
        ("33%", 5, 2, True),  # 2 ongoing upgrade over 5 clusters, skip a new one
        ("33%", 5, 3, True),  # 3 ongoing upgrade over 5 clusters, skip a new one
        ("33%", 5, 4, True),  # 4 ongoing upgrades over 5 clusters, skip a new one
        ("50%", 5, 1, False),  # 1 ongoing upgrades over 5 clusters, allow a new one
        ("50%", 5, 2, True),  # 2 ongoing upgrades over 5 clusters, skip a new one
        ("50%", 5, 3, True),  # 3 ongoing upgrades over 5 clusters, skip a new one
        ("50%", 5, 4, True),  # 4 ongoing upgrades over 5 clusters, skip a new one
        ("50%", 6, 1, False),  # 1 ongoing upgrades over 6 clusters, allow a new one
        ("50%", 6, 2, False),  # 2 ongoing upgrades over 6 clusters, allow a new one
        ("50%", 6, 3, True),  # 3 ongoing upgrades over 6 clusters, skip a new one
        ("50%", 6, 4, True),  # 4 ongoing upgrades over 6 clusters, skip a new one
        ("100%", 6, 5, False),  # 5 ongoing upgrades over 6 clusters, allow a new one
    ],
)
def test_calculate_diff_max_parallel_upgrades_set(
    max_parallel_upgrades: str,
    total_cluster_count: int,
    ongoing_cluster_upgrades: int,
    expected_skip: bool,
) -> None:
    workload = "wl"
    sector = "sector-1"
    mutex = "common-mutex"
    org = build_organization(
        sector_max_parallel_upgrades={sector: max_parallel_upgrades},
        sector_dependencies={sector: []},
    )
    clusters = [
        build_ocm_cluster(name=f"cluster-{id}") for id in range(total_cluster_count)
    ]
    upgrading_cluster_names = {
        f"cluster-{id}" for id in range(ongoing_cluster_upgrades)
    }
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(
                    workloads=[workload], soak_days=1, sector=sector, mutexes=[mutex]
                ),
                build_cluster_health(),
                [],
            )
            for cluster in clusters
        ],
        org=org,
    )

    desired = org_upgrade_spec.specs[-1]

    # the cluster always has 1 effective mutex which corresponds to the cluster itself
    # no other cluster is in the mutex set
    sector_mutex_upgrades: dict[tuple[str, str], set[str]] = {
        (sector, desired.cluster.id): set(),
        (sector, mutex): upgrading_cluster_names,
    }

    skip = base.verify_max_upgrades_should_skip(
        desired=desired,
        locked={mutex: "cluster-0"} if ongoing_cluster_upgrades else {},
        sector_mutex_upgrades=sector_mutex_upgrades,
        sector=org_upgrade_spec.sectors[sector],
    )
    assert skip == expected_skip


# test to verify that base.verify_max_upgrades_should_skip behaves correctly
# when there are no mutexes but max_parallel_upgrades is set
# In this case, each cluster effectively only has its own mutex
# and can be upgraded independently of the others.
# max_parallel_upgrades is effectively ignored
@pytest.mark.parametrize(
    "max_parallel_upgrades, total_cluster_count, ongoing_cluster_upgrades, expected_skip",
    [
        ("1", 5, 0, False),
        ("1", 5, 1, False),
        ("1", 5, 2, False),
        ("2", 5, 0, False),
        ("2", 5, 1, False),
        ("2", 5, 2, False),
        ("2", 5, 3, False),
        ("2", 5, 4, False),
        ("2%", 5, 1, False),
        ("33%", 5, 1, False),
        ("33%", 5, 2, False),
        ("33%", 5, 3, False),
        ("33%", 5, 4, False),
        ("50%", 5, 1, False),
        ("50%", 5, 2, False),
        ("50%", 5, 3, False),
        ("50%", 5, 4, False),
        ("50%", 6, 1, False),
        ("50%", 6, 2, False),
        ("50%", 6, 3, False),
        ("50%", 6, 4, False),
        ("100%", 6, 5, False),
    ],
)
def test_calculate_diff_max_parallel_upgrades_set_no_mutex(
    max_parallel_upgrades: str,
    total_cluster_count: int,
    ongoing_cluster_upgrades: int,
    expected_skip: bool,
) -> None:
    workload = "wl"
    sector = "sector-1"
    org = build_organization(
        sector_max_parallel_upgrades={sector: max_parallel_upgrades},
        sector_dependencies={sector: []},
    )
    clusters = [
        build_ocm_cluster(name=f"cluster-{id}") for id in range(total_cluster_count)
    ]
    upgrading_cluster_names = {
        f"cluster-{id}" for id in range(ongoing_cluster_upgrades)
    }
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster,
                build_upgrade_policy(
                    workloads=[workload], soak_days=1, sector=sector, mutexes=None
                ),
                build_cluster_health(),
                [],
            )
            for cluster in clusters
        ],
        org=org,
    )

    desired = org_upgrade_spec.specs[-1]

    locked = {cid: cid for cid in upgrading_cluster_names}

    # the cluster always has 1 effective mutex which corresponds to the cluster itself
    # no other cluster is in the mutex set
    sector_mutex_upgrades: dict[tuple[str, str], set[str]] = {
        (sector, desired.cluster.id): set()
    }

    skip = base.verify_max_upgrades_should_skip(
        desired=desired,
        locked=locked,
        sector_mutex_upgrades=sector_mutex_upgrades,
        sector=org_upgrade_spec.sectors[sector],
    )
    assert skip == expected_skip


# test to verify that base.verify_max_upgrades_should_skip behaves correctly
# when the cluster has multiple mutexes in common with other clusters in the sector
# In this case, max_parallel_upgrades is applied to each sector/mutex pair.
# The cluster is not allowed to upgrade if the number of ongoing upgrades
# over the sector/mutex pair is greater than max_parallel_upgrades
@pytest.mark.parametrize(
    "max_parallel_upgrades, clusters_info, expected_skip",
    [
        ("50%", {"c0": {"mutexes": ["m1"], "upgrading": False}}, False),
        ("50%", {"c0": {"mutexes": ["m1"], "upgrading": True}}, True),
        (
            "50%",
            {
                "c0": {"mutexes": ["m1"], "upgrading": False},
                "c1": {"mutexes": ["m2"], "upgrading": True},
            },
            True,
        ),
        (
            "50%",
            {
                "c0": {"mutexes": ["m1"], "upgrading": True},
                "c1": {"mutexes": ["m2"], "upgrading": True},
            },
            True,
        ),
        (
            "50%",
            {
                "c0": {"mutexes": ["m1"], "upgrading": True},
                "c1": {"mutexes": ["m2"], "upgrading": True},
                "c2": {"mutexes": ["m1", "m2"], "upgrading": False},
            },
            False,
        ),
        (
            "50%",
            {
                "c0": {"mutexes": ["m1"], "upgrading": True},
                "c1": {"mutexes": ["m2"], "upgrading": True},
                "c2": {"mutexes": ["m1", "m2"], "upgrading": True},
            },
            True,
        ),
        (
            "50%",
            {
                "c0": {"mutexes": ["m1"], "upgrading": False},
                "c1": {"mutexes": ["m2"], "upgrading": True},
                "c2": {"mutexes": ["m1", "m2"], "upgrading": True},
            },
            True,
        ),
        (
            "50%",
            {
                "c0": {"mutexes": ["m1"], "upgrading": False},
                "c1": {"mutexes": ["m2"], "upgrading": False},
                "c2": {"mutexes": ["m1", "m2"], "upgrading": True},
            },
            False,
        ),
    ],
)
def test_calculate_diff_max_parallel_upgrades_set_multiple_mutexes(
    max_parallel_upgrades: str,
    clusters_info: dict[str, dict[str, Any]],
    expected_skip: bool,
) -> None:
    workload = "wl"
    sector = "sector-1"
    mutexes = ["m1", "m2"]
    org = build_organization(
        sector_max_parallel_upgrades={sector: max_parallel_upgrades},
        sector_dependencies={sector: []},
    )
    # add our cluster to the list of clusters
    clusters_info["mycluster"] = {"mutexes": mutexes, "upgrading": False}
    clusters = {
        cluster_name: build_ocm_cluster(name=cluster_name)
        for cluster_name in clusters_info
    }
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                clusters[cluster_name],
                build_upgrade_policy(
                    workloads=[workload],
                    soak_days=1,
                    sector=sector,
                    mutexes=info["mutexes"],
                ),
                build_cluster_health(),
                [],
            )
            for cluster_name, info in clusters_info.items()
        ],
        org=org,
    )

    # get the spec of our cluster
    desired = next(s for s in org_upgrade_spec.specs if s.cluster.name == "mycluster")

    # maps mutexes to one of the clusters that is upgrading (holding the mutex)
    locked = {}
    for mutex in mutexes:
        for cluster_name, info in clusters_info.items():
            if info["upgrading"] and mutex in info["mutexes"]:
                locked[mutex] = cluster_name
                break

    # maps sector+mutex to the clusters that are upgrading within them
    sector_mutex_upgrades: dict[tuple[str, str], set[str]] = defaultdict(set)
    for cluster_name, info in clusters_info.items():
        if info["upgrading"]:
            for mutex in info["mutexes"]:
                sector_mutex_upgrades.setdefault((sector, mutex), set()).add(
                    cluster_name
                )

    skip = base.verify_max_upgrades_should_skip(
        desired=desired,
        locked=locked,
        sector_mutex_upgrades=sector_mutex_upgrades,
        sector=org_upgrade_spec.sectors[sector],
    )
    assert skip == expected_skip


def test__calculate_node_pool_diffs(
    cluster: OCMCluster,
    now: datetime,
) -> None:
    node_pool_spec = NodePoolSpec(id="foo", version="4.12.19")
    cluster_upgrade_spec = build_cluster_upgrade_spec(
        name="cluster",
        node_pools=[node_pool_spec],
    )

    created = _calculate_node_pool_diffs(cluster_upgrade_spec, now)

    assert created is not None
    assert isinstance(created.policy, NodePoolUpgradePolicy)
    assert created.policy.node_pool == "foo"
    assert cluster_upgrade_spec.current_version == "4.13.0"
    assert created.policy.version == "4.13.0"


def test__calculate_node_pool_diffs_multiple(
    cluster: OCMCluster,
    now: datetime,
) -> None:
    node_pool_specs = [
        NodePoolSpec(id="oof", version="4.12.19"),
        NodePoolSpec(id="foo", version="4.12.19"),
    ]
    cluster_upgrade_spec = build_cluster_upgrade_spec(
        name="cluster",
        node_pools=node_pool_specs,
    )

    created = _calculate_node_pool_diffs(cluster_upgrade_spec, now)

    assert created is not None
    assert isinstance(created.policy, NodePoolUpgradePolicy)
    assert created.policy.node_pool == "oof"
