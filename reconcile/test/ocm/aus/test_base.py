from collections.abc import Callable
from datetime import (
    datetime,
    timedelta,
)
from typing import (
    Any,
    Optional,
)

import pytest
from dateutil import parser
from pytest_mock import MockerFixture

from reconcile.aus import base
from reconcile.aus.base import (
    AbstractUpgradePolicy,
    AddonUpgradePolicy,
    ClusterUpgradePolicy,
    ControlPlaneUpgradePolicy,
    UpgradePolicyHandler,
)
from reconcile.aus.cluster_version_data import (
    Stats,
    VersionData,
    VersionHistory,
    WorkloadHistory,
)
from reconcile.aus.models import (
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
    Sector,
)
from reconcile.test.ocm.aus.fixtures import (
    build_addon_upgrade_spec,
    build_cluster_upgrade_spec,
    build_organization,
    build_organization_upgrade_spec,
    build_upgrade_policy,
)
from reconcile.test.ocm.fixtures import (
    OcmUrl,
    build_ocm_cluster,
)
from reconcile.utils.ocm.clusters import OCMCluster
from reconcile.utils.ocm.upgrades import OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def cluster_1() -> OCMCluster:
    return build_ocm_cluster(
        name="cluster-1",
        version="4.12.17",
        available_upgrades=["4.12.19"],
    )


@pytest.fixture
def cluster_2() -> OCMCluster:
    return build_ocm_cluster(
        name="cluster-2",
        version="4.12.17",
        available_upgrades=["4.12.19"],
    )


@pytest.fixture
def version_gate_4_13_ocp_id() -> str:
    return "f0bbef99-d1ea-11ed-aefd-0a580a800209"


@pytest.fixture
def version_gate_4_13_ocp(version_gate_4_13_ocp_id: str) -> dict[str, Any]:
    return {
        "kind": "VersionGate",
        "id": version_gate_4_13_ocp_id,
        "version_raw_id_prefix": "4.13",
        "value": "4.13",
        "sts_only": False,
    }


@pytest.fixture
def version_gate_4_13_sts_id() -> str:
    return "ec6fa2a0-d1ea-11ed-aefd-0a580a800209"


@pytest.fixture
def version_gate_4_13_sts(version_gate_4_13_sts_id: str) -> dict[str, Any]:
    return {
        "kind": "VersionGate",
        "id": version_gate_4_13_sts_id,
        "version_raw_id_prefix": "4.13",
        "label": "api.openshift.com/gate-sts",
        "value": "4.13",
        "sts_only": True,
    }


@pytest.fixture
def version_gates(
    version_gate_4_13_ocp: dict[str, Any], version_gate_4_13_sts: dict[str, Any]
) -> list[dict[str, Any]]:
    # this fixture is used to mock the response from the OCM API
    return [version_gate_4_13_ocp, version_gate_4_13_sts]


@pytest.fixture
def now(mocker: MockerFixture) -> datetime:
    d = parser.parse("2021-08-30T18:00:00.00000")
    datetime_mock = mocker.patch.object(base, "datetime", autospec=True)
    datetime_mock.utcnow.return_value = d
    return d


@pytest.fixture
def cluster_1_version_gate_agreement_4_13_ocp(
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    cluster_1: OCMCluster,
    version_gate_4_13_ocp: dict[str, Any],
) -> str:
    gate_agreement_id = "cluster-1-4-13-ocp"
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET",
                uri=f"/api/clusters_mgmt/v1/clusters/{cluster_1.id}/gate_agreements",
            ).add_list_response(
                [
                    {
                        "kind": "VersionGateAgreement",
                        "id": gate_agreement_id,
                        "href": f"/api/clusters_mgmt/v1/clusters/{cluster_1.id}/gate_agreements/{gate_agreement_id}",
                        "version_gate": version_gate_4_13_ocp,
                    }
                ]
            )
        ]
    )
    return gate_agreement_id


@pytest.fixture
def cluster_1_version_gate_agreement_4_13_sts(
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    cluster_1: OCMCluster,
    version_gate_4_13_sts: dict[str, Any],
) -> str:
    gate_agreement_id = "cluster-1-4-13-sts"
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET",
                uri=f"/api/clusters_mgmt/v1/clusters/{cluster_1.id}/gate_agreements",
            ).add_list_response(
                [
                    {
                        "kind": "VersionGateAgreement",
                        "id": gate_agreement_id,
                        "href": f"/api/clusters_mgmt/v1/clusters/{cluster_1.id}/gate_agreements/{gate_agreement_id}",
                        "version_gate": version_gate_4_13_sts,
                    }
                ]
            )
        ]
    )
    return gate_agreement_id


