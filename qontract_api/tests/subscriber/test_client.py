"""Tests for subscriber _client module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_api_client.schemas import ChatRequest, Secret

_MOD = "qontract_api.subscriber._client"


@pytest.fixture(autouse=True)
def _reset_client_configured() -> None:
    """Reset the module-level _client_configured flag between tests."""
    import qontract_api.subscriber._client as mod

    mod._client_configured = False


def _configure_settings(mock: MagicMock) -> None:
    """Set up mock settings with subscriber and secrets config."""
    mock.subscriber.slack_workspace = "test-workspace"
    mock.subscriber.slack_channel = "test-channel"
    mock.subscriber.slack_username = "test-bot"
    mock.subscriber.slack_icon_emoji = ":robot:"
    mock.subscriber.slack_token.path = "secret/slack"
    mock.subscriber.slack_token.field = "token"
    mock.subscriber.slack_token.version = 1
    mock.subscriber.qontract_api_url = "http://localhost:8080"
    mock.subscriber.qontract_api_token = "test-token"
    mock.secrets.default_provider_url = "https://vault.example.com"


@pytest.mark.asyncio
@patch(f"{_MOD}.post_chat", new_callable=AsyncMock)
@patch(f"{_MOD}.settings")
async def test_post_to_slack_sends_chat_request(
    mock_settings: MagicMock,
    mock_post_chat: AsyncMock,
) -> None:
    """post_to_slack builds a ChatRequest with channel and posts it."""
    _configure_settings(mock_settings)

    from qontract_api.subscriber._client import post_to_slack

    await post_to_slack("Hello world")

    mock_post_chat.assert_called_once()
    request = mock_post_chat.call_args.args[0]
    assert isinstance(request, ChatRequest)
    assert request.workspace_name == "test-workspace"
    assert request.channel == "test-channel"
    assert request.text == "Hello world"
    assert request.user is None
    assert request.username == "test-bot"
    assert request.icon_emoji == ":robot:"
    assert isinstance(request.secret, Secret)
    assert request.secret.path == "secret/slack"
    assert request.secret.field == "token"
    assert request.secret.version == 1
    assert request.secret.secret_manager_url == "https://vault.example.com"


@pytest.mark.asyncio
@patch(f"{_MOD}.qontract_api_client")
@patch(f"{_MOD}.post_chat", new_callable=AsyncMock)
@patch(f"{_MOD}.settings")
async def test_post_to_slack_raises_when_slack_token_is_none(
    mock_settings: MagicMock,
    mock_post_chat: AsyncMock,
    mock_client: MagicMock,
) -> None:
    """post_to_slack raises RuntimeError when slack_token is None."""
    _configure_settings(mock_settings)
    mock_settings.subscriber.slack_token = None

    from qontract_api.subscriber._client import post_to_slack

    with pytest.raises(RuntimeError, match="slack_token not configured"):
        await post_to_slack("Hello")

    mock_post_chat.assert_not_called()


@pytest.mark.asyncio
@patch(f"{_MOD}.post_chat", new_callable=AsyncMock)
@patch(f"{_MOD}.settings")
async def test_send_dm_sends_chat_request_with_user(
    mock_settings: MagicMock,
    mock_post_chat: AsyncMock,
) -> None:
    """send_dm builds a ChatRequest with user field instead of channel."""
    _configure_settings(mock_settings)

    from qontract_api.subscriber._client import send_dm

    await send_dm(org_username="alice", text="Hi Alice")

    mock_post_chat.assert_called_once()
    request = mock_post_chat.call_args.args[0]
    assert isinstance(request, ChatRequest)
    assert request.user == "alice"
    assert request.text == "Hi Alice"
    assert request.workspace_name == "test-workspace"
    assert request.channel is None
    assert request.secret.path == "secret/slack"


@pytest.mark.asyncio
@patch(f"{_MOD}.qontract_api_client")
@patch(f"{_MOD}.post_chat", new_callable=AsyncMock)
@patch(f"{_MOD}.settings")
async def test_send_dm_raises_when_slack_token_is_none(
    mock_settings: MagicMock,
    mock_post_chat: AsyncMock,
    mock_client: MagicMock,
) -> None:
    """send_dm raises RuntimeError when slack_token is None."""
    _configure_settings(mock_settings)
    mock_settings.subscriber.slack_token = None

    from qontract_api.subscriber._client import send_dm

    with pytest.raises(RuntimeError, match="slack_token not configured"):
        await send_dm(org_username="alice", text="Hi")

    mock_post_chat.assert_not_called()


@patch(f"{_MOD}.qontract_api_client")
@patch(f"{_MOD}.settings")
def test_setup_client_configures_client(
    mock_settings: MagicMock,
    mock_client: MagicMock,
) -> None:
    """_setup_client configures the clientele client with URL and token."""
    _configure_settings(mock_settings)

    from qontract_api.subscriber._client import _setup_client

    _setup_client()

    mock_client.configure.assert_called_once()
    config = mock_client.configure.call_args.kwargs["config"]
    assert config.base_url == "http://localhost:8080"
    assert config.headers["Authorization"] == "Bearer test-token"
    assert config.timeout == 30


@patch(f"{_MOD}.qontract_api_client")
@patch(f"{_MOD}.settings")
def test_setup_client_raises_when_token_empty(
    mock_settings: MagicMock,
    mock_client: MagicMock,
) -> None:
    """_setup_client raises RuntimeError when qontract_api_token is not set."""
    mock_settings.subscriber.qontract_api_token = ""

    from qontract_api.subscriber._client import _setup_client

    with pytest.raises(RuntimeError, match="qontract_api_token not set"):
        _setup_client()

    mock_client.configure.assert_not_called()
