from typing import Optional

from reconcile.gql_definitions.common.clusters_minimal import (
    ClusterV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.gql import GqlApi


def get_clusters_minimal(
    gql_api: Optional[GqlApi] = None, name: Optional[str] = None
) -> list[ClusterV1]:
    variables = {}
    if name:
        variables["name"] = name
    api = gql_api if gql_api else gql.get_api()
    data = query(query_func=api.query, variables=variables)
    return list(data.clusters or [])
