# ruff: file-ignore[mixed-case-variable-in-class-scope]
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from pydantic.dataclasses import dataclass

import reconcile.openshift_base as ob
from reconcile.gql_definitions.closedbox_endpoint_monitoring.endpoints import query
from reconcile.utils import gql
from reconcile.utils.defer import defer

if TYPE_CHECKING:
    from collections.abc import Callable

    from reconcile.utils.openshift_resource import (
        OpenshiftResource,
        ResourceInventory,
    )

LOG = logging.getLogger(__name__)


class ClosedBoxReconcilerError(Exception):
    pass


@dataclass(frozen=True, eq=True)
class BlackboxMonitoringProvider:
    module: str
    # the namespace of a blackbox-exporter provider is mapped as dict
    # since its only use with ob.fetch_current_state is as a dict
    namespace: dict[str, Any] = field(compare=False, hash=False)
    exporterUrl: str


@dataclass(frozen=True, eq=True)
class PrometheusMetricsImporterMonitoringProvider:
    # the exporter namespace is mapped as dict
    # since its only use with ob.fetch_current_state is as a dict
    namespace: dict[str, Any] = field(compare=False, hash=False)
    exporterUrl: str
    targetFilterLabel: str


@dataclass(frozen=True, eq=True)
class EndpointMonitoringProvider:
    name: str
    provider: str
    description: str
    timeout: str | None = None
    checkInterval: str | None = None
    blackboxExporter: BlackboxMonitoringProvider | None = None
    signalFx: PrometheusMetricsImporterMonitoringProvider | None = None
    prometheusMetricsImporter: PrometheusMetricsImporterMonitoringProvider | None = None
    metricLabels: str | None = None

    @property
    def namespace(self) -> dict[str, Any] | None:
        if self.blackboxExporter:
            return self.blackboxExporter.namespace

        if self.prometheusMetricsImporter:
            return self.prometheusMetricsImporter.namespace

        if self.signalFx:
            return self.signalFx.namespace

        return None

    @property
    def metric_labels(self) -> dict[str, Any]:
        return json.loads(self.metricLabels) if self.metricLabels else {}


@dataclass
class Endpoint:
    name: str
    description: str
    url: str

    @dataclass
    class Monitoring:
        provider: EndpointMonitoringProvider

    monitoring: list[Monitoring]


def parse_prober_url(url: str) -> dict[str, str]:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError(
            f"the prober URL needs to be an http:// or https:// one but is {url}"
        )
    data = {"url": parsed_url.netloc, "scheme": parsed_url.scheme}
    if parsed_url.path:
        data["path"] = parsed_url.path
    return data


def get_endpoints(
    provider: str | frozenset[str],
) -> dict[EndpointMonitoringProvider, list[Endpoint]]:
    providers = frozenset({provider}) if isinstance(provider, str) else provider
    endpoints: dict[EndpointMonitoringProvider, list[Endpoint]] = defaultdict(list)
    for app in query(query_func=gql.get_api().query).apps or []:
        for endpoint in app.end_points or []:
            monitoring = []
            for monitor in endpoint.monitoring or []:
                if monitor.provider is None:
                    raise ValueError(f"Missing monitoring provider for {endpoint.name}")
                if monitor.provider.provider in providers:
                    monitoring.append(
                        Endpoint.Monitoring(
                            provider=EndpointMonitoringProvider(
                                **monitor.provider.model_dump(
                                    by_alias=True, round_trip=True
                                )
                            )
                        )
                    )
            ep = Endpoint(
                name=endpoint.name,
                description=endpoint.description,
                url=endpoint.url,
                monitoring=monitoring,
            )
            for mon in monitoring:
                endpoints[mon.provider].append(ep)
    return endpoints


def fill_desired_state(
    namespace: dict[str, Any],
    probe: OpenshiftResource,
    ri: ResourceInventory,
) -> None:
    ri.add_desired(
        cluster=namespace["cluster"]["name"],
        namespace=namespace["name"],
        resource_type=probe.kind_and_group,
        name=probe.name,
        value=probe,
    )


@defer
def run_for_provider(
    provider: str | frozenset[str],
    probe_builder: Callable[
        [EndpointMonitoringProvider, list[Endpoint]],
        list[tuple[OpenshiftResource, dict[str, Any]]],
    ],
    integration: str,
    integration_version: str,
    dry_run: bool,
    thread_pool_size: int,
    internal: bool,
    managed_types: list[str] | None = None,
    defer: Callable | None = None,
) -> None:
    desired_endpoints = get_endpoints(provider)

    # Build all probes upfront to collect their target namespaces
    provider_probes = {
        ep_mon_provider: probe_builder(ep_mon_provider, endpoints)
        for ep_mon_provider, endpoints in desired_endpoints.items()
    }

    # Deduplicate target namespaces by (cluster, namespace-name)
    ns_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for probes in provider_probes.values():
        for _, ns in probes:
            if ns:
                ns_by_key[ns["cluster"]["name"], ns["name"]] = ns

    namespaces = list(ns_by_key.values())

    if namespaces:
        ri, oc_map = ob.fetch_current_state(
            namespaces,
            thread_pool_size=thread_pool_size,
            internal=internal,
            integration=integration,
            integration_version=integration_version,
            override_managed_types=managed_types or ["Probe.monitoring.rhobs"],
        )
        if defer:
            defer(oc_map.cleanup)

        for probes in provider_probes.values():
            for probe, ns in probes:
                if ns:
                    fill_desired_state(ns, probe, ri)
        ob.publish_metrics(ri, integration)
        ob.realize_data(dry_run, oc_map, ri, thread_pool_size, recycle_pods=False)

        if ri.has_error_registered():
            raise ClosedBoxReconcilerError("ResourceInventory has registered errors")
