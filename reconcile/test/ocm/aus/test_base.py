from collections.abc import Callable
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import Any
from unittest.mock import ANY, create_autospec

import pytest
from pytest_mock import MockerFixture

from reconcile.aus import base
from reconcile.aus.base import (
    AbstractUpgradePolicy,
    AddonUpgradePolicy,
    ClusterUpgradePolicy,
    ControlPlaneUpgradePolicy,
    RosaRoleUpgradeHandlerParams,
    UpgradePolicyHandler,
    get_orgs_for_environment,
)
from reconcile.aus.cluster_version_data import (
    Stats,
    VersionData,
)
from reconcile.aus.models import (
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
    Sector,
)
from reconcile.test.ocm.aus.fixtures import (
    build_addon_upgrade_spec,
    build_cluster_health,
    build_cluster_labels,
    build_cluster_upgrade_spec,
    build_healthy_cluster_health,
    build_organization,
    build_organization_upgrade_spec,
    build_upgrade_policy,
)
from reconcile.test.ocm.fixtures import build_label, build_ocm_cluster
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.ocm.addons import AddonService
from reconcile.utils.ocm.base import (
    OCMAWSSTS,
    OCMClusterAWSSettings,
    build_label_container,
)
from reconcile.utils.ocm.clusters import OCMCluster
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.secret_reader import SecretReaderBase


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
def now(mocker: MockerFixture) -> datetime:
    d = datetime(2021, 8, 30, 18, 0, 0, 0, tzinfo=UTC)
    mocker.patch.object(base, "utc_now", return_value=d)
    return d


#
# upgrade lock tests
#


@pytest.fixture
def version_gates() -> list[dict[str, Any]]:
    return [
        {
            "kind": "VersionGate",
            "id": "gate_id",
            "version_raw_id_prefix": "4.12",
            "label": "api.openshift.com/some-gate",
            "value": "4.12",
            "sts_only": False,
        }
    ]


def test_calculate_diff_no_lock(
    ocm_api: OCMBaseClient,
    cluster_1: OCMCluster,
    now: datetime,
    mocker: MockerFixture,
) -> None:
    """
    Test case: there is no other upgrade lock, so the cluster upgrade can be scheduled
    """
    get_version_agreement_mock = mocker.patch(
        "reconcile.aus.base.get_version_agreement"
    )
    get_version_agreement_mock.return_value = []

    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (
                cluster_1,
                build_upgrade_policy(
                    workloads=["workload1"], soak_days=0, mutexes=["mutex1"]
                ),
                build_cluster_health(),
                [],
            ),
        ],
    )
    diffs = base.calculate_diff([], org_upgrade_spec, ocm_api, VersionData())
    assert diffs == [
        UpgradePolicyHandler(
            action="create",
            policy=ClusterUpgradePolicy(
                organization_id="org-1-id",
                cluster=cluster_1,
                cluster_labels=build_cluster_labels(),
                version="4.12.19",
                schedule_type="manual",
                next_run="2021-08-30T18:07:00Z",
            ),
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
            organization_id="1",
            cluster=cluster_2,
            cluster_labels=build_label_container([
                build_label(
                    key="sre-capabilities.aus.version-gate-approvals",
                    value="api.openshift.com/gate-ocp,api.openshift.com/gate-sts",
                )
            ]),
            version="4.12.19",
            schedule_type="manual",
        )
    ]

    upgrade_policy_spec = build_upgrade_policy(
        workloads=["workload1"], soak_days=0, mutexes=["mutex1"]
    )
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (cluster_1, upgrade_policy_spec, build_cluster_health(), []),
            (cluster_2, upgrade_policy_spec, build_cluster_health(), []),
        ],
    )
    diffs = base.calculate_diff(current_state, org_upgrade_spec, ocm_api, VersionData())

    assert not diffs


