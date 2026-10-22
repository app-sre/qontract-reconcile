"""Tests for OcmApi machine pool and node pool operations."""

import json
from collections.abc import Generator
from typing import Any

import pytest
from pytest_httpserver import HTTPServer
from qontract_utils.ocm_api import (
    OcmApi,
    OcmMachinePool,
    OcmMachinePoolAutoscaling,
    OcmNodePool,
    OcmNodePoolAutoscaling,
    OcmNodePoolAws,
    OcmTaint,
)
from qontract_utils.user_agent import DEFAULT_USER_AGENT
from werkzeug import Request, Response

TOKEN_PATH = "/auth/token"
CLUSTER_ID = "cluster-1"
MACHINE_POOLS_PATH = f"/api/clusters_mgmt/v1/clusters/{CLUSTER_ID}/machine_pools"
NODE_POOLS_PATH = f"/api/clusters_mgmt/v1/clusters/{CLUSTER_ID}/node_pools"

_created_apis: list[OcmApi] = []


@pytest.fixture(autouse=True)
def _close_ocm_apis() -> Generator[None]:
    """Close every OcmApi created via `_make_ocm_api` after each test."""
    yield
    for api in _created_apis:
        api.close()
    _created_apis.clear()


def _make_ocm_api(httpserver: HTTPServer, token: str) -> OcmApi:
    """Build an OcmApi against the test HTTP server, closed after each test."""
    httpserver.expect_request(TOKEN_PATH, method="POST").respond_with_json(
        {"access_token": token, "token_type": "bearer", "expires_in": 300}
    )
    api = OcmApi(
        url=httpserver.url_for(""),
        access_token_url=httpserver.url_for(TOKEN_PATH),
        access_token_client_id="client-id",
        access_token_client_secret="client-secret",
        timeout=5,
        user_agent=DEFAULT_USER_AGENT,
    )
    _created_apis.append(api)
    return api


def _machine_pool_json(
    pool_id: str = "worker",
    instance_type: str = "m5.xlarge",
) -> dict[str, Any]:
    """A machine pool wire payload, including extra fields OCM returns."""
    return {
        "id": pool_id,
        "instance_type": instance_type,
        "replicas": 3,
        "autoscaling": {"min_replicas": 2, "max_replicas": 5},
        "labels": {"tier": "frontend"},
        "taints": [{"key": "dedicated", "value": "frontend", "effect": "NoSchedule"}],
        # extra fields returned by OCM must be ignored (MACHINE_POOL_DESIRED_KEYS)
        "href": f"/api/clusters_mgmt/v1/clusters/{CLUSTER_ID}/machine_pools/{pool_id}",
        "kind": "MachinePool",
    }


def _node_pool_json(
    pool_id: str = "worker",
    instance_type: str = "m5.xlarge",
) -> dict[str, Any]:
    """A node pool wire payload, including extra fields OCM returns."""
    return {
        "id": pool_id,
        "aws_node_pool": {"instance_type": instance_type},
        "replicas": 3,
        # Hypershift node pool autoscaling uses the singular form
        "autoscaling": {"min_replica": 2, "max_replica": 5},
        "labels": {"tier": "frontend"},
        "taints": [{"key": "dedicated", "value": "frontend", "effect": "NoSchedule"}],
        "subnet": "subnet-1234",
        # extra fields returned by OCM must be ignored (NODE_POOL_DESIRED_KEYS)
        "version": "4.15.0",
        "kind": "NodePool",
    }


#
# machine pools
#


def test_get_machine_pools_maps_fields(httpserver: HTTPServer) -> None:
    """Machine pool reads map all wire fields onto the domain model."""
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(MACHINE_POOLS_PATH, method="GET").respond_with_json(
        {"items": [_machine_pool_json()], "page": 1, "size": 1, "total": 1}
    )

    pools = api.get_machine_pools(CLUSTER_ID)

    assert len(pools) == 1
    pool = pools[0]
    assert pool == OcmMachinePool(
        id="worker",
        instance_type="m5.xlarge",
        replicas=3,
        autoscaling=OcmMachinePoolAutoscaling(min_replicas=2, max_replicas=5),
        labels={"tier": "frontend"},
        taints=[OcmTaint(key="dedicated", value="frontend", effect="NoSchedule")],
    )


