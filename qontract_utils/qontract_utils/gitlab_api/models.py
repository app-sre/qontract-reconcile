"""Pydantic models for GitLab group/project administration.

Following ADR-012 (Fully Typed Pydantic Models Over Nested Dicts):
- All models use Pydantic BaseModel with frozen=True
- Only fields consumed by integrations are declared
"""

from enum import StrEnum

from gitlab.const import AccessLevel as _GitlabConstAccessLevel
from pydantic import BaseModel, Field


class GitlabAccessLevel(StrEnum):
    """GitLab group access level, as declared in App-Interface permissions.

    Member names match `gitlab.const.AccessLevel` so `to_access_level()` can
    translate the human-readable value into GitLab's numeric access level
    without duplicating the mapping.
    """

    GUEST = "guest"
    REPORTER = "reporter"
    DEVELOPER = "developer"
    MAINTAINER = "maintainer"
    OWNER = "owner"

    def to_access_level(self) -> int:
        """Return the GitLab API numeric access level for this value."""
        return int(_GitlabConstAccessLevel[self.name])


class GitlabGroup(BaseModel, frozen=True):
    """A GitLab group and the projects directly under it.

    Attributes:
        id: GitLab group ID
        full_path: Full path of the group (e.g. "team/subteam")
        project_names: Names of projects directly under this group, excluding
            projects in subgroups
    """

    id: int = Field(..., description="GitLab group ID")
    full_path: str = Field(..., description="Full path of the group")
    project_names: list[str] = Field(
        ..., description="Names of projects directly under this group"
    )


class GitlabProject(BaseModel, frozen=True):
    """A GitLab project as returned by the create-project API.

    Attributes:
        id: GitLab project ID
        name: Project name
        path_with_namespace: Full path including namespace
        web_url: Web URL of the project
    """

    id: int = Field(..., description="GitLab project ID")
    name: str = Field(..., description="Project name")
    path_with_namespace: str = Field(..., description="Full path including namespace")
    web_url: str = Field(..., description="Web URL of the project")


class GitlabUser(BaseModel, frozen=True):
    """A GitLab user.

    Attributes:
        id: GitLab user ID
        username: GitLab username
        name: User's display name
    """

    id: int = Field(..., description="GitLab user ID")
    username: str = Field(..., description="GitLab username")
    name: str = Field(..., description="User's display name")


class GitlabGroupMember(BaseModel, frozen=True):
    """A member of a GitLab group.

    Attributes:
        id: GitLab user ID of the member
        username: GitLab username
        name: User's display name
        access_level: Access level granted in the group (see gitlab.const.AccessLevel)
    """

    id: int = Field(..., description="GitLab user ID of the member")
    username: str = Field(..., description="GitLab username")
    name: str = Field(..., description="User's display name")
    access_level: int = Field(..., description="Access level granted in the group")
