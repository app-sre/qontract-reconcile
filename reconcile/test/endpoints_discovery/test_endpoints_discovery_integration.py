from collections.abc import Callable, Sequence
from textwrap import dedent

from pytest_mock import MockerFixture

from reconcile.endpoints_discovery.integration import (
    EndpointsDiscoveryIntegration,
    Route,
    compile_endpoint_name,
    endpoint_prefix,
    render_template,
)
from reconcile.endpoints_discovery.merge_request_manager import App, Endpoint
from reconcile.gql_definitions.endpoints_discovery.namespaces import (
    AppEndPointsV1,
    NamespaceV1,
)
from reconcile.utils.oc_map import OCMap

TEMPLATE = """
---
name: {{ endpoint_name }}
url: {{ route.url }}
"""


def test_endpoints_discovery_integration_route() -> None:
    r = Route(name="with-tls", host="example.com", tls=True)
    assert r.tls is True
    assert r.url == "example.com:443"
    r = Route(name="no-tls", host="example.com", tls=False)
    assert r.tls is False
    assert r.url == "example.com:80"


def test_endpoints_discovery_integration_endpoint_prefix(
    namespaces: Sequence[NamespaceV1],
) -> None:
    ns = namespaces[0]
    assert endpoint_prefix(namespace=ns).endswith(ns.name + "/")


def test_endpoints_discovery_integration_compile_endpoint_name() -> None:
    r = Route(name="with-tls", host="example.com", tls=True)
    assert compile_endpoint_name("prefix-", r) == "prefix-with-tls"


def test_endpoints_discovery_integration_render_template() -> None:
    r = Route(name="no-tls", host="example.com", tls=False)
    # template must be a valid YAML
    tmpl = dedent("""
    # test access variables
    ---
    name: {{ endpoint_name }}
    monitoring:
      url: {{ route.url }}
    """)
    assert render_template(tmpl, "endpoint-name-foobar", r) == {
        "name": "endpoint-name-foobar",
        "monitoring": {"url": "example.com:80"},
    }


def test_endpoints_discovery_integration_get_desired_state_shard_config(
    intg: EndpointsDiscoveryIntegration,
) -> None:
    assert intg.get_desired_state_shard_config() is None  # type: ignore


def test_endpoints_discovery_integration_get_namespaces(
    query_func: Callable,
    intg: EndpointsDiscoveryIntegration,
) -> None:
    namespaces = intg.get_namespaces(query_func)
    assert len(namespaces) == 2
    assert namespaces[0].name == "app-1-ns-1"
    assert namespaces[0].app.end_points is None
    assert namespaces[1].name == "app-2-ns-1"
    assert len(namespaces[1].app.end_points) == 1  # type: ignore


def test_endpoints_discovery_integration_get_routes(
    oc_map: OCMap,
    intg: EndpointsDiscoveryIntegration,
    namespaces: Sequence[NamespaceV1],
) -> None:
    routes = intg.get_routes(oc_map, namespaces[0])
    # see fake_route fixture!
    assert len(routes) == 1
    assert isinstance(routes[0], Route)
    assert routes[0].name == "fake-route"


def test_endpoints_discovery_integration_get_endpoint_changes_no_routes_no_endpoints(
    intg: EndpointsDiscoveryIntegration,
) -> None:
    assert intg.get_endpoint_changes(
        app="app",
        endpoint_prefix="prefix-",
        endpoint_template=TEMPLATE,
        endpoints=[],
        routes=[],
    ) == (
        [],
        [],
        [],
    )


def test_endpoints_discovery_integration_get_endpoint_changes(
    intg: EndpointsDiscoveryIntegration,
) -> None:
    endpoints = [
        # must be changed
        AppEndPointsV1(name="prefix-change", url="change.com:443"),
        # must be deleted
        AppEndPointsV1(name="prefix-delete", url="whatever.com"),
        # up2date
        AppEndPointsV1(name="prefix-up2date", url="up2date.com:80"),
        # must be ignored
        AppEndPointsV1(name="manual-endpoint", url="https://manual-endpoint.com"),
        AppEndPointsV1(name="manual-endpoint-new", url="https://new.com"),
    ]
    routes = [
        Route(name="change", host="change.com", tls=False),
        Route(name="new", host="new.com", tls=False),
        Route(name="up2date", host="up2date.com", tls=False),
    ]
    endpoints_to_add, endpoints_to_change, endpoints_to_delete = (
        intg.get_endpoint_changes(
            app="app",
            endpoint_prefix="prefix-",
            endpoint_template=TEMPLATE,
            endpoints=endpoints,
            routes=routes,
        )
    )
    assert endpoints_to_add == [
        Endpoint(name="prefix-new", data={"name": "prefix-new", "url": "new.com:80"})
    ]
    assert endpoints_to_change == [
        Endpoint(
            name="prefix-change", data={"name": "prefix-change", "url": "change.com:80"}
        )
    ]
    assert endpoints_to_delete == [Endpoint(name="prefix-delete", data={})]


def test_endpoints_discovery_integration_get_apps(
    oc_map: OCMap,
    intg: EndpointsDiscoveryIntegration,
    namespaces: Sequence[NamespaceV1],
) -> None:
    apps = intg.get_apps(oc_map, TEMPLATE, namespaces)
    assert apps == [
        App(
            name="app-1",
            path="/path/app-1.yml",
            endpoints_to_add=[
                Endpoint(
                    name="endpoints-discovery/cluster-1/app-1-ns-1/fake-route",
                    data={
                        "name": "endpoints-discovery/cluster-1/app-1-ns-1/fake-route",
                        "url": "https://fake-route.com:80",
                    },
                )
            ],
            endpoints_to_change=[],
            endpoints_to_delete=[],
        ),
        App(
            name="app-2",
            path="/path/app-2.yml",
            endpoints_to_add=[
                Endpoint(
                    name="endpoints-discovery/cluster-1/app-2-ns-1/fake-route",
                    data={
                        "name": "endpoints-discovery/cluster-1/app-2-ns-1/fake-route",
                        "url": "https://fake-route.com:80",
                    },
                )
            ],
            endpoints_to_change=[],
            endpoints_to_delete=[],
        ),
    ]


def test_endpoints_discovery_integration_runner(
    mocker: MockerFixture,
    oc_map: OCMap,
    namespaces: Sequence[NamespaceV1],
    intg: EndpointsDiscoveryIntegration,
) -> None:
    mrm_mock = mocker.patch(
        "reconcile.endpoints_discovery.integration.MergeRequestManager", autospec=True
    )
    apps = [
        App(
            name="app-2",
            path="/path/app-2.yml",
            endpoints_to_add=[
                Endpoint(
                    name="endpoints-discovery/cluster-1/app-2-ns-1/fake-route",
                    data={
                        "name": "endpoints-discovery/cluster-1/app-2-ns-1/fake-route",
                        "url": "https://fake-route.com:80",
                    },
                )
            ],
            endpoints_to_change=[],
            endpoints_to_delete=[],
        )
    ]
    intg.get_apps = mocker.MagicMock(return_value=apps)  # type: ignore
    intg.runner(oc_map, mrm_mock, TEMPLATE, namespaces)
    mrm_mock.create_merge_request.assert_called_once_with(apps)
