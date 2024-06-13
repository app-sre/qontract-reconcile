from reconcile.aus.models import NodePoolSpec
from reconcile.utils.ocm import get_node_pools
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