def test_calculate_diff_inter_lock(
    ocm_api: OCMBaseClient,
    cluster_1: OCMCluster,
    cluster_2: OCMCluster,
    now: datetime,
    mocker: MockerFixture,
) -> None:
    """
    Test case: two clusters need an upgrade, but define the same mutex.
    only the first one will be upgraded
    """
    get_version_agreement_mock = mocker.patch(
        "reconcile.aus.base.get_version_agreement"
    )
    get_version_agreement_mock.return_value = []

    upgrade_policy_spec = build_upgrade_policy(
        workloads=["workload1"], soak_days=0, mutexes=["mutex1"]
    )
    org_upgrade_spec = build_organization_upgrade_spec(
        specs=[
            (cluster_1, upgrade_policy_spec, build_cluster_health(), []),
            (cluster_2, upgrade_policy_spec, build_cluster_health(), []),
        ],
    )
    diffs = base.calculate_diff([], org_upgrade_spec, ocm_api, VersionData())

    assert diffs == [
        UpgradePolicyHandler(
            action="create",
            policy=ClusterUpgradePolicy(
                organization_id="org-1-id",
                cluster=cluster_1,
                cluster_labels=build_cluster_labels(),
                version="4.12.19",
                schedule_type="manual",
                next_run="2021-08-30T18:07:00Z",
            ),
        )
    ]


#
# test upgradable versions
#


def test_upgradeable_org_version_blocked(cluster_1: OCMCluster) -> None:
    upgrade_spec = ClusterUpgradeSpec(
        org=build_organization(blocked_versions=[".*"]),
        cluster=cluster_1,
        upgradePolicy=build_upgrade_policy(workloads=["workload1"], soak_days=0),
        health=build_healthy_cluster_health(),
    )
    x = base.upgradeable_version(upgrade_spec, VersionData(), None)
    assert x is None


def test_upgradeable_cluster_version_blocked(cluster_1: OCMCluster) -> None:
    upgrade_spec = ClusterUpgradeSpec(
        org=build_organization(),
        cluster=cluster_1,
        upgradePolicy=build_upgrade_policy(
            workloads=["workload1"], soak_days=0, blocked_versions=[".*"]
        ),
        health=build_healthy_cluster_health(),
    )
    x = base.upgradeable_version(upgrade_spec, VersionData(), None)
    assert x is None


def test_upgradeable_cluster_and_org_version_blocked(cluster_1: OCMCluster) -> None:
    upgrade_spec = ClusterUpgradeSpec(
        org=build_organization(blocked_versions=["4.12.*"]),
        cluster=cluster_1,
        upgradePolicy=build_upgrade_policy(
            workloads=["workload1"], soak_days=0, blocked_versions=["4.13.0"]
        ),
        health=build_healthy_cluster_health(),
    )
    upgrade_spec.cluster.version.available_upgrades = ["4.12.5"]
    assert base.upgradeable_version(upgrade_spec, VersionData(), None) is None

    upgrade_spec.cluster.version.available_upgrades = ["4.13.0"]
    assert base.upgradeable_version(upgrade_spec, VersionData(), None) is None

    upgrade_spec.cluster.version.available_upgrades = ["4.13.1"]
    assert base.upgradeable_version(upgrade_spec, VersionData(), None) == "4.13.1"


def test_upgradeable_version_no_block(cluster_1: OCMCluster) -> None:
    upgrade_spec = ClusterUpgradeSpec(
        org=build_organization(),
        cluster=cluster_1,
        upgradePolicy=build_upgrade_policy(workloads=["workload1"], soak_days=0),
        health=build_healthy_cluster_health(),
    )
    assert base.upgradeable_version(upgrade_spec, VersionData(), None) == "4.12.19"


def test_addon_upgradable_version_cluster_level_blocked() -> None:
    upgrade_spec = build_addon_upgrade_spec(
        cluster_name="cluster-1",
        current_addon_version="1.2.3",
        addon_id="addon-1",
        available_addon_upgrades=["1.2.4", "1.2.5"],
        blocked_versions=["addon-1/1.2.5"],
    )

    assert base.upgradeable_version(upgrade_spec, VersionData(), None) == "1.2.4"


