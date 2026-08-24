"""Desired-state domain models for the quay-robot-accounts integration."""

from pydantic import BaseModel, Field, field_validator

from qontract_api.models import Secret


class QuayRobotDesiredState(BaseModel, frozen=True):
    """Desired state for a single Quay robot account."""

    name: str = Field(..., description="Robot short name (without org+ prefix)")
    description: str | None = Field(default=None, description="Robot description")
    teams: list[str] = Field(
        default_factory=list,
        description="Teams the robot should belong to (managedTeams only)",
    )
    repositories: dict[str, str] = Field(
        default_factory=dict,
        description="Repository name to permission (read/write/admin)",
    )
    delete: bool = Field(
        default=False,
        description="If True, delete the robot when it exists in Quay",
    )

    @field_validator("teams")
    @classmethod
    def sort_teams(cls, value: list[str]) -> list[str]:
        return sorted(value)

    @field_validator("repositories")
    @classmethod
    def sort_repositories(cls, value: dict[str, str]) -> dict[str, str]:
        return dict(sorted(value.items()))


class QuayOrgDesiredState(BaseModel, frozen=True):
    """Desired robot-account state for a single Quay organization."""

    instance_name: str = Field(..., description="Quay instance name")
    instance_url: str = Field(..., description="Quay instance URL or hostname")
    org_name: str = Field(..., description="Quay organization name")
    token: Secret = Field(
        ..., description="Vault secret reference for the org automation token"
    )
    managed_teams: list[str] = Field(
        default_factory=list,
        description="Teams this integration is allowed to manage",
    )
    managed_repos: bool = Field(
        default=False,
        description="Whether repository permissions may be reconciled",
    )
    managed_robot_accounts: bool = Field(
        default=False,
        description="Opt-in flag required to manage robot accounts in this org",
    )
    robots: list[QuayRobotDesiredState] = Field(
        default_factory=list,
        description="Desired robot accounts for this organization",
    )

    @field_validator("managed_teams")
    @classmethod
    def sort_managed_teams(cls, value: list[str]) -> list[str]:
        return sorted(value)
