"""Unit tests for Slack external chat endpoint."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from qontract_utils.slack_api import ChatPostMessageResponse, SlackApiError

from qontract_api.auth import create_access_token
from qontract_api.models import TokenData


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


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    """Create test client with mocked cache and secret_manager in app.state."""
    from qontract_api.main import app

    app.state.cache = Mock()
    app.state.secret_manager = Mock()

    yield TestClient(app, raise_server_exceptions=False)

    if hasattr(app.state, "cache"):
        delattr(app.state, "cache")
    if hasattr(app.state, "secret_manager"):
        delattr(app.state, "secret_manager")


@patch("qontract_api.external.slack.router.create_slack_workspace_client")
def test_post_chat_success(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
    chat_request: dict[str, str],
) -> None:
    """Test POST /chat returns 200 with ts and channel on success."""
    mock_client = MagicMock()
    mock_client.chat_post_message.return_value = ChatPostMessageResponse(
        ts="1234567890.123456",
        channel="C12345",
    )
    mock_factory.return_value = mock_client

    response = api_client.post(
        "/api/v1/external/slack/chat",
        json=chat_request,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["ts"] == "1234567890.123456"
    assert data["channel"] == "C12345"
    assert data["thread_ts"] is None


@patch("qontract_api.external.slack.router.create_slack_workspace_client")
def test_post_chat_with_thread_ts(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
    chat_request: dict[str, str],
) -> None:
    """Test POST /chat forwards thread_ts and returns it in response."""
    mock_client = MagicMock()
    mock_client.chat_post_message.return_value = ChatPostMessageResponse(
        ts="1234567890.999999",
        channel="C12345",
        thread_ts="1234567890.000001",
    )
    mock_factory.return_value = mock_client

    chat_request["thread_ts"] = "1234567890.000001"
    response = api_client.post(
        "/api/v1/external/slack/chat",
        json=chat_request,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["thread_ts"] == "1234567890.000001"

    mock_client.chat_post_message.assert_called_once_with(
        channel="sd-app-sre-reconcile",
        text="Hello from qontract-api",
        thread_ts="1234567890.000001",
        icon_emoji=None,
        icon_url=None,
        username=None,
    )


@patch("qontract_api.external.slack.router.create_slack_workspace_client")
def test_post_chat_slack_api_error_returns_502(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
    chat_request: dict[str, str],
) -> None:
    """Test POST /chat returns 502 when SlackApiError is raised."""
    mock_client = MagicMock()
    error_response = MagicMock()
    error_response.__getitem__ = MagicMock(return_value="channel_not_found")
    mock_client.chat_post_message.side_effect = SlackApiError(
        "channel_not_found", response=error_response
    )
    mock_factory.return_value = mock_client

    response = api_client.post(
        "/api/v1/external/slack/chat",
        json=chat_request,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.BAD_GATEWAY
    data = response.json()
    assert "Slack API error" in data["detail"]


def test_post_chat_requires_auth(
    client: TestClient,
    chat_request: dict[str, str],
) -> None:
    """Test POST /chat requires JWT authentication."""
    response = client.post(
        "/api/v1/external/slack/chat",
        json=chat_request,
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_post_chat_invalid_request_body(
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /chat returns 422 on invalid request body."""
    invalid_data = {"channel": "test"}  # missing required fields

    response = api_client.post(
        "/api/v1/external/slack/chat",
        json=invalid_data,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
