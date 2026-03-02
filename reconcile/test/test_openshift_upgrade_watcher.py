from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile import openshift_upgrade_watcher as ouw
from reconcile.gql_definitions.common.clusters import ClusterV1
from reconcile.test.fixtures import Fixtures
from reconcile.utils.models import data_default_none

fxt = Fixtures("openshift_upgrade_watcher")


def load_cluster(path: str) -> ClusterV1:
    content = fxt.get_anymarkup(path)
    data = data_default_none(ClusterV1, content)
    assert isinstance(data, dict)
    return ClusterV1(**data)


@pytest.fixture
def state(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("reconcile.utils.state.State", autospec=True).return_value


@pytest.fixture
def slack(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(
        "reconcile.utils.slack_api.SlackApi", autospec=True
    ).return_value


cluster_name = "cluster1"
upgrade_at = datetime(2020, 6, 1, 0, 0, 0, tzinfo=UTC)
old_version = "4.5.1"
upgrade_version = "4.5.2"


@pytest.fixture
def ouw_oc_map(mocker: MockerFixture) -> MagicMock:
    map = mocker.patch("reconcile.utils.oc_map.OCMap", autospec=True).return_value
    map.clusters.return_value = [cluster_name]
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.get.return_value = {"items": []}
    map.get.return_value = oc
    return map


@pytest.fixture
def ouw_ocm_map(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("reconcile.utils.ocm.OCMMap", autospec=True)


@pytest.fixture
def upgrade_config() -> dict[str, Any]:
    return {
        "items": [
            {
                "spec": {
                    "upgradeAt": upgrade_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "desired": {"version": upgrade_version},
                }
            }
        ]
    }


@pytest.fixture
def mock_utc_now(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("reconcile.openshift_upgrade_watcher.utc_now")


def test_new_upgrade_pending(
    mocker: MockerFixture,
    state: MagicMock,
    slack: MagicMock,
    ouw_oc_map: MagicMock,
    ouw_ocm_map: MagicMock,
    upgrade_config: dict[str, Any],
    mock_utc_now: MagicMock,
) -> None:
    """There is an UpgradeConfig on the cluster but its upgradeAt is in the future"""
    mock_utc_now.return_value = upgrade_at - timedelta(hours=1)
    gso = mocker.patch(
        "reconcile.openshift_upgrade_watcher._get_start_osd", autospec=True
    )
    gso.return_value = upgrade_at.strftime("%Y-%m-%dT%H:%M:%SZ"), upgrade_version
    ouw.notify_upgrades_start(
        ocm_map=ouw_ocm_map,
        oc_map=ouw_oc_map,
        clusters=[load_cluster("cluster1.yml")],
        state=state,
        slack=slack,
    )
    assert slack.chat_post_message.call_count == 0
    assert state.add.call_count == 0


def test_new_upgrade_notify(
    mocker: MockerFixture,
    state: MagicMock,
    slack: MagicMock,
    ouw_oc_map: MagicMock,
    ouw_ocm_map: MagicMock,
    upgrade_config: dict[str, Any],
    mock_utc_now: MagicMock,
) -> None:
    """There is an UpgradeConfig on the cluster, its upgradeAt is in the past,
    and we did not already notify"""
    mock_utc_now.return_value = upgrade_at + timedelta(hours=1)
    gso = mocker.patch(
        "reconcile.openshift_upgrade_watcher._get_start_osd", autospec=True
    )
    gso.return_value = upgrade_at.strftime("%Y-%m-%dT%H:%M:%SZ"), upgrade_version
    state.exists.return_value = False
    ouw.notify_upgrades_start(
        ocm_map=ouw_ocm_map,
        oc_map=ouw_oc_map,
        clusters=[load_cluster("cluster1.yml")],
        state=state,
        slack=slack,
    )
    assert slack.chat_post_message.call_count == 1
    assert state.add.call_count == 1


def test_new_upgrade_notify_multiple_channels(
    mocker: MockerFixture,
    state: MagicMock,
    slack: MagicMock,
    ouw_oc_map: MagicMock,
    ouw_ocm_map: MagicMock,
    upgrade_config: dict[str, Any],
    mock_utc_now: MagicMock,
) -> None:
    """There is an UpgradeConfig on the cluster, its upgradeAt is in the past,
    there are multiple channels, and we did not already notify"""
    mock_utc_now.return_value = upgrade_at + timedelta(hours=1)
    gso = mocker.patch(
        "reconcile.openshift_upgrade_watcher._get_start_osd", autospec=True
    )
    gso.return_value = upgrade_at.strftime("%Y-%m-%dT%H:%M:%SZ"), upgrade_version
    state.exists.return_value = False
    cluster = load_cluster("cluster1.yml")

    cluster.labels = {"notifications": "team-a-alert"}
    ouw.notify_upgrades_start(
        ocm_map=ouw_ocm_map,
        oc_map=ouw_oc_map,
        clusters=[cluster],
        state=state,
        slack=slack,
    )
    assert slack.chat_post_message.call_count == 2

    cluster.labels = {"notifications": "team-a-alert,team-b-alert"}
    ouw.notify_upgrades_start(
        ocm_map=ouw_ocm_map,
        oc_map=ouw_oc_map,
        clusters=[cluster],
        state=state,
        slack=slack,
    )
    assert slack.chat_post_message.call_count == 3


def test_new_upgrade_already_notified(
    mocker: MockerFixture,
    state: MagicMock,
    slack: MagicMock,
    ouw_oc_map: MagicMock,
    ouw_ocm_map: MagicMock,
    upgrade_config: dict[str, Any],
    mock_utc_now: MagicMock,
) -> None:
    """There is an UpgradeConfig on the cluster, its upgradeAt is in the past,
    and we already notified"""
    state.exists.return_value = True
    state.get.return_value = None
    mock_utc_now.return_value = upgrade_at + timedelta(hours=1)
    gso = mocker.patch(
        "reconcile.openshift_upgrade_watcher._get_start_osd", autospec=True
    )
    gso.return_value = upgrade_at.strftime("%Y-%m-%dT%H:%M:%SZ"), upgrade_version
    ouw.notify_upgrades_start(
        ocm_map=ouw_ocm_map,
        oc_map=ouw_oc_map,
        clusters=[load_cluster("cluster1.yml")],
        state=state,
        slack=slack,
    )
    assert slack.chat_post_message.call_count == 0
    assert state.add.call_count == 0


@pytest.fixture
def clusters() -> list[ClusterV1]:
    cluster = load_cluster("cluster1.yml")
    cluster.name = cluster_name
    if not cluster.spec:
        raise RuntimeError("This test requires a cluster_spec. Check your fixture.")
    cluster.spec.version = upgrade_version
    return [cluster]


def test_new_version_no_op(
    mocker: MockerFixture, state: MagicMock, slack: MagicMock, clusters: list[ClusterV1]
) -> None:
    """We already notified for this cluster & version"""
    state.exists.return_value = True
    state.get.return_value = upgrade_version  # same version, already notified
    ouw.notify_cluster_new_version(clusters, state=state, slack=slack)
    assert slack.chat_post_message.call_count == 0
    assert state.add.call_count == 0


def test_new_version_no_state(
    mocker: MockerFixture, state: MagicMock, slack: MagicMock, clusters: list[ClusterV1]
) -> None:
    """We never notified for this cluster"""
    state.exists.return_value = False  # never notified for this cluster
    state.get.return_value = None
    ouw.notify_cluster_new_version(clusters, state=state, slack=slack)
    assert slack.chat_post_message.call_count == 1
    assert state.add.call_count == 1


def test_new_version_notify(
    mocker: MockerFixture, state: MagicMock, slack: MagicMock, clusters: list[ClusterV1]
) -> None:
    """We already notified for this cluster, but on an old version"""
    state.exists.return_value = True
    state.get.return_value = old_version  # different version
    ouw.notify_cluster_new_version(clusters, state=state, slack=slack)
    assert slack.chat_post_message.call_count == 1
    assert state.add.call_count == 1


def test__get_start_hypershift_started(mocker: MockerFixture) -> None:
    get_control_plane_upgrade_policies_mock = mocker.patch.object(
        ouw, "get_control_plane_upgrade_policies", autospec=True
    )
    get_control_plane_upgrade_policies_mock.return_value = [
        {
            "next_run": upgrade_at,
            "version": upgrade_version,
            "state": "started",
        }
    ]
    ocm_api_mock = mocker.patch(
        "reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True
    )
    next_run, version = ouw._get_start_hypershift(ocm_api_mock, "cluster-id")
    assert next_run == upgrade_at
    assert version == upgrade_version


def test__get_start_hypershift_noop(mocker: MockerFixture) -> None:
    get_control_plane_upgrade_policies_mock = mocker.patch.object(
        ouw, "get_control_plane_upgrade_policies", autospec=True
    )
    get_control_plane_upgrade_policies_mock.return_value = []
    ocm_api_mock = mocker.patch(
        "reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True
    )
    next_run, version = ouw._get_start_hypershift(ocm_api_mock, "cluster-id")
    assert not next_run
    assert not version


def test__get_start_osd_no_op(ouw_oc_map: MagicMock) -> None:
    """There is no UpgradeConfig on the cluster"""
    next_run, version = ouw._get_start_osd(ouw_oc_map, cluster_name)
    assert not next_run
    assert not version


def test__get_start_osd_started(
    ouw_oc_map: MagicMock, upgrade_config: dict[str, Any]
) -> None:
    """There is no UpgradeConfig on the cluster"""
    oc = ouw_oc_map.get.return_value
    oc.get.return_value = upgrade_config
    next_run, version = ouw._get_start_osd(ouw_oc_map, cluster_name)
    assert next_run == "2020-06-01T00:00:00Z"
    assert version == "4.5.2"
