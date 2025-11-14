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
