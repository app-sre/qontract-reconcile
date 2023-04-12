from typing import Any

import pytest

from reconcile.test.fixtures import Fixtures
from reconcile.utils.ocm import OCM


@pytest.fixture
def clusters() -> list[dict[str, Any]]:
    """
    This cluster fixture overrides the one in conftest.py
    Clusters returned by this fixture are present in the
    ocm fixture.
    """
    return [Fixtures("clusters").get_anymarkup("osd_spec.json")]


def test_no_blocked_versions(ocm: OCM) -> None:
    result = ocm.version_blocked("1.2.3")
    assert result is False


def test_version_blocked(ocm: OCM) -> None:
    ocm.blocked_versions = ["1.2.3"]
    result = ocm.version_blocked("1.2.3")
    assert result is True


def test_version_not_blocked(ocm: OCM) -> None:
    ocm.blocked_versions = ["1.2.3"]
    result = ocm.version_blocked("1.2.4")
    assert result is False


def test_addon_version_blocked(ocm: OCM) -> None:
    ocm.blocked_versions = ["myaddon/1.2.3"]
    result = ocm.addon_version_blocked("1.2.3", "myaddon")
    assert result is True


def test_addon_version_not_blocked(ocm: OCM) -> None:
    ocm.blocked_versions = ["1.2.4", "myaddon/1.2.3"]
    result = ocm.addon_version_blocked("1.2.4", "myaddon")
    assert result is False


def test_version_blocked_multiple(ocm: OCM) -> None:
    ocm.blocked_versions = ["1.2.3", "1.2.4"]
    result = ocm.version_blocked("1.2.3")
    assert result is True


def test_version_blocked_regex(ocm: OCM) -> None:
    ocm.blocked_versions = [r"^.*-fc\..*$"]
    result = ocm.version_blocked("1.2.3-fc.1")
    assert result is True


def test_version_not_blocked_regex(ocm: OCM) -> None:
    ocm.blocked_versions = [r"^.*-fc\..*$"]
    result = ocm.version_blocked("1.2.3-rc.1")
    assert result is False


def test_version_invalid_regex(ocm: OCM) -> None:
    with pytest.raises(TypeError):
        OCM("name", "org_id", ocm._ocm_client, blocked_versions=["["])


def test_available_upgrades_versions(ocm: OCM) -> None:
    assert ocm.available_cluster_upgrades["test-cluster"] == [
        "4.11.33",
        "4.12.1",
        "4.12.8",
        "4.12.9",
    ]
