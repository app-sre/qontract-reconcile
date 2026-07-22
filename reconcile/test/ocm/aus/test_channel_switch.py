from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import HTTPError

from reconcile.aus import base as aus_base
from reconcile.aus.base import (
    ChannelSwitchAction,
    act_channel_switches,
    check_y_stream_channel_switch_needed,
)
from reconcile.test.ocm.aus.fixtures import (
    build_cluster_upgrade_spec,
)
from reconcile.test.ocm.fixtures import build_ocm_cluster


@pytest.mark.parametrize(
    "channel, expected",
    [
        ("stable-4.20", True),
        ("eus-4.22", True),
        ("fast-4.21", True),
        ("stable", False),
        ("stable-4.x", False),
    ],
)
def test_is_y_stream_channel(channel: str, expected: bool) -> None:
    cluster = build_ocm_cluster(name="c1", version="4.20.10", channel=channel)
    assert cluster.is_y_stream_channel() is expected


@pytest.mark.parametrize(
    "channel, expected",
    [
        ("stable-4.20", "stable"),
        ("eus-4.20", "eus"),
        ("fast-4.21", "fast"),
    ],
)
def test_channel_type(channel: str, expected: str) -> None:
    cluster = build_ocm_cluster(name="c1", version="4.20.10", channel=channel)
    assert cluster.channel_type() == expected


@pytest.mark.parametrize(
    "version, channel, expected",
    [
        ("4.20.10", "stable-4.20", "stable-4.21"),
        ("4.20.10", "eus-4.20", "eus-4.22"),
        ("4.22.5", "eus-4.22", "eus-4.24"),
        ("4.21.5", "fast-4.21", "fast-4.22"),
        ("4.20.10", "stable", None),
    ],
)
def test_target_y_stream_channel(
    version: str, channel: str, expected: str | None
) -> None:
    cluster = build_ocm_cluster(name="c1", version=version, channel=channel)
    assert cluster.target_y_stream_channel() == expected


def test_check_legacy_channel_no_switch() -> None:
    spec = build_cluster_upgrade_spec(
        name="c1", current_version="4.20.10", channel="stable"
    )
    assert check_y_stream_channel_switch_needed(spec, set()) is None


def test_check_target_channel_not_in_available_channels() -> None:
    spec = build_cluster_upgrade_spec(
        name="c1",
        current_version="4.21.10",
        channel="stable-4.21",
    )
    assert (
        check_y_stream_channel_switch_needed(
            spec, {"stable-4.21", "fast-4.21", "fast-4.22"}
        )
        is None
    )


def test_check_no_available_channels() -> None:
    spec = build_cluster_upgrade_spec(
        name="c1",
        current_version="4.20.10",
        channel="stable-4.20",
    )
    assert check_y_stream_channel_switch_needed(spec, set()) is None


def test_check_already_on_target_channel() -> None:
    spec = build_cluster_upgrade_spec(
        name="c1",
        current_version="4.21.10",
        channel="stable-4.21",
    )
    assert (
        check_y_stream_channel_switch_needed(spec, {"stable-4.21", "stable-4.22"})
        is not None
    )
    spec_same = build_cluster_upgrade_spec(
        name="c1",
        current_version="4.22.5",
        channel="stable-4.22",
    )
    assert (
        check_y_stream_channel_switch_needed(spec_same, {"stable-4.22", "stable-4.23"})
        is not None
    )


@pytest.mark.parametrize(
    "channel, available_channels, expected_from, expected_to",
    [
        ("stable-4.20", ["stable-4.20", "stable-4.21"], "stable-4.20", "stable-4.21"),
        ("eus-4.20", ["eus-4.20", "eus-4.22"], "eus-4.20", "eus-4.22"),
    ],
)
def test_check_switch_needed(
    channel: str,
    available_channels: list[str],
    expected_from: str,
    expected_to: str,
) -> None:
    spec = build_cluster_upgrade_spec(
        name="c1",
        current_version="4.20.10",
        channel=channel,
        available_channels=available_channels,
    )
    result = check_y_stream_channel_switch_needed(spec, set(available_channels))
    assert result is not None
    assert result.from_channel == expected_from
    assert result.to_channel == expected_to


def test_check_y1_blocked_still_switches() -> None:
    spec = build_cluster_upgrade_spec(
        name="c1",
        current_version="4.20.10",
        channel="stable-4.20",
        available_channels=["stable-4.20", "stable-4.21"],
        blocked_versions=[r"^4\.21\..*$"],
    )
    result = check_y_stream_channel_switch_needed(spec, {"stable-4.20", "stable-4.21"})
    assert result is not None
    assert result.to_channel == "stable-4.21"


# --- _get_available_channels tests ---


def test_get_available_channels_from_cluster_api() -> None:
    ocm_api = MagicMock()
    ocm_api.get.return_value = {
        "version": {
            "available_channels": ["stable-4.20", "stable-4.21"],
        },
    }
    cache: dict[str, set[str]] = {}
    result = aus_base._get_available_channels(
        ocm_api, "c1_id", "openshift-v4.20.10", cache
    )
    assert result == {"stable-4.20", "stable-4.21"}
    ocm_api.get.assert_called_once_with(api_path="/api/clusters_mgmt/v1/clusters/c1_id")
    assert cache["openshift-v4.20.10"] == {"stable-4.20", "stable-4.21"}


