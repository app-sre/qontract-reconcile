import pytest

from reconcile.ocm.types import (
    OCMSpec,
    OCMClusterSpec,
    OCMClusterNetwork,
)
from reconcile.ocm_update_recommended_version import (
    get_highest,
    get_majority,
    recommended_version,
    get_version_weights,
    get_updated_recommended_versions,
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
    assert get_version_weights(
        {"recommendedVersionWeight": {"majority": 2, "highest": 4}}
    ) == (4, 2)


def add_cluster(clusters: dict[str, OCMSpec], cluster_name: str, version: str):
    clusters[cluster_name] = OCMSpec(
        network=OCMClusterNetwork(vpc="", service="", pod=""),
        spec=OCMClusterSpec(
            version=version,
            channel="",
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
    add_cluster(clusters, "a", "2.0.0")

    assert get_updated_recommended_versions(ocm_info, clusters) == [
        {"recommendedVersion": "2.0.0", "workload": "foo"},
    ]


def test_get_updated_recommended_versions_a():
    ocm_info = {
        "recommendedVersions": [
            {"recommendedVersion": "1.0.0", "workload": "foo"},
        ],
        "upgradePolicyAllowedWorkloads": ["foo", "bar"],
        "upgradePolicyClusters": [],
    }
    clusters: dict[str, OCMSpec] = {}

    assert get_updated_recommended_versions(ocm_info, clusters) == [
        {"recommendedVersion": "1.0.0", "workload": "foo"},
    ]


def test_get_updated_recommended_versions_value_error():
    ocm_info = {
        "recommendedVersions": [
            {"recommendedVersion": "1.0.0", "workload": "foo"},
            {"recommendedVersion": "2.0.0", "workload": "foo"},
        ],
        "upgradePolicyAllowedWorkloads": ["foo"],
    }

    with pytest.raises(ValueError):
        get_updated_recommended_versions(ocm_info, {})
