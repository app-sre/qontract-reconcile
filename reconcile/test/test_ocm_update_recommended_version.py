import pytest

from reconcile.ocm_update_recommended_version import (
    get_highest,
    get_majority,
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
    assert recommended_version(versions, 10, 1) == "1.1.1"
    assert recommended_version(versions, 0, 1) == "1.1.0"
    assert recommended_version(["1.1.0", "1.1.0", "1.1.1"], 10, 5) == "1.1.1"
