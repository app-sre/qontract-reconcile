from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any
from unittest.mock import ANY

import pytest

from reconcile import closedbox_endpoint_monitoring_base as closedbox
from reconcile import signalfx_endpoint_monitoring as metrics_importer
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
)
from reconcile.signalfx_endpoint_monitoring import PROVIDER as SIGNALFX_PROVIDER
from reconcile.signalfx_endpoint_monitoring import build_probe as signalfx_probe_builder
from reconcile.utils.openshift_resource import ResourceInventory

from .fixtures import Fixtures

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

fxt = Fixtures("closedbox_exporter_endpoint_monitoring")


def get_endpoint_fixtures(path: str) -> dict[str, Any]:
    return fxt.get_anymarkup(path)["appInterface"]


def get_importer_fixtures(provider_kind: str) -> dict[str, Any]:
    data = get_endpoint_fixtures("test_signalfx_probe_building.yaml")
    if provider_kind == "prometheus-metrics-importer":
        for app in data["apps"]:
            for endpoint in app["endPoints"]:
                for monitor in endpoint["monitoring"]:
                    provider = monitor["provider"]
                    provider["provider"] = provider_kind
                    provider["prometheusMetricsImporter"] = provider.pop("signalFx")
    return data


@pytest.fixture
def importer_query(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(
        "reconcile.closedbox_endpoint_monitoring_base.gql.get_api"
    ).return_value.query


def test_invalid_endpoints(mocker: MockerFixture) -> None:
    query = mocker.patch(
        "reconcile.closedbox_endpoint_monitoring_base.gql.get_api"
    ).return_value.query
    query.return_value = get_endpoint_fixtures("test_invalid_endpoints.yaml")

    endpoints = get_endpoints(BLACKBOX_EXPORTER_PROVIDER)
    assert len(endpoints) == 0


def test_blackbox_exporter_endpoint_loading(mocker: MockerFixture) -> None:
    ep_query = mocker.patch(
        "reconcile.closedbox_endpoint_monitoring_base.gql.get_api"
    ).return_value.query
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


def test_parse_prober_url() -> None:
    assert parse_prober_url("http://host:1234/path") == {
        "url": "host:1234",
        "scheme": "http",
        "path": "/path",
    }

    assert parse_prober_url("http://host") == {"url": "host", "scheme": "http"}


def test_invalid_prober_url() -> None:
    # scheme missing
    with pytest.raises(ValueError):
        parse_prober_url("host:1234/path")


def test_blackbox_exporter_probe_building(mocker: MockerFixture) -> None:
    ep_query = mocker.patch(
        "reconcile.closedbox_endpoint_monitoring_base.gql.get_api"
    ).return_value.query
    ep_query.return_value = get_endpoint_fixtures("test_blackbox_probe_building.yaml")

    endpoints = get_endpoints(BLACKBOX_EXPORTER_PROVIDER)
    assert len(endpoints) == 1

    provider = next(iter(endpoints.keys()))
    provider_endpoints = endpoints.get(provider)
    assert provider_endpoints is not None
    probes = blackbox_exporter_probe_builder(provider, provider_endpoints)
    assert len(probes) == 1

    # verify COO rhobs probe
    probe_resource, coo_namespace = probes[0]
    assert probe_resource.body["apiVersion"] == "monitoring.rhobs/v1"
    assert coo_namespace["name"] == "app-sre-observability-per-cluster"

    # verify prober url decomposition
    spec = probe_resource.body.get("spec", {})
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


@pytest.mark.parametrize("provider_kind", ["signalfx", "prometheus-metrics-importer"])
def test_metrics_importer_probe_building(
    mocker: MockerFixture, provider_kind: str
) -> None:
    ep_query = mocker.patch(
        "reconcile.closedbox_endpoint_monitoring_base.gql.get_api"
    ).return_value.query
    ep_query.return_value = get_importer_fixtures(provider_kind)

    endpoints = get_endpoints(metrics_importer.PROVIDERS)
    assert len(endpoints) == 1

    provider = next(iter(endpoints.keys()))
    provider_endpoints = endpoints.get(provider)
    assert provider_endpoints is not None
    probes = signalfx_probe_builder(provider, provider_endpoints)
    assert len(probes) == 1

    # verify COO rhobs probe
    probe_resource, coo_namespace = probes[0]
    assert probe_resource.body["apiVersion"] == "monitoring.rhobs/v1"
    assert coo_namespace["name"] == "app-sre-observability-per-cluster"

    # verify prober url decomposition
    spec = probe_resource.body.get("spec", {})
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


def test_blackbox_exporter_filling_desired_state(mocker: MockerFixture) -> None:
    ep_query = mocker.patch(
        "reconcile.closedbox_endpoint_monitoring_base.gql.get_api"
    ).return_value.query
    ep_query.return_value = get_endpoint_fixtures("test_endpoint.yaml")
    add_desired_mock = mocker.patch.object(ResourceInventory, "add_desired")

    endpoints = get_endpoints(BLACKBOX_EXPORTER_PROVIDER)
    provider = next(iter(endpoints.keys()))
    probes = blackbox_exporter_probe_builder(provider, endpoints[provider])
    assert len(probes) == 1
    probe, ns = probes[0]
    fill_desired_state(ns, probe, ResourceInventory())

    assert add_desired_mock.call_count == 1
    add_desired_mock.assert_called_with(
        cluster="app-sre-stage-01",
        namespace="app-sre-observability-per-cluster",
        resource_type="Probe.monitoring.rhobs",
        name="blackbox-exporter-http-2xx",
        value=ANY,
    )


def test_signalfx_filling_desired_state(mocker: MockerFixture) -> None:
    ep_query = mocker.patch(
        "reconcile.closedbox_endpoint_monitoring_base.gql.get_api"
    ).return_value.query
    ep_query.return_value = get_endpoint_fixtures("test_endpoint.yaml")
    add_desired_mock = mocker.patch.object(ResourceInventory, "add_desired")

    endpoints = get_endpoints(SIGNALFX_PROVIDER)
    provider = next(iter(endpoints.keys()))
    probes = signalfx_probe_builder(provider, endpoints[provider])
    assert len(probes) == 1
    probe, ns = probes[0]
    fill_desired_state(ns, probe, ResourceInventory())

    assert add_desired_mock.call_count == 1
    add_desired_mock.assert_called_with(
        cluster="app-sre-stage-01",
        namespace="app-sre-observability-per-cluster",
        resource_type="Probe.monitoring.rhobs",
        name="signalfx-exporter-http-2xx",
        value=ANY,
    )


def test_loading_multiple_providers_per_endpoint(mocker: MockerFixture) -> None:
    ep_query = mocker.patch(
        "reconcile.closedbox_endpoint_monitoring_base.gql.get_api"
    ).return_value.query
    ep_query.return_value = get_endpoint_fixtures(
        "test_multiple_providers_per_endpoint.yaml"
    )
    endpoints = get_endpoints(BLACKBOX_EXPORTER_PROVIDER)

    assert len(endpoints) == 2

    for provider, eps in endpoints.items():
        assert provider.provider == BLACKBOX_EXPORTER_PROVIDER
        assert len(eps) == 2


@pytest.mark.parametrize("provider_kind", ["signalfx", "prometheus-metrics-importer"])
def test_provider_filter_does_not_mutate_response(
    importer_query: MagicMock, provider_kind: str
) -> None:
    response = get_importer_fixtures(provider_kind)
    original = deepcopy(response)
    importer_query.return_value = response

    assert get_endpoints(BLACKBOX_EXPORTER_PROVIDER) == {}
    assert len(get_endpoints(metrics_importer.PROVIDERS)) == 1
    assert response == original


def test_provider_migration_preserves_probe(importer_query: MagicMock) -> None:
    probes = []
    for provider_kind in ("signalfx", "prometheus-metrics-importer"):
        importer_query.return_value = get_importer_fixtures(provider_kind)
        endpoints = get_endpoints(metrics_importer.PROVIDERS)
        provider, targets = next(iter(endpoints.items()))
        probes.append(signalfx_probe_builder(provider, targets)[0])

    (legacy_probe, legacy_namespace), (generic_probe, generic_namespace) = probes
    assert legacy_probe.body == generic_probe.body
    assert legacy_namespace == generic_namespace
    assert (
        legacy_probe.integration
        == generic_probe.integration
        == ("signalfx-prometheus-endpoint-monitoring")
    )
    assert legacy_probe.integration_version == generic_probe.integration_version
    assert legacy_probe.sha256sum() == generic_probe.sha256sum()
    # A migrated Probe still recognizes the existing resource's ownership.
    generic_probe.body = legacy_probe.annotate().body
    assert generic_probe.has_qontract_annotations()


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize(
    "configuration", ["signalfx", "prometheus-metrics-importer", "mixed"]
)
def test_metrics_importer_reconciles_all_providers_together(
    mocker: MockerFixture,
    importer_query: MagicMock,
    dry_run: bool,
    configuration: str,
) -> None:
    legacy = get_importer_fixtures("signalfx")
    generic = get_importer_fixtures("prometheus-metrics-importer")
    expected_names = {"signalfx-exporter-http-2xx"}
    if configuration == "mixed":
        for app in generic["apps"]:
            app["endPoints"][0]["monitoring"][0]["provider"]["name"] = (
                "metrics-importer"
            )
        response = {"apps": legacy["apps"] + generic["apps"]}
        expected_names.add("metrics-importer")
    else:
        response = legacy if configuration == "signalfx" else generic
    # The unrelated blackbox provider must not enter this integration's inventory.
    response["apps"] += get_endpoint_fixtures("test_blackbox_probe_building.yaml")[
        "apps"
    ]
    importer_query.return_value = response
    ri = ResourceInventory()
    ri.initialize_resource_type(
        "app-sre-stage-01",
        "app-sre-observability-per-cluster",
        "Probe.monitoring.rhobs",
    )
    oc_map = mocker.Mock()
    fetch = mocker.patch.object(
        closedbox.ob, "fetch_current_state", return_value=(ri, oc_map)
    )
    publish = mocker.patch.object(closedbox.ob, "publish_metrics")
    realize = mocker.patch.object(closedbox.ob, "realize_data")

    metrics_importer.run(dry_run=dry_run, thread_pool_size=2, internal=False)

    importer_query.assert_called_once()
    fetch.assert_called_once()
    namespaces = fetch.call_args.args[0]
    assert len(namespaces) == 1
    assert namespaces[0]["name"] == "app-sre-observability-per-cluster"
    assert (
        fetch.call_args.kwargs["integration"]
        == "signalfx-prometheus-endpoint-monitoring"
    )
    assert fetch.call_args.kwargs["override_managed_types"] == [
        "Probe.monitoring.rhobs"
    ]
    desired = ri.get_desired_by_type(
        "app-sre-stage-01",
        "app-sre-observability-per-cluster",
        "Probe.monitoring.rhobs",
    )
    assert desired is not None
    assert set(desired) == expected_names
    for name, probe in desired.items():
        assert probe.body["spec"]["jobName"] == name
        assert probe.body["spec"]["targets"]["staticConfig"]["static"] == [
            "test_1",
            "test_2",
        ]
    publish.assert_called_once_with(ri, "signalfx-prometheus-endpoint-monitoring")
    realize.assert_called_once_with(dry_run, oc_map, ri, 2, recycle_pods=False)
    oc_map.cleanup.assert_called_once()


@pytest.mark.parametrize(
    "provider_kind,settings_key",
    [
        ("signalfx", "signalFx"),
        ("prometheus-metrics-importer", "prometheusMetricsImporter"),
    ],
)
def test_metrics_importer_missing_settings_fails_before_fetch(
    mocker: MockerFixture,
    importer_query: MagicMock,
    provider_kind: str,
    settings_key: str,
) -> None:
    data = get_importer_fixtures(provider_kind)
    del data["apps"][0]["endPoints"][0]["monitoring"][0]["provider"][settings_key]
    importer_query.return_value = data
    fetch = mocker.patch.object(closedbox.ob, "fetch_current_state")
    realize = mocker.patch.object(closedbox.ob, "realize_data")

    with pytest.raises(SystemExit, match="1"):
        metrics_importer.run(dry_run=True, thread_pool_size=2, internal=False)

    fetch.assert_not_called()
    realize.assert_not_called()


def test_missing_monitoring_provider_fails_before_fetch(
    mocker: MockerFixture, importer_query: MagicMock
) -> None:
    data = get_importer_fixtures("prometheus-metrics-importer")
    data["apps"][0]["endPoints"][0]["monitoring"][0]["provider"] = None
    importer_query.return_value = data
    fetch = mocker.patch.object(closedbox.ob, "fetch_current_state")

    with pytest.raises(SystemExit, match="1"):
        metrics_importer.run(dry_run=True, thread_pool_size=2, internal=False)

    fetch.assert_not_called()


@pytest.mark.parametrize("apps", [None, []])
def test_no_apps_skips_reconciliation(
    mocker: MockerFixture, importer_query: MagicMock, apps: list | None
) -> None:
    importer_query.return_value = {"apps": apps}
    fetch = mocker.patch.object(closedbox.ob, "fetch_current_state")

    metrics_importer.run(dry_run=True, thread_pool_size=2, internal=False)

    fetch.assert_not_called()


@pytest.mark.parametrize(
    "provider_kind,settings_key",
    [
        ("signalfx", "signalFx"),
        ("prometheus-metrics-importer", "prometheusMetricsImporter"),
    ],
)
def test_metrics_importer_defaults_and_root_exporter_url(
    importer_query: MagicMock, provider_kind: str, settings_key: str
) -> None:
    data = get_importer_fixtures(provider_kind)
    for app in data["apps"]:
        provider = app["endPoints"][0]["monitoring"][0]["provider"]
        provider["timeout"] = None
        provider["checkInterval"] = None
        provider["metricLabels"] = None
        provider[settings_key]["exporterUrl"] = "http://exporter:9091"
    importer_query.return_value = data
    provider, endpoints = next(iter(get_endpoints(metrics_importer.PROVIDERS).items()))

    probe, _ = signalfx_probe_builder(provider, endpoints)[0]

    assert probe.body["spec"]["prober"]["path"] == "/probe"
    assert probe.body["spec"]["interval"] == "10s"
    assert "scrapeTimeout" not in probe.body["spec"]
    assert probe.body["spec"]["targets"]["staticConfig"]["labels"] == {}
