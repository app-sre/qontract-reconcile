"""Factory for creating GithubOrgWorkspaceClient instances."""

from qontract_utils.github_org.api import GithubOrgApi

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.github.github_org_workspace_client import GithubOrgWorkspaceClient


class GithubOrgClientFactory:
    """Factory for creating GithubOrgWorkspaceClient instances.

    Encapsulates all dependencies and configuration needed to create
    GithubOrgWorkspaceClient instances with caching.
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
    def create_github_org_api(
        token: str,
        base_url: str = "https://api.github.com",
    ) -> GithubOrgApi:
        """Create a GithubOrgApi instance (Layer 1).

        Args:
            token: GitHub API token
            base_url: GitHub API base URL (override for GHE)

        Returns:
            GithubOrgApi instance
        """
        return GithubOrgApi(token=token, base_url=base_url)

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
        api = self.create_github_org_api(token=token, base_url=base_url)
        return GithubOrgWorkspaceClient(
            github_org_api=api,
            cache=self.cache,
            settings=self.settings,
        )
