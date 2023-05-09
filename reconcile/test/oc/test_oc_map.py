from collections.abc import Mapping
from typing import Any
from unittest.mock import (
    MagicMock,
    create_autospec,
)

import pytest

from reconcile.utils.oc import (
    OC,
    OCCli,
)
from reconcile.utils.oc_connection_parameters import OCConnectionParameters
from reconcile.utils.oc_map import (
    OCLogMsg,
    OCMap,
)


def make_connection_parameter(data: Mapping[str, Any]) -> OCConnectionParameters:
    return OCConnectionParameters(
        cluster_name=data.get("cluster_name", ""),
        automation_token=data.get("automation_token", None),
        cluster_admin_automation_token=data.get("cluster_admin_automation_token", None),
        is_cluster_admin=data.get("is_cluster_admin", False),
        is_internal=data.get("is_internal", False),
        jumphost_hostname=data.get("jumphost_hostname", None),
        jumphost_key=data.get("jumphost_key", None),
        jumphost_known_hosts=data.get("jumphost_known_hosts", None),
        jumphost_local_port=data.get("jumphost_local_port", None),
        jumphost_port=data.get("jumphost_port", None),
        jumphost_remote_port=data.get("jumphost_remote_port", None),
        jumphost_user=data.get("jumphost_user", None),
        server_url=data.get("server_url", ""),
        skip_tls_verify=data.get("skip_tls_verify", None),
        disabled_integrations=data.get("disabled_integrations", []),
    )


class OCTest(OC):
    def __new__(cls, **kwargs: Any):
        return create_autospec(spec=OCCli)


@pytest.fixture
def oc_cls() -> type[OC]:
    return MagicMock(return_value=create_autospec(spec=OCCli))


def test_oc_map_with_errors(oc_cls: type[OC]):
    params_1 = make_connection_parameter(
        {
            "cluster_name": "test-1",
            "server_url": "http://localhost",
        }
    )
    params_2 = make_connection_parameter(
        {
            "cluster_name": "test-2",
            "server_url": "http://localhost",
            "automation_token": "blub",
        }
    )

    cluster_names = [params_1.cluster_name, params_2.cluster_name]

    oc_map = OCMap(connection_parameters=[params_1, params_2], oc_cls=oc_cls)

    assert oc_map.clusters(include_errors=True) == cluster_names
    assert isinstance(oc_map._oc_map.get(params_1.cluster_name), OCLogMsg)
    assert isinstance(oc_map._oc_map.get(params_2.cluster_name), OCCli)


def test_privileged_clusters(oc_cls: type[OC]):
    param_1 = make_connection_parameter(
        {
            "cluster_name": "cluster-1",
            "is_cluster_admin": True,
            "server_url": "http://localhost",
            "cluster_admin_automation_token": "abc",
        }
    )
    param_2 = make_connection_parameter(
        {
            "cluster_name": "cluster-2",
            "server_url": "http://localhost",
            "automation_token": "abc",
        }
    )

    oc_map = OCMap(connection_parameters=[param_1, param_2], oc_cls=oc_cls)
    assert oc_map.clusters() == [param_2.cluster_name]
    assert oc_map.clusters(privileged=True) == [param_1.cluster_name]
    assert isinstance(oc_map.get(param_1.cluster_name), OCLogMsg)
    assert isinstance(oc_map.get(param_2.cluster_name), OCCli)
    assert isinstance(oc_map.get(param_1.cluster_name, privileged=True), OCCli)
    assert isinstance(oc_map.get(param_2.cluster_name, privileged=True), OCLogMsg)


@pytest.mark.parametrize(
    "parameters, error_message",
    [
        (
            make_connection_parameter(
                {
                    "cluster_name": "test",
                    "automation_token": "abc",
                }
            ),
            "[test] has no serverUrl",
        ),
        (
            make_connection_parameter(
                {
                    "cluster_name": "test",
                    "server_url": "localhost",
                }
            ),
            "[test] has no automationToken",
        ),
        (
            make_connection_parameter(
                {
                    "cluster_name": "test",
                    "server_url": "localhost",
                    "is_cluster_admin": True,
                }
            ),
            "[test] has no clusterAdminAutomationToken",
        ),
    ],
)
def test_errors(parameters: OCConnectionParameters, error_message: str):
    oc_map = OCMap(connection_parameters=[parameters])
    sut = oc_map.get(parameters.cluster_name, privileged=parameters.is_cluster_admin)
    assert isinstance(sut, OCLogMsg)
    assert sut.message == error_message
    assert len(oc_map.clusters()) == 0
