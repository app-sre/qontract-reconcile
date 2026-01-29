"""Data models for qontract-api."""

from enum import StrEnum

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    """Status for background tasks.

    Used across all async API endpoints to indicate task execution state.
    """

    PENDING = "pending"  # Task queued or in progress
    SUCCESS = "success"  # Task completed successfully
    FAILED = "failed"  # Task failed with errors


class TaskResult(BaseModel, frozen=True):
    """Result model for completed reconciliation task.

    Returned by GET /reconcile/{task_id}.
    Contains the reconciliation results and execution status.
    """

    status: TaskStatus = Field(
        ...,
        description="Task execution status (pending/success/failed)",
    )
    applied_count: int = Field(
        default=0,
        description="Number of actions actually applied (0 if dry_run=True)",
    )
    errors: list[str] = Field(
        default=[],
        description="List of errors encountered during reconciliation",
    )


class TokenData(BaseModel):
    """Data to be encoded in JWT token."""

    sub: str = Field(..., description="Subject (username)")


class TokenPayload(BaseModel):
    """Decoded JWT token payload."""

    sub: str = Field(..., description="Subject (username)")
    exp: int = Field(..., description="Expiration timestamp")


class Token(BaseModel):
    """Token response."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")


class User(BaseModel):
    """Current authenticated user."""

    username: str = Field(..., description="Username from token")


class Secret(BaseModel):
    """Reference to a secret stored in a secret manager."""

    secret_manager_url: str = Field(..., description="Secret Manager URL")
    path: str = Field(..., description="Path to the secret")
    field: str | None = Field(None, description="Specific field within the secret")
    version: int | None = Field(None, description="Version of the secret")

    @property
    def url(self) -> str:
        return self.secret_manager_url
