"""GitLab Repository API client with hook system for metrics and rate limiting."""

from collections.abc import Callable
from dataclasses import dataclass

import gitlab
from gitlab.v4.objects import Project


@dataclass
class GitLabApiCallContext:
    """Context for GitLab API call hooks.

    Provides metadata about the API call for hooks to use.
    """

    method: str  # e.g., "get_file", "get_tree"
    repo_url: str
    project_id: str


class GitLabRepoApi:
    """GitLab Repository API client with hook system.

    Args:
        project_id: GitLab project ID or path (e.g., "group/project")
        token: GitLab personal access token
        gitlab_url: GitLab instance URL (default: https://gitlab.com)
        timeout: Request timeout in seconds
        before_api_call_hooks: List of hooks called before each API call
    """

    def __init__(
        self,
        project_id: str,
        token: str,
        gitlab_url: str,
        timeout: int = 30,
        before_api_call_hooks: list[Callable[[GitLabApiCallContext], None]]
        | None = None,
    ) -> None:
        self.project_id = project_id
        self.repo_url = f"{gitlab_url}/{project_id}"
        self._timeout = timeout
        self._before_api_call_hooks = before_api_call_hooks or []

        # Create GitLab client
        self._gitlab = gitlab.Gitlab(
            url=gitlab_url,
            private_token=token,
            timeout=timeout,
        )
        self._project: Project = self._gitlab.projects.get(project_id)

    def _execute_hooks(self, context: GitLabApiCallContext) -> None:
        """Execute all before_api_call_hooks with the given context.

        Args:
            context: API call context with method, repo_url, project_id
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
        context = GitLabApiCallContext(
            method="get_file",
            repo_url=self.repo_url,
            project_id=self.project_id,
        )
        self._execute_hooks(context)

        try:
            file = self._project.files.get(file_path=path, ref=ref)
            return file.decode().decode("utf-8")
        except Exception:  # noqa: BLE001
            # File not found or other error - python-gitlab can raise various exceptions
            return None
