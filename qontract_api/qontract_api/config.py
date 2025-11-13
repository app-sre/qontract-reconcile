"""Configuration management using Pydantic Settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_NAME: str = "qontract-api"
    VERSION: str = "0.1.0"
    DEBUG: bool = Field(default=False, description="Enable debug mode")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Cache Backend
    CACHE_BACKEND: str = Field(
        default="redis",
        description="Cache backend type: redis (more backends: dynamodb, firestore coming later)",
    )
    CACHE_BROKER_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Cache and message broker URL (Redis or Valkey)",
    )

    # Celery
    CELERY_BROKER_URL: str = Field(
        default="",
        description="Celery broker URL (defaults to CACHE_BROKER_URL if empty)",
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="",
        description="Celery result backend URL (defaults to CACHE_BROKER_URL if empty)",
    )

    # JWT Authentication
    JWT_SECRET_KEY: str = Field(
        default="dev-secret-key-change-in-production",
        description="Secret key for JWT token signing",
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    JWT_EXPIRE_MINUTES: int = Field(
        default=60, description="JWT token expiration in minutes"
    )

    # Vault Integration
    USE_VAULT: bool = Field(
        default=False, description="Use Vault for secrets (False for local dev)"
    )

    def get_celery_broker_url(self) -> str:
        """Get Celery broker URL, defaulting to CACHE_BROKER_URL."""
        return self.CELERY_BROKER_URL or self.CACHE_BROKER_URL

    def get_celery_result_backend(self) -> str:
        """Get Celery result backend URL, defaulting to CACHE_BROKER_URL."""
        return self.CELERY_RESULT_BACKEND or self.CACHE_BROKER_URL


settings: Settings = Settings()
