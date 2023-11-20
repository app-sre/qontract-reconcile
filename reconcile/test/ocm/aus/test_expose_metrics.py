from datetime import (
    datetime,
    timedelta,
)

from reconcile.aus.base import remaining_soak_day_metric_values_for_cluster
from reconcile.aus.metrics import (
    UPGRADE_BLOCKED_METRIC_VALUE,
    UPGRADE_LONG_RUNNING_METRIC_VALUE,
    UPGRADE_SCHEDULED_METRIC_VALUE,
    UPGRADE_STARTED_METRIC_VALUE,
)
from reconcile.test.ocm.aus.fixtures import (
    build_cluster_upgrade_policy,
    build_cluster_upgrade_spec,
)


def test_remaining_soak_day_metric_values_for_cluster_skip_early_ready() -> None:
    """
    Test that ready versions are skipped in metric reporting if there is a later
    version that is not ready.
    """
    assert {"4.13.11": 0.0} == remaining_soak_day_metric_values_for_cluster(
        spec=build_cluster_upgrade_spec(
            name="cluster1",
            current_version="4.13.0",
            available_upgrades=["4.13.10", "4.13.11"],
            soak_days=0,
        ),
        soaked_versions={},
        current_upgrade=None,
    )


def test_remaining_soak_day_metric_values_for_cluster_skip_early_non_ready() -> None:
    """
    Test that still soaking versions are skipped in metric reporting if there is
    a later version that is not ready.
    """
    assert {"4.13.11": 0.0} == remaining_soak_day_metric_values_for_cluster(
        spec=build_cluster_upgrade_spec(
            name="cluster1",
            current_version="4.13.0",
            available_upgrades=["4.13.10", "4.13.11"],
            soak_days=2,
        ),
        soaked_versions={"4.13.10": 1.8, "4.13.11": 2.0},
        current_upgrade=None,
    )


def test_remaining_soak_day_metric_values_for_cluster_skip_early_mixed() -> None:
    """
    Test that still soaking versions and soakey versions are skipped in metric
    reporting if there is a later version that is not ready.
    """
    assert {"4.13.11": 0.0} == remaining_soak_day_metric_values_for_cluster(
        spec=build_cluster_upgrade_spec(
            name="cluster1",
            current_version="4.13.0",
            available_upgrades=["4.13.9", "4.13.10", "4.13.11"],
            soak_days=2,
        ),
        soaked_versions={"4.13.9": 2.0, "4.13.10": 1.8, "4.13.11": 2.0},
        current_upgrade=None,
    )


def test_remaining_soak_day_metric_values_for_cluster_blocked_versions() -> None:
    """
    Test that blocked versions are reported as blocked
    """
    assert {
        "4.14.0-rc.1": UPGRADE_BLOCKED_METRIC_VALUE,
        "4.14.0": 0.0,
    } == remaining_soak_day_metric_values_for_cluster(
        spec=build_cluster_upgrade_spec(
            name="cluster1",
            current_version="4.13.0",
            available_upgrades=["4.14.0-rc.1", "4.14.0"],
            soak_days=0,
            blocked_versions=[r"^.*-rc\..*$"],
        ),
        soaked_versions={},
        current_upgrade=None,
    )


def test_remaining_soak_day_metric_values_for_cluster_blocked_versions_and_skip_early_ready() -> (
    None
):
    """
    Test that blocked versions are reported as blocked and do not interfere with
    skipping ready early versions.
    """
    assert {
        "4.14.0-rc.1": UPGRADE_BLOCKED_METRIC_VALUE,
        "4.14.0": 0.0,
    } == remaining_soak_day_metric_values_for_cluster(
        spec=build_cluster_upgrade_spec(
            name="cluster1",
            current_version="4.13.0",
            available_upgrades=["4.13.11", "4.14.0-rc.1", "4.14.0"],
            soak_days=0,
            blocked_versions=[r"^.*-rc\..*$"],
        ),
        soaked_versions={},
        current_upgrade=None,
    )


def test_remaining_soak_day_metric_values_for_cluster_blocked_version_currently_upgrading() -> (
    None
):
    """
    Test that blocked versions are still reporting as currently upgrading if an upgrade
    has been scheduled
    """
    spec = build_cluster_upgrade_spec(
        name="cluster1",
        current_version="4.13.0",
        available_upgrades=["4.13.11", "4.14.0-rc.1", "4.14.0"],
        soak_days=0,
        blocked_versions=[r"^.*-rc\..*$"],
    )
    assert {
        "4.14.0-rc.1": UPGRADE_SCHEDULED_METRIC_VALUE,
        "4.14.0": 0.0,
    } == remaining_soak_day_metric_values_for_cluster(
        spec=spec,
        soaked_versions={},
        current_upgrade=build_cluster_upgrade_policy(
            cluster=spec.cluster,
            version="4.14.0-rc.1",
            state="scheduled",
        ),
    )


