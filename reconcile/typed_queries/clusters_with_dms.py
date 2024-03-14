from typing import Optional

from reconcile.gql_definitions.common.clusters_with_dms import (
    ClusterV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.gql import GqlApi


def get_clusters_with_dms(
    gql_api: Optional[GqlApi] = None,
) -> list[ClusterV1]:
    api = gql_api if gql_api else gql.get_api()
    data = query(query_func=api.query)
    return (data.clusters or [])
