from typing import Optional

from reconcile.gql_definitions.common.clusters import (
    ClusterV1,
    query,
)
from reconcile.utils import gql


def get_clusters(name: Optional[str] = None) -> list[ClusterV1]:
    variables = {}
    if name:
        variables["name"] = name
    gqlapi = gql.get_api()
    data = query(gqlapi.query, variables=variables)
    return list(data.clusters or [])
