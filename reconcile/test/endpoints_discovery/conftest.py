from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.endpoints_discovery.integration import (
    EndpointsDiscoveryIntegration,
    EndpointsDiscoveryIntegrationParams,
)
from reconcile.gql_definitions.endpoints_discovery.namespaces import NamespaceV1
from reconcile.test.fixtures import Fixtures
from reconcile.utils.oc import OCNative
from reconcile.utils.oc_map import OCMap


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("endpoints_discovery")


@pytest.fixture
def intg() -> EndpointsDiscoveryIntegration:
    return EndpointsDiscoveryIntegration(EndpointsDiscoveryIntegrationParams())


@pytest.fixture
def raw_fixture_data(fx: Fixtures) -> dict[str, Any]:
    return fx.get_anymarkup("namespaces.yml")


@pytest.fixture
def query_func(
    data_factory: Callable[[type[NamespaceV1], Mapping[str, Any]], Mapping[str, Any]],
    raw_fixture_data: dict[str, Any],
) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "namespaces": [
                data_factory(NamespaceV1, item)
                for item in raw_fixture_data["namespaces"]
            ]
        }

    return q


@pytest.fixture
def namespaces(
    intg: EndpointsDiscoveryIntegration, query_func: Callable
) -> list[NamespaceV1]:
    return intg.get_namespaces(query_func)


@pytest.fixture
def fake_route() -> dict[str, Any]:
    return {
        "metadata": {
            "name": "fake-route",
        },
        "spec": {
            "host": "https://fake-route.com",
        },
    }


@pytest.fixture
def oc(mocker: MockerFixture, fake_route: dict[str, Any]) -> OCNative:
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.project_exists.return_value = True
    # return 2 routes with the same hostname. this should be filtered out by get_routes
    fake_route2 = deepcopy(fake_route)
    fake_route2["metadata"]["name"] = "zzz-fake-route"
    oc.get_items.return_value = [fake_route, fake_route2]
    return oc


@pytest.fixture
def oc_map(mocker: MockerFixture, oc: OCNative) -> OCMap:
    oc_map = mocker.patch("reconcile.utils.oc_map.OCMap", autospec=True)
    oc_map.get_cluster.return_value = oc
    return oc_map
