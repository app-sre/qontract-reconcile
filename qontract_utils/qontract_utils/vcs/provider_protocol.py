"""Protocols for VCS provider abstraction.

Defines interfaces for VCS API clients and providers to enable
extensible provider registry pattern.
"""

from collections.abc import Callable
from typing import Any, Protocol


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

    name: str
    """Provider name (e.g., 'github', 'gitlab')"""

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
        hooks: list[Callable[[Any], None]],
        **provider_kwargs: Any,
    ) -> VCSApiProtocol:
        """Create VCS API client instance for this provider.

        Args:
            url: Repository URL
            token: API authentication token
            timeout: Request timeout in seconds
            hooks: List of hook functions to execute before API calls
            **provider_kwargs: Provider-specific keyword arguments
                (e.g., github_api_url for GitHub)

        Returns:
            VCS API client instance implementing VCSApiProtocol

        Raises:
            ValueError: If URL cannot be parsed or required kwargs missing
        """
        ...
