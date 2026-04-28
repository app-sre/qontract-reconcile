"""API schemas for VCS external integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class VCSProvider(StrEnum):
    """VCS provider types."""

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


# --- File read schemas ---


class GetFileParams(Secret):
    """Query parameters for reading a file from a VCS repository."""

    repo_url: str = Field(
        ...,
        description="Repository URL (e.g., https://gitlab.com/group/project)",
    )
    file_path: str = Field(..., description="File path in the repository")
    ref: str = Field(..., description="Git reference (branch, tag, SHA)")


class GetFileResponse(BaseModel, frozen=True):
    """Response with file content from a VCS repository."""

    content: str = Field(
        ...,
        description="File content as string",
    )


# --- File sync schemas ---


class FileSyncCreate(BaseModel, frozen=True):
    """Create a new file in the repository."""

    action: Literal["create"] = "create"
    path: str = Field(..., description="File path in the repository")
    content: str = Field(..., description="File content")
    commit_message: str = Field(..., description="Commit message for this change")


class FileSyncUpdate(BaseModel, frozen=True):
    """Update an existing file in the repository."""

    action: Literal["update"] = "update"
    path: str = Field(..., description="File path in the repository")
    content: str = Field(..., description="New file content")
    commit_message: str = Field(..., description="Commit message for this change")


class FileSyncDelete(BaseModel, frozen=True):
    """Delete a file from the repository."""

    action: Literal["delete"] = "delete"
    path: str = Field(..., description="File path in the repository")
    commit_message: str = Field(..., description="Commit message for this change")


FileSyncFileOperation = Annotated[
    FileSyncCreate | FileSyncUpdate | FileSyncDelete,
    Field(discriminator="action"),
]


class FileSyncRequest(BaseModel, frozen=True):
    """Request to reconcile file state in a VCS repository.

    Deduplicates by MR title and creates a merge request with the
    given file operations. Relies on the VCS provider for validation.
    """

    repo_url: str = Field(
        ...,
        description="Repository URL (e.g., https://gitlab.com/group/project)",
    )
    token: Secret = Field(..., description="Secret reference for VCS API token")
    title: str = Field(..., description="Merge request title (used for deduplication)")
    description: str = Field(default="", description="Merge request description")
    target_branch: str = Field(..., description="Target branch name")
    file_operations: list[FileSyncFileOperation] = Field(
        ...,
        min_length=1,
        description="File operations to reconcile",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Labels to apply to the MR",
    )
    auto_merge: bool = Field(default=False, description="Whether to enable auto-merge")


class FileSyncStatus(StrEnum):
    """Outcome of a file sync reconciliation."""

    MR_CREATED = "mr_created"
    MR_EXISTS = "mr_exists"


class FileSyncResponse(BaseModel, frozen=True):
    """Response from file sync reconciliation."""

    status: FileSyncStatus = Field(..., description="Reconciliation outcome")
    mr_url: str | None = Field(
        default=None,
        description="URL of the created or existing merge request",
    )