@pytest.fixture
def cluster_1_version_gate_agreement_none(
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    cluster_1: OCMCluster,
    version_gate_4_13_sts: dict[str, Any],
) -> str:
    gate_agreement_id = "cluster-1-4-13-sts"
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET",
                uri=f"/api/clusters_mgmt/v1/clusters/{cluster_1.id}/gate_agreements",
            ).add_list_response([])
        ]
    )
    return gate_agreement_id


#
# upgrade lock tests
#


def test_calculate_diff_no_lock(
    ocm_api: OCMBaseClient,
    cluster_1: OCMCluster,
    now: datetime,
) -> None:
    """
    Test case: there is no other upgrade lock, so the cluster upgrade can be scheduled
    """
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster_1,
                build_upgrade_policy(
                    workloads=["workload1"], soak_days=0, mutexes=["mutex1"]
                ),
            ),
        ],
    )
    diffs = base.calculate_diff([], org_upgrade_spec, ocm_api, VersionData())
    assert diffs == [
        UpgradePolicyHandler(
            action="create",
            policy=ClusterUpgradePolicy(
                cluster=cluster_1.name,
                cluster_id=cluster_1.id,
                version="4.12.19",
                schedule_type="manual",
                next_run="2021-08-30T18:06:00Z",
            ),
            gates_to_agree=[],
        )
    ]


def test_calculate_diff_locked_out(
    ocm_api: OCMBaseClient,
    cluster_1: OCMCluster,
    cluster_2: OCMCluster,
    now: datetime,
) -> None:
    """
    Test case: cluster cluster_rosa_z_stream is currently being upgraded and holds the mutex1
    lock, so cluster cluster_osd_z_stream cannot be upgraded
    """
    current_state: list[AbstractUpgradePolicy] = [
        ClusterUpgradePolicy(
            cluster=cluster_2.name,
            cluster_uuid=cluster_2.external_id,
            cluster_id=cluster_2.id,
            version="4.12.19",
            schedule_type="manual",
        )
    ]

    upgrade_policy_spec = build_upgrade_policy(
        workloads=["workload1"], soak_days=0, mutexes=["mutex1"]
    )
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (cluster_1, upgrade_policy_spec),
            (cluster_2, upgrade_policy_spec),
        ],
    )
    diffs = base.calculate_diff(current_state, org_upgrade_spec, ocm_api, VersionData())

    assert not diffs


def test_calculate_diff_inter_lock(
    ocm_api: OCMBaseClient,
    cluster_1: OCMCluster,
    cluster_2: OCMCluster,
    now: datetime,
) -> None:
    """
    Test case: two clusters need an upgrade, but define the same mutex.
    only the first one will be upgraded
    """
    upgrade_policy_spec = build_upgrade_policy(
        workloads=["workload1"], soak_days=0, mutexes=["mutex1"]
    )
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (cluster_1, upgrade_policy_spec),
            (cluster_2, upgrade_policy_spec),
        ],
    )
    diffs = base.calculate_diff([], org_upgrade_spec, ocm_api, VersionData())

    assert diffs == [
        UpgradePolicyHandler(
            action="create",
            policy=ClusterUpgradePolicy(
                cluster=cluster_1.name,
                cluster_id=cluster_1.id,
                version="4.12.19",
                schedule_type="manual",
                next_run="2021-08-30T18:06:00Z",
            ),
            gates_to_agree=[],
        )
    ]


#
# test upgradable versions
#


def test_upgradeable_version_blocked(cluster_1: OCMCluster) -> None:
    upgrade_spec = ClusterUpgradeSpec(
        org=build_organization(blocked_versions=[".*"]),
        cluster=cluster_1,
        upgradePolicy=build_upgrade_policy(workloads=["workload1"], soak_days=0),
    )
    x = base.upgradeable_version(upgrade_spec, VersionData(), None)
    assert x is None


def test_upgradeable_version_no_block(cluster_1: OCMCluster) -> None:
    upgrade_spec = ClusterUpgradeSpec(
        org=build_organization(),
        cluster=cluster_1,
        upgradePolicy=build_upgrade_policy(workloads=["workload1"], soak_days=0),
    )
    assert "4.12.19" == base.upgradeable_version(upgrade_spec, VersionData(), None)


