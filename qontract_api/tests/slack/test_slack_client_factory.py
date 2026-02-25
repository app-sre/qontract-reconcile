"""Unit tests for create_slack_workspace_client factory function."""

from unittest.mock import MagicMock

from qontract_api.config import Settings
from qontract_api.models import Secret
from qontract_api.slack.slack_client_factory import create_slack_workspace_client
from qontract_api.slack.slack_workspace_client import SlackWorkspaceClient


def test_create_slack_workspace_client_resolves_secret(
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    """Verify factory calls secret_manager.read(secret) with the provided Secret object."""
    secret = Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/slack/test-workspace",
    )
    mock_secret_manager.read.return_value = "xoxb-test-token"

    create_slack_workspace_client(
        secret=secret,
        workspace_name="test-workspace",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    mock_secret_manager.read.assert_called_once_with(secret)


def test_create_slack_workspace_client_creates_slack_api(
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    """Verify the returned client has a SlackApi with correct workspace_name."""
    secret = Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/slack/test-workspace",
    )
    mock_secret_manager.read.return_value = "xoxb-test-token"

    client = create_slack_workspace_client(
        secret=secret,
        workspace_name="test-workspace",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    # Verify client has SlackApi with correct workspace_name
    assert client.slack_api is not None
    assert client.slack_api.workspace_name == "test-workspace"


def test_create_slack_workspace_client_returns_workspace_client(
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    """Verify return type is SlackWorkspaceClient with correct slack_api, cache, settings."""
    secret = Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/slack/test-workspace",
    )
    mock_secret_manager.read.return_value = "xoxb-test-token"

    client = create_slack_workspace_client(
        secret=secret,
        workspace_name="test-workspace",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    assert isinstance(client, SlackWorkspaceClient)
    assert client.slack_api is not None
    assert client.cache is mock_cache
    assert client.settings is mock_settings
