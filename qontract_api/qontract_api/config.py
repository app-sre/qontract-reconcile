"""Configuration management using Pydantic Settings."""

from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SlackSettings(BaseModel):
    """Slack API and integration configuration."""

    # Slack API Client Configuration
    api_timeout: int = Field(
        default=30,
        description="Slack API timeout in seconds",
    )
    api_max_retries: int = Field(
        default=5,
        description="Slack API max retries for failed requests",
    )
    api_method_configs: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "users.list": {"limit": 1000},
            "conversations.list": {"limit": 1000},
        },
        description="Slack API method-specific configurations",
    )

    # Rate Limiting (Token Bucket)
    rate_limit_tier: str = Field(
        default="tier2",
        description="Slack rate limit tier (tier1/tier2/tier3/tier4)",
    )
    rate_limit_tokens: int = Field(
        default=20,
        description="Token bucket capacity",
    )
    rate_limit_refill_rate: float = Field(
        default=1.0,
        description="Token bucket refill rate (tokens per second)",
    )

    # Cache TTLs (seconds)
    usergroup_cache_ttl: int = Field(
        default=60 * 60,
        description="Slack usergroup cache TTL in seconds (one hour)",
    )
    users_cache_ttl: int = Field(
        default=60 * 60 * 12,
        description="Slack users list TTL in seconds (12 hours)",
    )
    channels_cache_ttl: int = Field(
        default=60 * 60 * 12,
        description="Slack channels list cache TTL in seconds (12 hours)",
    )


class Settings(BaseSettings):
    """Application settings from environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_prefix="QAPI_",
        env_nested_delimiter="__",
    )

    # Application
    app_name: str = "qontract-api"
    version: str = "0.1.0"
    debug: bool = Field(default=False, description="Enable debug mode")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format_json: bool = Field(
        default=True,
        description="Use JSON logging format (False for human-readable logs in development)",
    )
    log_exclude_loggers: str = Field(
        default="slack_sdk",
        description="Comma-separated list of logger names to exclude from DEBUG logging",
    )

    # Cache Backend
    cache_backend: str = Field(
        default="redis",
        description="Cache backend type: redis (more backends: dynamodb, firestore coming later)",
    )
    cache_broker_url: str = Field(
        default="redis://localhost:6379/0",
        description="Cache and message broker URL (Redis or Valkey)",
    )
    cache_memory_max_size: int = Field(
        default=1000,
        description="In-memory cache max items (LRU eviction). Set to 0 to disable memory cache.",
    )
    cache_memory_ttl: int = Field(
        default=60,
        description="In-memory cache TTL in seconds (time-based expiration)",
    )

    # Celery
    celery_broker_url: str = Field(
        default="",
        description="Celery broker URL (defaults to cache_broker_url if empty)",
    )
    celery_result_backend: str = Field(
        default="",
        description="Celery result backend URL (defaults to cache_broker_url if empty)",
    )

    # JWT Authentication
    jwt_secret_key: str = Field(
        default="dev-secret-key-change-in-production",
        description="Secret key for JWT token signing",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expire_minutes: int = Field(
        default=60, description="JWT token expiration in minutes"
    )

    # Vault Integration
    use_vault: bool = Field(
        default=False, description="Use Vault for secrets (False for local dev)"
    )

    # API Task Execution
    api_task_max_timeout: int = Field(
        default=300,
        description="Maximum timeout in seconds for blocking GET requests (must align with OpenShift route timeout)",
    )
    api_task_default_timeout: int | None = Field(
        default=None,
        description="Default timeout for blocking GET requests. None = non-blocking by default.",
    )

    # Slack Configuration (nested)
    slack: SlackSettings = Field(
        default_factory=SlackSettings,
        description="Slack API and integration configuration",
    )

    def get_celery_broker_url(self) -> str:
        """Get Celery broker URL, defaulting to cache_broker_url."""
        return self.celery_broker_url or self.cache_broker_url

    def get_celery_result_backend(self) -> str:
        """Get Celery result backend URL, defaulting to cache_broker_url."""
        return self.celery_result_backend or self.cache_broker_url


settings = Settings()
