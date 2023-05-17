from collections.abc import Callable
from typing import Optional

from reconcile.gql_definitions.common.clusters_minimal import (
    ClusterV1,
    query,
)
from reconcile.utils import gql


def get_clusters_minimal(
    name: Optional[str] = None, query_func: Optional[Callable] = None
) -> list[ClusterV1]:
    variables = {}
    if name:
        variables["name"] = name
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func=query_func, variables=variables)
    return list(data.clusters or [])
