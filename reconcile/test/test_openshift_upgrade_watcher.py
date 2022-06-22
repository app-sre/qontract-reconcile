from datetime import datetime, timedelta
import pytest
from reconcile import openshift_upgrade_watcher as ouw


@pytest.fixture
def state(mocker):
    return mocker.patch("reconcile.utils.state.State", autospec=True).return_value


@pytest.fixture
def slack(mocker):
    return mocker.patch(
        "reconcile.utils.slack_api.SlackApi", autospec=True
    ).return_value


cluster_name = "cluster1"
upgrade_at = datetime(2020, 6, 1, 0, 0, 0)
old_version = "4.5.1"
upgrade_version = "4.5.2"


@pytest.fixture
def oc_map(mocker):
    map = mocker.patch("reconcile.utils.oc.OC_Map", autospec=True).return_value
    map.clusters.return_value = [cluster_name]
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.get.return_value = {"items": []}
    map.get.return_value = oc
    return map


@pytest.fixture
def upgrade_config():
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
def dt(mocker):
    return mocker.patch(
        "reconcile.openshift_upgrade_watcher.datetime",
        mocker.Mock(datetime, wraps=datetime),
    )


def test_new_upgrade_no_op(mocker, state, slack, oc_map):
    """There is no UpgradeConfig on the cluster"""
    ouw.notify_upgrades_start(oc_map, state=state, slack=slack)
    assert slack.chat_post_message.call_count == 0
    assert state.add.call_count == 0


def test_new_upgrade_pending(mocker, state, slack, oc_map, upgrade_config, dt):
    """There is an UpgradeConfig on the cluster but its upgradeAt is in the future"""
    dt.utcnow.return_value = upgrade_at - timedelta(hours=1)
    oc = oc_map.get.return_value
    oc.get.return_value = upgrade_config
    ouw.notify_upgrades_start(oc_map, state=state, slack=slack)
    assert slack.chat_post_message.call_count == 0
    assert state.add.call_count == 0


def test_new_upgrade_notify(mocker, state, slack, oc_map, upgrade_config, dt):
    """There is an UpgradeConfig on the cluster, its upgradeAt is in the past,
    and we did not already notify"""
    dt.utcnow.return_value = upgrade_at + timedelta(hours=1)
    oc = oc_map.get.return_value
    oc.get.return_value = upgrade_config
    state.exists.return_value = False
    ouw.notify_upgrades_start(oc_map, state=state, slack=slack)
    assert slack.chat_post_message.call_count == 1
    assert state.add.call_count == 1


def test_new_upgrade_already_notified(mocker, state, slack, oc_map, upgrade_config, dt):
    """There is an UpgradeConfig on the cluster, its upgradeAt is in the past,
    and we already notified"""
    dt.utcnow.return_value = upgrade_at + timedelta(hours=1)
    oc = oc_map.get.return_value
    oc.get.return_value = upgrade_config
    state.exists.return_value = True
    state.get.return_value = None
    ouw.notify_upgrades_start(oc_map, state=state, slack=slack)
    assert slack.chat_post_message.call_count == 0
    assert state.add.call_count == 0


@pytest.fixture
def clusters():
    return [
        {
            "name": cluster_name,
            "spec": {
                "version": upgrade_version,
            },
        }
    ]


def test_new_version_no_op(mocker, state, slack, clusters):
    """We already notified for this cluster & version"""
    state.exists.return_value = True
    state.get.return_value = upgrade_version  # same version, already notified
    ouw.notify_upgrades_done(clusters, state=state, slack=slack)
    assert slack.chat_post_message.call_count == 0
    assert state.add.call_count == 0


def test_new_version_no_state(mocker, state, slack, clusters):
    """We never notified for this cluster"""
    state.exists.return_value = False  # never notified for this cluster
    state.get.return_value = None
    ouw.notify_upgrades_done(clusters, state=state, slack=slack)
    assert slack.chat_post_message.call_count == 1
    assert state.add.call_count == 1


def test_new_version_notify(mocker, state, slack, clusters):
    """We already notified for this cluster, but on an old version"""
    state.exists.return_value = True
    state.get.return_value = old_version  # different version
    ouw.notify_upgrades_done(clusters, state=state, slack=slack)
    assert slack.chat_post_message.call_count == 1
    assert state.add.call_count == 1
