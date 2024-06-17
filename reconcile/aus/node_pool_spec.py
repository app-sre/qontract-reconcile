from collections.abc import Iterable, Mapping

from reconcile.aus.models import NodePoolSpec
from reconcile.utils.ocm import get_node_pools
from reconcile.utils.ocm.base import ClusterDetails
from reconcile.utils.ocm.clusters import get_version
from reconcile.utils.ocm_base_client import OCMBaseClient


def get_node_pool_specs(ocm_api: OCMBaseClient, cluster_id: str) -> list[NodePoolSpec]:
    node_pools = get_node_pools(ocm_api, cluster_id)
    return [
        NodePoolSpec(
            id=p["id"],
            version=get_version(ocm_api, version_id)["raw_id"],
        )
        for p in node_pools
        if (version_id := p.get("version", {}).get("id"))
    ]


def get_node_pool_specs_by_org_cluster(
    ocm_api: OCMBaseClient,
    clusters_by_org: Mapping[str, Iterable[ClusterDetails]],
) -> dict[str, dict[str, list[NodePoolSpec]]]:
    """
    Fetch node pool specs for all rosa hypershift clusters
    Returns a dict with org IDs as keys, the values are dicts with cluster id as key
    """
    return {
        org_id: {
            c.ocm_cluster.id: get_node_pool_specs(ocm_api, c.ocm_cluster.id)
            for c in clusters
            if c.ocm_cluster.is_rosa_hypershift()
        }
        for org_id, clusters in clusters_by_org.items()
    }