def test_get_machine_pools_empty(httpserver: HTTPServer) -> None:
    """A cluster with no machine pools yields an empty list."""
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(MACHINE_POOLS_PATH, method="GET").respond_with_json(
        {"items": [], "page": 1, "size": 0, "total": 0}
    )

    assert api.get_machine_pools(CLUSTER_ID) == []


def test_get_machine_pools_paginates(httpserver: HTTPServer) -> None:
    """Machine pool reads follow pagination until the last short page."""
    api = _make_ocm_api(httpserver, token="test-token")

    def handler(request: Request) -> Response:
        """Serve a full first page of machine pools, then a single-item second page."""
        page = int(request.args.get("page", "1"))
        if page == 1:
            items = [_machine_pool_json(pool_id=f"pool-{i}") for i in range(100)]
            body = {"items": items, "page": 1, "size": 100, "total": 101}
        else:
            items = [_machine_pool_json(pool_id="pool-100")]
            body = {"items": items, "page": 2, "size": 1, "total": 101}
        return Response(json.dumps(body), content_type="application/json")

    httpserver.expect_request(MACHINE_POOLS_PATH, method="GET").respond_with_handler(
        handler
    )

    assert len(api.get_machine_pools(CLUSTER_ID)) == 101


def test_get_machine_pools_without_autoscaling_or_labels(
    httpserver: HTTPServer,
) -> None:
    """Machine pool fields absent from the wire payload map to None."""
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(MACHINE_POOLS_PATH, method="GET").respond_with_json(
        {
            "items": [{"id": "worker", "instance_type": "m5.xlarge", "replicas": 3}],
            "page": 1,
            "size": 1,
            "total": 1,
        }
    )

    pool = api.get_machine_pools(CLUSTER_ID)[0]

    assert pool.autoscaling is None
    assert pool.labels is None
    assert pool.taints is None


def test_get_node_pools_accepts_taint_without_value(httpserver: HTTPServer) -> None:
    """OCM's Taint schema does not require a value."""
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(NODE_POOLS_PATH, method="GET").respond_with_json(
        {
            "items": [
                {
                    "id": "worker",
                    "aws_node_pool": {"instance_type": "m5.xlarge"},
                    "taints": [{"key": "dedicated", "effect": "NoSchedule"}],
                }
            ],
            "page": 1,
            "size": 1,
            "total": 1,
        }
    )

    pool = api.get_node_pools(CLUSTER_ID)[0]

    assert pool.taints == [OcmTaint(key="dedicated", value=None, effect="NoSchedule")]


def test_create_machine_pool_sends_full_body(httpserver: HTTPServer) -> None:
    """Machine pool creation sends the full spec, including the pool id."""
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(MACHINE_POOLS_PATH, method="POST").respond_with_json(
        _machine_pool_json()
    )

    pool = OcmMachinePool(
        id="worker",
        instance_type="m5.xlarge",
        replicas=3,
        autoscaling=OcmMachinePoolAutoscaling(min_replicas=2, max_replicas=5),
        labels={"tier": "frontend"},
        taints=[OcmTaint(key="dedicated", value="frontend", effect="NoSchedule")],
    )

    result = api.create_machine_pool(CLUSTER_ID, pool)

    # the pool id is client-chosen in OCM, so it must be part of the body
    create_requests = [
        req for req, _ in httpserver.log if req.path == MACHINE_POOLS_PATH
    ]
    assert len(create_requests) == 1
    body = create_requests[0].get_json()
    assert body["id"] == "worker"
    assert body["instance_type"] == "m5.xlarge"
    assert body["replicas"] == 3
    assert body["autoscaling"] == {"min_replicas": 2, "max_replicas": 5}
    assert body["labels"] == {"tier": "frontend"}
    assert body["taints"] == [
        {"key": "dedicated", "value": "frontend", "effect": "NoSchedule"}
    ]
    assert result == pool


