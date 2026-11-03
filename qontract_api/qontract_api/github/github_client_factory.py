"""Factory for creating GitHub workspace client instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.github_api.api import GithubApi

from qontract_api.github.github_org_workspace_client import GithubOrgWorkspaceClient
from qontract_api.github.github_user_workspace_client import GithubUserWorkspaceClient

if TYPE_CHECKING:
    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings


class GithubClientFactory:
    """Factory for creating GitHub workspace client instances.

    Encapsulates all dependencies and configuration needed to create
    GithubOrgWorkspaceClient (org membership) and GithubUserWorkspaceClient
    (account validation) instances with caching.
    """

    def __init__(self, cache: CacheBackend, settings: Settings) -> None:
        """Initialize factory with shared dependencies.

        Args:
            cache: Cache backend for distributed locking and caching
            settings: Application settings
        """
        self.cache = cache
        self.settings = settings

    @staticmethod
    def create_github_api(
        token: str,
        base_url: str = "https://api.github.com",
    ) -> GithubApi:
        """Create a GithubApi instance (Layer 1).

        Args:
            token: GitHub API token
            base_url: GitHub API base URL (override for GHE)

        Returns:
            GithubApi instance
        """
        return GithubApi(token=token, base_url=base_url)

    def create_workspace_client(
        self,
        token: str,
        base_url: str = "https://api.github.com",
    ) -> GithubOrgWorkspaceClient:
        """Create GithubOrgWorkspaceClient with full dependency stack.

        Args:
            token: GitHub API token
            base_url: GitHub API base URL (override for GHE)

        Returns:
            GithubOrgWorkspaceClient with caching layer
        """
        api = self.create_github_api(token=token, base_url=base_url)
        return GithubOrgWorkspaceClient(
            github_api=api,
            cache=self.cache,
            settings=self.settings,
        )

    def create_user_workspace_client(
        self,
        token: str,
        base_url: str = "https://api.github.com",
    ) -> GithubUserWorkspaceClient:
        """Create GithubUserWorkspaceClient with full dependency stack.

        Args:
            token: GitHub API token
            base_url: GitHub API base URL (override for GHE)

        Returns:
            GithubUserWorkspaceClient with caching layer
        """
        api = self.create_github_api(token=token, base_url=base_url)
        return GithubUserWorkspaceClient(
            github_api=api,
            cache=self.cache,
            settings=self.settings,
        )
