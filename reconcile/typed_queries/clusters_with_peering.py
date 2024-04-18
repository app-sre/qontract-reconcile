from reconcile.gql_definitions.common.clusters_with_peering import (
    ClusterV1,
    query,
)
from reconcile.utils.gql import GqlApi


def get_clusters_with_peering(gql_api: GqlApi) -> list[ClusterV1]:
    filter = {"filter": {"peering": {"ne": None}}}
    data = query(gql_api.query, variables=filter)
    clusters = data.clusters or []
    return clusters
