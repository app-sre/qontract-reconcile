from reconcile.gql_definitions.dynatrace_log_metrics.dynatrace_log_metrics import (
    ClusterV1,
    query,
)
from reconcile.utils.gql import GqlApi


def get_dynatrace_log_metrics_per_cluster(gql_api: GqlApi) -> list[ClusterV1]:
    data = query(query_func=gql_api.query)
    return [cluster for cluster in data.clusters if cluster.dynatrace_log_metrics]
