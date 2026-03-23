"""Desired-state domain models for the github-owners integration.

These models represent the desired membership state sent by the client-side
integration. They are separate from the API schemas (request/response/action
models) in schemas.py.
"""

from pydantic import BaseModel, Field, field_validator

from qontract_api.models import Secret


class GithubOrgDesiredState(BaseModel, frozen=True):
    """Desired owner state for a single GitHub organization.

    Attributes:
        org_name: GitHub organization name
        token: Vault secret reference for the org's GitHub API token
        base_url: GitHub API base URL (override for GitHub Enterprise)
        owners: Desired set of lowercase GitHub usernames that should be org admins
    """

    org_name: str = Field(..., description="GitHub organization name")
    token: Secret = Field(
        ..., description="Vault secret reference for the GitHub API token"
    )
    base_url: str = Field(
        default="https://api.github.com",
        description="GitHub API base URL (override for GitHub Enterprise)",
    )
    owners: list[str] = Field(
        ..., description="Desired set of GitHub usernames that should be org admins"
    )

    @field_validator("owners")
    @classmethod
    def sort_and_lowercase_owners(cls, v: list[str]) -> list[str]:
        """Normalize and sort the owners list for deterministic output."""
        return sorted(username.lower() for username in v)
