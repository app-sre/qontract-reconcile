from unittest.mock import create_autospec

import pytest

from reconcile.aus.models import NodePoolSpec
from reconcile.aus.node_pool_spec import (
    get_node_pool_specs,
    get_node_pool_specs_by_org_cluster,
)
from reconcile.test.ocm.aus.fixtures import build_cluster_upgrade_spec
from reconcile.test.ocm.fixtures import build_cluster_details
from reconcile.utils.ocm_base_client import OCMBaseClient


def test_get_node_pool_specs() -> None:
    ocm_api = create_autospec(OCMBaseClient)
    ocm_api.get_paginated.return_value = {}
    node_pool = {
        "id": "np1",
        "version": {
            "id": "openshift-v4.15.17-candidate",
            "raw_id": "4.15.17",
        },
    }
    ocm_api.get_paginated.return_value = [node_pool]
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


def test_get_node_pool_specs_by_org_cluster_for_hypershift_cluster() -> None:
    ocm_api = create_autospec(OCMBaseClient)
    ocm_api.get_paginated.return_value = {}
    node_pool = {
        "id": "np1",
        "version": {
            "id": "openshift-v4.15.17-candidate",
            "raw_id": "4.15.17",
        },
    }
    ocm_api.get_paginated.return_value = [node_pool]
    cluster_details = build_cluster_details("cluster-1", hypershift=True)
    specs = get_node_pool_specs_by_org_cluster(
        ocm_api=ocm_api,
        clusters_by_org={
            "org1": [cluster_details],
        },
    )

    assert specs == {
        "org1": {
            cluster_details.ocm_cluster.id: [
                NodePoolSpec(
                    id="np1",
                    version="4.15.17",
                )
            ],
        }
    }
    ocm_api.get_paginated.assert_called_once_with(
        f"/api/clusters_mgmt/v1/clusters/{cluster_details.ocm_cluster.id}/node_pools"
    )


def test_get_node_pool_specs_by_org_cluster_for_non_hypershift_cluster() -> None:
    ocm_api = create_autospec(OCMBaseClient)
    cluster_details = build_cluster_details("cluster-1", hypershift=False)
    specs = get_node_pool_specs_by_org_cluster(
        ocm_api=ocm_api,
        clusters_by_org={
            "org1": [cluster_details],
        },
    )

    assert specs == {"org1": {}}
    ocm_api.get_paginated.assert_not_called()
    ocm_api.get.assert_not_called()


@pytest.mark.parametrize(
    "current_version, node_pools, expected_version",
    [
        (
            "4.13.0",
            [],
            "4.13.0",
        ),
        (
            "4.13.0",
            [NodePoolSpec(id="np1", version="4.12.0")],
            "4.12.0",
        ),
        (
            "4.13.0",
            [NodePoolSpec(id="np1", version="4.13.0")],
            "4.13.0",
        ),
        (
            "4.13.0",
            [
                NodePoolSpec(id="np1", version="4.12.0"),
                NodePoolSpec(id="np2", version="4.13.0"),
            ],
            "4.12.0",
        ),
    ],
)
def test_cluster_upgrade_spec_oldest_current_version(
    current_version: str,
    node_pools: list[NodePoolSpec],
    expected_version: str,
) -> None:
    spec = build_cluster_upgrade_spec(
        name="cluster-1",
        current_version=current_version,
        node_pools=node_pools,
    )

    assert spec.oldest_current_version == expected_version
