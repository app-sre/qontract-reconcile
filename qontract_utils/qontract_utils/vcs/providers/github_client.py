"""GitHub Repository API client with hook system for metrics and rate limiting."""

from collections.abc import Callable
from dataclasses import dataclass

from github import Github
from github.Repository import Repository


@dataclass
class GitHubApiCallContext:
    """Context for GitHub API call hooks.

    Provides metadata about the API call for hooks to use.
    """

    method: str  # e.g., "get_file", "get_tree"
    repo_url: str
    owner: str
    repo: str


class GitHubRepoApi:
    """GitHub Repository API client with hook system.

    Args:
        owner: GitHub repository owner (user or organization)
        repo: GitHub repository name
        token: GitHub personal access token
        github_api_url: GitHub API base URL (default: https://api.github.com)
        timeout: Request timeout in seconds
        before_api_call_hooks: List of hooks called before each API call
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str,
        github_api_url: str = "https://api.github.com",
        timeout: int = 30,
        before_api_call_hooks: list[Callable[[GitHubApiCallContext], None]]
        | None = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.repo_url = f"https://github.com/{owner}/{repo}"
        self._timeout = timeout
        self._before_api_call_hooks = before_api_call_hooks or []

        # PyGithub expects base_url without /api/v3
        self._github = Github(
            login_or_token=token, base_url=github_api_url.rstrip("/"), timeout=timeout
        )
        self._repository: Repository = self._github.get_repo(f"{owner}/{repo}")

    def _execute_hooks(self, context: GitHubApiCallContext) -> None:
        """Execute all before_api_call_hooks with the given context.

        Args:
            context: API call context with method, repo_url, owner, repo
        """
        for hook in self._before_api_call_hooks:
            hook(context)

    def get_file(self, path: str, ref: str = "master") -> str | None:
        """Fetch file content from repository.

        Args:
            path: File path relative to repository root
            ref: Git reference (branch, tag, commit SHA)

        Returns:
            File content as string, or None if file not found
        """
        context = GitHubApiCallContext(
            method="get_file",
            repo_url=self.repo_url,
            owner=self.owner,
            repo=self.repo,
        )
        self._execute_hooks(context)

        try:
            content_file = self._repository.get_contents(path, ref=ref)
            if isinstance(content_file, list):
                # Path is a directory, not a file
                return None
            return content_file.decoded_content.decode("utf-8")
        except Exception:  # noqa: BLE001
            # File not found or other error - PyGithub can raise various exceptions
            return None