def test_addon_upgradable_version_org_level_blocked() -> None:
    upgrade_spec = build_addon_upgrade_spec(
        org=build_organization(blocked_versions=["addon-1/1.2.5"]),
        cluster_name="cluster-1",
        current_addon_version="1.2.3",
        addon_id="addon-1",
        available_addon_upgrades=["1.2.4", "1.2.5"],
    )

    assert base.upgradeable_version(upgrade_spec, VersionData(), None) == "1.2.4"


def test_addon_upgradable_version_cluster_and_org_level_blocked() -> None:
    upgrade_spec = build_addon_upgrade_spec(
        org=build_organization(blocked_versions=["addon-1/1.2.5"]),
        cluster_name="cluster-1",
        current_addon_version="1.2.3",
        addon_id="addon-1",
        available_addon_upgrades=["1.2.4", "1.2.5"],
        blocked_versions=["addon-1/1.2.4"],
    )

    assert base.upgradeable_version(upgrade_spec, VersionData(), None) is None


def test_addon_upgradable_version_no_block() -> None:
    upgrade_spec = build_addon_upgrade_spec(
        cluster_name="cluster-1",
        current_addon_version="1.2.3",
        addon_id="addon-1",
        available_addon_upgrades=["1.2.4", "1.2.5"],
    )

    assert base.upgradeable_version(upgrade_spec, VersionData(), None) == "1.2.5"


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
    assert [s.cluster.name for s in org.specs] == ["cluster1", "cluster2", "cluster3"]


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
    assert [s.cluster.name for s in org.specs] == ["cluster1", "cluster2", "cluster3"]


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
    assert [s.cluster.name for s in org.specs] == [
        "cluster11",
        "cluster12",
        "cluster21",
        "cluster22",
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
    sector_1.set_specs([
        build_cluster_upgrade_spec(
            name="high-version-cluster",
            current_version="2.0.0",
            workloads=[workload],
        )
    ])
    assert base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_3
    )

    # no cluster with higher version in deps: upgrade not ok
    sector_1.set_specs([
        build_cluster_upgrade_spec(
            name="low-version-cluster",
            current_version="1.0.0",
            workloads=[workload],
        )
    ])
    assert not base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_3
    )

    # not all clusters with higher version in deps: upgrade not ok
    sector_1.set_specs([
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
    ])
    assert not base.version_conditions_met(
        "1.2.3", empty_version_data, upgrade_policy, sector=sector_3
    )


#
# policy handler
#


class StubPolicy(base.AbstractUpgradePolicy):
    created: bool = False
    deleted: bool = False

    def create(
        self,
        ocm_api: OCMBaseClient,
        rosa_role_upgrade_handler_params: RosaRoleUpgradeHandlerParams | None = None,
        secret_reader: SecretReaderBase | None = None,
    ) -> None:
        self.created = True

    def delete(self, ocm_api: OCMBaseClient) -> None:
        self.deleted = True

    def summarize(self) -> str:
        return "do-something"


@pytest.fixture
def stub_policy(cluster_1: OCMCluster) -> StubPolicy:
    return StubPolicy(
        cluster=cluster_1,
        schedule_type="manual",
        version="4.1.2",
    )


@pytest.fixture
def cluster_upgrade_policy(cluster_1: OCMCluster) -> ClusterUpgradePolicy:
    return ClusterUpgradePolicy(
        organization_id="org-1-id",
        cluster_labels=build_label_container([
            build_label(
                key="sre-capabilities.aus.version-gate-approvals",
                value="api.openshift.com/gate-ocp,api.openshift.com/gate-sts",
            )
        ]),
        id="test-policy-id",
        cluster=cluster_1,
        schedule_type="manual",
        version="4.1.2",
        next_run="soon",
    )


@pytest.fixture
def control_plane_upgrade_policy(cluster_2: OCMCluster) -> ControlPlaneUpgradePolicy:
    return ControlPlaneUpgradePolicy(
        id="test-policy-id",
        cluster=cluster_2,
        schedule_type="manual",
        version="4.1.2",
        next_run="soon",
    )


@pytest.fixture
def addon_service(mocker: MockerFixture) -> AddonService:
    return mocker.MagicMock(spec=AddonService, autospec=True)


