import logging
from collections.abc import Callable
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from typing import (
    Any,
    Optional,
)

from dateutil import parser

from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.tekton_pipeline_providers import (
    get_tekton_pipeline_providers,
)
from reconcile.utils.defer import defer
from reconcile.utils.oc_map import (
    OCLogMsg,
    init_oc_map_from_namespaces,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-saas-deploy-trigger-cleaner"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def within_retention_days(resource: dict[str, Any], days: int) -> bool:
    metadata = resource["metadata"]
    creation_date = parser.parse(metadata["creationTimestamp"])
    now_date = datetime.now(timezone.utc)
    interval = now_date.timestamp() - creation_date.timestamp()

    return interval < timedelta(days=days).seconds


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: Optional[bool] = None,
    use_jump_host: bool = True,
    defer: Optional[Callable] = None,
) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    pipeline_providers = get_tekton_pipeline_providers()
    tkn_namespaces = [pp.namespace for pp in pipeline_providers]
    oc_map = init_oc_map_from_namespaces(
        namespaces=tkn_namespaces,
        integration=QONTRACT_INTEGRATION,
        secret_reader=secret_reader,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )

    if defer:
        defer(oc_map.cleanup)

    for pp in pipeline_providers:
        if not pp.retention:
            continue

        oc = oc_map.get(pp.namespace.cluster.name)
        if isinstance(oc, OCLogMsg):
            logging.log(level=oc.log_level, msg=oc.message)
            continue
        pipeline_runs = sorted(
            oc.get(pp.namespace.name, "PipelineRun")["items"],
            key=lambda k: k["metadata"]["creationTimestamp"],
            reverse=True,
        )

        if pp.retention.minimum:
            pipeline_runs = pipeline_runs[pp.retention.minimum :]

        for pr in pipeline_runs:
            name = pr["metadata"]["name"]
            if pp.retention.days and within_retention_days(pr, pp.retention.days):
                continue

            logging.info(
                [
                    "delete_trigger",
                    pp.namespace.cluster.name,
                    pp.namespace.name,
                    "PipelineRun",
                    name,
                ]
            )
            if not dry_run:
                oc.delete(pp.namespace.name, "PipelineRun", name)
