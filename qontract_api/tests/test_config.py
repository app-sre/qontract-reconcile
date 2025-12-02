"""Tests for configuration settings."""


# ruff: noqa: FBT001 - Boolean positional args acceptable in parametrized tests
# ruff: noqa: PLC1901

import pytest
from pydantic import ValidationError

from qontract_api.config import Settings, SlackSettings


def test_settings_defaults() -> None:
    """Test Settings uses default values."""
    settings = Settings()
    assert settings.app_name == "qontract-api"
    assert settings.version == "0.1.0"
    assert settings.debug is False
    assert settings.log_level == "INFO"
    assert settings.log_format_json is True
    assert settings.log_exclude_loggers == "slack_sdk,httpcore,github.Requester"
    assert settings.cache_backend == "redis"
    assert settings.cache_broker_url == "redis://localhost:6379/0"
    assert not settings.celery_broker_url
    assert not settings.celery_result_backend
    assert settings.jwt_secret_key == "dev-secret-key-change-in-production"
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expire_minutes == 60


def test_slack_settings_defaults() -> None:
    """Test SlackSettings uses default values."""
    slack = SlackSettings()
    assert slack.api_timeout == 30
    assert slack.api_max_retries == 5
    assert slack.api_method_configs == {
        "users.list": {"limit": 1000},
        "conversations.list": {"limit": 1000},
    }
    assert slack.rate_limit_tier == "tier2"
    assert slack.rate_limit_tokens == 20
    assert slack.rate_limit_refill_rate == 1.0
    assert slack.usergroup_cache_ttl >= 300
    assert slack.users_cache_ttl >= 900
    assert slack.channels_cache_ttl >= 900


def test_settings_with_nested_slack_defaults() -> None:
    """Test Settings includes nested SlackSettings with defaults."""
    settings = Settings()
    assert isinstance(settings.slack, SlackSettings)
    assert settings.slack.api_timeout == 30
    assert settings.slack.rate_limit_tier == "tier2"


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_timeout", 60),
        ("api_max_retries", 10),
        ("rate_limit_tier", "tier4"),
        ("rate_limit_tokens", 100),
        ("rate_limit_refill_rate", 5.0),
        ("usergroup_cache_ttl", 600),
        ("users_cache_ttl", 1800),
        ("channels_cache_ttl", 1800),
    ],
)
def test_slack_settings_custom_values(field: str, value: str | float) -> None:
    """Test SlackSettings accepts custom values for all fields."""
    slack = SlackSettings(**{field: value})
    assert getattr(slack, field) == value


def test_slack_settings_custom_method_configs() -> None:
    """Test SlackSettings accepts custom api_method_configs."""
    method_configs = {
        "users.list": {"limit": 500},
        "conversations.list": {"limit": 200},
        "custom.method": {"foo": "bar"},
    }
    slack = SlackSettings(api_method_configs=method_configs)
    assert slack.api_method_configs == method_configs


def test_settings_with_custom_slack_settings() -> None:
    """Test Settings accepts custom nested SlackSettings."""
    slack = SlackSettings(
        api_timeout=90,
        rate_limit_tier="tier4",
        rate_limit_tokens=100,
    )
    settings = Settings(slack=slack)
    assert settings.slack.api_timeout == 90
    assert settings.slack.rate_limit_tier == "tier4"
    assert settings.slack.rate_limit_tokens == 100


@pytest.mark.parametrize(
    ("log_level", "expected"),
    [
        ("DEBUG", "DEBUG"),
        ("INFO", "INFO"),
        ("WARNING", "WARNING"),
        ("ERROR", "ERROR"),
        ("CRITICAL", "CRITICAL"),
    ],
)
def test_settings_log_level_values(log_level: str, expected: str) -> None:
    """Test Settings accepts valid log levels."""
    settings = Settings(log_level=log_level)
    assert settings.log_level == expected


@pytest.mark.parametrize(
    ("debug", "expected"),
    [
        (True, True),
        (False, False),
    ],
)
def test_settings_debug_flag(debug: bool, expected: bool) -> None:
    """Test Settings debug flag."""
    settings = Settings(debug=debug)
    assert settings.debug == expected


@pytest.mark.parametrize(
    ("backend", "broker_url"),
    [
        ("memory", ""),
        ("redis", "redis://localhost:6379/0"),
        ("redis", "redis://redis:6379/0"),
    ],
)
def test_settings_cache_configuration(backend: str, broker_url: str) -> None:
    """Test Settings cache configuration combinations."""
    settings = Settings(cache_backend=backend, cache_broker_url=broker_url)
    assert settings.cache_backend == backend
    assert settings.cache_broker_url == broker_url


