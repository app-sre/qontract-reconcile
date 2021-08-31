import pytest

from unittest import TestCase
from unittest.mock import patch

from reconcile.utils.ocm import OCM


class TestVersionBlocked(TestCase):
    @patch.object(OCM, '_init_access_token')
    @patch.object(OCM, '_init_request_headers')
    @patch.object(OCM, '_init_clusters')
    # pylint: disable=arguments-differ
    def setUp(self, ocm_init_access_token,
              ocm_init_request_headers, ocm_init_clusters):
        self.ocm = OCM('name', 'url', 'tid', 'turl', 'ot')

    def test_no_blocked_versions(self):
        result = self.ocm.version_blocked('1.2.3')
        self.assertFalse(result)

    def test_version_blocked(self):
        self.ocm.blocked_versions = ['1.2.3']
        result = self.ocm.version_blocked('1.2.3')
        self.assertTrue(result)

    def test_version_not_blocked(self):
        self.ocm.blocked_versions = ['1.2.3']
        result = self.ocm.version_blocked('1.2.4')
        self.assertFalse(result)

    def test_version_blocked_multiple(self):
        self.ocm.blocked_versions = ['1.2.3', '1.2.4']
        result = self.ocm.version_blocked('1.2.3')
        self.assertTrue(result)

    def test_version_blocked_regex(self):
        self.ocm.blocked_versions = [r'^.*-fc\..*$']
        result = self.ocm.version_blocked('1.2.3-fc.1')
        self.assertTrue(result)

    def test_version_not_blocked_regex(self):
        self.ocm.blocked_versions = [r'^.*-fc\..*$']
        result = self.ocm.version_blocked('1.2.3-rc.1')
        self.assertFalse(result)

class TestVersionRegex(TestCase):
    @patch.object(OCM, '_init_access_token')
    @patch.object(OCM, '_init_request_headers')
    @patch.object(OCM, '_init_clusters')
    # pylint: disable=arguments-differ
    def test_invalid_regex(self, ocm_init_access_token,
              ocm_init_request_headers, ocm_init_clusters):
        with pytest.raises(TypeError):
            ocm = OCM('name', 'url', 'tid', 'turl', 'ot',
                      blocked_versions=['['])