@pytest.fixture
def addon_upgrade_policy(
    cluster_1: OCMCluster, addon_service: AddonService
) -> AddonUpgradePolicy:
    return AddonUpgradePolicy(
        id="test-policy-id",
        cluster=cluster_1,
        schedule_type="manual",
        version="1.2.3",
        next_run="soon",
        addon_id="test-addon",
        addon_service=addon_service,
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
        cluster_upgrade_policy.cluster.id,
        {
            "version": cluster_upgrade_policy.version,
            "schedule_type": cluster_upgrade_policy.schedule_type,
            "next_run": cluster_upgrade_policy.next_run,
        },
    )


def test_policy_handler_create_cluster_upgrade_with_sts_enabled(
    cluster_upgrade_policy: ClusterUpgradePolicy,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    secret_reader: SecretReaderBase,
) -> None:
    create_upgrade_policy_mock = mocker.patch.object(
        base, "create_upgrade_policy", autospec=True
    )

    mock_job_controller = create_autospec(K8sJobController)
    mocker.patch(
        "reconcile.aus.base.build_job_controller", return_value=mock_job_controller
    )

    aus_sts_gate_handler_mock = mocker.patch(
        "reconcile.aus.base.AUSSTSGateHandler",
        autospec=True,
    )
    aus_sts_handler_instance = aus_sts_gate_handler_mock.return_value
    aus_sts_handler_instance.upgrade_rosa_roles.return_value = True

    mock_sts = OCMAWSSTS(
        enabled=True,
        role_arn="arn:aws:iam::123456789012:role/test-installer-role",
        support_role_arn="arn:aws:iam::123456789012:role/test-support-role",
        oidc_endpoint_url=None,
        operator_iam_roles=None,
        instance_iam_roles=None,
        operator_role_prefix=None,
    )
    mock_aws = OCMClusterAWSSettings(
        sts=mock_sts,
    )
    cluster_upgrade_policy.cluster.aws = mock_aws
    handler = base.UpgradePolicyHandler(
        policy=cluster_upgrade_policy,
        action="create",
    )
    rosa_role_upgrade_handler_params = RosaRoleUpgradeHandlerParams(
        integration_name="integration-name",
        integration_version="integration-version",
        job_controller_cluster="job-controller-cluster",
        job_controller_namespace="job-controller-namespace",
        rosa_role="rosa-role",
        rosa_job_service_account="rosa-job-service-account",
    )
    base.act(
        dry_run=False,
        diffs=[handler],
        ocm_api=ocm_api,
        rosa_role_upgrade_handler_params=rosa_role_upgrade_handler_params,
        secret_reader=secret_reader,
    )
    create_upgrade_policy_mock.assert_called_once_with(
        ocm_api,
        cluster_upgrade_policy.cluster.id,
        {
            "version": cluster_upgrade_policy.version,
            "schedule_type": cluster_upgrade_policy.schedule_type,
            "next_run": cluster_upgrade_policy.next_run,
        },
    )

    aus_sts_gate_handler_mock.assert_called_once_with(
        job_controller=mock_job_controller,
        aws_iam_role=rosa_role_upgrade_handler_params.rosa_role,
        rosa_job_service_account=rosa_role_upgrade_handler_params.rosa_job_service_account,
        rosa_job_image=mocker.ANY,
    )


