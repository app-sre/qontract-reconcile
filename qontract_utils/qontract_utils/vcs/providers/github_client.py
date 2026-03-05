"""GitHub Repository API client with hook system for metrics and rate limiting."""

import contextvars
import time
from dataclasses import dataclass

import structlog
from github import Github
from github.Repository import Repository
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

# Prometheus metrics
github_request = Counter(
    # Following naming convention (qontract_reconcile_external_api_<component>_requests_total) to
    # automatically include this metric in dashboards
    "qontract_reconcile_external_api_github_requests_total",
    "Total number of GitHub API requests",
    ["method", "repo_url"],
)

github_request_duration = Histogram(
    "qontract_reconcile_external_api_github_request_duration_seconds",
    "GitHub API request duration in seconds",
    ["method", "repo_url"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

# Local storage for latency tracking (tuple stack to support nested calls)
_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)


@dataclass(frozen=True)
class GitHubApiCallContext:
    """Context for GitHub API call hooks.

    Provides metadata about the API call for hooks to use.
    """

    method: str  # e.g., "get_file", "get_tree"
    repo_url: str


def _metrics_hook(context: GitHubApiCallContext) -> None:
    """Built-in Prometheus metrics hook.

    Records all API calls with method and verb labels.
    """
    github_request.labels(context.method, context.repo_url).inc()


def _latency_start_hook(_context: GitHubApiCallContext) -> None:
    """Built-in hook to start latency measurement.

    Pushes the start time onto the stack to support nested calls.
    """
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: GitHubApiCallContext) -> None:
    """Built-in hook to record latency measurement.

    Pops the most recent start time from the stack and records duration.
    """
    stack = _latency_tracker.get()
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    github_request_duration.labels(context.method, context.repo_url).observe(duration)


def _request_log_hook(context: GitHubApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug("API request", method=context.method, repo_url=context.repo_url)


@with_hooks(
    hooks=Hooks(
        pre_hooks=[
            _metrics_hook,
            _request_log_hook,
            _latency_start_hook,
        ],
        post_hooks=[_latency_end_hook],
    )
)
class GitHubRepoApi:
    """GitHub Repository API client with hook system.

    Args:
        owner: GitHub repository owner (user or organization)
        repo: GitHub repository name
        token: GitHub personal access token
        github_api_url: GitHub API base URL (default: https://api.github.com)
        timeout: Request timeout in seconds
        hooks: Optional custom hooks to merge with built-in hooks.
            Built-in hooks (metrics, logging, latency) are automatically included.
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str,
        github_api_url: str = "https://api.github.com",
        timeout: int = 30,
        hooks: Hooks | None = None,  # noqa: ARG002 - Handled by @with_hooks decorator
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.repo_url = f"https://github.com/{owner}/{repo}"
        self._timeout = timeout

        # PyGithub expects base_url without /api/v3
        self._github = Github(
            login_or_token=token, base_url=github_api_url.rstrip("/"), timeout=timeout
        )
        self._repository: Repository = self._github.get_repo(f"{owner}/{repo}")

    @invoke_with_hooks(
        lambda self: GitHubApiCallContext(method="get_file", repo_url=self.repo_url)
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
            content_file = self._repository.get_contents(path, ref=ref)
            if isinstance(content_file, list):
                # Path is a directory, not a file
                return None
            return content_file.decoded_content.decode("utf-8")
        except Exception:  # noqa: BLE001
            # File not found or other error - PyGithub can raise various exceptions
            return None
