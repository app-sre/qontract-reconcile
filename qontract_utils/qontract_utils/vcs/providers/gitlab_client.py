"""GitLab Repository API client with hook system for metrics and rate limiting."""

import contextvars
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import gitlab
import structlog
from gitlab.v4.objects import Project
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import DEFAULT_RETRY_CONFIG, RetryConfig, invoke_with_hooks

logger = structlog.get_logger(__name__)

# Prometheus metrics
gitlab_request = Counter(
    # Following naming convention (qontract_reconcile_external_api_<component>_requests_total) to
    # automatically include this metric in dashboards
    "qontract_reconcile_external_api_gitlab_requests_total",
    "Total number of GitLab API requests",
    ["method", "repo_url"],
)

gitlab_request_duration = Histogram(
    "qontract_reconcile_external_api_gitlab_request_duration_seconds",
    "GitLab API request duration in seconds",
    ["method", "repo_url"],
)

# Local storage for latency tracking
_latency_tracker = contextvars.ContextVar("latency_tracker", default=0.0)


@dataclass(frozen=True)
class GitLabApiCallContext:
    """Context for GitLab API call hooks.

    Provides metadata about the API call for hooks to use.
    """

    method: str  # e.g., "get_file", "get_tree"
    repo_url: str


def _metrics_hook(context: GitLabApiCallContext) -> None:
    """Built-in Prometheus metrics hook.

    Records all API calls with method and verb labels.
    """
    gitlab_request.labels(context.method, context.repo_url).inc()


def _latency_start_hook(_context: GitLabApiCallContext) -> None:
    """Built-in hook to start latency measurement.

    Stores the start time in local storage.
    """
    _latency_tracker.set(time.perf_counter())


def _latency_end_hook(context: GitLabApiCallContext) -> None:
    """Built-in hook to record latency measurement.

    Calculates duration from start time and records to Prometheus histogram.
    """
    duration = time.perf_counter() - _latency_tracker.get()
    gitlab_request_duration.labels(context.method, context.repo_url).observe(duration)
    _latency_tracker.set(0.0)


def _request_log_hook(context: GitLabApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug("API request", method=context.method, repo_url=context.repo_url)


class GitLabRepoApi:
    """GitLab Repository API client with hook system.

    Args:
        project_id: GitLab project ID or path (e.g., "group/project")
        token: GitLab personal access token
        gitlab_url: GitLab instance URL (default: https://gitlab.com)
        timeout: Request timeout in seconds
        pre_hooks: List of hooks called before each API call
    """

    def __init__(
        self,
        project_id: str,
        token: str,
        gitlab_url: str,
        timeout: int = 30,
        pre_hooks: Iterable[Callable[[GitLabApiCallContext], None]] | None = None,
        post_hooks: Iterable[Callable[[GitLabApiCallContext], None]] | None = None,
        error_hooks: Iterable[Callable[[GitLabApiCallContext], None]] | None = None,
        retry_hooks: Iterable[Callable[[GitLabApiCallContext, int], None]]
        | None = None,
        retry_config: RetryConfig | None = DEFAULT_RETRY_CONFIG,
    ) -> None:
        self.project_id = project_id
        self.repo_url = f"{gitlab_url}/{project_id}"
        self._timeout = timeout
        # Setup hook system - always include built-in hooks
        self._pre_hooks: list[Callable[[GitLabApiCallContext], None]] = [
            _metrics_hook,
            _latency_start_hook,
            _request_log_hook,
        ]
        if pre_hooks:
            self._pre_hooks.extend(pre_hooks)
        self._post_hooks: list[Callable[[GitLabApiCallContext], None]] = [
            _latency_end_hook
        ]
        if post_hooks:
            self._post_hooks.extend(post_hooks)
        self._error_hooks: list[Callable[[GitLabApiCallContext], None]] = []
        if error_hooks:
            self._error_hooks.extend(error_hooks)
        self._retry_hooks: list[Callable[[GitLabApiCallContext, int], None]] = []
        if retry_hooks:
            self._retry_hooks.extend(retry_hooks)
        self._retry_config = retry_config

        # Create GitLab client
        self._gitlab = gitlab.Gitlab(
            url=gitlab_url,
            private_token=token,
            timeout=timeout,
        )
        self._project: Project = self._gitlab.projects.get(project_id)

    @invoke_with_hooks(
        lambda self: GitLabApiCallContext(method="get_file", repo_url=self.repo_url)
    )
    def get_file(self, path: str, ref: str = "master") -> str | None:
        """Fetch file content from repository.

        Args:
            path: File path relative to repository root
            ref: Git reference (branch, tag, commit SHA)

        Returns:
            File content as string, or None if file not found
        """
        try:
            file = self._project.files.get(file_path=path, ref=ref)
            return file.decode().decode("utf-8")
        except Exception:  # noqa: BLE001
            # File not found or other error - python-gitlab can raise various exceptions
            return None
