"""Unit tests for Slack usergroups router endpoints."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.integrations.slack_usergroups.models import (
    SlackUsergroup,
    SlackUsergroupActionCreate,
    SlackUsergroupConfig,
    SlackUsergroupsReconcileRequest,
    SlackUsergroupsTaskResult,
    SlackWorkspace,
)
from qontract_api.models import TaskStatus, TokenData


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with valid JWT token."""
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def sample_reconcile_request() -> SlackUsergroupsReconcileRequest:
    """Create sample reconcile request."""
    return SlackUsergroupsReconcileRequest(
        workspaces=[
            SlackWorkspace(
                name="test-workspace",
                managed_usergroups=["oncall"],
                usergroups=[
                    SlackUsergroup(
                        handle="oncall",
                        config=SlackUsergroupConfig(
                            users=["alice@example.com"],
                            channels=["general"],
                            description="On-call team",
                        ),
                    )
                ],
            )
        ],
        dry_run=True,
    )


@patch(
    "qontract_api.integrations.slack_usergroups.router.reconcile_slack_usergroups_task"
)
def test_post_reconcile_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    sample_reconcile_request: SlackUsergroupsReconcileRequest,
) -> None:
    """Test POST /reconcile queues Celery task and returns task ID."""
    mock_async_result = MagicMock()
    mock_async_result.id = "test-task-id-123"
    mock_task.delay.return_value = mock_async_result

    response = client.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        json=sample_reconcile_request.model_dump(),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    data = response.json()
    assert data["id"] == "test-task-id-123"
    assert data["status"] == TaskStatus.PENDING.value
    assert "status_url" in data
    assert "/reconcile/test-task-id-123" in data["status_url"]

    mock_task.delay.assert_called_once()
    call_kwargs = mock_task.delay.call_args.kwargs
    assert call_kwargs["dry_run"] is True
    assert len(call_kwargs["workspaces"]) == 1


@patch(
    "qontract_api.integrations.slack_usergroups.router.reconcile_slack_usergroups_task"
)
def test_post_reconcile_dry_run_false(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /reconcile with dry_run=False."""
    mock_async_result = MagicMock()
    mock_async_result.id = "task-123"
    mock_task.delay.return_value = mock_async_result

    request_data = {
        "workspaces": [
            {
                "name": "test-workspace",
                "vault_token_path": "slack/test-workspace/token",
                "managed_usergroups": ["oncall"],
                "usergroups": [],
            }
        ],
        "dry_run": False,
    }

    response = client.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        json=request_data,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    call_kwargs = mock_task.delay.call_args.kwargs
    assert call_kwargs["dry_run"] is False


def test_post_reconcile_requires_auth(
    client: TestClient,
    sample_reconcile_request: SlackUsergroupsReconcileRequest,
) -> None:
    """Test POST /reconcile requires authentication."""
    response = client.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        json=sample_reconcile_request.model_dump(),
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_post_reconcile_invalid_request_body(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /reconcile validates request body."""
    invalid_data = {
        "workspaces": [
            {
                "name": "test-workspace",
            }
        ],
        "dry_run": True,
    }

    response = client.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        json=invalid_data,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@patch("qontract_api.integrations.slack_usergroups.router.get_celery_task_result")
def test_get_task_status_non_blocking_pending(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /reconcile/{task_id} non-blocking mode returns pending status."""
    mock_get_result.return_value = SlackUsergroupsTaskResult(
        status=TaskStatus.PENDING,
        actions=[],
        applied_count=0,
        errors=None,
    )

    response = client.get(
        "/api/v1/integrations/slack-usergroups/reconcile/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.PENDING.value
    assert data["actions"] == []
    assert data["applied_count"] == 0


@patch("qontract_api.integrations.slack_usergroups.router.get_celery_task_result")
def test_get_task_status_non_blocking_success(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /reconcile/{task_id} non-blocking mode returns completed task."""
    mock_get_result.return_value = SlackUsergroupsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[
            SlackUsergroupActionCreate(
                workspace="test-workspace",
                usergroup="oncall",
                users=["alice"],
                description="Test",
            )
        ],
        applied_count=1,
        errors=None,
    )

    response = client.get(
        "/api/v1/integrations/slack-usergroups/reconcile/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.SUCCESS.value
    assert len(data["actions"]) == 1
    assert data["applied_count"] == 1


@patch("qontract_api.integrations.slack_usergroups.router.get_celery_task_result")
def test_get_task_status_non_blocking_failed(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /reconcile/{task_id} non-blocking mode returns failed task."""
    mock_get_result.return_value = SlackUsergroupsTaskResult(
        status=TaskStatus.FAILED,
        actions=[],
        applied_count=0,
        errors=["test-workspace: Slack API error"],
    )

    response = client.get(
        "/api/v1/integrations/slack-usergroups/reconcile/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.FAILED.value
    assert len(data["errors"]) == 1
    assert "Slack API error" in data["errors"][0]


@patch("qontract_api.integrations.slack_usergroups.router.get_celery_task_result")
def test_get_task_status_blocking_success(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /reconcile/{task_id} blocking mode waits for completion."""
    mock_get_result.side_effect = [
        SlackUsergroupsTaskResult(
            status=TaskStatus.PENDING, actions=[], applied_count=0, errors=None
        ),
        SlackUsergroupsTaskResult(
            status=TaskStatus.SUCCESS, actions=[], applied_count=0, errors=None
        ),
    ]

    response = client.get(
        "/api/v1/integrations/slack-usergroups/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 5},
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.SUCCESS.value
    assert mock_get_result.call_count >= 2


@patch("qontract_api.integrations.slack_usergroups.router.get_celery_task_result")
def test_get_task_status_blocking_timeout(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /reconcile/{task_id} blocking mode returns 408 on timeout."""
    mock_get_result.return_value = SlackUsergroupsTaskResult(
        status=TaskStatus.PENDING, actions=[], applied_count=0, errors=None
    )

    response = client.get(
        "/api/v1/integrations/slack-usergroups/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 1},
    )

    assert response.status_code == HTTPStatus.REQUEST_TIMEOUT


def test_get_task_status_requires_auth(client: TestClient) -> None:
    """Test GET /reconcile/{task_id} requires authentication."""
    response = client.get(
        "/api/v1/integrations/slack-usergroups/reconcile/task-123",
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_get_task_status_validates_timeout_range(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /reconcile/{task_id} validates timeout parameter range."""
    response = client.get(
        "/api/v1/integrations/slack-usergroups/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 999},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    response = client.get(
        "/api/v1/integrations/slack-usergroups/reconcile/task-123",
        headers=auth_headers,
        params={"timeout": 0},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
