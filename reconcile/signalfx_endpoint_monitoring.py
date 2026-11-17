import logging
import sys
from typing import Any

from reconcile.closedbox_endpoint_monitoring_base import (
    Endpoint,
    EndpointMonitoringProvider,
    parse_prober_url,
    run_for_provider,
)
from reconcile.utils.openshift_resource import OpenshiftResource
from reconcile.utils.semver_helper import make_semver

# Keep the deployed command and resource ownership stable during provider migration.
QONTRACT_INTEGRATION = "signalfx-prometheus-endpoint-monitoring"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

LOG = logging.getLogger(__name__)

PROVIDER = "signalfx"
PROVIDERS = frozenset({PROVIDER, "prometheus-metrics-importer"})
COO_NAMESPACE_NAME = "app-sre-observability-per-cluster"
MANAGED_TYPES = ["Probe.monitoring.rhobs"]


def run(dry_run: bool, thread_pool_size: int, internal: bool) -> None:
    try:
        run_for_provider(
            provider=PROVIDERS,
            probe_builder=build_probe,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            dry_run=dry_run,
            thread_pool_size=thread_pool_size,
            internal=internal,
            managed_types=MANAGED_TYPES,
        )
    except Exception as e:
        LOG.error(e)
        sys.exit(1)


def build_probe(
    provider: EndpointMonitoringProvider, endpoints: list[Endpoint]
) -> list[tuple[OpenshiftResource, dict[str, Any]]]:
    match provider.provider:
        case "signalfx":
            importer = provider.signalFx
        case "prometheus-metrics-importer":
            importer = provider.prometheusMetricsImporter
        case _:
            raise ValueError(
                f"Unsupported metrics importer provider: {provider.provider}"
            )
    if importer is None:
        raise ValueError(
            f"Missing metrics importer settings for provider {provider.name}"
        )
    prober_url = parse_prober_url(importer.exporterUrl)
    prober_url["path"] = prober_url.get("path", "") + "/" + importer.targetFilterLabel

    # the scraped metrics have the endpoint name in their instance label. to be
    # compatible with the results of blackbox exporter, we replace the endpoint
    # name with the endpoint url. the endpoint name itself will still be
    # available on the scraped metrics in the field specified by
    # `targetFilterLabel``
    relabeling = [
        {
            "action": "replace",
            "regex": f"^{ep.name}$",
            "replacement": ep.url,
            "sourceLabels": ["instance"],
            "targetLabel": "instance",
        }
        for ep in endpoints
    ]
    relabeling.append({"action": "labeldrop", "regex": "namespace"})

    spec: dict[str, Any] = {
        "jobName": provider.name,
        "interval": provider.checkInterval or "10s",
        "prober": prober_url,
        "targets": {
            "staticConfig": {
                "relabelingConfigs": relabeling,
                "labels": provider.metric_labels,
                "static": [ep.name for ep in endpoints],
            }
        },
    }
    if provider.timeout:
        spec["scrapeTimeout"] = provider.timeout

    namespace = importer.namespace
    coo_namespace: dict[str, Any] = {**namespace, "name": COO_NAMESPACE_NAME}
    rhobs_body: dict[str, Any] = {
        "apiVersion": "monitoring.rhobs/v1",
        "kind": "Probe",
        "metadata": {
            "name": provider.name,
            "namespace": COO_NAMESPACE_NAME,
            "labels": {"prometheus": "app-sre"},
        },
        "spec": spec,
    }
    return [
        (
            OpenshiftResource(
                rhobs_body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
            ),
            coo_namespace,
        ),
    ]
