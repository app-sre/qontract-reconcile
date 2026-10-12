"""Desired-state domain models for the gitlab-projects integration.

These models represent the desired group/project state sent by the
client-side integration. They are separate from the API schemas
(request/response/action models) in schemas.py.
"""

from collections import Counter

from pydantic import BaseModel, Field, field_validator

from qontract_api.models import Secret


class GitlabGroupConfig(BaseModel, frozen=True):
    """Configuration for a single GitLab group and its desired projects."""

    group: str = Field(..., description="GitLab group full path")
    projects: list[str] = Field(
        default_factory=list, description="Desired project names under this group"
    )

    @field_validator("projects")
    @classmethod
    def project_names_unique(cls, projects: list[str]) -> list[str]:
        duplicate_counter = Counter(projects)
        if duplicates := {
            name for name, count in duplicate_counter.items() if count > 1
        }:
            raise ValueError(
                f"duplicate project names: {', '.join(sorted(duplicates))}"
            )
        return projects


class GitlabInstanceConfig(BaseModel, frozen=True):
    """Configuration for a single GitLab instance to reconcile."""

    name: str = Field(..., description="GitLab instance name")
    url: str = Field(..., description="GitLab instance URL")
    ssl_verify: bool = Field(
        default=True, description="Whether to verify SSL certificates"
    )
    token: Secret = Field(..., description="Secret reference for the instance token")
    groups: list[GitlabGroupConfig] = Field(
        default_factory=list, description="Desired group/project state"
    )

    def lock_key(self) -> str:
        return self.name
