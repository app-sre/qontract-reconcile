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
        ("jwt_expire_minutes", 120),
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
