"""Tests for the endpoints-discovery router."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.integrations.endpoints_discovery.schemas import (
    EndpointsDiscoveryTaskResult,
)
from qontract_api.models import TaskStatus, TokenData
from qontract_api.tasks import QUEUE_MR_CHECK, QUEUE_PROD

RECONCILE_PATH = "/api/v1/integrations/endpoints-discovery/reconcile"


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token(data=TokenData(sub="testuser"))
    return {"Authorization": f"Bearer {token}"}


def _secret() -> dict:
    return {
        "secret_manager_url": "https://vault.example.org",
        "path": "cluster/token",
        "field": "token",
    }


def _request_body(*, dry_run: bool = True) -> dict:
    return {
        "endpoint_template": "name: {{ endpoint_name }}\nurl: {{ route.url }}\n",
        "app_interface": {
            "repo_url": "https://gitlab.example.com/group/app-interface",
            "token": _secret(),
            "target_branch": "master",
        },
        "apps": [
            {
                "name": "app-1",
                "path": "/services/app-1/app.yml",
                "end_points": [],
                "namespaces": [
                    {
                        "name": "ns-1",
                        "cluster": {
                            "cluster_name": "cluster-1",
                            "server_url": "https://cluster-1:6443",
                            "automation_token": _secret(),
                        },
                    }
                ],
            }
        ],
        "auto_merge": False,
        "dry_run": dry_run,
    }


@patch(
    "qontract_api.integrations.endpoints_discovery.router.reconcile_endpoints_discovery_task"
)
def test_post_reconcile_returns_202(
    mock_task: MagicMock,
    client_with_cache: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """POST /reconcile returns 202 and queues the task with the request."""
    response = client_with_cache.post(
        RECONCILE_PATH,
        json=_request_body(),
        headers=auth_headers,
    )

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "pending"
    assert data["id"]
    assert data["status_url"].endswith(
        f"/api/v1/integrations/endpoints-discovery/reconcile/{data['id']}"
    )

    mock_task.apply_async.assert_called_once()
    call = mock_task.apply_async.call_args.kwargs
    assert call["queue"] == QUEUE_MR_CHECK
    assert call["task_id"] == data["id"]
    assert call["kwargs"]["dry_run"] is True
    assert call["kwargs"]["request"].apps[0].name == "app-1"


@patch(
    "qontract_api.integrations.endpoints_discovery.router.reconcile_endpoints_discovery_task"
)
def test_post_reconcile_live_uses_prod_queue(
    mock_task: MagicMock,
    client_with_cache: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A live request is routed to the production queue."""
    response = client_with_cache.post(
        RECONCILE_PATH,
        json=_request_body(dry_run=False),
        headers=auth_headers,
    )

    assert response.status_code == 202
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_PROD


@patch(
    "qontract_api.integrations.endpoints_discovery.router.reconcile_endpoints_discovery_task"
)
def test_post_reconcile_requires_auth(
    mock_task: MagicMock,
    client_with_cache: TestClient,
) -> None:
    """POST without authentication returns 401."""
    response = client_with_cache.post(RECONCILE_PATH, json=_request_body())

    assert response.status_code == 401
    mock_task.apply_async.assert_not_called()


@patch(
    "qontract_api.integrations.endpoints_discovery.router.wait_for_task_completion",
    new_callable=AsyncMock,
)
def test_get_task_status_delegates_to_waiter(
    mock_wait: AsyncMock,
    client_with_cache: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /reconcile/{task_id} returns the task result via the shared waiter."""
    expected = EndpointsDiscoveryTaskResult(status=TaskStatus.SUCCESS)
    mock_wait.return_value = expected

    response = client_with_cache.get(
        f"{RECONCILE_PATH}/task-id",
        params={"timeout": 1},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_wait.assert_awaited_once()
