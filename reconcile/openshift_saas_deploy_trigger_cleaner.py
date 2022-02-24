import logging

from datetime import datetime, timedelta, timezone
from dateutil import parser

from reconcile import queries

from reconcile.utils.oc import OC_Map
from reconcile.utils.defer import defer
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.saasherder import Providers


QONTRACT_INTEGRATION = "openshift-saas-deploy-trigger-cleaner"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def within_retention_days(resource, days):
    metadata = resource["metadata"]
    creation_date = parser.parse(metadata["creationTimestamp"])
    now_date = datetime.now(timezone.utc)
    interval = now_date.timestamp() - creation_date.timestamp()

    return interval < timedelta(days=days).seconds


@defer
def run(dry_run, thread_pool_size=10, internal=None, use_jump_host=True, defer=None):
    settings = queries.get_app_interface_settings()
    pipelines_providers = queries.get_pipelines_providers()
    tkn_namespaces = [
        pp["namespace"]
        for pp in pipelines_providers
        if pp["provider"] == Providers.TEKTON
    ]

    oc_map = OC_Map(
        namespaces=tkn_namespaces,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )
    defer(oc_map.cleanup)

    for pp in pipelines_providers:
        retention = pp.get("retention")
        if not retention:
            continue

        if pp["provider"] == Providers.TEKTON:
            ns_info = pp["namespace"]
            namespace = ns_info["name"]
            cluster = ns_info["cluster"]["name"]
            oc = oc_map.get(cluster)
            pipeline_runs = sorted(
                oc.get(namespace, "PipelineRun")["items"],
                key=lambda k: k["metadata"]["creationTimestamp"],
                reverse=True,
            )

            retention_min = retention.get("minimum")
            if retention_min:
                pipeline_runs = pipeline_runs[retention_min:]

            retention_days = retention.get("days")
            for pr in pipeline_runs:
                name = pr["metadata"]["name"]
                if retention_days and within_retention_days(pr, retention_days):
                    continue

                logging.info(
                    ["delete_trigger", cluster, namespace, "PipelineRun", name]
                )
                if not dry_run:
                    oc.delete(namespace, "PipelineRun", name)
