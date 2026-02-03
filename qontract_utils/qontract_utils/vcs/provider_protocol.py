"""Protocols for VCS provider abstraction.

Defines interfaces for VCS API clients and providers to enable
extensible provider registry pattern.
"""

from collections.abc import Callable, Iterable
from typing import Any, Protocol

from qontract_utils.vcs.models import Provider


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
        pre_hooks: Iterable[Callable[[Any], None]],
        post_hooks: Iterable[Callable[[Any], None]],
        error_hooks: Iterable[Callable[[Any], None]],
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