def test_get_available_channels_cache_hit() -> None:
    ocm_api = MagicMock()
    cache = {"openshift-v4.20.10": {"stable-4.20", "stable-4.21"}}
    result = aus_base._get_available_channels(
        ocm_api, "c1_id", "openshift-v4.20.10", cache
    )
    assert result == {"stable-4.20", "stable-4.21"}
    ocm_api.get.assert_not_called()


def test_get_available_channels_http_error() -> None:
    ocm_api = MagicMock()
    response = MagicMock()
    response.text = "not found"
    ocm_api.get.side_effect = HTTPError(response=response)
    cache: dict[str, set[str]] = {}
    result = aus_base._get_available_channels(
        ocm_api, "c1_id", "openshift-v4.20.10", cache
    )
    assert result == set()
    assert cache["openshift-v4.20.10"] == set()


# --- _try_channel_switch tests ---


def test_try_channel_switch_skips_addon() -> None:
    spec = build_cluster_upgrade_spec(
        name="c1",
        current_version="4.20.10",
        channel="stable-4.20",
    )
    switches: list[ChannelSwitchAction] = []
    aus_base._try_channel_switch(spec, "some-addon", switches, MagicMock(), {})
    assert switches == []


def test_try_channel_switch_uses_cluster_get_fallback() -> None:
    spec = build_cluster_upgrade_spec(
        name="c1",
        current_version="4.20.10",
        channel="stable-4.20",
    )
    ocm_api = MagicMock()
    ocm_api.get.return_value = {
        "version": {
            "available_channels": ["stable-4.20", "stable-4.21"],
        },
    }
    switches: list[ChannelSwitchAction] = []
    cache: dict[str, set[str]] = {}
    aus_base._try_channel_switch(spec, "", switches, ocm_api, cache)
    assert len(switches) == 1
    assert switches[0].to_channel == "stable-4.21"
    ocm_api.get.assert_called_once()


# --- act_channel_switches tests ---


@pytest.fixture
def channel_switch() -> ChannelSwitchAction:
    cluster = build_ocm_cluster(name="c1", version="4.20.10", channel="stable-4.20")
    return ChannelSwitchAction(
        cluster=cluster,
        from_channel="stable-4.20",
        to_channel="stable-4.21",
        org_id="org1",
    )


@patch("reconcile.aus.base.update_cluster_channel")
@patch("reconcile.aus.base.metrics")
def test_act_dry_run_skips_api_and_gauge(
    mock_metrics: MagicMock,
    mock_update: MagicMock,
    channel_switch: ChannelSwitchAction,
) -> None:
    act_channel_switches(
        dry_run=True,
        channel_switches=[channel_switch],
        ocm_api=MagicMock(),
    )
    mock_update.assert_not_called()
    mock_metrics.set_gauge.assert_not_called()


@patch("reconcile.aus.base.update_cluster_channel")
@patch("reconcile.aus.base.metrics")
def test_act_success_emits_gauge(
    mock_metrics: MagicMock,
    mock_update: MagicMock,
    channel_switch: ChannelSwitchAction,
) -> None:
    act_channel_switches(
        dry_run=False,
        channel_switches=[channel_switch],
        ocm_api=MagicMock(),
        integration="test-int",
        ocm_env="test-env",
    )
    mock_update.assert_called_once()
    mock_metrics.set_gauge.assert_called_once()
    gauge = mock_metrics.set_gauge.call_args[0][0]
    assert gauge.from_channel == "stable-4.20"
    assert gauge.to_channel == "stable-4.21"


@patch("reconcile.aus.base.update_cluster_channel")
@patch("reconcile.aus.base.metrics")
def test_act_http_400_warns_and_continues(
    mock_metrics: MagicMock, mock_update: MagicMock
) -> None:
    response = MagicMock()
    response.text = "Could not locate organization id"
    response.status_code = 400
    mock_update.side_effect = HTTPError(response=response)
    cluster1 = build_ocm_cluster(name="c1", version="4.20.10", channel="stable-4.20")
    cluster2 = build_ocm_cluster(name="c2", version="4.20.10", channel="stable-4.20")
    switches = [
        ChannelSwitchAction(
            cluster=c,
            from_channel="stable-4.20",
            to_channel="stable-4.21",
            org_id="org1",
        )
        for c in [cluster1, cluster2]
    ]
    act_channel_switches(
        dry_run=False,
        channel_switches=switches,
        ocm_api=MagicMock(),
    )
    assert mock_update.call_count == 2
    mock_metrics.set_gauge.assert_not_called()


@patch("reconcile.aus.base.update_cluster_channel")
@patch("reconcile.aus.base.metrics")
def test_act_http_non_400_error_raises(
    mock_metrics: MagicMock, mock_update: MagicMock
) -> None:
    response = MagicMock()
    response.text = "forbidden"
    response.status_code = 403
    mock_update.side_effect = HTTPError(response=response)
    cluster1 = build_ocm_cluster(name="c1", version="4.20.10", channel="stable-4.20")
    switches = [
        ChannelSwitchAction(
            cluster=cluster1,
            from_channel="stable-4.20",
            to_channel="stable-4.21",
            org_id="org1",
        )
    ]
    with pytest.raises(ExceptionGroup, match="Channel switch errors"):
        act_channel_switches(
            dry_run=False,
            channel_switches=switches,
            ocm_api=MagicMock(),
        )
    mock_metrics.set_gauge.assert_not_called()
