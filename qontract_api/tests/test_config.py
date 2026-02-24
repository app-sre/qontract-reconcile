"""Tests for configuration settings."""
# ruff: noqa: FBT001 - Boolean positional args acceptable in parametrized tests

import pytest

from qontract_api.config import Settings


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("app_name", "my-app"),
        ("version", "1.2.3"),
        ("log_level", "DEBUG"),
        ("log_format_json", False),
        ("log_exclude_loggers", "foo,bar"),
        ("cache_backend", "redis"),
        ("cache_broker_url", "redis://localhost:6379/0"),
        ("celery_broker_url", "redis://localhost:6379/1"),
        ("celery_result_backend", "redis://localhost:6379/2"),
        ("jwt_secret_key", "my-secret"),
        ("jwt_algorithm", "HS512"),
        ("jwt_expire_days", 42),
    ],
)
def test_settings_custom_values(field: str, value: str | bool | int) -> None:
    """Test Settings accepts custom values for all fields."""
    settings = Settings(**{field: value})  # type: ignore[arg-type]
    assert getattr(settings, field) == value


def test_settings_model_config_case_insensitive() -> None:
    """Test Settings model_config has case_sensitive=False."""
    assert Settings.model_config["case_sensitive"] is False


def test_settings_model_config_env_prefix() -> None:
    """Test Settings model_config has QAPI_ prefix."""
    assert Settings.model_config["env_prefix"] == "QAPI_"


def test_settings_model_config_env_nested_delimiter() -> None:
    """Test Settings model_config uses __ for nested settings."""
    assert Settings.model_config["env_nested_delimiter"] == "__"


def test_secret_model() -> None:
    """Test Secret model with all fields."""
    from qontract_api.config import Secret

    secret = Secret(path="secret/test/token", field="value", version=2)
    assert secret.path == "secret/test/token"
    assert secret.field == "value"
    assert secret.version == 2


def test_secret_model_minimal() -> None:
    """Test Secret model with only path (field and version optional)."""
    from qontract_api.config import Secret

    secret = Secret(path="secret/test/token")
    assert secret.path == "secret/test/token"
    assert secret.field is None
    assert secret.version is None


def test_slack_settings_notification_channel_default_none() -> None:
    """Test SlackSettings notification_channel defaults to None."""
    from qontract_api.config import SlackSettings

    slack = SlackSettings()
    assert slack.notification_channel is None


def test_slack_settings_notification_workspace_default_none() -> None:
    """Test SlackSettings notification_workspace defaults to None."""
    from qontract_api.config import SlackSettings

    slack = SlackSettings()
    assert slack.notification_workspace is None


def test_slack_settings_secret_path_default() -> None:
    """Test SlackSettings secret_path defaults to app-sre/slack/bot-token."""
    from qontract_api.config import SlackSettings

    slack = SlackSettings()
    assert slack.secret_path == "app-sre/slack/bot-token"


def test_slack_settings_notification_fields_custom() -> None:
    """Test SlackSettings accepts custom notification field values."""
    from qontract_api.config import SlackSettings

    slack = SlackSettings(
        notification_channel="sd-app-sre-reconcile",
        notification_workspace="app-sre",
        secret_path="custom/slack/token",
    )
    assert slack.notification_channel == "sd-app-sre-reconcile"
    assert slack.notification_workspace == "app-sre"
    assert slack.secret_path == "custom/slack/token"


def test_slack_settings_backwards_compatible() -> None:
    """Test SlackSettings maintains backwards compatibility with existing defaults."""
    from qontract_api.config import SlackSettings

    slack = SlackSettings()
    # Verify existing fields maintain their defaults
    assert slack.api_url == "https://slack.com/api/"
    assert slack.api_timeout == 30
    assert slack.api_max_retries == 100
    assert slack.usergroup_cache_ttl == 60 * 60
    assert slack.users_cache_ttl == 60 * 60 * 12
    assert slack.channels_cache_ttl == 60 * 60 * 12
    # Verify new fields have correct defaults
    assert slack.notification_channel is None
    assert slack.notification_workspace is None
    assert slack.secret_path == "app-sre/slack/bot-token"