#
# test gate agreement
#


def test_gates_to_agree_same_version(
    cluster_1: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_ocp_id: str,
    cluster_1_version_gate_agreement_none: str,
    ocm_api: OCMBaseClient,
) -> None:
    gates = base.gates_to_agree(
        gates=[OCMVersionGate(**g) for g in version_gates],
        version_prefix="4.12",
        cluster=cluster_1,
        ocm_api=ocm_api,
    )
    assert gates == []


def test_gates_to_agree_ocp_agreement_required(
    cluster_1: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_ocp_id: str,
    cluster_1_version_gate_agreement_none: str,
    ocm_api: OCMBaseClient,
) -> None:
    cluster_1.version.available_upgrades = ["4.13.2"]
    cluster_1.aws.sts.enabled = False  # type: ignore
    gates = base.gates_to_agree(
        gates=[OCMVersionGate(**g) for g in version_gates],
        version_prefix="4.13",
        cluster=cluster_1,
        ocm_api=ocm_api,
    )
    assert gates == [version_gate_4_13_ocp_id]


def test_gates_to_agree_ocp_agreement_present(
    cluster_1: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_ocp_id: str,
    cluster_1_version_gate_agreement_4_13_ocp: str,
    ocm_api: OCMBaseClient,
) -> None:
    cluster_1.version.available_upgrades = ["4.13.2"]
    cluster_1.aws.sts.enabled = False  # type: ignore
    gates = base.gates_to_agree(
        gates=[OCMVersionGate(**g) for g in version_gates],
        version_prefix="4.13",
        cluster=cluster_1,
        ocm_api=ocm_api,
    )
    assert gates == []


def test_gates_to_agree_sts_agreement_required(
    cluster_1: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_sts_id: str,
    cluster_1_version_gate_agreement_none: str,
    ocm_api: OCMBaseClient,
) -> None:
    cluster_1.version.available_upgrades = ["4.13.2"]
    cluster_1.aws.sts.enabled = True  # type: ignore
    gates = base.gates_to_agree(
        gates=[OCMVersionGate(**g) for g in version_gates],
        version_prefix="4.13",
        cluster=cluster_1,
        ocm_api=ocm_api,
    )
    assert gates == [version_gate_4_13_sts_id]


def test_gates_to_agree_sts_agreement_present(
    cluster_1: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_sts_id: str,
    cluster_1_version_gate_agreement_4_13_sts: str,
    ocm_api: OCMBaseClient,
) -> None:
    cluster_1.version.available_upgrades = ["4.13.2"]
    cluster_1.aws.sts.enabled = True  # type: ignore
    gates = base.gates_to_agree(
        gates=[OCMVersionGate(**g) for g in version_gates],
        version_prefix="4.13",
        cluster=cluster_1,
        ocm_api=ocm_api,
    )
    assert gates == []


#
# upgrade priority
#


def test_sorted_version() -> None:
    """
    cluster upgrades are prioritized according to their current versions
    """
    org = OrganizationUpgradeSpec(
        org=build_organization(),
        specs=[
            build_cluster_upgrade_spec(
                name="cluster2", current_version="4.2.0", soak_days=0
            ),
            build_cluster_upgrade_spec(
                name="cluster1", current_version="4.1.0", soak_days=0
            ),
            build_cluster_upgrade_spec(
                name="cluster3", current_version="4.3.0", soak_days=0
            ),
        ],
    )
    assert ["cluster1", "cluster2", "cluster3"] == [s.cluster.name for s in org.specs]


def test_sorted_soakdays() -> None:
    """
    cluster upgrades are prioritized according to their soakdays
    """
    org = OrganizationUpgradeSpec(
        org=build_organization(),
        specs=[
            build_cluster_upgrade_spec(
                name="cluster2", current_version="4.1.0", soak_days=2
            ),
            build_cluster_upgrade_spec(
                name="cluster1", current_version="4.1.0", soak_days=1
            ),
            build_cluster_upgrade_spec(
                name="cluster3", current_version="4.1.0", soak_days=3
            ),
        ],
    )
    assert ["cluster1", "cluster2", "cluster3"] == [s.cluster.name for s in org.specs]


