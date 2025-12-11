"""GitLab provider implementation for VCS provider registry.

Following ADR-011: Dependency Injection Pattern
Following ADR-017: VCS Provider Registry Pattern
"""

from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from qontract_utils.vcs.provider_protocol import VCSApiProtocol
from qontract_utils.vcs.providers.gitlab_client import GitLabRepoApi


class Repo(BaseModel):
    project_id: str
    gitlab_url: str


class GitLabProviderSettings(BaseModel):
    """GitLab provider settings."""


class GitLabProvider:
    """GitLab VCS provider implementation.

    Handles GitLab.com and self-hosted GitLab instances.
    Detects GitLab URLs by checking for "gitlab" in hostname.
    """

    name = "gitlab"

    @staticmethod
    def detect(url: str) -> bool:
        """Detect if URL is a GitLab repository.

        Args:
            url: Repository URL

        Returns:
            True if hostname contains "gitlab"
        """
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        return "gitlab" in hostname.lower()

    @staticmethod
    def parse_url(url: str) -> Repo:
        """Parse GitLab repository URL.

        Args:
            url: GitLab repository URL (e.g., https://gitlab.com/group/project)

        Returns:
            Repo instance with project_id and gitlab_url

        Raises:
            ValueError: If URL format is invalid

        Examples:
            >>> provider = GitLabProvider()
            >>> provider.parse_url("https://gitlab.com/group/project")
            {"project_id": "group/project", "gitlab_url": "https://gitlab.com"}
        """
        parsed = urlparse(url)

        # Remove .git suffix and trailing slashes
        path = parsed.path.rstrip("/")
        path = path.removesuffix(".git")

        # Split path into parts
        parts = [p for p in path.split("/") if p]

        # Must have at least group and project
        min_parts = 2
        if len(parts) < min_parts:
            msg = f"Invalid GitLab URL format (expected group/project): {url}"
            raise ValueError(msg)

        # GitLab project_id is "group/project"
        project_id = f"{parts[0]}/{parts[1]}"

        # GitLab instance URL
        gitlab_url = f"{parsed.scheme}://{parsed.netloc}"

        return Repo(project_id=project_id, gitlab_url=gitlab_url)

    def create_api_client(
        self,
        url: str,
        token: str,
        timeout: int,
        hooks: list[Callable[[Any], None]],
        provider_settings: GitLabProviderSettings,  # noqa: ARG002
    ) -> VCSApiProtocol:
        """Create GitLabRepoApi instance.

        Args:
            url: GitLab repository URL
            token: GitLab API token
            timeout: Request timeout in seconds
            hooks: List of hooks for pre_hooks
            **provider_kwargs: Optional keyword arguments (currently unused)

        Returns:
            GitLabRepoApi instance

        Raises:
            ValueError: If URL cannot be parsed
        """
        parsed_url = self.parse_url(url)

        return GitLabRepoApi(
            project_id=parsed_url.project_id,
            token=token,
            gitlab_url=parsed_url.gitlab_url,
            timeout=timeout,
            pre_hooks=hooks,
        )
