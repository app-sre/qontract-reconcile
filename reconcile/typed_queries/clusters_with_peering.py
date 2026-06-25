from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.clusters_with_peering import (
    ClusterV1,
    query,
)

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_clusters_with_peering(gql_api: GqlApi) -> list[ClusterV1]:
    data = query(gql_api.query)
    clusters = data.clusters or []
    return [c for c in clusters if c.peering is not None]
