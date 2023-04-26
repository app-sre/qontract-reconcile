from collections.abc import (
    Callable,
    MutableMapping,
)
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.skupper_network.skupper_networks import SkupperNetworkV1
from reconcile.skupper_network import integration as intg
from reconcile.skupper_network.models import SkupperSite
from reconcile.test.fixtures import Fixtures
from reconcile.utils.oc import OCNative
from reconcile.utils.oc_map import OCMap


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("skupper_network")


@pytest.fixture
def skupper_networks(
    fx: Fixtures,
    data_factory: Callable[
        [type[SkupperNetworkV1], MutableMapping[str, Any]], MutableMapping[str, Any]
    ],
) -> list[SkupperNetworkV1]:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        raw_data = fx.get_anymarkup("skupper_networks.yml")
        return {
            "skupper_networks": [
                data_factory(SkupperNetworkV1, item)
                for item in raw_data["skupper_networks"]
            ]
        }

    return intg.get_skupper_networks(q)


@pytest.fixture
def fake_get_resource(mocker: MockerFixture) -> MagicMock:
    gql_mock = mocker.patch("reconcile.utils.gql.get_api", autospec=True)
    gql_mock.return_value.get_resource.return_value = {
        "content": """
---
kind: ConfigMap
apiVersion: v1
metadata:
  name: skupper-site
  labels:
    label1: value1

data:
  namespace: {{ resource.namespace.name }}
  variable: "{{ foo }}"
  edge: "{{ edge | default('false') }}"
"""
    }
    return gql_mock


@pytest.fixture
def skupper_sites(
    skupper_networks: list[SkupperNetworkV1], fake_get_resource: MagicMock
) -> list[SkupperSite]:
    return sorted(intg.compile_skupper_sites(skupper_networks))


@pytest.fixture
def fake_site_configmap() -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": intg.CONFIG_NAME,
            "labels": {
                "foo": "bar",
            },
        },
        "data": {
            "edge": "false",
            "name": "name",
        },
    }


@pytest.fixture
def oc(mocker: MockerFixture, fake_site_configmap: dict[str, Any]) -> OCNative:
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.get_items.return_value = [fake_site_configmap]
    return oc


@pytest.fixture
def oc_map(mocker: MockerFixture, oc: OCNative) -> OCMap:
    oc_map = mocker.patch("reconcile.utils.oc_map.OCMap", autospec=True)
    oc_map.get_cluster.return_value = oc
    return oc_map
