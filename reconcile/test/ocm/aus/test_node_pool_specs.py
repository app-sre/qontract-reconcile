from unittest.mock import create_autospec

from reconcile.aus.models import NodePoolSpec
from reconcile.aus.node_pool_spec import get_node_pool_specs
from reconcile.utils.ocm_base_client import OCMBaseClient


def test_get_node_pool_specs() -> None:
    ocm_api = create_autospec(OCMBaseClient)
    ocm_api.get_paginated.return_value = {}
    node_pool = {
        "id": "np1",
        "version": {
            "id": "openshift-v4.15.17-candidate",
        },
    }
    ocm_api.get_paginated.return_value = [node_pool]
    ocm_api.get.return_value = {
        "id": "openshift-v4.15.17-candidate",
        "raw_id": "4.15.17",
    }
    specs = get_node_pool_specs(ocm_api=ocm_api, cluster_id="cluster-1")

    assert specs == [
        NodePoolSpec(
            id="np1",
            version="4.15.17",
        )
    ]
    ocm_api.get_paginated.assert_called_once_with(
        "/api/clusters_mgmt/v1/clusters/cluster-1/node_pools"
    )
    ocm_api.get.assert_called_once_with(
        "/api/clusters_mgmt/v1/versions/openshift-v4.15.17-candidate"
    )
