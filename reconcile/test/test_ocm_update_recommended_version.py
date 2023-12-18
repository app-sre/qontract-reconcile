import pytest

from reconcile.ocm.types import (
    OCMClusterNetwork,
    OCMClusterSpec,
    OCMSpec,
)
from reconcile.ocm_update_recommended_version import (
    format_initial_version,
    get_highest,
    get_majority,
    get_updated_recommended_versions,
    get_version_weights,
    recommended_version,
)


@pytest.fixture
def versions() -> list[str]:
    return ["1.0.0", "1.1.0", "1.1.1", "1.1.0"]


@pytest.fixture
def version_set(versions) -> set[str]:
    return set(versions)


def test_get_highest(version_set):
    highest = get_highest(version_set)
    assert highest == "1.1.1"

    assert get_highest(set(["1.1.1"])) == "1.1.1"


def test_get_majority(versions, version_set):
    majority = get_majority(version_set, versions)
    assert majority == "1.1.0"

    assert get_majority(set(["1.1.1"]), ["1.1.1"]) == "1.1.1"


def test_recommended_version(versions, version_set):
    assert recommended_version(versions, high_weight=10, majority_weight=1) == "1.1.1"
    assert recommended_version(versions, high_weight=0, majority_weight=1) == "1.1.0"
    assert (
        recommended_version(
            versions=["1.1.0", "1.1.0", "1.1.1"], high_weight=10, majority_weight=5
        )
        == "1.1.1"
    )


def test_get_version_weights():
    assert get_version_weights({}) == (1, 1)
    assert get_version_weights({"recommendedVersionWeight": {"majority": 0}}) == (1, 0)
    assert get_version_weights({
        "recommendedVersionWeight": {"majority": 2, "highest": 4}
    }) == (4, 2)


def add_cluster(
    clusters: dict[str, OCMSpec], cluster_name: str, version: str, channel: str
):
    clusters[cluster_name] = OCMSpec(
        network=OCMClusterNetwork(vpc="", service="", pod=""),
        spec=OCMClusterSpec(
            version=version,
            channel=channel,
            instance_type="",
            multi_az=True,
            private=True,
            product="",
            provider="",
            region="",
        ),
    )


def test_get_updated_recommended_versions():
    ocm_info = {
        "recommendedVersions": [],
        "upgradePolicyAllowedWorkloads": ["foo", "bar"],
        "upgradePolicyClusters": [
            {"name": "a", "upgradePolicy": {"workloads": ["foo"]}},
        ],
    }
    clusters: dict[str, OCMSpec] = {}
    add_cluster(clusters, "a", "2.0.0", "stable")

    assert get_updated_recommended_versions(ocm_info, clusters) == [
        {
            "channel": "stable",
            "recommendedVersion": "2.0.0",
            "workload": "foo",
            "initialVersion": "openshift-v2.0.0",
        },
    ]


def test_get_updated_recommended_versions_multiple_channel():
    ocm_info = {
        "recommendedVersions": [
            {"recommendedVersion": "1.0.0", "workload": "foo"},
        ],
        "upgradePolicyAllowedWorkloads": ["foo", "bar"],
        "upgradePolicyClusters": [
            {"name": "a", "upgradePolicy": {"workloads": ["foo"]}},
            {"name": "c", "upgradePolicy": {"workloads": ["foo", "bar"]}},
            {"name": "b", "upgradePolicy": {"workloads": ["bar"]}},
            {"name": "b2", "upgradePolicy": {"workloads": ["bar"]}},
            {"name": "b3", "upgradePolicy": {"workloads": ["bar"]}},
        ],
    }
    clusters: dict[str, OCMSpec] = {}
    add_cluster(clusters, "a", "2.1.0", "stable")
    add_cluster(clusters, "c", "2.0.0", "stable")
    add_cluster(clusters, "b", "3.0.0", "fast")
    add_cluster(clusters, "b2", "3.0.0", "fast")
    add_cluster(clusters, "b3", "2.0.0", "fast")

    assert get_updated_recommended_versions(ocm_info, clusters) == [
        {
            "channel": "stable",
            "recommendedVersion": "2.1.0",
            "workload": "foo",
            "initialVersion": "openshift-v2.1.0",
        },
        {
            "channel": "stable",
            "recommendedVersion": "2.0.0",
            "workload": "bar",
            "initialVersion": "openshift-v2.0.0",
        },
        {
            "channel": "fast",
            "recommendedVersion": "3.0.0",
            "workload": "bar",
            "initialVersion": "openshift-v3.0.0-fast",
        },
    ]


def test_format_initial_version():
    assert format_initial_version("2.0.0", "stable") == "openshift-v2.0.0"
    assert format_initial_version("2.0.0", "fast") == "openshift-v2.0.0-fast"