def test_policy_handler_create_cluster_upgrade_without_sts_enabled(
    cluster_upgrade_policy: ClusterUpgradePolicy,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    secret_reader: SecretReaderBase,
) -> None:
    create_upgrade_policy_mock = mocker.patch.object(
        base, "create_upgrade_policy", autospec=True
    )

    mock_job_controller = create_autospec(K8sJobController)
    mocker.patch(
        "reconcile.aus.base.build_job_controller", return_value=mock_job_controller
    )

    aus_sts_gate_handler_mock = mocker.patch(
        "reconcile.aus.base.AUSSTSGateHandler",
        autospec=True,
    )
    aus_sts_handler_instance = aus_sts_gate_handler_mock.return_value
    aus_sts_handler_instance.upgrade_rosa_roles.return_value = True
    handler = base.UpgradePolicyHandler(
        policy=cluster_upgrade_policy,
        action="create",
    )
    rosa_role_upgrade_handler_params = RosaRoleUpgradeHandlerParams(
        integration_name="integration-name",
        integration_version="integration-version",
        job_controller_cluster="job-controller-cluster",
        job_controller_namespace="job-controller-namespace",
        rosa_role="rosa-role",
        rosa_job_service_account="rosa-job-service-account",
    )
    base.act(
        dry_run=False,
        diffs=[handler],
        ocm_api=ocm_api,
        rosa_role_upgrade_handler_params=rosa_role_upgrade_handler_params,
        secret_reader=secret_reader,
    )
    create_upgrade_policy_mock.assert_called_once_with(
        ocm_api,
        cluster_upgrade_policy.cluster.id,
        {
            "version": cluster_upgrade_policy.version,
            "schedule_type": cluster_upgrade_policy.schedule_type,
            "next_run": cluster_upgrade_policy.next_run,
        },
    )

    aus_sts_gate_handler_mock.assert_not_called()


def test_policy_handler_create_cluster_upgrade_without_sts_enabled_and_rosa_classic(
    cluster_upgrade_policy: ClusterUpgradePolicy,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    secret_reader: SecretReaderBase,
) -> None:
    create_upgrade_policy_mock = mocker.patch.object(
        base, "create_upgrade_policy", autospec=True
    )

    mock_job_controller = create_autospec(K8sJobController)
    mocker.patch(
        "reconcile.aus.base.build_job_controller", return_value=mock_job_controller
    )

    aus_sts_gate_handler_mock = mocker.patch(
        "reconcile.aus.base.AUSSTSGateHandler",
        autospec=True,
    )
    aus_sts_handler_instance = aus_sts_gate_handler_mock.return_value
    aus_sts_handler_instance.upgrade_rosa_roles.return_value = True
    cluster_upgrade_policy.cluster.hypershift.enabled = False
    handler = base.UpgradePolicyHandler(
        policy=cluster_upgrade_policy,
        action="create",
    )

    rosa_role_upgrade_handler_params = RosaRoleUpgradeHandlerParams(
        integration_name="integration-name",
        integration_version="integration-version",
        job_controller_cluster="job-controller-cluster",
        job_controller_namespace="job-controller-namespace",
        rosa_role="rosa-role",
        rosa_job_service_account="rosa-job-service-account",
    )
    base.act(
        dry_run=False,
        diffs=[handler],
        ocm_api=ocm_api,
        rosa_role_upgrade_handler_params=rosa_role_upgrade_handler_params,
        secret_reader=secret_reader,
    )
    create_upgrade_policy_mock.assert_called_once_with(
        ocm_api,
        cluster_upgrade_policy.cluster.id,
        {
            "version": cluster_upgrade_policy.version,
            "schedule_type": cluster_upgrade_policy.schedule_type,
            "next_run": cluster_upgrade_policy.next_run,
        },
    )

    aus_sts_gate_handler_mock.assert_not_called()


