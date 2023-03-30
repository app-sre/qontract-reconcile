import pytest
from pytest_mock import MockerFixture

from reconcile.utils.ocm import OCM
from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def ocm(mocker: MockerFixture) -> OCM:
    mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient._init_access_token")
    mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient._init_request_headers")
    mocker.patch("reconcile.utils.ocm.OCM.whoami")
    mocker.patch("reconcile.utils.ocm.OCM._init_clusters")
    mocker.patch("reconcile.utils.ocm.OCM._init_version_gates")
    ocm_client = OCMBaseClient("url", "tid", "turl", "cid")
    return OCM("name", "org_id", ocm_client)


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
