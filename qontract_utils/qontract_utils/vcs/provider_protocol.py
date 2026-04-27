"""Protocols for VCS provider abstraction.

Defines interfaces for VCS API clients and providers to enable
extensible provider registry pattern.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from qontract_utils.hooks import Hooks
from qontract_utils.vcs.models import Provider

AUTO_MERGE_LABEL = "bot/automerge"
"""Label used to trigger automatic merging of merge requests."""


class FileAction(StrEnum):
    """Explicit action for a file operation in a merge request."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True)
class MergeRequestFile:
    """A file operation for a merge request."""

    path: str
    action: FileAction
    content: str | None = None
    commit_message: str = ""


@dataclass(frozen=True)
class CreateMergeRequestInput:
    """Input for creating a merge request."""

    title: str
    description: str
    target_branch: str = "master"
    file_operations: list[MergeRequestFile] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    auto_merge: bool = False


class VCSApiProtocol(Protocol):
    """Protocol for VCS API clients (GitHub, GitLab, etc.).

    Defines the interface that all VCS API clients must implement
    for repository operations.
    """

    repo_url: str
    """Repository URL (e.g., https://github.com/owner/repo)"""

    def get_file(self, path: str, ref: str) -> str | None:
        """Fetch file content from repository.

        Args:
            path: File path relative to repository root
            ref: Git reference (branch, tag, commit SHA)

        Returns:
            File content as string, or None if file not found
        """
        ...

    def create_merge_request(self, mr_input: CreateMergeRequestInput) -> str:
        """Create a merge request with file changes.

        Args:
            mr_input: Merge request details including file operations

        Returns:
            URL of the created merge request
        """
        ...

    def find_merge_request(self, title: str) -> str | None:
        """Find an open merge request by title.

        Args:
            title: MR title to search for

        Returns:
            URL of the open merge request, or None if not found
        """
        ...


class VCSProviderProtocol(Protocol):
    """Protocol for VCS providers (GitHub, GitLab, etc.).

    Defines the interface that all VCS providers must implement
    to support the provider registry pattern.
    """

    """Provider type (e.g., 'github', 'gitlab')"""
    type: Provider

    def detect(self, url: str) -> bool:
        """Detect if this provider can handle the given repository URL.

        Args:
            url: Repository URL (e.g., https://github.com/owner/repo)

        Returns:
            True if this provider can handle the URL, False otherwise
        """
        ...

    def parse_url(self, url: str) -> Any:
        """Parse repository URL to extract provider-specific information.

        Args:
            url: Repository URL

        Returns:
            Specific representation of the repository

        Raises:
            ValueError: If URL format is invalid for this provider
        """
        ...

    def create_api_client(
        self,
        url: str,
        token: str,
        timeout: int,
        hooks: Hooks,
        provider_settings: Any,
    ) -> VCSApiProtocol:
        """Create VCS API client instance for this provider.

        Args:
            url: Repository URL
            token: API authentication token
            timeout: Request timeout in seconds
            hooks: List of hook functions to execute before API calls
            provider_settings: Provider-specific settings

        Returns:
            VCS API client instance implementing VCSApiProtocol

        Raises:
            ValueError: If URL cannot be parsed or required kwargs missing
        """
        ...
