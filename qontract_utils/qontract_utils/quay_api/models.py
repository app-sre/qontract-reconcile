"""Pydantic models for the Quay API.

Following ADR-012 (Fully Typed Pydantic Models Over Nested Dicts):
- All models use Pydantic BaseModel
- Immutable with frozen=True (thread-safe)
"""

from pydantic import BaseModel, ConfigDict, Field


class RobotAccount(BaseModel):
    """A Quay organization robot account (short name, without org prefix)."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    teams: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)


class RobotAccountRepository(BaseModel):
    """Repository referenced by a robot permission."""

    model_config = ConfigDict(frozen=True)

    name: str


class RobotAccountPermission(BaseModel):
    """A robot's role on a repository."""

    model_config = ConfigDict(frozen=True)

    repository: RobotAccountRepository
    role: str
