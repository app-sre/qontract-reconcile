"""GitLab group/project administration API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
Scoped to a single GitLab instance. Provides group listing, project creation,
and the file/branch primitives needed to bootstrap a SaaS bundle repo.
"""

import contextvars
import time
from dataclasses import dataclass
from typing import Self

import gitlab
import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.gitlab_api.models import GitlabGroup, GitlabProject
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

gitlab_projects_request = Counter(
    "qontract_reconcile_external_api_gitlab_projects_requests_total",
    "Total number of GitLab group/project administration API requests",
    ["method", "url"],
)

gitlab_projects_request_duration = Histogram(
    "qontract_reconcile_external_api_gitlab_projects_request_duration_seconds",
    "GitLab group/project administration API request duration in seconds",
    ["method", "url"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)

DEFAULT_BRANCH = "master"
SAAS_BUNDLE_BRANCHES = ("staging", "production")
README_PATH = "README.md"
README_COMMIT_MESSAGE = "Initial commit"
README_CONTENT = "Use the staging or the production branches."


@dataclass(frozen=True)
class GitlabApiCallContext:
    """Context information passed to API call hooks."""

    method: str
    url: str


def _metrics_hook(context: GitlabApiCallContext) -> None:
    gitlab_projects_request.labels(context.method, context.url).inc()


def _latency_start_hook(_context: GitlabApiCallContext) -> None:
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: GitlabApiCallContext) -> None:
    stack = _latency_tracker.get()
    if not stack:
        return
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    gitlab_projects_request_duration.labels(context.method, context.url).observe(
        duration
    )


def _request_log_hook(context: GitlabApiCallContext) -> None:
    logger.debug("API request", method=context.method, url=context.url)


@with_hooks(
    hooks=Hooks(
        pre_hooks=[_metrics_hook, _request_log_hook, _latency_start_hook],
        post_hooks=[_latency_end_hook],
    )
)
class GitlabApi:
    """Stateless GitLab group/project administration client.

    Layer 1 (Pure Communication) client following ADR-014. Scoped to a single
    GitLab instance.
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        url: str,
        token: str,
        *,
        ssl_verify: bool = True,
        timeout: int = 30,
        hooks: Hooks | None = None,  # ruff: ignore[unused-method-argument] - Handled by @with_hooks decorator
    ) -> None:
        self.url = url
        self._gitlab = gitlab.Gitlab(
            url,
            private_token=token,
            ssl_verify=ssl_verify,
            timeout=timeout,
            per_page=100,
            pagination="keyset",
        )

    @invoke_with_hooks(
        lambda self: GitlabApiCallContext(method="get_group", url=self.url)
    )
    def get_group(self, group_name: str) -> GitlabGroup:
        """Fetch a group and the names of the projects directly under it.

        Does not include projects in subgroups - pass the subgroup's own full
        path (e.g. "team/subteam") to list its projects instead.
        """
        group = self._gitlab.groups.get(group_name)
        return GitlabGroup(
            id=group.id,
            full_path=group.full_path,
            project_names=[p.name for p in group.projects.list(iterator=True)],
        )

    @invoke_with_hooks(
        lambda self: GitlabApiCallContext(method="create_project", url=self.url)
    )
    def create_project(self, group_id: int, name: str) -> GitlabProject:
        """Create a project under the given group."""
        project = self._gitlab.projects.create({"name": name, "namespace_id": group_id})
        return GitlabProject(
            id=project.id,
            name=project.name,
            path_with_namespace=project.path_with_namespace,
            web_url=project.web_url,
        )

    @invoke_with_hooks(
        lambda self: GitlabApiCallContext(method="create_file", url=self.url)
    )
    def create_file(
        self,
        project_id: int,
        branch: str,
        file_path: str,
        commit_message: str,
        content: str,
    ) -> None:
        """Create a file via a new commit on the given branch."""
        project = self._gitlab.projects.get(project_id, lazy=True)
        project.commits.create(
            {
                "branch": branch,
                "commit_message": commit_message,
                "actions": [
                    {"action": "create", "file_path": file_path, "content": content}
                ],
            }
        )

    @invoke_with_hooks(
        lambda self: GitlabApiCallContext(method="create_branch", url=self.url)
    )
    def create_branch(
        self, project_id: int, new_branch: str, source_branch: str
    ) -> None:
        """Create a branch from an existing source branch."""
        project = self._gitlab.projects.get(project_id, lazy=True)
        project.branches.create({"branch": new_branch, "ref": source_branch})

    def initiate_saas_bundle_repo(self, project_id: int) -> None:
        """Bootstrap a SaaS bundle repo: a README commit on `master`, then `staging`/`production` branches cut from it."""
        self.create_file(
            project_id,
            DEFAULT_BRANCH,
            README_PATH,
            README_COMMIT_MESSAGE,
            README_CONTENT,
        )
        for branch in SAAS_BUNDLE_BRANCHES:
            self.create_branch(project_id, branch, DEFAULT_BRANCH)

    def close(self) -> None:
        """Close the underlying HTTP session and release connections."""
        self._gitlab.session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
