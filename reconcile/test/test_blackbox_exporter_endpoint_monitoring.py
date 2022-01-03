from unittest.mock import ANY
import pytest

from reconcile.blackbox_exporter_endpoint_monitoring import (
    queries, get_endpoints, build_probe, parse_prober_url, fill_desired_state)
from reconcile.utils.openshift_resource import ResourceInventory
from .fixtures import Fixtures


fxt = Fixtures('blackbox_exporter_endpoint_monitoring')


def get_endpoint_fixtures(path: str) -> dict:
    return fxt.get_anymarkup(path)["appInterface"]["apps"]


def test_invalid_endpoints(mocker):
    query = mocker.patch.object(queries, 'get_service_monitoring_endpoints')
    query.return_value = get_endpoint_fixtures("test_invalid_endpoints.yaml")

    endpoints = get_endpoints()
    assert len(endpoints) == 0


def test_endpoint_loading(mocker):
    ep_query = mocker.patch.object(queries, 'get_service_monitoring_endpoints')
    ep_query.return_value = get_endpoint_fixtures("test_endpoint.yaml")

    endpoints = get_endpoints()
    assert len(endpoints) == 1

    provider = list(endpoints.keys())[0]
    ep = endpoints.get(provider)[0]

    assert ep.monitoring.provider.provider == "blackbox-exporter"


def test_parse_prober_url():
    assert parse_prober_url("http://host:1234/path") == {
        "url": "host:1234",
        "scheme": "http",
        "path": "/path"
    }

    assert parse_prober_url("http://host") == {
        "url": "host",
        "scheme": "http"
    }


def test_invalid_prober_url():
    # scheme missing
    with pytest.raises(ValueError):
        parse_prober_url("host:1234/path")


def test_probe_building(mocker):
    ep_query = mocker.patch.object(queries, 'get_service_monitoring_endpoints')
    ep_query.return_value = get_endpoint_fixtures("test_probe_building.yaml")

    endpoints = get_endpoints()
    assert len(endpoints) == 1

    provider = list(endpoints.keys())[0]
    probe_resource = build_probe(provider, endpoints.get(provider))
    assert probe_resource is not None

    # verify prober url decomposition
    spec = probe_resource.body.get("spec")
    assert spec.get("prober") == {
        "url": "exporterhost:9115",
        "scheme": "http",
        "path": "/probe"
    }

    # verify labels
    labels = spec["targets"]["staticConfig"]["labels"]
    assert labels.get("environment") == "staging"

    assert "https://test1.url" in spec["targets"]["staticConfig"]["static"]
    assert "https://test2.url" in spec["targets"]["staticConfig"]["static"]


def test_filling_desired_state(mocker):
    ep_query = mocker.patch.object(queries, 'get_service_monitoring_endpoints')
    ep_query.return_value = get_endpoint_fixtures("test_endpoint.yaml")
    add_desired_mock = mocker.patch.object(ResourceInventory, 'add_desired')

    endpoints = get_endpoints()
    provider = list(endpoints.keys())[0]
    fill_desired_state(provider, endpoints[provider], ResourceInventory())

    assert add_desired_mock.call_count == 1
    add_desired_mock.assert_called_with(
        cluster="app-sre-stage-01",
        namespace="openshift-customer-monitoring",
        resource_type="Probe",
        name="endpoint-monitoring-blackbox-exporter-http-2xx",
        value=ANY
    )
