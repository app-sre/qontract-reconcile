from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.clusters_with_dms import (
    ClusterV1,
    query,
)
from reconcile.utils import gql

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_clusters_with_dms(
    gql_api: GqlApi | None = None,
) -> list[ClusterV1]:
    # get the clusters containing the filed enableDeadMansSnitch
    variable = {"filter": {"enableDeadMansSnitch": {"ne": None}}}
    api = gql_api or gql.get_api()
    data = query(query_func=api.query, variables=variable)
    return data.clusters or []
