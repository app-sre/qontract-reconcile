"""API schemas for VCS external integration."""

from enum import StrEnum

from pydantic import BaseModel, Field

from qontract_api.models import Secret


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


# --- Merge Request schemas ---


class MergeRequestFileOperation(BaseModel, frozen=True):
    """A file operation within a merge request.

    Set ``content`` to ``None`` to delete the file.
    """

    path: str = Field(..., description="File path in the repository")
    content: str | None = Field(
        ...,
        description="File content (None = delete the file)",
    )
    commit_message: str = Field(..., description="Commit message for this file change")


class CreateMergeRequestRequest(BaseModel, frozen=True):
    """Request to create a merge request in a VCS repository."""

    repo_url: str = Field(
        ...,
        description="Repository URL (e.g., https://gitlab.com/group/project)",
    )
    token: Secret = Field(..., description="Secret reference for VCS API token")
    title: str = Field(..., description="Merge request title")
    description: str = Field(default="", description="Merge request description")
    source_branch: str = Field(..., description="Source branch name")
    target_branch: str = Field(default="master", description="Target branch name")
    file_operations: list[MergeRequestFileOperation] = Field(
        ...,
        description="File operations to include in the MR",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Labels to apply to the MR",
    )
    auto_merge: bool = Field(default=False, description="Whether to enable auto-merge")


class FindMergeRequestParams(Secret):
    """Query parameters for finding an existing merge request."""

    repo_url: str = Field(
        ...,
        description="Repository URL (e.g., https://gitlab.com/group/project)",
    )
    source_branch: str = Field(..., description="Source branch name to search for")


class CreateMergeRequestResponse(BaseModel, frozen=True):
    """Response after creating a merge request."""

    url: str = Field(..., description="URL of the created merge request")