def test_policy_handler_create_cluster_upgrade_without_gate_labels(
    cluster_upgrade_policy: ClusterUpgradePolicy,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    secret_reader: SecretReaderBase,
) -> None:
    create_upgrade_policy_mock = mocker.patch.object(
        base, "create_upgrade_policy", autospec=True
    )

    mock_job_controller = create_autospec(K8sJobController)
    mocker.patch(
        "reconcile.aus.base.build_job_controller", return_value=mock_job_controller
    )

    aus_sts_gate_handler_mock = mocker.patch(
        "reconcile.aus.base.AUSSTSGateHandler",
        autospec=True,
    )
    aus_sts_handler_instance = aus_sts_gate_handler_mock.return_value
    aus_sts_handler_instance.upgrade_rosa_roles.return_value = True
    cluster_upgrade_policy.cluster_labels = build_label_container([])
    mock_sts = OCMAWSSTS(
        enabled=True,
        role_arn="arn:aws:iam::123456789012:role/test-installer-role",
        support_role_arn="arn:aws:iam::123456789012:role/test-support-role",
        oidc_endpoint_url=None,
        operator_iam_roles=None,
        instance_iam_roles=None,
        operator_role_prefix=None,
    )
    mock_aws = OCMClusterAWSSettings(
        sts=mock_sts,
    )
    cluster_upgrade_policy.cluster.aws = mock_aws
    handler = base.UpgradePolicyHandler(
        policy=cluster_upgrade_policy,
        action="create",
    )
    rosa_role_upgrade_handler_params = RosaRoleUpgradeHandlerParams(
        integration_name="integration-name",
        integration_version="integration-version",
        job_controller_cluster="job-controller-cluster",
        job_controller_namespace="job-controller-namespace",
        rosa_role="rosa-role",
        rosa_job_service_account="rosa-job-service-account",
    )
    base.act(
        dry_run=False,
        diffs=[handler],
        ocm_api=ocm_api,
        rosa_role_upgrade_handler_params=rosa_role_upgrade_handler_params,
        secret_reader=secret_reader,
    )
    create_upgrade_policy_mock.assert_called_once_with(
        ocm_api,
        cluster_upgrade_policy.cluster.id,
        {
            "version": cluster_upgrade_policy.version,
            "schedule_type": cluster_upgrade_policy.schedule_type,
            "next_run": cluster_upgrade_policy.next_run,
        },
    )

    aus_sts_gate_handler_mock.assert_not_called()


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
        control_plane_upgrade_policy.cluster.id,
        {
            "version": control_plane_upgrade_policy.version,
            "schedule_type": control_plane_upgrade_policy.schedule_type,
            "next_run": control_plane_upgrade_policy.next_run,
            "cluster_id": control_plane_upgrade_policy.cluster.id,
            "upgrade_type": "ControlPlane",
        },
    )


def test_policy_handler_create_addon_upgrade(
    addon_upgrade_policy: AddonUpgradePolicy,
    ocm_api: OCMBaseClient,
    addon_service: AddonService,
) -> None:
    handler = base.UpgradePolicyHandler(
        policy=addon_upgrade_policy,
        action="create",
    )
    base.act(dry_run=False, diffs=[handler], ocm_api=ocm_api)
    addon_service.create_addon_upgrade_policy.assert_called_once_with(  # type: ignore
        ocm_api=ocm_api,
        addon_id=addon_upgrade_policy.addon_id,
        cluster_id=addon_upgrade_policy.cluster.id,
        schedule_type="manual",
        version=addon_upgrade_policy.version,
        next_run=ANY,
    )
    addon_service.delete_addon_upgrade_policy.assert_not_called()  # type: ignore


def test_policy_handler_delete_addon_upgrade(
    addon_upgrade_policy: AddonUpgradePolicy,
    ocm_api: OCMBaseClient,
    addon_service: AddonService,
) -> None:
    handler = base.UpgradePolicyHandler(
        policy=addon_upgrade_policy,
        action="delete",
    )
    base.act(dry_run=False, diffs=[handler], ocm_api=ocm_api)
    addon_service.delete_addon_upgrade_policy.assert_called_once_with(  # type: ignore
        ocm_api=ocm_api,
        cluster_id=addon_upgrade_policy.cluster.id,
        policy_id=addon_upgrade_policy.id,
    )
    addon_service.create_addon_upgrade_policy.assert_not_called()  # type: ignore


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
    skip = base.verify_max_upgrades_should_skip(
        desired=cluster_upgrade_spec,
        locked={},
        sector_mutex_upgrades={},
        sector=None,
    )
    assert not skip


def test_verify_lock_should_skip_locked_by_self() -> None:
    cluster_upgrade_spec = build_cluster_upgrade_spec(
        name="cluster",
        available_upgrades=["1", "2", "3"],
        mutexes=["mutex-1"],
    )
    skip = base.verify_max_upgrades_should_skip(
        desired=cluster_upgrade_spec,
        locked={"mutex-1": cluster_upgrade_spec.cluster.id},
        sector_mutex_upgrades={},
        sector=None,
    )
    assert skip


