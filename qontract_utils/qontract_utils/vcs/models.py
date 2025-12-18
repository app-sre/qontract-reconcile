"""Pydantic models for VCS data structures."""

from enum import StrEnum

from pydantic import BaseModel, Field


class Provider(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"


class RepoTreeItem(BaseModel, frozen=True):
    """Represents a file or directory in a Git repository tree.

    Immutable model for repository tree items (files/directories).
    """

    path: str = Field(..., description="File or directory path relative to repo root")
    type: str = Field(..., description="Type: 'blob' (file) or 'tree' (directory)")
    sha: str = Field(default="", description="Git object SHA hash")


class OwnersFileData(BaseModel, frozen=True):
    """Represents raw parsed OWNERS file YAML data.

    Intermediate model for OWNERS file content before alias resolution.
    Immutable model following ADR-012.
    """

    approvers: list[str] = Field(
        default_factory=list,
        description="List of approver usernames (may include aliases)",
    )
    reviewers: list[str] = Field(
        default_factory=list,
        description="List of reviewer usernames (may include aliases)",
    )


class RepoOwners(BaseModel, frozen=True):
    """Represents parsed OWNERS file data from a Git repository.

    Contains lists of approvers and reviewers extracted from OWNERS files.
    Immutable model for repository owners data.
    """

    approvers: list[str] = Field(
        default_factory=list,
        description="List of usernames with approval permissions",
    )
    reviewers: list[str] = Field(
        default_factory=list,
        description="List of usernames with review permissions (optional reviewers)",
    )
