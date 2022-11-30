import logging
import sys
from typing import (
    Any,
    Optional,
)

from reconcile import queries
from reconcile.closedbox_endpoint_monitoring_base import (
    Endpoint,
    EndpointMonitoringProvider,
    parse_prober_url,
    run_for_provider,
)
from reconcile.utils.openshift_resource import OpenshiftResource
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "blackbox-exporter-endpoint-monitoring"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

PROVIDER = "blackbox-exporter"

LOG = logging.getLogger(__name__)


def run(
    dry_run: bool, thread_pool_size: int, internal: bool, use_jump_host: bool
) -> None:
    # verify that only allowed blackbox-exporter modules are used
    settings = queries.get_app_interface_settings()
    allowed_modules = set(settings["endpointMonitoringBlackboxExporterModules"])
    verification_errors = False
    if allowed_modules:
        for p in get_blackbox_providers():
            if p.blackboxExporter and p.blackboxExporter.module not in allowed_modules:
                LOG.error(
                    f"endpoint monitoring provider {p.name} uses "
                    f"blackbox-exporter module {p.blackboxExporter.module} "
                    f"which is not in the allow list {allowed_modules} of "
                    "app-interface-settings"
                )
                verification_errors = True
    if verification_errors:
        sys.exit(1)

    try:
        run_for_provider(
            provider=PROVIDER,
            probe_builder=build_probe,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            dry_run=dry_run,
            thread_pool_size=thread_pool_size,
            internal=internal,
            use_jump_host=use_jump_host,
        )
    except Exception as e:
        LOG.error(e)
        sys.exit(1)


def get_blackbox_providers() -> list[EndpointMonitoringProvider]:
    return [
        EndpointMonitoringProvider(**p)
        for p in queries.get_blackbox_exporter_monitoring_provider()
        if p["provider"] == PROVIDER
    ]


def build_probe(
    provider: EndpointMonitoringProvider, endpoints: list[Endpoint]
) -> Optional[OpenshiftResource]:
    blackbox_exporter = provider.blackboxExporter
    if blackbox_exporter:
        prober_url = parse_prober_url(blackbox_exporter.exporterUrl)
        body: dict[str, Any] = {
            "apiVersion": "monitoring.coreos.com/v1",
            "kind": "Probe",
            "metadata": {
                "name": provider.name,
                "namespace": blackbox_exporter.namespace.get("name"),
                "labels": {"prometheus": "app-sre"},
            },
            "spec": {
                "jobName": provider.name,
                "interval": provider.checkInterval or "10s",
                "module": blackbox_exporter.module,
                "prober": prober_url,
                "targets": {
                    "staticConfig": {
                        "relabelingConfigs": [
                            {"action": "labeldrop", "regex": "namespace"}
                        ],
                        "labels": provider.metric_labels,
                        "static": [ep.url for ep in endpoints],
                    }
                },
            },
        }
        if provider.timeout:
            body["spec"]["scrapeTimeout"] = provider.timeout
        return OpenshiftResource(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )
    else:
        return None