@pytest.mark.parametrize(
    ("jwt_algorithm", "expire_minutes"),
    [
        ("HS256", 60),
        ("HS384", 120),
        ("HS512", 30),
    ],
)
def test_settings_jwt_configuration(jwt_algorithm: str, expire_minutes: int) -> None:
    """Test Settings JWT configuration."""
    settings = Settings(jwt_algorithm=jwt_algorithm, jwt_expire_minutes=expire_minutes)
    assert settings.jwt_algorithm == jwt_algorithm
    assert settings.jwt_expire_minutes == expire_minutes


@pytest.mark.parametrize(
    ("tier", "tokens", "refill_rate"),
    [
        ("tier1", 1, 1.0),
        ("tier2", 20, 1.0),
        ("tier3", 50, 1.0),
        ("tier4", 100, 10.0),
    ],
)
def test_slack_settings_rate_limit_tiers(
    tier: str, tokens: int, refill_rate: float
) -> None:
    """Test SlackSettings rate limit tier configurations."""
    slack = SlackSettings(
        rate_limit_tier=tier,
        rate_limit_tokens=tokens,
        rate_limit_refill_rate=refill_rate,
    )
    assert slack.rate_limit_tier == tier
    assert slack.rate_limit_tokens == tokens
    assert slack.rate_limit_refill_rate == refill_rate


@pytest.mark.parametrize(
    ("usergroup_ttl", "users_ttl", "channels_ttl"),
    [
        (300, 900, 900),
        (600, 1800, 1800),
        (0, 0, 0),
        (3600, 3600, 3600),
    ],
)
def test_slack_settings_cache_ttl_values(
    usergroup_ttl: int, users_ttl: int, channels_ttl: int
) -> None:
    """Test SlackSettings cache TTL configurations."""
    slack = SlackSettings(
        usergroup_cache_ttl=usergroup_ttl,
        users_cache_ttl=users_ttl,
        channels_cache_ttl=channels_ttl,
    )
    assert slack.usergroup_cache_ttl == usergroup_ttl
    assert slack.users_cache_ttl == users_ttl
    assert slack.channels_cache_ttl == channels_ttl


def test_settings_model_config_case_insensitive() -> None:
    """Test Settings model_config has case_sensitive=False."""
    assert Settings.model_config["case_sensitive"] is False


def test_settings_model_config_env_prefix() -> None:
    """Test Settings model_config has QAPI_ prefix."""
    assert Settings.model_config["env_prefix"] == "QAPI_"


def test_settings_model_config_env_nested_delimiter() -> None:
    """Test Settings model_config uses __ for nested settings."""
    assert Settings.model_config["env_nested_delimiter"] == "__"


@pytest.mark.parametrize(
    ("invalid_field", "invalid_value"),
    [
        ("jwt_expire_minutes", "not-a-number"),
        ("debug", "not-a-bool"),
    ],
)
def test_settings_validation_errors(
    invalid_field: str, invalid_value: str | int
) -> None:
    """Test Settings raises ValidationError for invalid values."""
    with pytest.raises(ValidationError):
        Settings(**{invalid_field: invalid_value})  # type: ignore[arg-type]


def test_slack_settings_api_method_configs_default_factory() -> None:
    """Test SlackSettings api_method_configs uses default_factory."""
    slack1 = SlackSettings()
    slack2 = SlackSettings()
    assert slack1.api_method_configs is not slack2.api_method_configs
    assert slack1.api_method_configs == slack2.api_method_configs


def test_settings_slack_default_factory() -> None:
    """Test Settings slack field uses default_factory."""
    settings1 = Settings()
    settings2 = Settings()
    assert settings1.slack is not settings2.slack
    assert settings1.slack.api_timeout == settings2.slack.api_timeout


def test_secret_settings_defaults() -> None:
    """Test SecretSettings uses default values."""
    from qontract_api.config import SecretSettings

    secret_settings = SecretSettings()
    assert secret_settings.backend_type == "vault"
    assert secret_settings.vault_server == ""
    assert secret_settings.vault_role_id == ""
    assert secret_settings.vault_secret_id == ""
    assert secret_settings.vault_kube_auth_role == ""
    assert secret_settings.vault_kube_auth_mount == "kubernetes"
    assert (
        secret_settings.vault_kube_sa_token_path
        == "/var/run/secrets/kubernetes.io/serviceaccount/token"
    )
    assert secret_settings.vault_auto_refresh is True


def test_settings_secrets_defaults() -> None:
    """Test Settings includes nested SecretSettings with defaults."""
    settings = Settings()
    assert settings.secrets.backend_type == "vault"
    assert settings.secrets.vault_auto_refresh is True


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