def test_sorted_version_soakdays() -> None:
    """
    cluster upgrades are prioritized according to their curent version and soakdays
    in that order
    The test test_calculate_diff_inter_lock above ensures that
    only the first cluster with a given mutex will get upgraded.
    """
    org = OrganizationUpgradeSpec(
        org=build_organization(),
        specs=[
            build_cluster_upgrade_spec(
                name="cluster22", current_version="4.2.0", soak_days=2
            ),
            build_cluster_upgrade_spec(
                name="cluster12", current_version="4.1.0", soak_days=2
            ),
            build_cluster_upgrade_spec(
                name="cluster11", current_version="4.1.0", soak_days=1
            ),
            build_cluster_upgrade_spec(
                name="cluster21", current_version="4.2.0", soak_days=1
            ),
        ],
    )
    assert ["cluster11", "cluster12", "cluster21", "cluster22"] == [
        s.cluster.name for s in org.specs
    ]


#
# test version conditions met sector
#


@pytest.fixture
def sector_1() -> Sector:
    return Sector(name="sector_1")


@pytest.fixture
def sector_2(sector_1: Sector) -> Sector:
    return Sector(name="sector_2", dependencies=[sector_1])


@pytest.fixture
def sector_3(sector_2: Sector) -> Sector:
    return Sector(name="sector_3", dependencies=[sector_2])


@pytest.fixture
def empty_version_data() -> VersionData:
    return VersionData(
        check_in="2021-08-29T18:00:00",
        versions={},
        stats=Stats(min_version="1.0.0", min_version_per_workload={}),
    )


def test_conditions_met_no_deps(
    sector_1: Sector, empty_version_data: VersionData
) -> None:
    upgrade_policy = build_upgrade_policy(workloads=["workload1"], soak_days=0)
    assert base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_1
    )


def test_conditions_met_single_deps_no_cluster(
    sector_2: Sector, empty_version_data: VersionData
) -> None:
    upgrade_policy = build_upgrade_policy(workloads=["workload1"], soak_days=0)
    assert base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector_2
    )


def test_conditions_met_single_deps_high_version(
    sector_1: Sector,
    sector_2: Sector,
    empty_version_data: VersionData,
) -> None:
    """
    Test case: version conditions are met because all clusters in sector 1
    run at least the version we want to upgrade to in sector 2.
    """
    workload = "wl"
    sector_1.add_spec(
        build_cluster_upgrade_spec(
            name="high-version-cluster", current_version="2.0.0", workloads=[workload]
        )
    )
    sector_1.add_spec(
        build_cluster_upgrade_spec(
            name="same-version-cluster", current_version="1.2.3", workloads=[workload]
        )
    )
    upgrade_policy = build_upgrade_policy(workloads=[workload], soak_days=0)
    assert base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_2
    )


def test_conditions_met_single_deps_low_version(
    sector_1: Sector,
    sector_2: Sector,
    empty_version_data: VersionData,
) -> None:
    """
    Test case: version conditions are not met because not all clusters in
    sector 1 run the version we want to upgrade to in sector 2
    """
    workload = "wl"
    sector_1.add_spec(
        build_cluster_upgrade_spec(
            name="low-version-cluster", current_version="1.0.0", workloads=[workload]
        )
    )
    sector_1.add_spec(
        build_cluster_upgrade_spec(
            name="same-version-cluster", current_version="1.2.3", workloads=[workload]
        )
    )
    upgrade_policy = build_upgrade_policy(workloads=[workload], soak_days=0)
    assert not base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_2
    )


def test_conditions_met_single_deps_mixed_version(
    sector_1: Sector,
    sector_2: Sector,
    empty_version_data: VersionData,
) -> None:
    """
    Test case: version conditions are not met because not all clusters in
    sector 1 run the version we want to upgrade to in sector 2
    """
    workload = "wl"
    sector_1.add_spec(
        build_cluster_upgrade_spec(
            name="low-version-cluster", current_version="1.0.0", workloads=[workload]
        )
    )
    sector_1.add_spec(
        build_cluster_upgrade_spec(
            name="same-version-cluster", current_version="1.2.3", workloads=[workload]
        )
    )
    sector_1.add_spec(
        build_cluster_upgrade_spec(
            name="high-version-cluster", current_version="2.0.0", workloads=[workload]
        )
    )
    upgrade_policy = build_upgrade_policy(workloads=[workload], soak_days=0)
    assert not base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_2
    )


