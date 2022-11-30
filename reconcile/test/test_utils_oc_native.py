import json
import os
from unittest import TestCase
from unittest.mock import patch

from reconcile.test.fixtures import Fixtures
from reconcile.utils.oc import (
    OC,
    ApiClient,
    StatusCodeError,
)

fixture = Fixtures("oc_native").get_anymarkup("api.yml")


class RespMock:
    def __init__(self, data):
        self.data = json.dumps(data).encode()


def request(
    method,
    url,
    query_params=None,
    headers=None,
    post_params=None,
    body=None,
    _preload_content=True,
    _request_timeout=None,
):
    url_list = url.split("/", 1)
    cluster = fixture.get(url_list[0])
    data = cluster.get(url_list[1], None)
    return RespMock(data)


class TestOCNative(TestCase):
    @patch.dict(os.environ, {"USE_NATIVE_CLIENT": "True"}, clear=True)
    @patch.object(ApiClient, "request")
    def test_oc_native(self, mock_request):
        mock_request.side_effect = request

        oc = OC("cluster", "server", "token", init_projects=True, local=True)
        expected = fixture["api_kind_version"]
        self.assertEqual(oc.api_kind_version, expected)

        expected = fixture["projects"]
        self.assertEqual(oc.projects, expected)

        kind = "Project.config.openshift.io"
        _k, group_version = oc._parse_kind(kind)
        self.assertEqual(group_version, "config.openshift.io/v1")

        kind = "Test"
        with self.assertRaises(StatusCodeError):
            oc._parse_kind(kind)

        kind = "Project.test.io"
        with self.assertRaises(StatusCodeError):
            oc._parse_kind(kind)
