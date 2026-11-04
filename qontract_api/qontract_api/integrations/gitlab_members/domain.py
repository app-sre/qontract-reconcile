"""Desired-state domain models for the gitlab-members integration.

These models represent the desired group membership state sent by the
client-side integration. They are separate from the API schemas
(request/response/action models) in schemas.py.
"""

from pydantic import BaseModel, Field
from qontract_utils.gitlab_api import GitlabAccessLevel

from qontract_api.models import Secret


class GitlabMemberConfig(BaseModel, frozen=True):
    """Desired membership for a single GitLab user in a group."""

    username: str = Field(..., description="GitLab username")
    access_level: GitlabAccessLevel = Field(..., description="Desired access level")


class GitlabMembersGroupConfig(BaseModel, frozen=True):
    """Configuration for a single GitLab group and its desired members."""

    group: str = Field(..., description="GitLab group full path")
    members: list[GitlabMemberConfig] = Field(
        default_factory=list, description="Desired members and their access levels"
    )


class GitlabMembersInstanceConfig(BaseModel, frozen=True):
    """Configuration for a single GitLab instance to reconcile."""

    name: str = Field(..., description="GitLab instance name")
    url: str = Field(..., description="GitLab instance URL")
    ssl_verify: bool = Field(
        default=True, description="Whether to verify SSL certificates"
    )
    token: Secret = Field(..., description="Secret reference for the instance token")
    groups: list[GitlabMembersGroupConfig] = Field(
        default_factory=list, description="Desired group membership state"
    )

    def lock_key(self) -> str:
        return self.name