def test_remaining_soak_day_metric_values_for_cluster_currently_upgrading() -> None:
    """
    Test that a version that is currently being target of an upgrade, is reported correctly together with upcoming
    upgrades.
    """
    spec = build_cluster_upgrade_spec(
        name="cluster1",
        current_version="4.13.0",
        available_upgrades=["4.13.11", "4.14.0"],
        soak_days=0,
    )
    assert {
        "4.13.11": UPGRADE_STARTED_METRIC_VALUE,
        "4.14.0": 0.0,
    } == remaining_soak_day_metric_values_for_cluster(
        spec=spec,
        soaked_versions={},
        current_upgrade=build_cluster_upgrade_policy(
            cluster=spec.cluster,
            version="4.13.11",
            state="started",
        ),
    )


def test_remaining_soak_day_metric_values_for_cluster_currently_scheduled() -> None:
    """
    Test that a version that is currently being scheduled for upgrade, is reported correctly together with
    other ready future versions.
    """
    spec = build_cluster_upgrade_spec(
        name="cluster1",
        current_version="4.13.0",
        available_upgrades=["4.13.11", "4.14.0"],
        soak_days=0,
    )
    assert {
        "4.13.11": UPGRADE_SCHEDULED_METRIC_VALUE,
        "4.14.0": 0.0,
    } == remaining_soak_day_metric_values_for_cluster(
        spec=spec,
        soaked_versions={},
        current_upgrade=build_cluster_upgrade_policy(
            cluster=spec.cluster,
            version="4.13.11",
            state="scheduled",
        ),
    )


def test_remaining_soak_day_metric_values_for_cluster_currently_scheduled_skip_earlier() -> (
    None
):
    """
    Test that earlier versions from the one that is currently target of a scheduled
    upgrade, are skipped in metric reporting.
    """
    spec = build_cluster_upgrade_spec(
        name="cluster1",
        current_version="4.13.0",
        available_upgrades=["4.13.11", "4.14.0"],
        soak_days=0,
    )
    assert {
        "4.14.0": UPGRADE_SCHEDULED_METRIC_VALUE
    } == remaining_soak_day_metric_values_for_cluster(
        spec=spec,
        soaked_versions={},
        current_upgrade=build_cluster_upgrade_policy(
            cluster=spec.cluster,
            version="4.14.0",
            state="scheduled",
        ),
    )


def test_remaining_soak_day_metric_values_for_cluster_currently_upgrading_skip_earlier() -> (
    None
):
    """
    Test that earlier versions from the one that is currently target of an
    upgrade, are skipped in metric reporting.
    """
    spec = build_cluster_upgrade_spec(
        name="cluster1",
        current_version="4.13.0",
        available_upgrades=["4.13.11", "4.14.0"],
        soak_days=0,
    )
    assert {
        "4.14.0": UPGRADE_STARTED_METRIC_VALUE
    } == remaining_soak_day_metric_values_for_cluster(
        spec=spec,
        soaked_versions={},
        current_upgrade=build_cluster_upgrade_policy(
            cluster=spec.cluster,
            version="4.14.0",
            state="started",
        ),
    )


def test_remaining_soak_day_metric_values_for_cluster_long_running_upgrade() -> None:
    """
    Test that an upgrade running for more than 6h is reported as a long running upgrade.
    """
    spec = build_cluster_upgrade_spec(
        name="cluster1",
        current_version="4.13.0",
        available_upgrades=["4.13.11"],
        soak_days=0,
    )
    assert {
        "4.13.11": UPGRADE_LONG_RUNNING_METRIC_VALUE
    } == remaining_soak_day_metric_values_for_cluster(
        spec=spec,
        soaked_versions={},
        current_upgrade=build_cluster_upgrade_policy(
            cluster=spec.cluster,
            version="4.13.11",
            state="started",
            next_run=datetime.utcnow() - timedelta(hours=7),
        ),
    )


def test_remaining_soak_day_metric_values_for_cluster_not_filtering() -> None:
    spec = build_cluster_upgrade_spec(
        name="cluster1",
        current_version="4.13.0",
        available_upgrades=["4.13.11", "4.13.12", "4.14.1"],
        soak_days=2,
        blocked_versions=[r"^4\.14\..*$"],
    )
    assert {
        "4.13.11": 0.0,
        "4.13.12": 2.0,
        "4.14.1": UPGRADE_BLOCKED_METRIC_VALUE,
    } == remaining_soak_day_metric_values_for_cluster(
        spec=spec,
        soaked_versions={"4.13.11": 2.0},
        current_upgrade=None,
    )
