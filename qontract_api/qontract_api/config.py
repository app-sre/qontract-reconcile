"""Configuration management using Pydantic Settings."""

from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class Secret(BaseModel):
    """Secret reference configuration."""

    path: str = Field(
        ...,
        description="Path to the secret",
    )
    field: str | None = Field(
        default=None,
        description="Field within the secret",
    )
    version: int | None = Field(
        default=None,
        description="Version of the secret (if applicable)",
    )


class SlackIntegrationsSettings(BaseModel):
    """Slack integration-specific configuration."""

    token: Secret = Field(
        ...,
        description="Slack token secret path",
    )


class SlackWorkspaceSettings(BaseModel):
    """Slack workspace-specific configuration."""

    integrations: dict[str, SlackIntegrationsSettings] = Field(
        default_factory=dict,
        description="Slack integrations by name",
    )


class SlackSettings(BaseModel):
    """Slack API and integration configuration."""

    # Slack API Client Configuration
    api_url: str = Field(
        # use "https://slack-gov.com/api/" for Gov Slack workspaces
        default="https://slack.com/api/",
        description="Slack API base URL",
    )
    api_timeout: int = Field(
        default=30,
        description="Slack API timeout in seconds",
    )
    api_max_retries: int = Field(
        default=100,
        description="Slack API max retries for failed requests including rate limiting",
    )
    api_method_configs: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "users.list": {"limit": 1000},
            "conversations.list": {"limit": 1000},
        },
        description="Slack API method-specific configurations",
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
    workspaces: dict[str, SlackWorkspaceSettings] = Field(
        default_factory=dict,
        description="Slack workspaces by name",
    )


class PagerDutyInstanceSettings(BaseModel):
    """PagerDuty instance-specific configuration."""

    token: Secret = Field(
        ...,
        description="PagerDuty instance token secret path",
    )


class PagerDutySettings(BaseModel):
    """PagerDuty API and integration configuration."""

    # PagerDuty API Client Configuration
    api_timeout: int = Field(
        default=30,
        description="PagerDuty API timeout in seconds",
    )

    # Cache TTLs (seconds)
    schedule_cache_ttl: int = Field(
        default=60 * 5,
        description="PagerDuty schedule users cache TTL in seconds (5 minutes)",
    )
    escalation_policy_cache_ttl: int = Field(
        default=60 * 5,
        description="PagerDuty escalation policy users cache TTL in seconds (5 minutes)",
    )

    instances: dict[str, PagerDutyInstanceSettings] = Field(
        default_factory=dict,
        description="PagerDuty instances by name",
    )


class GitHubOrgSettings(BaseModel):
    """GitHub organization-specific configuration."""

    token: Secret = Field(
        ...,
        description="GitHub organization token secret path",
    )


class GitHubProviderSettings(BaseModel):
    """GitHub provider configuration."""

    api_url: str = Field(
        default="https://github-mirror.devshift.net",
        description="GitHub API URL (for GitHub Enterprise)",
    )
    api_timeout: int = Field(
        default=30,
        description="GitHub API timeout in seconds",
    )

    # Rate Limiting (Token Bucket)
    rate_limit_tier: str = Field(
        default="tier2",
        description="GitHub rate limit tier (tier1/tier2/tier3/tier4)",
    )
    rate_limit_tokens: int = Field(
        default=20,
        description="Token bucket capacity",
    )
    rate_limit_refill_rate: float = Field(
        default=1.0,
        description="Token bucket refill rate (tokens per second)",
    )

    organizations: dict[str, GitHubOrgSettings] = Field(
        default_factory=dict,
        description="GitHub organization-specific settings by GitHub organization URL",
    )


class GitLabInstanceSettings(BaseModel):
    """GitLab instance-specific configuration."""

    token: Secret = Field(
        ...,
        description="GitLab instance token secret path",
    )


class GitLabProviderSettings(BaseModel):
    """GitLab provider configuration."""

    api_timeout: int = Field(
        default=30,
        description="GitLab API timeout in seconds",
    )

    # Rate Limiting (Token Bucket)
    rate_limit_tier: str = Field(
        default="tier2",
        description="GitLab rate limit tier (tier1/tier2/tier3/tier4)",
    )
    rate_limit_tokens: int = Field(
        default=20,
        description="Token bucket capacity",
    )
    rate_limit_refill_rate: float = Field(
        default=1.0,
        description="Token bucket refill rate (tokens per second)",
    )
    instances: dict[str, GitLabInstanceSettings] = Field(
        default_factory=dict,
        description="GitLab instance-specific settings by GitLab instance URL",
    )


