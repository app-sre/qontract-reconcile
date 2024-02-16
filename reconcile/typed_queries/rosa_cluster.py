from typing import Any, Callable, Optional

from reconcile.gql_definitions.common.rosa_clusters import (
    ClusterV1,
)
from reconcile.gql_definitions.common.rosa_clusters import (
    query as rosa_clusters_query,
)


def get_rosa_clusters(
    query_func: Callable, orgId: Optional[str] = None
) -> list[ClusterV1]:
    """
    Returns a list of ROSA clusters from app-interface.
    Allows for filtering by orgId.
    """
    filter: dict[str, Any] = {"spec": {"filter": {"product": "rosa"}}}
    if orgId:
        filter["ocm"] = {"filter": {"orgId": orgId}}
    return rosa_clusters_query(query_func, variables={"filter": filter}).clusters or []
