from reconcile.gql_definitions.common.clusters_with_peering import (
    ClusterV1,
    query,
)
from reconcile.utils import gql


def get_clusters_with_peering() -> list[ClusterV1]:
    query_func = gql.get_api().query
    data = query(query_func)
    clusters = data.clusters or []
    return [c for c in clusters if c.peering is not None]