def test_verify_lock_should_skip_locked_by_another_cluster() -> None:
    cluster_upgrade_spec = build_cluster_upgrade_spec(
        name="cluster",
        available_upgrades=["1", "2", "3"],
        mutexes=["mutex-1"],
    )
    skip = base.verify_max_upgrades_should_skip(
        desired=cluster_upgrade_spec,
        locked={"mutex-1": "some-other-cluster-id"},
        sector_mutex_upgrades={},
        sector=None,
    )
    assert skip


#
# test verify schedule should skip
#


def test_verify_schedule_should_skip_cluster_now() -> None:
    cluster_upgrade_spec = build_cluster_upgrade_spec(name="cluster")
    now = datetime.now(tz=UTC)
    expected = now + timedelta(minutes=7)
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
    now = datetime.now(tz=UTC)
    expected = now + timedelta(minutes=2)
    s = base.verify_schedule_should_skip(
        addon_upgrade_spec, now, addon_upgrade_spec.addon.id
    )
    assert s == expected.strftime("%Y-%m-%dT%H:%M:00Z")


def test_verify_schedule_should_skip_cluster_future() -> None:
    cluster_upgrade_spec = build_cluster_upgrade_spec(name="cluster")
    now = datetime.now(tz=UTC)
    next_day = now + timedelta(hours=3)
    cluster_upgrade_spec.upgrade_policy.schedule = f"* {next_day.hour} * * *"
    s = base.verify_schedule_should_skip(
        cluster_upgrade_spec,
        now,
    )
    assert s is None


#
# test organization filtering
#


@pytest.fixture
def orgs_query_func() -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return {
            "organizations": [
                build_organization(
                    org_id="org1", env_name="env1", addon_managed_upgrades=False
                ).model_dump(by_alias=True),
                build_organization(
                    org_id="org2", env_name="env1", addon_managed_upgrades=True
                ).model_dump(by_alias=True),
                build_organization(
                    org_id="org3", env_name="env2", addon_managed_upgrades=False
                ).model_dump(by_alias=True),
                build_organization(
                    org_id="org4",
                    env_name="env2",
                    addon_managed_upgrades=False,
                    disabled_integrations=["integration"],
                ).model_dump(by_alias=True),
            ]
        }

    return q


@pytest.mark.parametrize(
    "ocm_env_name,only_addon_managed_upgrades,ocm_organization_ids,excluded_ocm_organization_ids,expected_org_ids",
    [
        ("env1", False, set(), set(), {"org1", "org2"}),
        ("env1", False, None, None, {"org1", "org2"}),
        ("env2", False, set(), set(), {"org3"}),
        ("env1", True, set(), set(), {"org2"}),
        ("env1", False, {"org1"}, set(), {"org1"}),
        ("env1", False, set(), {"org1"}, {"org2"}),
        ("env1", False, {"org1"}, {"org1"}, set()),
        ("env2", True, set(), set(), set()),
    ],
    ids=[
        "get all orgs from env1",
        "get all orgs from env1 (None filters)",
        "get all orgs from env2",
        "get only the orgs with addon mgmt enabled from env1",
        "get only org1 from env1",
        "exclude org1 from env1",
        "include and exclude an org should exclude it",
        "nothing matches in an env",
    ],
)
def test_aus_get_orgs_for_environment(
    orgs_query_func: Callable,
    ocm_env_name: str,
    only_addon_managed_upgrades: bool,
    ocm_organization_ids: set[str],
    excluded_ocm_organization_ids: set[str],
    expected_org_ids: set[str],
) -> None:
    orgs = get_orgs_for_environment(
        "integration",
        ocm_env_name=ocm_env_name,
        query_func=orgs_query_func,
        only_addon_managed_upgrades=only_addon_managed_upgrades,
        ocm_organization_ids=ocm_organization_ids,
        excluded_ocm_organization_ids=excluded_ocm_organization_ids,
    )

    assert {o.org_id for o in orgs} == expected_org_ids
