"""Unit tests for SlackApiFactory."""

# ruff: noqa: S106 - Hardcoded tokens acceptable in tests
# ruff: noqa: PLR2004 - Magic values acceptable in tests for readability

from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.slack_api import SlackApi, SlackApiCallContext

from qontract_api.config import Settings, SlackSettings
from qontract_api.integrations.slack_usergroups.slack_factory import create_slack_api


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create mock cache backend."""
    cache = MagicMock()
    cache.get = MagicMock(return_value=None)
    cache.set = MagicMock(return_value=None)
    return cache


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        cache_backend="redis",
        cache_broker_url="redis://localhost:6379/0",
    )


@patch("qontract_api.integrations.slack_usergroups.slack_factory.SlackApi")
def test_create_slack_api_returns_slack_api_instance(
    mock_slack_api_class: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> None:
    """Test that create_slack_api returns SlackApi instance."""
    mock_instance = MagicMock(spec=SlackApi)
    mock_slack_api_class.return_value = mock_instance

    result = create_slack_api(
        workspace_name="test-workspace",
        token="test-token",
        cache=mock_cache,
        settings=settings,
    )

    assert result == mock_instance
    mock_slack_api_class.assert_called_once()


@patch("qontract_api.integrations.slack_usergroups.slack_factory.SlackApi")
def test_create_slack_api_configures_rate_limiting(
    mock_slack_api_class: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> None:
    """Test that create_slack_api configures rate limiting hook."""
    mock_instance = MagicMock(spec=SlackApi)
    mock_slack_api_class.return_value = mock_instance

    create_slack_api(
        workspace_name="test-workspace",
        token="test-token",
        cache=mock_cache,
        settings=settings,
    )

    # Verify SlackApi was called with before_api_call_hooks
    call_kwargs = mock_slack_api_class.call_args.kwargs
    assert "before_api_call_hooks" in call_kwargs
    assert isinstance(call_kwargs["before_api_call_hooks"], list)
    assert len(call_kwargs["before_api_call_hooks"]) == 1
    assert callable(call_kwargs["before_api_call_hooks"][0])


@patch("qontract_api.integrations.slack_usergroups.slack_factory.SlackApi")
def test_create_slack_api_passes_workspace_and_token(
    mock_slack_api_class: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> None:
    """Test that create_slack_api passes workspace name and token to SlackApi."""
    mock_instance = MagicMock(spec=SlackApi)
    mock_slack_api_class.return_value = mock_instance

    create_slack_api(
        workspace_name="test-workspace",
        token="test-token",
        cache=mock_cache,
        settings=settings,
    )

    # Check positional args (workspace_name, token)
    call_args = mock_slack_api_class.call_args.args
    assert call_args[0] == "test-workspace"
    assert call_args[1] == "test-token"

    # Check keyword args - timeout and max_retries should be passed
    call_kwargs = mock_slack_api_class.call_args.kwargs
    assert "timeout" in call_kwargs
    assert "max_retries" in call_kwargs


@patch("qontract_api.integrations.slack_usergroups.slack_factory.TokenBucket")
@patch("qontract_api.integrations.slack_usergroups.slack_factory.SlackApi")
def test_create_slack_api_configures_token_bucket_from_settings(
    mock_slack_api_class: MagicMock,
    mock_token_bucket_class: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> None:
    """Test that create_slack_api configures TokenBucket from settings."""
    mock_slack_instance = MagicMock(spec=SlackApi)
    mock_slack_api_class.return_value = mock_slack_instance

    mock_bucket = MagicMock()
    mock_token_bucket_class.return_value = mock_bucket

    create_slack_api(
        workspace_name="test-workspace",
        token="test-token",
        cache=mock_cache,
        settings=settings,
    )

    # Verify TokenBucket was created with correct settings
    mock_token_bucket_class.assert_called_once_with(
        cache=mock_cache,
        bucket_name="slack:tier2:test-workspace",
        capacity=20,
        refill_rate=1.0,
    )


@patch("qontract_api.integrations.slack_usergroups.slack_factory.TokenBucket")
@patch("qontract_api.integrations.slack_usergroups.slack_factory.SlackApi")
def test_rate_limit_hook_calls_token_bucket_acquire(
    mock_slack_api_class: MagicMock,
    mock_token_bucket_class: MagicMock,
    mock_cache: MagicMock,
    settings: Settings,
) -> None:
    """Test that rate limit hook calls TokenBucket.acquire."""
    mock_slack_instance = MagicMock(spec=SlackApi)
    mock_slack_api_class.return_value = mock_slack_instance

    mock_bucket = MagicMock()
    mock_token_bucket_class.return_value = mock_bucket

    create_slack_api(
        workspace_name="test-workspace",
        token="test-token",
        cache=mock_cache,
        settings=settings,
    )

    # Get the hook function that was passed to SlackApi
    call_kwargs = mock_slack_api_class.call_args.kwargs
    hooks = call_kwargs["before_api_call_hooks"]
    assert len(hooks) == 1
    rate_limit_hook = hooks[0]

    # Call the hook with a mock context
    mock_context = SlackApiCallContext(
        method="test.method", verb="POST", workspace="test-workspace"
    )
    rate_limit_hook(mock_context)

    # Verify it called acquire on the token bucket
    mock_bucket.acquire.assert_called_once_with(tokens=1, timeout=30)


@patch("qontract_api.integrations.slack_usergroups.slack_factory.SlackApi")
def test_create_slack_api_with_custom_tier(
    mock_slack_api_class: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test that create_slack_api uses custom rate limit tier from settings."""
    mock_instance = MagicMock(spec=SlackApi)
    mock_slack_api_class.return_value = mock_instance

    custom_settings = Settings(
        cache_backend="redis",
        cache_broker_url="redis://localhost:6379/0",
        slack=SlackSettings(
            rate_limit_tier="tier4",
            rate_limit_tokens=100,
            rate_limit_refill_rate=10.0,
        ),
    )

    with patch(
        "qontract_api.integrations.slack_usergroups.slack_factory.TokenBucket"
    ) as mock_bucket_class:
        create_slack_api(
            workspace_name="test-workspace",
            token="test-token",
            cache=mock_cache,
            settings=custom_settings,
        )

        # Verify bucket name includes custom tier
        call_kwargs = mock_bucket_class.call_args.kwargs
        assert call_kwargs["bucket_name"] == "slack:tier4:test-workspace"
        assert call_kwargs["capacity"] == 100
        assert call_kwargs["refill_rate"] == 10.0
