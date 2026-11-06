"""Unit tests for OCM machine pools reconciliation router endpoints."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.integrations.ocm_machine_pools.schemas import (
    OcmMachinePoolsReconcileRequest,
    OcmMachinePoolsTaskResult,
)
from qontract_api.models import TaskStatus, TokenData
from qontract_api.tasks import QUEUE_MR_CHECK, QUEUE_PROD

ENDPOINT = "/api/v1/integrations/ocm-machine-pools/reconcile"


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with valid JWT token."""
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def sample_reconcile_request() -> OcmMachinePoolsReconcileRequest:
    """Create a valid reconcile request with one OSD and one HCP cluster."""
    return OcmMachinePoolsReconcileRequest(
        ocm_environment="prod",
        ocm_connection={
            "secret_manager_url": "https://vault.example.com",
            "path": "ocm/prod",
            "ocm_url": "https://api.openshift.com",
            "access_token_url": "https://sso.redhat.com/token",
            "access_token_client_id": "client-id",
        },
        clusters=[
            {
                "name": "osd-cluster",
                "cluster_id": "cid-osd",
                "cluster_type": "osd",
                "pools": [
                    {
                        "id": "worker",
                        "instance_type": "m5.xlarge",
                        "replicas": 3,
                    }
                ],
            },
            {
                "name": "hcp-cluster",
                "cluster_id": "cid-hcp",
                "cluster_type": "hypershift",
                "pools": [
                    {
                        "id": "worker",
                        "aws_node_pool": {"instance_type": "m5.xlarge"},
                        "replicas": 3,
                    }
                ],
            },
        ],
        dry_run=True,
    )


@patch(
    "qontract_api.integrations.ocm_machine_pools.router.reconcile_ocm_machine_pools_task"
)
def test_post_reconcile_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: OcmMachinePoolsReconcileRequest,
) -> None:
    """Test POST /reconcile queues a Celery task and returns task ID."""
    response = client.post(
        ENDPOINT, json=sample_reconcile_request.model_dump(), headers=auth_headers
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    data = response.json()
    request_id = response.headers[REQUEST_ID_HEADER]
    assert data["id"] == request_id
    assert data["status"] == TaskStatus.PENDING.value
    assert f"/reconcile/{request_id}" in data["status_url"]

    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["dry_run"] is True
    assert len(call_kwargs["clusters"]) == 2
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_MR_CHECK


@patch(
    "qontract_api.integrations.ocm_machine_pools.router.reconcile_ocm_machine_pools_task"
)
def test_post_reconcile_dry_run_false_uses_prod_queue(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: OcmMachinePoolsReconcileRequest,
) -> None:
    """Non-dry-run reconciles go to the prod queue."""
    request_data = sample_reconcile_request.model_dump()
    request_data["dry_run"] = False

    response = client.post(ENDPOINT, json=request_data, headers=auth_headers)

    assert response.status_code == HTTPStatus.ACCEPTED
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["dry_run"] is False
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_PROD


def test_post_reconcile_requires_auth(
    client: TestClient, sample_reconcile_request: OcmMachinePoolsReconcileRequest
) -> None:
    """Unauthenticated requests are rejected."""
    response = client.post(ENDPOINT, json=sample_reconcile_request.model_dump())
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_post_reconcile_invalid_body(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Invalid request bodies are rejected with 422."""
    response = client.post(ENDPOINT, json={"invalid": "body"}, headers=auth_headers)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_post_reconcile_rejects_pool_shape_mismatch(
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: OcmMachinePoolsReconcileRequest,
) -> None:
    """An OSD cluster declaring a node pool is rejected with 422."""
    request_data = sample_reconcile_request.model_dump()
    request_data["clusters"][0]["pools"][0] = {
        "id": "worker",
        "aws_node_pool": {"instance_type": "m5.xlarge"},
    }

    response = client.post(ENDPOINT, json=request_data, headers=auth_headers)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_post_reconcile_rejects_duplicate_cluster_names(
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: OcmMachinePoolsReconcileRequest,
) -> None:
    """Reject duplicate cluster names with 422.

    Two clusters with the same name would collide in the (name, pool id)
    diff key - rejected instead of silently overwriting state.
    """
    request_data = sample_reconcile_request.model_dump()
    request_data["clusters"].append(dict(request_data["clusters"][0]))

    response = client.post(ENDPOINT, json=request_data, headers=auth_headers)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@patch("qontract_api.integrations.ocm_machine_pools.router.wait_for_task_completion")
def test_get_task_status(
    mock_wait: MagicMock, client: TestClient, auth_headers: dict[str, str]
) -> None:
    """GET /reconcile/{task_id} returns the task result."""
    expected_result = OcmMachinePoolsTaskResult(
        status=TaskStatus.SUCCESS, actions=[], applied_count=0, errors=[]
    )
    mock_wait.return_value = expected_result

    response = client.get(f"{ENDPOINT}/test-task-id", headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == TaskStatus.SUCCESS.value
