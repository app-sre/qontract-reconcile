import logging
import sys
from urllib.parse import urlparse
from typing import Any, Optional
import json
from dataclasses import field

from pydantic.dataclasses import dataclass

from reconcile import queries
from reconcile.utils.openshift_resource import (
    OpenshiftResource, ResourceInventory)
from reconcile.utils.defer import defer
from reconcile.utils.semver_helper import make_semver
import reconcile.openshift_base as ob

QONTRACT_INTEGRATION = "blackbox-exporter-endpoint-monitoring"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

LOG = logging.getLogger(__name__)


@dataclass(frozen=True, eq=True)
class BlackboxMonitoringProvider:

    module: str
    # the namespace of a blackbox-exporter provider is mapped as dict
    # since its only use with ob.fetch_current_state is as a dict
    namespace: dict[str, Any] = field(compare=False, hash=False)
    exporterUrl: str


@dataclass(frozen=True, eq=True)
class EndpointMonitoringProvider:

    name: str
    provider: str
    description: str
    timeout: Optional[str] = None
    checkInterval: Optional[str] = None
    blackboxExporter: Optional[BlackboxMonitoringProvider] = None
    metricLabels: Optional[str] = None

    @property
    def metric_labels(self):
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
    if parsed_url.scheme not in ["http", "https"]:
        raise ValueError(
            "the prober URL needs to be an http:// or https:// one "
            f"but is {url}"
        )
    data = {
        "url": parsed_url.netloc,
        "scheme": parsed_url.scheme
    }
    if parsed_url.path:
        data["path"] = parsed_url.path
    return data


def build_probe(provider: EndpointMonitoringProvider,
                endpoints: list[Endpoint]) -> Optional[OpenshiftResource]:
    blackbox_exporter = provider.blackboxExporter
    if blackbox_exporter:
        prober_url = parse_prober_url(blackbox_exporter.exporterUrl)
        body: dict[str, Any] = {
            "apiVersion": "monitoring.coreos.com/v1",
            "kind": "Probe",
            "metadata": {
                "name": provider.name,
                "namespace": blackbox_exporter.namespace.get("name"),
                "labels": {
                    "prometheus": "app-sre"
                }
            },
            "spec": {
                "jobName": provider.name,
                "interval": provider.checkInterval or "10s",
                "module": blackbox_exporter.module,
                "prober": prober_url,
                "targets": {
                    "staticConfig": {
                        "relabelingConfigs": [
                            {
                                "action": "labeldrop",
                                "regex": "namespace"
                            }
                        ],
                        "labels": provider.metric_labels,
                        "static": [
                            ep.url for ep in endpoints
                        ]
                    }
                }
            }
        }
        if provider.timeout:
            body["spec"]["scrapeTimeout"] = provider.timeout
        return OpenshiftResource(
            body,
            QONTRACT_INTEGRATION,
            QONTRACT_INTEGRATION_VERSION
        )
    else:
        return None


def get_endpoints() -> dict[EndpointMonitoringProvider, list[Endpoint]]:
    endpoints: dict[EndpointMonitoringProvider, list[Endpoint]] = {}
    for app in queries.get_service_monitoring_endpoints():
        for ep_data in app.get("endPoints") or []:
            monitoring = ep_data.get("monitoring")
            if monitoring:
                ep_data["monitoring"] = [
                    m for m in monitoring
                    if m["provider"]["provider"] == "blackbox-exporter"
                ]
                ep = Endpoint(**ep_data)
                for mon in ep.monitoring:
                    endpoints.setdefault(mon.provider, [])
                    endpoints[mon.provider].append(ep)
    return endpoints


def fill_desired_state(provider: EndpointMonitoringProvider,
                       endpoints: list[Endpoint],
                       ri: ResourceInventory) -> None:
    probe = build_probe(provider, endpoints)
    if probe and provider.blackboxExporter:
        ns = provider.blackboxExporter.namespace
        ri.add_desired(
            cluster=ns["cluster"]["name"],
            namespace=ns["name"],
            resource_type=probe.kind,
            name=probe.name,
            value=probe
        )


@defer
def run(dry_run: bool, thread_pool_size: int, internal: bool,
        use_jump_host: bool, defer=None) -> None:
    # prepare
    desired_endpoints = get_endpoints()
    namespaces = {
        p.blackboxExporter.namespace.get("name"):
        p.blackboxExporter.namespace
        for p in desired_endpoints
        if p.blackboxExporter
    }

    if namespaces:
        ri, oc_map = ob.fetch_current_state(
            namespaces.values(),
            thread_pool_size=thread_pool_size,
            internal=internal,
            use_jump_host=use_jump_host,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            override_managed_types=["Probe"]
        )
        defer(oc_map.cleanup)

        # reconcile
        for provider, endpoints in desired_endpoints.items():
            fill_desired_state(provider, endpoints, ri)
        ob.realize_data(dry_run, oc_map, ri, thread_pool_size, recycle_pods=False)

        if ri.has_error_registered():
            sys.exit(1)
