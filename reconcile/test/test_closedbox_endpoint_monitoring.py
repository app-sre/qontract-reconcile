from unittest.mock import ANY

import pytest

from reconcile.blackbox_exporter_endpoint_monitoring import (
    PROVIDER as BLACKBOX_EXPORTER_PROVIDER,
)
from reconcile.blackbox_exporter_endpoint_monitoring import (
    build_probe as blackbox_exporter_probe_builder,
)
from reconcile.closedbox_endpoint_monitoring_base import (
    fill_desired_state,
    get_endpoints,
    parse_prober_url,
    queries,
)
from reconcile.signalfx_endpoint_monitoring import PROVIDER as SIGNALFX_PROVIDER
from reconcile.signalfx_endpoint_monitoring import build_probe as signalfx_probe_builder
from reconcile.utils.openshift_resource import ResourceInventory

from .fixtures import Fixtures

fxt = Fixtures("closedbox_exporter_endpoint_monitoring")


def get_endpoint_fixtures(path: str) -> dict:
    return fxt.get_anymarkup(path)["appInterface"]["apps"]


def test_invalid_endpoints(mocker):
    query = mocker.patch.object(queries, "get_service_monitoring_endpoints")
    query.return_value = get_endpoint_fixtures("test_invalid_endpoints.yaml")

    endpoints = get_endpoints(BLACKBOX_EXPORTER_PROVIDER)
    assert len(endpoints) == 0


def test_blackbox_exporter_endpoint_loading(mocker):
    ep_query = mocker.patch.object(queries, "get_service_monitoring_endpoints")
    ep_query.return_value = get_endpoint_fixtures("test_endpoint.yaml")

    endpoints = get_endpoints(BLACKBOX_EXPORTER_PROVIDER)
    assert endpoints is not None
    assert len(endpoints) == 1

    provider = next(iter(endpoints.keys()))
    assert provider.provider == BLACKBOX_EXPORTER_PROVIDER
    provider_endpoints = endpoints.get(provider)
    assert provider_endpoints is not None
    assert len(provider_endpoints) == 1
    assert len(provider_endpoints[0].monitoring) == 1


def test_parse_prober_url():
    assert parse_prober_url("http://host:1234/path") == {
        "url": "host:1234",
        "scheme": "http",
        "path": "/path",
    }

    assert parse_prober_url("http://host") == {"url": "host", "scheme": "http"}


def test_invalid_prober_url():
    # scheme missing
    with pytest.raises(ValueError):
        parse_prober_url("host:1234/path")


def test_blackbox_exporter_probe_building(mocker):
    ep_query = mocker.patch.object(queries, "get_service_monitoring_endpoints")
    ep_query.return_value = get_endpoint_fixtures("test_blackbox_probe_building.yaml")

    endpoints = get_endpoints(BLACKBOX_EXPORTER_PROVIDER)
    assert len(endpoints) == 1

    provider = next(iter(endpoints.keys()))
    provider_endpoints = endpoints.get(provider)
    assert provider_endpoints is not None
    probe_resource = blackbox_exporter_probe_builder(provider, provider_endpoints)
    assert probe_resource is not None

    # verify prober url decomposition
    spec = probe_resource.body.get("spec")
    assert spec.get("prober") == {
        "url": "exporterhost:9115",
        "scheme": "http",
        "path": "/probe",
    }

    # verify labels
    labels = spec["targets"]["staticConfig"]["labels"]
    assert labels.get("environment") == "staging"

    # verify timeout and interval
    assert spec["scrapeTimeout"] == provider.timeout
    assert spec["interval"] == provider.checkInterval

    # verify targets
    assert "https://test1.url" in spec["targets"]["staticConfig"]["static"]
    assert "https://test2.url" in spec["targets"]["staticConfig"]["static"]