def test_conditions_met_deep_deps_mix_versions(
    sector_3: Sector,
    empty_version_data: VersionData,
) -> None:
    sector_1 = sector_3.dependencies[0].dependencies[0]
    workload = "wl"
    upgrade_policy = build_upgrade_policy(workloads=[workload], soak_days=0)

    # no clusters in deps: upgrade ok
    assert base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_3
    )

    # all clusters with higher version in deps: upgrade ok
    sector_1.set_specs(
        [
            build_cluster_upgrade_spec(
                name="high-version-cluster",
                current_version="2.0.0",
                workloads=[workload],
            )
        ]
    )
    assert base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_3
    )

    # no cluster with higher version in deps: upgrade not ok
    sector_1.set_specs(
        [
            build_cluster_upgrade_spec(
                name="low-version-cluster",
                current_version="1.0.0",
                workloads=[workload],
            )
        ]
    )
    assert not base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_3
    )

    # not all clusters with higher version in deps: upgrade not ok
    sector_1.set_specs(
        [
            build_cluster_upgrade_spec(
                name="low-version-cluster",
                current_version="1.0.0",
                workloads=[workload],
            ),
            build_cluster_upgrade_spec(
                name="low-version-cluster",
                current_version="1.0.0",
                workloads=[workload],
            ),
        ]
    )
    assert not base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_3
    )


#
# policy handler
#


class StubPolicy(base.AbstractUpgradePolicy):
    created = False
    deleted = False

    def create(self, ocm_api: OCMBaseClient) -> None:
        self.created = True

    def delete(self, ocm_api: OCMBaseClient) -> None:
        self.deleted = True

    def summarize(self) -> str:
        return "do-something"


@pytest.fixture
def stub_policy() -> StubPolicy:
    return StubPolicy(
        cluster="cluster",
        cluster_id="cluster-id",
        schedule_type="manual",
        version="4.1.2",
    )


@pytest.fixture
def cluster_upgrade_policy() -> ClusterUpgradePolicy:
    return ClusterUpgradePolicy(
        id="test-policy-id",
        cluster="cluster",
        cluster_id="cluster-id",
        schedule_type="manual",
        version="4.1.2",
        next_run="soon",
    )


@pytest.fixture
def control_plane_upgrade_policy() -> ControlPlaneUpgradePolicy:
    return ControlPlaneUpgradePolicy(
        id="test-policy-id",
        cluster="cluster",
        cluster_id="cluster-id",
        schedule_type="manual",
        version="4.1.2",
        next_run="soon",
    )


@pytest.fixture
def addon_upgrade_policy() -> AddonUpgradePolicy:
    return AddonUpgradePolicy(
        id="test-policy-id",
        cluster="cluster",
        cluster_id="cluster-id",
        schedule_type="manual",
        version="1.2.3",
        next_run="soon",
        addon_id="test-addon",
    )


def test_policy_handler_act_with_diff(
    stub_policy: StubPolicy, ocm_api: OCMBaseClient
) -> None:
    handler = base.UpgradePolicyHandler(
        policy=stub_policy,
        action="create",
    )
    base.act(dry_run=False, diffs=[handler], ocm_api=ocm_api)
    assert stub_policy.created
    assert not stub_policy.deleted


def test_policy_handler_act_delete(
    stub_policy: StubPolicy, ocm_api: OCMBaseClient
) -> None:
    handler = base.UpgradePolicyHandler(
        policy=stub_policy,
        action="delete",
    )
    base.act(dry_run=False, diffs=[handler], ocm_api=ocm_api)
    assert not stub_policy.created
    assert stub_policy.deleted


def test_policy_handler_create_cluster_upgrade(
    cluster_upgrade_policy: ClusterUpgradePolicy,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
) -> None:
    create_upgrade_policy_mock = mocker.patch.object(
        base, "create_upgrade_policy", autospec=True
    )
    handler = base.UpgradePolicyHandler(
        policy=cluster_upgrade_policy,
        action="create",
    )
    base.act(dry_run=False, diffs=[handler], ocm_api=ocm_api)
    create_upgrade_policy_mock.assert_called_once_with(
        ocm_api,
        cluster_upgrade_policy.cluster_id,
        {
            "version": cluster_upgrade_policy.version,
            "schedule_type": cluster_upgrade_policy.schedule_type,
            "next_run": cluster_upgrade_policy.next_run,
        },
    )