class VCSProvidersSettings(BaseModel):
    """VCS providers configuration."""

    github: GitHubProviderSettings = Field(
        default_factory=GitHubProviderSettings,
        description="GitHub provider configuration",
    )
    gitlab: GitLabProviderSettings = Field(
        default_factory=GitLabProviderSettings,
        description="GitLab provider configuration",
    )


class VCSSettings(BaseModel):
    """VCS (Version Control System) API and integration configuration.

    Each provider has its own configuration namespace.
    """

    providers: VCSProvidersSettings = Field(
        default_factory=VCSProvidersSettings,
        description="Provider-specific configuration",
    )

    # Cache TTLs (seconds)
    owners_cache_ttl: int = Field(
        default=60 * 60 * 12,
        description="Repository OWNERS file cache TTL in seconds (12 hours)",
    )


class SecretSettings(BaseModel):
    """Secret backend configuration.

    Supports HashiCorp Vault, AWS KMS, and Google Secret Manager.
    """

    # Backend type
    backend_type: str = Field(
        default="vault",
        description="Secret backend type: vault, aws_kms, google",
    )

    # Vault-specific configuration
    vault_server: str = Field(
        default="",
        description="Vault server URL (e.g., https://vault.example.com)",
    )
    vault_role_id: str = Field(
        default="",
        description="Vault AppRole role_id (for AppRole auth)",
    )
    vault_secret_id: str = Field(
        default="",
        description="Vault AppRole secret_id (for AppRole auth)",
    )
    vault_kube_auth_role: str = Field(
        default="",
        description="Vault Kubernetes auth role (for Kubernetes auth)",
    )
    vault_kube_auth_mount: str = Field(
        default="kubernetes",
        description="Vault Kubernetes auth mount point",
    )
    vault_kube_sa_token_path: str = Field(
        default="/var/run/secrets/kubernetes.io/serviceaccount/token",
        description="Kubernetes service account token path",
    )
    vault_auto_refresh: bool = Field(
        default=True,
        description="Auto-refresh Vault token in background thread",
    )


class Settings(BaseSettings):
    """Application settings from environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QAPI_",
        env_nested_delimiter="__",
        json_file=".env.json",
        json_file_encoding="utf-8",
        yaml_file=".env.yaml",
        yaml_file_encoding="utf-8",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            env_settings,
            file_secret_settings,
            init_settings,
            dotenv_settings,
            JsonConfigSettingsSource(settings_cls),
            YamlConfigSettingsSource(settings_cls),
            YamlConfigSettingsSource(settings_cls, yaml_file="/config/config.yml"),
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
        default="slack_sdk,httpcore,github.Requester",
        description="Comma-separated list of logger names to exclude from DEBUG logging",
    )

    # Cache Backend
    cache_backend: str = Field(
        default="redis",
        description="Cache backend type: redis (more backends: dynamodb, firestore coming later)",
    )
    cache_broker_url: str = Field(
        default="redis://localhost:6379/0",
        description="Cache and message broker URL (Redis or Redis-compatible Valkey)",
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
    # worker metrics config
    worker_metrics_port: int = Field(
        default=8000,
        description="Port for worker metrics HTTP server",
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

    # PagerDuty Configuration (nested)
    pagerduty: PagerDutySettings = Field(
        default_factory=PagerDutySettings,
        description="PagerDuty API and integration configuration",
    )

    # VCS Configuration (nested)
    vcs: VCSSettings = Field(
        default_factory=VCSSettings,
        description="VCS (Version Control System) API and integration configuration",
    )

    # Secret Backend Configuration (nested)
    secrets: SecretSettings = Field(
        default_factory=SecretSettings,
        description="Secret backend configuration (Vault, AWS KMS, Google)",
    )

    def get_celery_broker_url(self) -> str:
        """Get Celery broker URL, defaulting to cache_broker_url."""
        return self.celery_broker_url or self.cache_broker_url

    def get_celery_result_backend(self) -> str:
        """Get Celery result backend URL, defaulting to cache_broker_url."""
        return self.celery_result_backend or self.cache_broker_url


settings = Settings()
