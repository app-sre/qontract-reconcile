import os
import json
from typing import Dict, List
from datetime import date, timedelta

from unittest import TestCase
from unittest.mock import patch

from reconcile.utils.aggregated_list import RunnerException
from reconcile import queries
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.openshift_resource import OpenshiftResource as OR
import reconcile.openshift_base as ob

from reconcile.test.fixtures import Fixtures
from reconcile.utils.oc import ApiClient, OCDeprecated
import reconcile.gabi_authorized_users as gabi_u

apply = Fixtures("gabi_authorized_users").get_anymarkup("apply.yml")
delete = Fixtures("gabi_authorized_users").get_anymarkup("delete.yml")


class RespMock:
    def __init__(self, data):
        self.data = json.dumps(data).encode()


def apply_request(
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
    cluster = apply.get(url_list[0])
    data = cluster.get(url_list[1], None)
    return RespMock(data)


def delete_request(
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
    cluster = delete.get(url_list[0])
    data = cluster.get(url_list[1], None)
    return RespMock(data)


def mock_get_gabi_instances(expirationDate: str) -> List[Dict]:
    gabi_instances = apply["gql_response"]
    gabi_instances[0]["expirationDate"] = str(expirationDate)
    return gabi_instances


@patch.object(queries, "get_app_interface_settings", autospec=True)
@patch.object(SecretReader, "read", autospec=True)
@patch.object(OCDeprecated, "get_version", autospec=True)
@patch.object(queries, "get_gabi_instances", autospec=True)
@patch.object(ApiClient, "request")
@patch.dict(os.environ, {"USE_NATIVE_CLIENT": "True"}, clear=True)
class TestGabiAuthorizedUser(TestCase):
    def test_gabi_authorized_users_exceed(
        self, mock_request, get_gabi_instances, oc_version, secret_read, get_settings
    ):
        expirationDate = date.today() + timedelta(days=(gabi_u.EXPIRATION_MAX + 1))
        get_gabi_instances.return_value = mock_get_gabi_instances(expirationDate)
        mock_request.side_effect = apply_request
        with self.assertRaises(RunnerException):
            gabi_u.run(dry_run=False)

    @patch.object(ob, "apply", autospec=True)
    def test_gabi_authorized_users_apply(
        self,
        mock_apply,
        mock_request,
        get_gabi_instances,
        oc_version,
        secret_read,
        get_settings,
    ):
        expirationDate = date.today()
        get_gabi_instances.return_value = mock_get_gabi_instances(expirationDate)
        mock_request.side_effect = apply_request
        gabi_u.run(dry_run=False)
        expected = OR(
            apply["desired"],
            gabi_u.QONTRACT_INTEGRATION,
            gabi_u.QONTRACT_INTEGRATION_VERSION,
        )
        args, _ = mock_apply.call_args
        self.assertEqual(args[5], expected)

    @patch.object(OR, "calculate_sha256sum", autospec=True)
    @patch.object(OCDeprecated, "apply", autospec=True)
    def test_gabi_authorized_users_exist(
        self,
        mock_apply,
        sha,
        mock_request,
        get_gabi_instances,
        oc_version,
        secret_read,
        get_settings,
    ):
        # pylint: disable=no-self-use
        expirationDate = date.today()
        get_gabi_instances.return_value = mock_get_gabi_instances(expirationDate)
        mock_request.side_effect = delete_request
        sha.return_value = "abc"
        gabi_u.run(dry_run=False)
        mock_apply.assert_not_called()

    @patch.object(ob, "apply", autospec=True)
    def test_gabi_authorized_users_expire(
        self,
        mock_apply,
        mock_request,
        get_gabi_instances,
        oc_version,
        secret_read,
        get_settings,
    ):
        # pylint: disable=no-self-use
        expirationDate = date.today() - timedelta(days=1)
        get_gabi_instances.return_value = mock_get_gabi_instances(expirationDate)
        mock_request.side_effect = delete_request
        gabi_u.run(dry_run=False)
        expected = OR(
            delete["desired"],
            gabi_u.QONTRACT_INTEGRATION,
            gabi_u.QONTRACT_INTEGRATION_VERSION,
        )
        args, _ = mock_apply.call_args
        self.assertEqual(args[5], expected)
