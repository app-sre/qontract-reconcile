"""GitHub provider implementation for VCS provider registry."""

from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from qontract_utils.vcs.models import Provider
from qontract_utils.vcs.provider_protocol import VCSApiProtocol
from qontract_utils.vcs.providers.github_client import GitHubRepoApi


class Repo(BaseModel):
    owner: str
    name: str

    @property
    def owner_url(self) -> str:
        """Get owner URL

        Returns:
            Repository owner URL
        """
        return f"https://github.com/{self.owner}"


class GitHubProviderSettings(BaseModel):
    """GitHub provider settings.

    Attributes:
        organizations: Mapping of organization URLs to token provider functions.
    """

    github_api_url: str = "https://api.github.com"


class GitHubProvider:
    """GitHub VCS provider implementation.

    Handles GitHub and GitHub Enterprise repositories.
    Detects GitHub URLs by checking for "github" in hostname.
    """

    type = Provider.GITHUB

    @staticmethod
    def detect(url: str) -> bool:
        """Detect if URL is a GitHub repository.

        Args:
            url: Repository URL

        Returns:
            True if hostname contains "github"
        """
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        return "github" in hostname.lower()

    @staticmethod
    def parse_url(url: str) -> Repo:
        """Parse GitHub repository URL.

        Args:
            url: GitHub repository URL (e.g., https://github.com/owner/repo)

        Returns:
            Repo instance with owner and name

        Raises:
            ValueError: If URL format is invalid

        Examples:
            >>> provider = GitHubProvider()
            >>> provider.parse_url("https://github.com/openshift/osdctl")
            {"owner": "openshift", "repo": "osdctl"}
        """
        parsed = urlparse(url)

        # Remove .git suffix and trailing slashes
        path = parsed.path.rstrip("/")
        path = path.removesuffix(".git")

        # Split path into parts
        parts = [p for p in path.split("/") if p]

        # Must have at least owner and repo
        min_parts = 2
        if len(parts) < min_parts:
            msg = f"Invalid GitHub URL format (expected owner/repo): {url}"
            raise ValueError(msg)

        return Repo(owner=parts[0], name=parts[1])

    def create_api_client(
        self,
        url: str,
        token: str,
        timeout: int,
        hooks: list[Callable[[Any], None]],
        provider_settings: GitHubProviderSettings,
    ) -> VCSApiProtocol:
        """Create GitHubRepoApi instance.

        Args:
            url: GitHub repository URL
            token: GitHub API token
            timeout: Request timeout in seconds
            hooks: List of hooks for pre_hooks
            **provider_kwargs: Optional keyword arguments:
                - github_api_url: GitHub API base URL (default: https://api.github.com)

        Returns:
            GitHubRepoApi instance

        Raises:
            ValueError: If URL cannot be parsed
        """
        parsed_url = self.parse_url(url)

        return GitHubRepoApi(
            owner=parsed_url.owner,
            repo=parsed_url.name,
            token=token,
            github_api_url=provider_settings.github_api_url,
            timeout=timeout,
            pre_hooks=hooks,
        )
