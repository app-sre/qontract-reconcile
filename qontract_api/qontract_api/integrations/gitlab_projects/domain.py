"""Desired-state domain models for the gitlab-projects integration.

These models represent the desired group/project state sent by the
client-side integration. They are separate from the API schemas
(request/response/action models) in schemas.py.
"""

from collections import Counter

from pydantic import BaseModel, Field, field_validator

from qontract_api.models import Secret


class GitlabProjectConfig(BaseModel, frozen=True):
    """Desired state for a single GitLab project."""

    name: str = Field(..., description="Project name")
    is_saas_bundle: bool = Field(
        default=False,
        description=(
            "Whether this project should be initialized as a SaaS bundle repo "
            "(README + staging/production branches) rather than left empty"
        ),
    )


class GitlabGroupConfig(BaseModel, frozen=True):
    """Configuration for a single GitLab group and its desired projects."""

    group: str = Field(..., description="GitLab group full path")
    projects: list[GitlabProjectConfig] = Field(
        default_factory=list, description="Desired projects under this group"
    )

    @field_validator("projects")
    @classmethod
    def project_names_unique(
        cls, projects: list[GitlabProjectConfig]
    ) -> list[GitlabProjectConfig]:
        duplicate_counter = Counter(project.name for project in projects)
        if duplicates := {name for name, count in duplicate_counter.items() if count > 1}:
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
