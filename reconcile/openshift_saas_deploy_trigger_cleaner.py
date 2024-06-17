import logging
from collections.abc import Callable
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import Any

from dateutil import parser

from reconcile.gql_definitions.fragments.pipeline_provider_retention import (
    PipelineProviderRetention,
)
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


def within_retention_days(
    resource: dict[str, Any], days: int, now_date: datetime
) -> bool:
    metadata = resource["metadata"]
    creation_date = parser.parse(metadata["creationTimestamp"])
    interval = now_date.timestamp() - creation_date.timestamp()

    return interval < timedelta(days=days).total_seconds()


def get_pipeline_runs_to_delete(
    pipeline_runs: list[dict[str, Any]],
    retention: PipelineProviderRetention,
    now_date: datetime,
) -> list[dict[str, Any]]:
    pipeline_runs_to_delete = []
    if retention.minimum:
        pipeline_runs = pipeline_runs[retention.minimum :]
    elif retention.maximum:
        pipeline_runs_to_delete = pipeline_runs[retention.maximum :]
        pipeline_runs = pipeline_runs[: retention.maximum]

    for pr in pipeline_runs:
        if retention.days and within_retention_days(pr, retention.days, now_date):
            continue
        pipeline_runs_to_delete.append(pr)

    return pipeline_runs_to_delete


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    defer: Callable | None = None,
) -> None:
    now_date = datetime.now(UTC)
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
            pp.retention = pp.defaults.retention

        oc = oc_map.get(pp.namespace.cluster.name)
        if isinstance(oc, OCLogMsg):
            logging.log(level=oc.log_level, msg=oc.message)
            continue
        pipeline_runs = sorted(
            oc.get(pp.namespace.name, "PipelineRun")["items"],
            key=lambda k: k["metadata"]["creationTimestamp"],
            reverse=True,
        )

        for pr in get_pipeline_runs_to_delete(pipeline_runs, pp.retention, now_date):
            name = pr["metadata"]["name"]
            logging.info([
                "delete_trigger",
                pp.namespace.cluster.name,
                pp.namespace.name,
                "PipelineRun",
                name,
            ])
            if not dry_run:
                oc.delete(pp.namespace.name, "PipelineRun", name)