def test_policy_handler_delete_cluster_upgrade(
    cluster_upgrade_policy: ClusterUpgradePolicy,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
) -> None:
    delete_upgrade_policy_mock = mocker.patch.object(
        base, "delete_upgrade_policy", autospec=True
    )
    handler = base.UpgradePolicyHandler(
        policy=cluster_upgrade_policy,
        action="delete",
    )
    base.act(dry_run=False, diffs=[handler], ocm_api=ocm_api)
    delete_upgrade_policy_mock.assert_called_once_with(
        ocm_api,
        cluster_upgrade_policy.cluster_id,
        cluster_upgrade_policy.id,
    )


def test_policy_handler_create_control_plane_upgrade(
    control_plane_upgrade_policy: ControlPlaneUpgradePolicy,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
) -> None:
    create_control_plane_upgrade_policy_mock = mocker.patch.object(
        base, "create_control_plane_upgrade_policy", autospec=True
    )
    handler = base.UpgradePolicyHandler(
        policy=control_plane_upgrade_policy,
        action="create",
    )
    base.act(dry_run=False, diffs=[handler], ocm_api=ocm_api)
    create_control_plane_upgrade_policy_mock.assert_called_once_with(
        ocm_api,
        control_plane_upgrade_policy.cluster_id,
        {
            "version": control_plane_upgrade_policy.version,
            "schedule_type": control_plane_upgrade_policy.schedule_type,
            "next_run": control_plane_upgrade_policy.next_run,
            "cluster_id": control_plane_upgrade_policy.cluster_id,
            "upgrade_type": "ControlPlane",
        },
    )


def test_policy_handler_delete_control_plane_upgrade(
    control_plane_upgrade_policy: ControlPlaneUpgradePolicy,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
) -> None:
    delete_control_plane_upgrade_policy_mock = mocker.patch.object(
        base, "delete_control_plane_upgrade_policy", autospec=True
    )
    handler = base.UpgradePolicyHandler(
        policy=control_plane_upgrade_policy,
        action="delete",
    )
    base.act(dry_run=False, diffs=[handler], ocm_api=ocm_api)
    delete_control_plane_upgrade_policy_mock.assert_called_once_with(
        ocm_api,
        control_plane_upgrade_policy.cluster_id,
        control_plane_upgrade_policy.id,
    )


def test_policy_handler_create_addon_upgrade(
    addon_upgrade_policy: AddonUpgradePolicy,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
) -> None:
    create_addon_upgrade_policy_mock = mocker.patch.object(
        base, "create_addon_upgrade_policy", autospec=True
    )
    handler = base.UpgradePolicyHandler(
        policy=addon_upgrade_policy,
        action="create",
    )
    base.act(dry_run=False, diffs=[handler], ocm_api=ocm_api)
    create_addon_upgrade_policy_mock.assert_called_once_with(
        ocm_api,
        addon_upgrade_policy.cluster_id,
        {
            "version": addon_upgrade_policy.version,
            "schedule_type": addon_upgrade_policy.schedule_type,
            "cluster_id": addon_upgrade_policy.cluster_id,
            "upgrade_type": "ADDON",
            "addon_id": addon_upgrade_policy.addon_id,
        },
    )


def test_policy_handler_delete_addon_upgrade(
    addon_upgrade_policy: AddonUpgradePolicy,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
) -> None:
    delete_addon_upgrade_policy_mock = mocker.patch.object(
        base, "delete_addon_upgrade_policy", autospec=True
    )
    handler = base.UpgradePolicyHandler(
        policy=addon_upgrade_policy,
        action="delete",
    )
    base.act(dry_run=False, diffs=[handler], ocm_api=ocm_api)
    delete_addon_upgrade_policy_mock.assert_called_once_with(
        ocm_api,
        addon_upgrade_policy.cluster_id,
        addon_upgrade_policy.id,
    )


#
# calculate diff
#


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


def test_calculate_diff_create_cluster_upgrade_no_gate(
    ocm_api: OCMBaseClient,
    cluster_1: OCMCluster,
    now: datetime,
) -> None:
    workload = "wl"
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster_1,
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
            version=cluster_1.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert diffs == [
        UpgradePolicyHandler(
            action="create",
            policy=ClusterUpgradePolicy(
                cluster=cluster_1.name,
                cluster_id=cluster_1.id,
                version="4.12.19",
                schedule_type="manual",
                next_run="2021-08-30T18:06:00Z",
            ),
            gates_to_agree=[],
        )
    ]


