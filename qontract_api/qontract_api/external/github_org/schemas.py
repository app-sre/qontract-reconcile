"""API schemas for the GitHub organization external integration."""

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class GithubOrgMembersParams(Secret):
    """Query parameters for the GitHub org members endpoint.

    Inherits the Vault secret reference fields (secret_manager_url, path,
    field, version) from Secret; the referenced secret holds the GitHub API
    token used to list organization members.
    """

    org_name: str = Field(..., description="GitHub organization name")


class GithubOrgMembersResponse(BaseModel, frozen=True):
    """Response with all members of a GitHub organization."""

    members: list[str] = Field(
        default_factory=list,
        description="GitHub usernames (original case) of all organization members",
    )
