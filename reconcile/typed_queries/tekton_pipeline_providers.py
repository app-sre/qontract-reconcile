from collections.abc import Callable

from reconcile.gql_definitions.common.pipeline_providers import (
    PipelinesProviderTektonV1,
    query,
)
from reconcile.utils import gql


def get_tekton_pipeline_providers(
    query_func: Callable | None = None,
) -> list[PipelinesProviderTektonV1]:
    if not query_func:
        query_func = gql.get_api().query
    pipeline_providers = query(query_func).pipelines_providers or []
    return [p for p in pipeline_providers if isinstance(p, PipelinesProviderTektonV1)]
