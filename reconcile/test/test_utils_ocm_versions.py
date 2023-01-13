import pytest

from reconcile.utils.ocm import OCM


@pytest.fixture
def ocm(mocker):
    mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient._init_access_token")
    mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient._init_request_headers")
    mocker.patch("reconcile.utils.ocm.OCM.whoami")
    mocker.patch("reconcile.utils.ocm.OCM._init_clusters")
    mocker.patch("reconcile.utils.ocm.OCM._init_version_gates")
    return OCM("name", "url", "tid", "turl", "ot")


def test_no_blocked_versions(ocm):
    result = ocm.version_blocked("1.2.3")
    assert result is False


def test_version_blocked(ocm):
    ocm.blocked_versions = ["1.2.3"]
    result = ocm.version_blocked("1.2.3")
    assert result is True


def test_version_not_blocked(ocm):
    ocm.blocked_versions = ["1.2.3"]
    result = ocm.version_blocked("1.2.4")
    assert result is False


def test_addon_version_blocked(ocm):
    ocm.blocked_versions = ["myaddon/1.2.3"]
    result = ocm.addon_version_blocked("1.2.3", "myaddon")
    assert result is True


def test_addon_version_not_blocked(ocm):
    ocm.blocked_versions = ["1.2.4", "myaddon/1.2.3"]
    result = ocm.addon_version_blocked("1.2.4", "myaddon")
    assert result is False


def test_version_blocked_multiple(ocm):
    ocm.blocked_versions = ["1.2.3", "1.2.4"]
    result = ocm.version_blocked("1.2.3")
    assert result is True


def test_version_blocked_regex(ocm):
    ocm.blocked_versions = [r"^.*-fc\..*$"]
    result = ocm.version_blocked("1.2.3-fc.1")
    assert result is True


def test_version_not_blocked_regex(ocm):
    ocm.blocked_versions = [r"^.*-fc\..*$"]
    result = ocm.version_blocked("1.2.3-rc.1")
    assert result is False


def test_version_invalid_regex(ocm):
    with pytest.raises(TypeError):
        OCM("name", "url", "tid", "turl", "ot", blocked_versions=["["])
