import logging
import sys
from typing import Any, Optional

from reconcile import queries
from reconcile.closedbox_endpoint_monitoring_base import (
    EndpointMonitoringProvider,
    Endpoint,
    parse_prober_url,
    run_for_provider,
)
from reconcile.utils.openshift_resource import OpenshiftResource
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "signalfx-prometheus-endpoint-monitoring"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

LOG = logging.getLogger(__name__)

PROVIDER = "signalfx"

LOG = logging.getLogger(__name__)


def run(
    dry_run: bool, thread_pool_size: int, internal: bool, use_jump_host: bool
) -> None:
    run_for_provider(
        PROVIDER,
        build_probe,
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        dry_run,
        thread_pool_size,
        internal,
        use_jump_host,
    )


def build_probe(
    provider: EndpointMonitoringProvider, endpoints: list[Endpoint]
) -> Optional[OpenshiftResource]:
    signalfx = provider.signalFx
    if signalfx:
        prober_url = parse_prober_url(signalfx.exporterUrl)
        prober_url["path"] += "/" + signalfx.targetFilterLabel

        relabeling = [
            {
                "action": "replace",
                "regex": f"^{ep.name}$",
                "replacement": ep.url,
                "sourceLabels": ["instance"],
                "targetLabel": ["instance"],
            }
            for ep in endpoints
        ]
        relabeling.append({"action": "labeldrop", "regex": "namespace"})

        body: dict[str, Any] = {
            "apiVersion": "monitoring.coreos.com/v1",
            "kind": "Probe",
            "metadata": {
                "name": provider.name,
                "namespace": signalfx.namespace.get("name"),
                "labels": {"prometheus": "app-sre"},
            },
            "spec": {
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
            },
        }
        if provider.timeout:
            body["spec"]["scrapeTimeout"] = provider.timeout
        return OpenshiftResource(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )
    else:
        return None
