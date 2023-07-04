from unittest.mock import Mock

from dateutil import parser
from pytest_mock import MockerFixture

from reconcile.aus import base
from reconcile.aus.base import get_version_data_map
from reconcile.aus.cluster_version_data import VersionData
from reconcile.test.ocm.aus.fixtures import (
    build_organization,
    build_organization_upgrade_spec,
    build_upgrade_policy,
)
from reconcile.test.ocm.fixtures import build_ocm_cluster

#
# tests for reading version data and inheriting from other orgs
#


def test_get_version_data_map(
    mocker: MockerFixture,
    state: Mock,
) -> None:
    mocker.patch("reconcile.utils.ocm.ocm.SecretReader")
    mocker.patch.object(
        base,
        "init_state",
        autospec=True,
    ).return_value = state
    ocm_env = "prod"
    org_id = "org-1"
    version_data = get_version_data_map(
        dry_run=True,
        org_upgrade_spec=build_organization_upgrade_spec(
            org=build_organization(
                env_name=ocm_env,
                org_id=org_id,
            ),
            specs=[
                (
                    build_ocm_cluster(
                        name="cluster-1",
                        version="4.12.0",
                        available_upgrades=["4.13.2"],
                    ),
                    build_upgrade_policy(
                        workloads=["workload-1"],
                        soak_days=1,
                    ),
                )
            ],
        ),
        integration="test",
    )

    org_data = version_data.get(ocm_env, org_id)
    assert org_data
    assert org_data.stats and org_data.stats.inherited is None


def test_get_version_data_map_with_inheritance(
    mocker: MockerFixture,
    state: Mock,
) -> None:
    mocker.patch("reconcile.utils.ocm.ocm.SecretReader")
    mocker.patch.object(
        base,
        "init_state",
        autospec=True,
    ).return_value = state

    ocm_env = "prod"
    org_id = "org-1-id"
    version_data = get_version_data_map(
        dry_run=True,
        org_upgrade_spec=build_organization_upgrade_spec(
            org=build_organization(
                env_name=ocm_env,
                org_id=org_id,
                inherit_version_data_from_org_ids=[(ocm_env, "org-2-id", True)],
            ),
            specs=[
                (
                    build_ocm_cluster(
                        name="cluster-1",
                        version="4.13.0",
                        available_upgrades=["4.13.2"],
                    ),
                    build_upgrade_policy(
                        workloads=["workload-1"],
                        soak_days=1,
                    ),
                )
            ],
        ),
        integration="test",
    )

    assert version_data.get("prod", org_id).stats.inherited


#
# tests for history update
#


def test_update_history(ocm1_version_data: VersionData, mocker: MockerFixture) -> None:
    """
    Test scenario: test that the two clusters with workload 1 increase the soakdays after one day by 2
    and that the cluster with workload 2 increases the soakdays after one day by 1
    """
    datetime_mock = mocker.patch.object(base, "datetime", autospec=True)
    datetime_mock.utcnow.return_value = parser.parse("2021-08-30T18:00:00.00000")
    ocm_env = "prod"
    org_id = "org-id"
    org_upgrade_spec = build_organization_upgrade_spec(
        org=build_organization(
            env_name=ocm_env,
            org_id=org_id,
            inherit_version_data_from_org_ids=[(ocm_env, "org-2-id", True)],
        ),
        specs=[
            (
                build_ocm_cluster(
                    name="cluster1",
                    version="4.12.1",
                    available_upgrades=["4.13.2"],
                ),
                build_upgrade_policy(workloads=["workload1"], soak_days=0),
            ),
            (
                build_ocm_cluster(
                    name="cluster2",
                    version="4.12.1",
                    available_upgrades=["4.13.2"],
                ),
                build_upgrade_policy(workloads=["workload1"], soak_days=0),
            ),
            (
                build_ocm_cluster(
                    name="cluster3",
                    version="4.12.1",
                    available_upgrades=["4.13.2"],
                ),
                build_upgrade_policy(workloads=["workload2"], soak_days=0),
            ),
        ],
    )
    base.update_history(ocm1_version_data, org_upgrade_spec)

    expected = {
        "check_in": "2021-08-30T18:00:00",
        "versions": {
            "4.12.1": {
                "workloads": {
                    "workload1": {
                        "soak_days": 23.0,
                        "reporting": ["cluster1", "cluster2"],
                    },
                    "workload2": {"soak_days": 7.0, "reporting": ["cluster3"]},
                }
            }
        },
        "stats": {
            "min_version": "4.12.1",
            "min_version_per_workload": {
                "workload1": "4.12.1",
                "workload2": "4.12.1",
            },
        },
    }
    assert expected == ocm1_version_data.jsondict()


#
# test version conditions soak days
#


def test_version_conditions_met_larger(ocm1_version_data: VersionData) -> None:
    """
    Testcase: the versiondata contains 21 soakdays for workload 1, so a policy
    requiring 1 soak day should meet the requirement
    """
    assert base.version_conditions_met(
        "4.12.1",
        ocm1_version_data,
        upgrade_policy=build_upgrade_policy(
            workloads=["workload1"],
            soak_days=1,
        ),
        sector=None,
    )


def test_version_conditions_met_equal(ocm1_version_data: VersionData) -> None:
    """
    Testcase: the versiondata contains 21 soakdays for workload 1, so a policy
    requiring 21 soak day should meet the requirement
    """
    assert base.version_conditions_met(
        "4.12.1",
        ocm1_version_data,
        upgrade_policy=build_upgrade_policy(
            workloads=["workload1"],
            soak_days=21,
        ),
        sector=None,
    )


def test_version_conditions_not_met(ocm1_version_data: VersionData) -> None:
    """
    Testcase: the versiondata contains 21 soakdays for workload 1, so a policy
    requiring 32 soak day is not enough
    """
    assert not base.version_conditions_met(
        "4.12.1",
        ocm1_version_data,
        upgrade_policy=build_upgrade_policy(
            workloads=["workload1"],
            soak_days=42,
        ),
        sector=None,
    )


def test_version_conditions_new_version_zero_soak_days(
    ocm1_version_data: VersionData,
) -> None:
    """
    Testcase: the versiondata does not contain any data for a version,
    but soak days are 0 so the version condition is met
    """
    assert base.version_conditions_met(
        "4.13.0",
        ocm1_version_data,
        upgrade_policy=build_upgrade_policy(
            workloads=["workload1"],
            soak_days=0,
        ),
        sector=None,
    )


def test_version_conditions_new_version_higher_soakdays(
    ocm1_version_data: VersionData,
) -> None:
    """
    Testcase: the versiondata does not contain any data for a version,
    and since soak days are > 0 the version condition is not met
    """
    assert not base.version_conditions_met(
        "4.13.0",
        ocm1_version_data,
        upgrade_policy=build_upgrade_policy(
            workloads=["workload1"],
            soak_days=1,
        ),
        sector=None,
    )
