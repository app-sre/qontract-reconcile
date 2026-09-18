"""Pydantic models for GitLab group/project administration.

Following ADR-012 (Fully Typed Pydantic Models Over Nested Dicts):
- All models use Pydantic BaseModel with frozen=True
- Only fields consumed by integrations are declared
"""

from pydantic import BaseModel, Field


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
