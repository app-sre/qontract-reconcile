"""Tests for openshift-namespaces router."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.models import TokenData


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with valid JWT token."""
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


def _request_body() -> dict:
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
        "dry_run": True,
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
