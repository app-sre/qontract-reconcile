from unittest.mock import (
    Mock,
    patch,
)

import pytest
from dateutil import parser

import reconcile.aus.base as aus
import reconcile.aus.ocm_addons_upgrade_scheduler_org as oauso


@pytest.fixture
def cluster() -> str:
    return "cluster1"


@pytest.fixture
def addon_id() -> str:
    return "myaddon"


@pytest.fixture
def ocm_addon_version():
    return "3.0.0"


@pytest.fixture
def automatic_upgrade_policy(addon_id, cluster):
    return aus.AddonUpgradePolicy(
        **{
            "id": "automatic-policy-id",
            "schedule": "0,15,30,45 * * * *",
            "schedule_type": "automatic",
            "version": "",
            "next_run": "2023-01-13T09:45:00Z",
            "addon_id": addon_id,
            "cluster": cluster,
        }
    )


@pytest.fixture
def desired_state(addon_id, cluster):
    return aus.ConfiguredAddonUpgradePolicy(
        **{
            "workloads": ["workload"],
            "schedule": "0 * * * 1-5",
            "conditions": {"soakDays": 0},
            "addon_id": addon_id,
            "cluster": cluster,
            "cluster_uuid": f"{cluster}-uuid",
            "current_version": "2.0.0",
        }
    )


@pytest.fixture
@patch("reconcile.aus.ocm_upgrade_scheduler.OCMMap", autospec=True)
def ocm_map(mock_ocm_map, addon_id, cluster, ocm_addon_version):
    map = mock_ocm_map.return_value
    ocm = map.get.return_value
    ocm.addons = [{"id": addon_id, "version": {"id": ocm_addon_version}}]
    ocm.version_blocked.return_value = False
    ocm.addon_version_blocked.return_value = False
    ocm.cluster_ids = {cluster: "clusterid"}
    return map


def test_delete_automatic_upgrade_policy(
    automatic_upgrade_policy, desired_state, ocm_map, addon_id, cluster
):
    ocm = ocm_map.get(cluster)

    diffs = oauso.calculate_diff(
        [automatic_upgrade_policy],
        [desired_state],
        ocm_map,
        {},
        addon_id,
    )
    diffs[0].act(dry_run=False, ocm=ocm)

    assert diffs == [
        aus.UpgradePolicyHandler(
            action="delete",
            policy=aus.AddonUpgradePolicy(
                **{
                    "action": "delete",
                    "cluster": cluster,
                    "version": "automatic",
                    "id": automatic_upgrade_policy.id,
                    "schedule_type": automatic_upgrade_policy.schedule_type,
                    "addon_id": addon_id,
                }
            ),
        )
    ]
    ocm.delete_addon_upgrade_policy.assert_called_once_with(
        cluster,
        {
            "id": automatic_upgrade_policy.id,
        },
    )


@pytest.fixture
def set_upgradeable(monkeypatch):
    datetime_mock = Mock(wraps=aus.datetime)
    datetime_mock.utcnow.return_value = parser.parse("2021-08-30T18:55:00.00000")
    monkeypatch.setattr(aus, "datetime", datetime_mock)

    croniter_mock = Mock(wraps=aus.croniter)
    croniter_mock.return_value.get_next.return_value = parser.parse(
        "2021-08-30T19:00:00.00000"
    )
    monkeypatch.setattr(aus, "croniter", croniter_mock)

    version_conditions_met = Mock(wraps=aus.version_conditions_met)
    version_conditions_met.return_value = True
    monkeypatch.setattr(aus, "version_conditions_met", version_conditions_met)
    return True


def test_noop(desired_state, ocm_map, addon_id, ocm_addon_version, set_upgradeable):
    desired_state.current_version = ocm_addon_version
    diffs = oauso.calculate_diff(
        [],
        [desired_state],
        ocm_map,
        {},
        addon_id,
    )
    assert not diffs


def test_upgrade_needed(
    desired_state, ocm_map, addon_id, cluster, ocm_addon_version, set_upgradeable
):
    diffs = oauso.calculate_diff(
        [],
        [desired_state],
        ocm_map,
        {},
        addon_id,
    )
    assert diffs == [
        aus.UpgradePolicyHandler(
            action="create",
            policy=aus.AddonUpgradePolicy(
                **{
                    "cluster": cluster,
                    "version": ocm_addon_version,
                    "schedule_type": "manual",
                    "addon_id": addon_id,
                    "cluster_id": "clusterid",
                    "upgrade_type": "ADDON",
                }
            ),
        )
    ]


def test_blocked_upgrade(
    desired_state, ocm_map, addon_id, cluster, ocm_addon_version, set_upgradeable
):
    ocm_map.get("ocm").addon_version_blocked.return_value = True
    diffs = oauso.calculate_diff(
        [],
        [desired_state],
        ocm_map,
        {},
        addon_id,
    )
    assert not diffs