def test_update_machine_pool_excludes_id_and_instance_type(
    httpserver: HTTPServer,
) -> None:
    """Machine pool updates exclude the id and the immutable instance_type."""
    api = _make_ocm_api(httpserver, token="test-token")
    update_path = f"{MACHINE_POOLS_PATH}/worker"
    httpserver.expect_request(update_path, method="PATCH").respond_with_json(
        _machine_pool_json()
    )

    pool = OcmMachinePool(
        id="worker",
        instance_type="m5.2xlarge",
        replicas=5,
        labels={"tier": "backend"},
        taints=[OcmTaint(key="dedicated", value="backend", effect="NoSchedule")],
    )

    api.update_machine_pool(CLUSTER_ID, pool)

    update_requests = [req for req, _ in httpserver.log if req.path == update_path]
    assert len(update_requests) == 1
    body = update_requests[0].get_json()
    # instance_type is immutable on OCM, id travels in the URL path
    assert "id" not in body
    assert "instance_type" not in body
    assert body["replicas"] == 5
    assert body["labels"] == {"tier": "backend"}
    assert body["taints"] == [
        {"key": "dedicated", "value": "backend", "effect": "NoSchedule"}
    ]


def test_update_machine_pool_drops_empty_labels_and_taints(
    httpserver: HTTPServer,
) -> None:
    """Machine pool updates drop empty labels and taints entries."""
    api = _make_ocm_api(httpserver, token="test-token")
    update_path = f"{MACHINE_POOLS_PATH}/worker"
    httpserver.expect_request(update_path, method="PATCH").respond_with_json(
        _machine_pool_json()
    )

    pool = OcmMachinePool(id="worker", instance_type="m5.xlarge", replicas=5)

    api.update_machine_pool(CLUSTER_ID, pool)

    update_requests = [req for req, _ in httpserver.log if req.path == update_path]
    body = update_requests[0].get_json()
    assert "labels" not in body
    assert "taints" not in body


def test_delete_machine_pool(httpserver: HTTPServer) -> None:
    """Machine pool deletion hits the per-pool DELETE endpoint."""
    api = _make_ocm_api(httpserver, token="test-token")
    delete_path = f"{MACHINE_POOLS_PATH}/worker"
    httpserver.expect_request(delete_path, method="DELETE").respond_with_data(
        status=204
    )

    api.delete_machine_pool(CLUSTER_ID, "worker")

    delete_requests = [req for req, _ in httpserver.log if req.path == delete_path]
    assert len(delete_requests) == 1
    assert delete_requests[0].method == "DELETE"


#
# node pools
#


def test_get_node_pools_maps_fields(httpserver: HTTPServer) -> None:
    """Node pool reads map all wire fields onto the domain model."""
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(NODE_POOLS_PATH, method="GET").respond_with_json(
        {"items": [_node_pool_json()], "page": 1, "size": 1, "total": 1}
    )

    pools = api.get_node_pools(CLUSTER_ID)

    assert len(pools) == 1
    pool = pools[0]
    assert pool == OcmNodePool(
        id="worker",
        aws_node_pool=OcmNodePoolAws(instance_type="m5.xlarge"),
        replicas=3,
        autoscaling=OcmNodePoolAutoscaling(min_replica=2, max_replica=5),
        labels={"tier": "frontend"},
        taints=[OcmTaint(key="dedicated", value="frontend", effect="NoSchedule")],
        subnet="subnet-1234",
    )


def test_get_node_pools_empty(httpserver: HTTPServer) -> None:
    """A cluster with no node pools yields an empty list."""
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(NODE_POOLS_PATH, method="GET").respond_with_json(
        {"items": [], "page": 1, "size": 0, "total": 0}
    )

    assert api.get_node_pools(CLUSTER_ID) == []


def test_get_node_pools_paginates(httpserver: HTTPServer) -> None:
    """Node pool reads follow pagination until the last short page."""
    api = _make_ocm_api(httpserver, token="test-token")

    def handler(request: Request) -> Response:
        """Serve a full first page of node pools, then a single-item second page."""
        page = int(request.args.get("page", "1"))
        if page == 1:
            items = [_node_pool_json(pool_id=f"pool-{i}") for i in range(100)]
            body = {"items": items, "page": 1, "size": 100, "total": 101}
        else:
            items = [_node_pool_json(pool_id="pool-100")]
            body = {"items": items, "page": 2, "size": 1, "total": 101}
        return Response(json.dumps(body), content_type="application/json")

    httpserver.expect_request(NODE_POOLS_PATH, method="GET").respond_with_handler(
        handler
    )

    assert len(api.get_node_pools(CLUSTER_ID)) == 101


