"""API schemas for VCS external integration."""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

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


class FileAction(StrEnum):
    """File operation type for merge request file operations."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class MergeRequestFileOperation(BaseModel, frozen=True):
    """A file operation within a merge request.

    The ``action`` field specifies the operation: create, update, or delete.
    """

    path: str = Field(..., description="File path in the repository")
    action: FileAction = Field(..., description="File operation type")
    content: str | None = Field(
        default=None,
        description="File content (required for create/update, None for delete)",
    )
    commit_message: str = Field(..., description="Commit message for this file change")

    @model_validator(mode="after")
    def _validate_action_content(self) -> "MergeRequestFileOperation":
        match self.action:
            case FileAction.CREATE | FileAction.UPDATE:
                if self.content is None:
                    raise ValueError(
                        f"content is required for {self.action.value} action"
                    )
            case FileAction.DELETE:
                if self.content is not None:
                    raise ValueError("content must be None for delete action")
        return self


class CreateMergeRequestRequest(BaseModel, frozen=True):
    """Request to create a merge request in a VCS repository."""

    repo_url: str = Field(
        ...,
        description="Repository URL (e.g., https://gitlab.com/group/project)",
    )
    token: Secret = Field(..., description="Secret reference for VCS API token")
    title: str = Field(..., description="Merge request title")
    description: str = Field(default="", description="Merge request description")
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
    title: str = Field(..., description="MR title to search for (exact match)")


class CreateMergeRequestResponse(BaseModel, frozen=True):
    """Response after creating a merge request."""

    url: str = Field(..., description="URL of the created merge request")


# --- File read schemas ---


class GetFileParams(Secret):
    """Query parameters for reading a file from a VCS repository."""

    repo_url: str = Field(
        ...,
        description="Repository URL (e.g., https://gitlab.com/group/project)",
    )
    file_path: str = Field(..., description="File path in the repository")
    ref: str = Field(default="master", description="Git reference (branch, tag, SHA)")


class GetFileResponse(BaseModel, frozen=True):
    """Response with file content from a VCS repository."""

    content: str = Field(
        ...,
        description="File content as string",
    )
