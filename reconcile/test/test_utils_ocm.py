from unittest import TestCase
from unittest.mock import patch

import pytest

from reconcile.utils.ocm import OCM


class TestVersionBlocked(TestCase):
    @patch.object(OCM, "_init_access_token")
    @patch.object(OCM, "_init_request_headers")
    @patch.object(OCM, "_init_clusters")
    # pylint: disable=arguments-differ
    def setUp(self, ocm_init_access_token, ocm_init_request_headers, ocm_init_clusters):
        self.ocm = OCM("name", "url", "tid", "turl", "ot")

    def test_no_blocked_versions(self):
        result = self.ocm.version_blocked("1.2.3")
        self.assertFalse(result)

    def test_version_blocked(self):
        self.ocm.blocked_versions = ["1.2.3"]
        result = self.ocm.version_blocked("1.2.3")
        self.assertTrue(result)

    def test_version_not_blocked(self):
        self.ocm.blocked_versions = ["1.2.3"]
        result = self.ocm.version_blocked("1.2.4")
        self.assertFalse(result)

    def test_version_blocked_multiple(self):
        self.ocm.blocked_versions = ["1.2.3", "1.2.4"]
        result = self.ocm.version_blocked("1.2.3")
        self.assertTrue(result)

    def test_version_blocked_regex(self):
        self.ocm.blocked_versions = [r"^.*-fc\..*$"]
        result = self.ocm.version_blocked("1.2.3-fc.1")
        self.assertTrue(result)

    def test_version_not_blocked_regex(self):
        self.ocm.blocked_versions = [r"^.*-fc\..*$"]
        result = self.ocm.version_blocked("1.2.3-rc.1")
        self.assertFalse(result)


class TestVersionRegex(TestCase):
    @patch.object(OCM, "_init_access_token")
    @patch.object(OCM, "_init_request_headers")
    @patch.object(OCM, "_init_clusters")
    # pylint: disable=arguments-differ
    def test_invalid_regex(
        self, ocm_init_access_token, ocm_init_request_headers, ocm_init_clusters
    ):
        with self.assertRaises(TypeError):
            OCM("name", "url", "tid", "turl", "ot", blocked_versions=["["])


@pytest.fixture
def ocm(mocker):
    mocker.patch("reconcile.utils.ocm.OCM._init_access_token")
    mocker.patch("reconcile.utils.ocm.OCM._init_request_headers")
    mocker.patch("reconcile.utils.ocm.OCM._init_clusters")
    mocker.patch("reconcile.utils.ocm.OCM._init_blocked_versions")
    return OCM("name", "url", "tid", "turl", "ot")


def test_get_cluster_aws_account_id_none(mocker, ocm):
    role_grants_mock = mocker.patch.object(
        ocm, "get_aws_infrastructure_access_role_grants"
    )
    role_grants_mock.return_value = []
    result = ocm.get_cluster_aws_account_id("cluster")
    assert result is None


def test_get_cluster_aws_account_id_ok(mocker, ocm):
    console_url = (
        "https://signin.aws.amazon.com/switchrole?account=12345&roleName=role-1"
    )
    expected = "12345"
    role_grants_mock = mocker.patch.object(
        ocm, "get_aws_infrastructure_access_role_grants"
    )
    role_grants_mock.return_value = [(None, None, None, console_url)]
    result = ocm.get_cluster_aws_account_id("cluster")
    assert result == expected
