"""Unit tests for the Slack external chat endpoint."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.external.slack.schemas import ChatTaskResult
from qontract_api.models import TaskStatus, TokenData


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with valid JWT token."""
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def chat_request() -> dict[str, object]:
    """Create a valid chat request body."""
    return {
        "workspace_name": "test-workspace",
        "channel": "sd-app-sre-reconcile",
        "text": "Hello from qontract-api",
        "secret": {
            "secret_manager_url": "https://vault.example.com",
            "path": "app-sre/slack/bot-token",
        },
    }


@patch("qontract_api.external.slack.router.send_slack_chat_message_task")
def test_post_chat_queues_task(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    chat_request: dict[str, str],
) -> None:
    """Test POST /chat queues a Celery task and returns task ID."""
    response = client.post(
        "/api/v1/external/slack/chat",
        json=chat_request,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    data = response.json()
    request_id = response.headers[REQUEST_ID_HEADER]
    assert data["id"] == request_id
    assert data["status"] == TaskStatus.PENDING.value
    assert f"/chat/{request_id}" in data["status_url"]

    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args.kwargs
    assert call_kwargs["task_id"] == request_id
    queued_request = call_kwargs["kwargs"]["request"]
    assert queued_request.channel == "sd-app-sre-reconcile"
    assert queued_request.text == "Hello from qontract-api"


@patch("qontract_api.external.slack.router.send_slack_chat_message_task")
def test_post_chat_forwards_thread_ts(
    mock_task: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
    chat_request: dict[str, str],
) -> None:
    """Test POST /chat forwards thread_ts to the queued task's request."""
    chat_request["thread_ts"] = "1234567890.000001"
    response = client.post(
        "/api/v1/external/slack/chat",
        json=chat_request,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    queued_request = mock_task.apply_async.call_args.kwargs["kwargs"]["request"]
    assert queued_request.thread_ts == "1234567890.000001"


def test_post_chat_requires_auth(
    client: TestClient,
    chat_request: dict[str, str],
) -> None:
    """Test POST /chat requires JWT authentication."""
    response = client.post(
        "/api/v1/external/slack/chat",
        json=chat_request,
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_post_chat_invalid_request_body(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /chat returns 422 on invalid request body."""
    invalid_data = {"channel": "test"}  # missing required fields

    response = client.post(
        "/api/v1/external/slack/chat",
        json=invalid_data,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@patch("qontract_api.external.slack.router.get_celery_task_result")
def test_get_chat_task_status_non_blocking_pending(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /chat/{task_id} non-blocking mode returns pending status."""
    mock_get_result.return_value = ChatTaskResult(status=TaskStatus.PENDING)

    response = client.get(
        "/api/v1/external/slack/chat/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == TaskStatus.PENDING.value


@patch("qontract_api.external.slack.router.get_celery_task_result")
def test_get_chat_task_status_non_blocking_success(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /chat/{task_id} non-blocking mode returns completed task."""
    mock_get_result.return_value = ChatTaskResult(
        status=TaskStatus.SUCCESS,
        applied_count=1,
        ts="1234567890.123456",
        channel="C12345",
    )

    response = client.get(
        "/api/v1/external/slack/chat/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.SUCCESS.value
    assert data["ts"] == "1234567890.123456"
    assert data["channel"] == "C12345"


@patch("qontract_api.external.slack.router.get_celery_task_result")
def test_get_chat_task_status_non_blocking_failed(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /chat/{task_id} non-blocking mode returns failed task."""
    mock_get_result.return_value = ChatTaskResult(
        status=TaskStatus.FAILED,
        errors=["Slack API error: channel_not_found"],
    )

    response = client.get(
        "/api/v1/external/slack/chat/task-123",
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["status"] == TaskStatus.FAILED.value
    assert "Slack API error" in data["errors"][0]


@patch("qontract_api.external.slack.router.get_celery_task_result")
def test_get_chat_task_status_blocking_success(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /chat/{task_id} blocking mode waits for completion."""
    mock_get_result.side_effect = [
        ChatTaskResult(status=TaskStatus.PENDING),
        ChatTaskResult(status=TaskStatus.SUCCESS, ts="1.0", channel="C1"),
    ]

    response = client.get(
        "/api/v1/external/slack/chat/task-123",
        headers=auth_headers,
        params={"timeout": 5},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == TaskStatus.SUCCESS.value
    assert mock_get_result.call_count >= 2


@patch("qontract_api.external.slack.router.get_celery_task_result")
def test_get_chat_task_status_blocking_timeout(
    mock_get_result: MagicMock,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /chat/{task_id} blocking mode returns 408 on timeout."""
    mock_get_result.return_value = ChatTaskResult(status=TaskStatus.PENDING)

    response = client.get(
        "/api/v1/external/slack/chat/task-123",
        headers=auth_headers,
        params={"timeout": 1},
    )

    assert response.status_code == HTTPStatus.REQUEST_TIMEOUT


def test_get_chat_task_status_requires_auth(client: TestClient) -> None:
    """Test GET /chat/{task_id} requires authentication."""
    response = client.get("/api/v1/external/slack/chat/task-123")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