def test_signalfx_probe_building(mocker):
    ep_query = mocker.patch.object(queries, "get_service_monitoring_endpoints")
    ep_query.return_value = get_endpoint_fixtures("test_signalfx_probe_building.yaml")

    endpoints = get_endpoints(SIGNALFX_PROVIDER)
    assert len(endpoints) == 1

    provider = next(iter(endpoints.keys()))
    provider_endpoints = endpoints.get(provider)
    assert provider_endpoints is not None
    probe_resource = signalfx_probe_builder(provider, provider_endpoints)
    assert probe_resource is not None

    # verify prober url decomposition
    spec = probe_resource.body.get("spec")
    assert spec.get("prober") == {
        "url": "signalfxexporter:9091",
        "scheme": "http",
        "path": "/metrics/probe",
    }

    # verify labels
    labels = spec["targets"]["staticConfig"]["labels"]
    assert labels.get("environment") == "staging"

    # verify timeout and interval
    assert spec["scrapeTimeout"] == provider.timeout
    assert spec["interval"] == provider.checkInterval

    # verify targets
    assert "test_1" in spec["targets"]["staticConfig"]["static"]
    assert "test_2" in spec["targets"]["staticConfig"]["static"]

    # verify relabeling
    assert {
        "action": "replace",
        "regex": "^test_1$",
        "replacement": "https://test1.url",
        "sourceLabels": ["instance"],
        "targetLabel": "instance",
    } in spec["targets"]["staticConfig"]["relabelingConfigs"]
    assert {
        "action": "replace",
        "regex": "^test_2$",
        "replacement": "https://test2.url",
        "sourceLabels": ["instance"],
        "targetLabel": "instance",
    } in spec["targets"]["staticConfig"]["relabelingConfigs"]


def test_blackbox_exporter_filling_desired_state(mocker):
    ep_query = mocker.patch.object(queries, "get_service_monitoring_endpoints")
    ep_query.return_value = get_endpoint_fixtures("test_endpoint.yaml")
    add_desired_mock = mocker.patch.object(ResourceInventory, "add_desired")

    endpoints = get_endpoints(BLACKBOX_EXPORTER_PROVIDER)
    provider = next(iter(endpoints.keys()))
    probe = blackbox_exporter_probe_builder(provider, endpoints[provider])
    assert probe is not None
    fill_desired_state(provider, probe, ResourceInventory())

    assert add_desired_mock.call_count == 1
    add_desired_mock.assert_called_with(
        cluster="app-sre-stage-01",
        namespace="openshift-customer-monitoring",
        resource_type="Probe",
        name="blackbox-exporter-http-2xx",
        value=ANY,
    )


def test_signalfx_filling_desired_state(mocker):
    ep_query = mocker.patch.object(queries, "get_service_monitoring_endpoints")
    ep_query.return_value = get_endpoint_fixtures("test_endpoint.yaml")
    add_desired_mock = mocker.patch.object(ResourceInventory, "add_desired")

    endpoints = get_endpoints(SIGNALFX_PROVIDER)
    provider = next(iter(endpoints.keys()))
    probe = signalfx_probe_builder(provider, endpoints[provider])
    assert probe is not None
    fill_desired_state(provider, probe, ResourceInventory())

    assert add_desired_mock.call_count == 1
    add_desired_mock.assert_called_with(
        cluster="app-sre-stage-01",
        namespace="openshift-customer-monitoring",
        resource_type="Probe",
        name="signalfx-exporter-http-2xx",
        value=ANY,
    )


def test_loading_multiple_providers_per_endpoint(mocker):
    ep_query = mocker.patch.object(queries, "get_service_monitoring_endpoints")
    ep_query.return_value = get_endpoint_fixtures(
        "test_multiple_providers_per_endpoint.yaml"
    )
    endpoints = get_endpoints(BLACKBOX_EXPORTER_PROVIDER)

    assert len(endpoints) == 2

    for provider, eps in endpoints.items():
        assert provider.provider == BLACKBOX_EXPORTER_PROVIDER
        assert len(eps) == 2
