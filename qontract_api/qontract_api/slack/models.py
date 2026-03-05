"""Pydantic models for Slack usergroups reconciliation API."""

from pydantic import BaseModel, Field, field_validator

from qontract_api.models import Secret


class SlackUsergroupConfig(BaseModel, frozen=True):
    """Desired state configuration for a single Slack usergroup."""

    description: str = Field("", description="Usergroup description")
    users: list[str] = Field(
        [],
        description="List of user emails (e.g., user@example.com)",
    )
    channels: list[str] = Field(
        [],
        description="List of channel names (e.g., #general, team-channel)",
    )

    @field_validator("users", "channels", mode="after")
    @classmethod
    def sorted_list(cls, value: list[str]) -> list[str]:
        return sorted(value)


class SlackUsergroup(BaseModel, frozen=True):
    """A single Slack usergroup with its handle and configuration."""

    handle: str = Field(..., description="Usergroup handle/name (unique identifier)")
    config: SlackUsergroupConfig = Field(..., description="Usergroup configuration")


class SlackWorkspace(BaseModel, frozen=True):
    """A Slack workspace with its token and usergroups."""

    name: str = Field(..., description="Workspace name (unique identifier)")
    usergroups: list[SlackUsergroup] = Field(
        ..., description="List of usergroups in this workspace"
    )
    managed_usergroups: list[str] = Field(
        ...,
        description="This list shows the usergroup handles/names managed by qontract-api. Any user group not included here will be abandoned during reconciliation.",
    )
    token: Secret = Field(
        ...,
        description="Secret reference for the Slack workspace token",
    )
