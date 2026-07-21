"""Unit tests for Slack external chat endpoint."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from qontract_utils.slack_api import (
    ChatPostMessageResponse,
    SlackApiError,
    SlackMessage,
    SlackMessageAttachment,
    SlackMessageReaction,
)

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
def api_client() -> Generator[TestClient]:
    """Create test client with mocked cache and secret_manager in app.state."""
    from qontract_api.main import app

    app.state.cache = Mock()
    app.state.secret_manager = Mock()

    yield TestClient(app, raise_server_exceptions=False)

    if hasattr(app.state, "cache"):
        del app.state.cache
    if hasattr(app.state, "secret_manager"):
        del app.state.secret_manager


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

    assert response.status_code == HTTPStatus.UNAUTHORIZED


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


@pytest.fixture
def conversation_history_query() -> dict[str, str]:
    """Query params for the conversation history endpoint."""
    return {
        "workspace_name": "test-workspace",
        "channel": "sd-app-sre-reconcile",
        "from_timestamp": "1700000000",
        "secret_manager_url": "https://vault.example.com",
        "path": "app-sre/slack/bot-token",
    }


@patch("qontract_api.external.slack.router.create_slack_workspace_client")
def test_get_conversations_history_success(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
    conversation_history_query: dict[str, str],
) -> None:
    """Test GET /conversations/history returns messages on success."""
    mock_client = MagicMock()
    mock_client.get_flat_conversation_history.return_value = [
        SlackMessage(
            ts="1700000002.000000",
            text="alert fired",
            subtype="bot_message",
            username="alertbot",
            reply_count=1,
            reactions=[SlackMessageReaction(name="eyes", count=2)],
            attachments=[
                SlackMessageAttachment(title="Alert: Foo [FIRING:1]", text="bar")
            ],
        )
    ]
    mock_factory.return_value = mock_client

    response = api_client.get(
        "/api/v1/external/slack/conversations/history",
        params=conversation_history_query,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert len(data["messages"]) == 1
    message = data["messages"][0]
    assert message["ts"] == "1700000002.000000"
    assert message["subtype"] == "bot_message"
    assert message["username"] == "alertbot"
    assert message["reply_count"] == 1
    assert message["reactions"][0]["name"] == "eyes"
    assert message["attachments"][0]["title"] == "Alert: Foo [FIRING:1]"

    mock_client.get_flat_conversation_history.assert_called_once_with(
        channel="sd-app-sre-reconcile",
        from_timestamp=1700000000,
        to_timestamp=None,
    )


@patch("qontract_api.external.slack.router.create_slack_workspace_client")
def test_get_conversations_history_forwards_to_timestamp(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
    conversation_history_query: dict[str, str],
) -> None:
    """Test GET /conversations/history forwards to_timestamp when provided."""
    mock_client = MagicMock()
    mock_client.get_flat_conversation_history.return_value = []
    mock_factory.return_value = mock_client

    conversation_history_query["to_timestamp"] = "1700000100"
    response = api_client.get(
        "/api/v1/external/slack/conversations/history",
        params=conversation_history_query,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    mock_client.get_flat_conversation_history.assert_called_once_with(
        channel="sd-app-sre-reconcile",
        from_timestamp=1700000000,
        to_timestamp=1700000100,
    )


@patch("qontract_api.external.slack.router.create_slack_workspace_client")
def test_get_conversations_history_channel_not_found_returns_404(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
    conversation_history_query: dict[str, str],
) -> None:
    """Test GET /conversations/history returns 404 when channel is not found."""
    mock_client = MagicMock()
    mock_client.get_flat_conversation_history.side_effect = ValueError(
        "Channel 'sd-app-sre-reconcile' not found"
    )
    mock_factory.return_value = mock_client

    response = api_client.get(
        "/api/v1/external/slack/conversations/history",
        params=conversation_history_query,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


@patch("qontract_api.external.slack.router.create_slack_workspace_client")
def test_get_conversations_history_slack_api_error_returns_502(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
    conversation_history_query: dict[str, str],
) -> None:
    """Test GET /conversations/history returns 502 when SlackApiError is raised."""
    mock_client = MagicMock()
    error_response = MagicMock()
    error_response.__getitem__ = MagicMock(return_value="internal_error")
    mock_client.get_flat_conversation_history.side_effect = SlackApiError(
        "internal_error", response=error_response
    )
    mock_factory.return_value = mock_client

    response = api_client.get(
        "/api/v1/external/slack/conversations/history",
        params=conversation_history_query,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.BAD_GATEWAY
    data = response.json()
    assert "Slack API error" in data["detail"]


def test_get_conversations_history_requires_auth(
    client: TestClient,
    conversation_history_query: dict[str, str],
) -> None:
    """Test GET /conversations/history requires JWT authentication."""
    response = client.get(
        "/api/v1/external/slack/conversations/history",
        params=conversation_history_query,
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED
