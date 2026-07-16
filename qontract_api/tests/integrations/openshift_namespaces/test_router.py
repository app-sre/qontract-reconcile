"""Tests for openshift-namespaces router."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.models import TokenData
from qontract_api.tasks import QUEUE_MR_CHECK, QUEUE_PROD


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with valid JWT token."""
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


def _request_body(*, dry_run: bool = True) -> dict:
    return {
        "clusters": [
            {
                "cluster_name": "prod-1",
                "server_url": "https://prod-1:6443",
                "automation_token": {
                    "secret_manager_url": "https://vault",
                    "path": "k8s/prod/token",
                    "field": "token",
                },
                "namespaces": [{"name": "app-a"}],
            }
        ],
        "dry_run": dry_run,
    }


@patch(
    "qontract_api.integrations.openshift_namespaces.router.reconcile_openshift_namespaces_task"
)
def test_post_reconcile_returns_202(
    mock_task: MagicMock,
    client_with_cache: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """POST /reconcile returns 202 and queues task."""
    response = client_with_cache.post(
        "/api/v1/integrations/openshift-namespaces/reconcile",
        json=_request_body(),
        headers=auth_headers,
    )
    assert response.status_code == 202
    data = response.json()
    assert "id" in data
    assert data["status"] == "pending"
    assert "status_url" in data
    mock_task.apply_async.assert_called_once()
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_MR_CHECK


@patch(
    "qontract_api.integrations.openshift_namespaces.router.reconcile_openshift_namespaces_task"
)
def test_post_reconcile_dry_run_false_uses_prod_queue(
    mock_task: MagicMock,
    client_with_cache: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """POST /reconcile with dry_run=False routes to the prod queue."""
    response = client_with_cache.post(
        "/api/v1/integrations/openshift-namespaces/reconcile",
        json=_request_body(dry_run=False),
        headers=auth_headers,
    )
    assert response.status_code == 202
    mock_task.apply_async.assert_called_once()
    assert mock_task.apply_async.call_args.kwargs["queue"] == QUEUE_PROD


@patch(
    "qontract_api.integrations.openshift_namespaces.router.reconcile_openshift_namespaces_task"
)
def test_post_reconcile_requires_auth(
    mock_task: MagicMock,
    client_with_cache: TestClient,
) -> None:
    """POST without auth returns 401."""
    response = client_with_cache.post(
        "/api/v1/integrations/openshift-namespaces/reconcile",
        json=_request_body(),
    )
    assert response.status_code == 401
