from collections.abc import Callable
from typing import Optional

from reconcile.gql_definitions.common.pipeline_providers import (
    PipelinesProviderTektonV1,
    query,
)
from reconcile.utils import gql


def get_tekton_pipeline_providers(
    query_func: Optional[Callable] = None,
) -> list[PipelinesProviderTektonV1]:
    if not query_func:
        query_func = gql.get_api().query
    providers: list[PipelinesProviderTektonV1] = []
    for provider in query(query_func).pipelines_providers or []:
        if not isinstance(provider, PipelinesProviderTektonV1):
            continue
        providers.append(provider)
    return providers