def test_calculate_diff_create_control_plane_upgrade_no_gate(
    ocm_api: OCMBaseClient,
    cluster_1: OCMCluster,
    now: datetime,
) -> None:
    workload = "wl"
    cluster_1.hypershift.enabled = True
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster_1,
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
            version=cluster_1.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert diffs == [
        UpgradePolicyHandler(
            action="create",
            policy=ControlPlaneUpgradePolicy(
                cluster=cluster_1.name,
                cluster_id=cluster_1.id,
                version="4.12.19",
                schedule_type="manual",
                next_run="2021-08-30T18:06:00Z",
            ),
            gates_to_agree=[],
        )
    ]


def test_calculate_diff_not_soaked(
    ocm_api: OCMBaseClient,
    cluster_1: OCMCluster,
    now: datetime,
) -> None:
    workload = "wl"
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster_1,
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
            version=cluster_1.available_upgrades()[0],
            workload=workload,
            soak_days=11,
        ),
    )
    assert not diffs


#
# get available upgrades
#


def test_get_available_upgrades_cluster_upgrade_spec() -> None:
    cluster_upgrade_spec = build_cluster_upgrade_spec(
        name="cluster",
        available_upgrades=["1", "2", "3"],
    )
    assert cluster_upgrade_spec.get_available_upgrades() == ["1", "2", "3"]


def test_get_available_upgrades_addon_upgrade_spec() -> None:
    addon_upgrade_spec = build_addon_upgrade_spec(
        cluster_name="cluster-1",
        addon_id="addon-1",
        available_cluster_upgrades=["1", "2", "3"],
        available_addon_upgrades=["4", "5", "6"],
    )
    assert addon_upgrade_spec.get_available_upgrades() == ["4", "5", "6"]


#
# test verify lock should skip
#


def test_verify_lock_should_skip_not_locked() -> None:
    cluster_upgrade_spec = build_cluster_upgrade_spec(
        name="cluster",
        available_upgrades=["1", "2", "3"],
        mutexes=["mutex-1"],
    )
    locked = base.verify_lock_should_skip(cluster_upgrade_spec, {})
    assert not locked


def test_verify_lock_should_skip_locked_by_self() -> None:
    cluster_upgrade_spec = build_cluster_upgrade_spec(
        name="cluster",
        available_upgrades=["1", "2", "3"],
        mutexes=["mutex-1"],
    )
    locked = base.verify_lock_should_skip(
        cluster_upgrade_spec, {"mutex-1": cluster_upgrade_spec.cluster.id}
    )
    assert locked


def test_verify_lock_should_skip_locked_by_another_cluster() -> None:
    cluster_upgrade_spec = build_cluster_upgrade_spec(
        name="cluster",
        available_upgrades=["1", "2", "3"],
        mutexes=["mutex-1"],
    )
    locked = base.verify_lock_should_skip(
        cluster_upgrade_spec, {"mutex-1": "some-other-cluster-id"}
    )
    assert locked


#
# test verify schedule should skip
#


def test_verify_schedule_should_skip_cluster_now() -> None:
    cluster_upgrade_spec = build_cluster_upgrade_spec(name="cluster")
    now = datetime.now()
    expected = now + timedelta(minutes=6)
    s = base.verify_schedule_should_skip(
        cluster_upgrade_spec,
        now,
    )
    assert s == expected.strftime("%Y-%m-%dT%H:%M:00Z")


def test_verify_schedule_should_skip_addon_now() -> None:
    addon_upgrade_spec = build_addon_upgrade_spec(
        cluster_name="cluster",
        addon_id="addon",
    )
    now = datetime.now()
    expected = now + timedelta(minutes=2)
    s = base.verify_schedule_should_skip(
        addon_upgrade_spec, now, addon_upgrade_spec.addon.id
    )
    assert s == expected.strftime("%Y-%m-%dT%H:%M:00Z")


def test_verify_schedule_should_skip_cluster_future() -> None:
    cluster_upgrade_spec = build_cluster_upgrade_spec(name="cluster")
    now = datetime.now()
    next_day = now + timedelta(hours=3)
    cluster_upgrade_spec.upgrade_policy.schedule = f"* {next_day.hour} * * *"
    s = base.verify_schedule_should_skip(
        cluster_upgrade_spec,
        now,
    )
    assert s is None
