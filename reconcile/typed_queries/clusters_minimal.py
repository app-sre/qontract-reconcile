from typing import Optional

from reconcile.utils import gql
from reconcile.gql_definitions.common.clusters_minimal import (
    query,
    ClusterV1,
)


def get_clusters_minimal(name: Optional[str]) -> list[ClusterV1]:
    variables = {}
    if name:
        variables["name"] = name
    gqlapi = gql.get_api()
    data = query(gqlapi.query, variables=variables)
    return list(data.clusters or [])
