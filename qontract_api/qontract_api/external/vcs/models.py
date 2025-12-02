"""API models for VCS external integration."""

from enum import StrEnum

from pydantic import BaseModel, Field


class VCSProvider(StrEnum):
    """VCS provider types.

    Extensible enum for supported VCS providers.
    """

    GITHUB = "github"
    GITLAB = "gitlab"


class RepoOwnersResponse(BaseModel, frozen=True):
    """Response model for repository OWNERS file data.

    Attention: usernames are provider-specific (e.g., GitHub usernames).
    """

    provider: VCSProvider = Field(
        ...,
        description="VCS provider type",
    )
    approvers: list[str] = Field(
        default_factory=list,
        description="List of usernames who can approve changes",
    )
    reviewers: list[str] = Field(
        default_factory=list,
        description="List of usernames who can review changes",
    )
