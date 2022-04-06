import logging
import sys
from typing import Any, Optional

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


def run(
    dry_run: bool, thread_pool_size: int, internal: bool, use_jump_host: bool
) -> None:
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


def build_probe(
    provider: EndpointMonitoringProvider, endpoints: list[Endpoint]
) -> Optional[OpenshiftResource]:
    signalfx = provider.signalFx
    if not signalfx:
        return None
    prober_url = parse_prober_url(signalfx.exporterUrl)
    prober_url["path"] += "/" + signalfx.targetFilterLabel

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
    return OpenshiftResource(body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION)