def test_create_node_pool_sends_full_body(httpserver: HTTPServer) -> None:
    """Node pool creation sends the full spec, including the pool id."""
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(NODE_POOLS_PATH, method="POST").respond_with_json(
        _node_pool_json()
    )

    pool = OcmNodePool(
        id="worker",
        aws_node_pool=OcmNodePoolAws(instance_type="m5.xlarge"),
        replicas=3,
        autoscaling=OcmNodePoolAutoscaling(min_replica=2, max_replica=5),
        labels={"tier": "frontend"},
        taints=[OcmTaint(key="dedicated", value="frontend", effect="NoSchedule")],
        subnet="subnet-1234",
    )

    result = api.create_node_pool(CLUSTER_ID, pool)

    create_requests = [req for req, _ in httpserver.log if req.path == NODE_POOLS_PATH]
    assert len(create_requests) == 1
    body = create_requests[0].get_json()
    assert body["id"] == "worker"
    assert body["aws_node_pool"] == {"instance_type": "m5.xlarge"}
    assert body["autoscaling"] == {"min_replica": 2, "max_replica": 5}
    assert body["subnet"] == "subnet-1234"
    assert result == pool


def test_update_node_pool_excludes_immutable_fields(httpserver: HTTPServer) -> None:
    """Node pool updates exclude the id and the immutable aws_node_pool/subnet."""
    api = _make_ocm_api(httpserver, token="test-token")
    update_path = f"{NODE_POOLS_PATH}/worker"
    httpserver.expect_request(update_path, method="PATCH").respond_with_json(
        _node_pool_json()
    )

    pool = OcmNodePool(
        id="worker",
        aws_node_pool=OcmNodePoolAws(instance_type="m5.2xlarge"),
        replicas=5,
        subnet="subnet-5678",
        labels={"tier": "backend"},
        taints=[OcmTaint(key="dedicated", value="backend", effect="NoSchedule")],
    )

    api.update_node_pool(CLUSTER_ID, pool)

    update_requests = [req for req, _ in httpserver.log if req.path == update_path]
    assert len(update_requests) == 1
    body = update_requests[0].get_json()
    # aws_node_pool (instance_type) and subnet are immutable on OCM
    assert "id" not in body
    assert "aws_node_pool" not in body
    assert "subnet" not in body
    assert body["replicas"] == 5
    assert body["labels"] == {"tier": "backend"}


def test_update_node_pool_drops_empty_labels_and_taints(
    httpserver: HTTPServer,
) -> None:
    """Node pool updates drop empty labels and taints entries."""
    api = _make_ocm_api(httpserver, token="test-token")
    update_path = f"{NODE_POOLS_PATH}/worker"
    httpserver.expect_request(update_path, method="PATCH").respond_with_json(
        _node_pool_json()
    )

    pool = OcmNodePool(
        id="worker",
        aws_node_pool=OcmNodePoolAws(instance_type="m5.xlarge"),
        replicas=5,
    )

    api.update_node_pool(CLUSTER_ID, pool)

    update_requests = [req for req, _ in httpserver.log if req.path == update_path]
    body = update_requests[0].get_json()
    assert "labels" not in body
    assert "taints" not in body


def test_delete_node_pool(httpserver: HTTPServer) -> None:
    """Node pool deletion hits the per-pool DELETE endpoint."""
    api = _make_ocm_api(httpserver, token="test-token")
    delete_path = f"{NODE_POOLS_PATH}/worker"
    httpserver.expect_request(delete_path, method="DELETE").respond_with_data(
        status=204
    )

    api.delete_node_pool(CLUSTER_ID, "worker")

    delete_requests = [req for req, _ in httpserver.log if req.path == delete_path]
    assert len(delete_requests) == 1
    assert delete_requests[0].method == "DELETE"
