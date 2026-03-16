"""Pydantic domain models for Glitchtip reconciliation desired state."""

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class GlitchtipUser(BaseModel, frozen=True):
    """Desired state for a single Glitchtip organization user."""

    email: str = Field(..., description="User email address")
    role: str = Field(default="member", description="Organization role")


class GlitchtipTeam(BaseModel, frozen=True):
    """Desired state for a single Glitchtip team."""

    name: str = Field(..., description="Team name (slug will be derived)")
    users: list[GlitchtipUser] = Field(
        default=[], description="Desired members of this team"
    )


class GIProject(BaseModel, frozen=True):
    """Desired state for a single Glitchtip project."""

    name: str = Field(..., description="Project name")
    slug: str = Field(..., description="Project slug (URL-friendly identifier)")
    platform: str | None = Field(default=None, description="Project platform")
    event_throttle_rate: int = Field(
        default=0, description="Event throttle rate (0 = no throttle)"
    )
    teams: list[str] = Field(
        default=[], description="Team slugs this project belongs to"
    )


class GIOrganization(BaseModel, frozen=True):
    """Desired state for a single Glitchtip organization."""

    name: str = Field(..., description="Organization name")
    teams: list[GlitchtipTeam] = Field(
        default=[], description="Desired teams in this organization"
    )
    projects: list[GIProject] = Field(
        default=[], description="Desired projects in this organization"
    )
    users: list[GlitchtipUser] = Field(
        default=[], description="Desired members of this organization"
    )


class GIInstance(BaseModel, frozen=True):
    """Glitchtip instance configuration with desired state."""

    name: str = Field(..., description="Instance name (unique identifier)")
    console_url: str = Field(..., description="Glitchtip instance base URL")
    token: Secret = Field(..., description="Secret reference for the API token")
    automation_user_email: Secret = Field(
        ..., description="Secret reference for the automation user email"
    )
    read_timeout: int = Field(default=30, description="HTTP read timeout in seconds")
    max_retries: int = Field(default=3, description="Max HTTP retries")
    organizations: list[GIOrganization] = Field(
        default=[], description="Desired organizations to reconcile"
    )
