from datetime import datetime
from typing import Optional

import pytest
from dateutil import parser
from pytest_mock import MockerFixture

from reconcile.aus import base
from reconcile.aus.base import (
    ClusterUpgradePolicy,
    ControlPlaneUpgradePolicy,
    UpgradePolicyHandler,
)
from reconcile.aus.cluster_version_data import (
    VersionData,
    VersionHistory,
    WorkloadHistory,
)
from reconcile.test.ocm.aus.fixtures import (
    build_organization_upgrade_spec,
    build_upgrade_policy,
)
from reconcile.test.ocm.fixtures import build_ocm_cluster
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


def test_calculate_diff_create_cluster_upgrade_no_gate(
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
    assert diffs == [
        UpgradePolicyHandler(
            action="create",
            policy=ClusterUpgradePolicy(
                cluster=cluster,
                version="4.12.19",
                schedule_type="manual",
                next_run="2021-08-30T18:06:00Z",
            ),
            gates_to_agree=[],
        )
    ]


def test_calculate_diff_create_control_plane_upgrade_no_gate(
    ocm_api: OCMBaseClient,
    cluster: OCMCluster,
    now: datetime,
) -> None:
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
                next_run="2021-08-30T18:06:00Z",
            ),
            gates_to_agree=[],
        )
    ]


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
