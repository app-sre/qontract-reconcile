from collections.abc import (
    Callable,
    MutableMapping,
)
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.skupper_network.skupper_networks import SkupperNetworkV1
from reconcile.skupper_network import integration as intg
from reconcile.skupper_network.models import SkupperSite
from reconcile.skupper_network.site_controller import CONFIG_NAME
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
def skupper_sites(skupper_networks: list[SkupperNetworkV1]) -> list[SkupperSite]:
    return sorted(intg.compile_skupper_sites(skupper_networks))


@pytest.fixture
def fake_site_configmap() -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": CONFIG_NAME,
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
