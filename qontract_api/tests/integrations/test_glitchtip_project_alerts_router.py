"""Unit tests for Glitchtip project alerts router endpoints."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.integrations.glitchtip_project_alerts.models import (
    GlitchtipInstance,
    GlitchtipOrganization,
    GlitchtipProjectAlertsReconcileRequest,
    GlitchtipProjectAlertsTaskResult,
)
from qontract_api.models import Secret, TaskStatus, TokenData


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with valid JWT token."""
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def sample_reconcile_request() -> GlitchtipProjectAlertsReconcileRequest:
    """Create sample reconcile request."""
    return GlitchtipProjectAlertsReconcileRequest(
        instances=[
            GlitchtipInstance(
                name="test-instance",
                console_url="https://glitchtip.example.com",
                token=Secret(
                    secret_manager_url="https://vault.example.com",
                    path="secret/glitchtip/token",
                ),
                organizations=[GlitchtipOrganization(name="my-org", projects=[])],
            )
        ],
        dry_run=True,
    )


@patch(
    "qontract_api.integrations.glitchtip_project_alerts.router.reconcile_glitchtip_project_alerts_task"
)
def test_post_reconcile_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: GlitchtipProjectAlertsReconcileRequest,
) -> None:
    """Test POST /reconcile queues Celery task and returns task ID."""
    response = client.post(
        "/api/v1/integrations/glitchtip-project-alerts/reconcile",
        json=sample_reconcile_request.model_dump(),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    data = response.json()
    request_id = response.headers[REQUEST_ID_HEADER]
    assert data["id"] == request_id
    assert data["status"] == TaskStatus.PENDING.value
    assert "status_url" in data
    assert f"/reconcile/{request_id}" in data["status_url"]

    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["dry_run"] is True
    assert len(call_kwargs["instances"]) == 1


@patch(
    "qontract_api.integrations.glitchtip_project_alerts.router.reconcile_glitchtip_project_alerts_task"
)
def test_post_reconcile_dry_run_false(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /reconcile with dry_run=False."""
    request_data = {
        "instances": [
            {
                "name": "test-instance",
                "console_url": "https://glitchtip.example.com",
                "token": {
                    "secret_manager_url": "https://vault.example.com",
                    "path": "secret/glitchtip/token",
                },
                "organizations": [],
            }
        ],
        "dry_run": False,
    }

    response = client.post(
        "/api/v1/integrations/glitchtip-project-alerts/reconcile",
        json=request_data,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["dry_run"] is False


def test_post_reconcile_requires_auth(
    client: TestClient,
    sample_reconcile_request: GlitchtipProjectAlertsReconcileRequest,
) -> None:
    """Test POST /reconcile requires authentication."""
    response = client.post(
        "/api/v1/integrations/glitchtip-project-alerts/reconcile",
        json=sample_reconcile_request.model_dump(),
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_post_reconcile_invalid_request_body(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /reconcile rejects invalid request body."""
    response = client.post(
        "/api/v1/integrations/glitchtip-project-alerts/reconcile",
        json={"invalid": "body"},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@patch(
    "qontract_api.integrations.glitchtip_project_alerts.router.wait_for_task_completion"
)
def test_get_task_status(
    mock_wait: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /reconcile/{task_id} returns task result."""
    expected_result = GlitchtipProjectAlertsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[],
        applied_count=0,
        errors=[],
    )
    mock_wait.return_value = expected_result

    response = client.get(
        "/api/v1/integrations/glitchtip-project-alerts/reconcile/test-task-id",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.SUCCESS.value
