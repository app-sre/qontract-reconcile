"""GitLab group/project administration API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
Scoped to a single GitLab instance. Provides group listing and project
creation. File/branch content operations live in
qontract_utils.vcs.providers.gitlab_client.GitLabRepoApi.
"""

import contextvars
import re
import time
from dataclasses import dataclass
from typing import Self

import gitlab
import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.gitlab_api.models import (
    GitlabAccessLevel,
    GitlabGroup,
    GitlabGroupMember,
    GitlabProject,
    GitlabUser,
)
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API
from qontract_utils.user_agent import DEFAULT_USER_AGENT

logger = structlog.get_logger(__name__)

# Internal GitLab bot users created for group access tokens follow this naming
# convention: https://docs.gitlab.com/administration/internal_users/
_GROUP_BOT_USERNAME_RE = re.compile(r"group_.+_bot_.+")

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


class GitlabUserNotFoundError(Exception):
    pass


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

    Args:
        url: GitLab instance URL
        token: GitLab personal access token
        ssl_verify: Whether to verify SSL certificates
        timeout: Request timeout in seconds
        hooks: Optional custom hooks to merge with built-in hooks.
        user_agent: User-Agent header sent with every request. Defaults to
            identifying qontract-utils itself.
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
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.url = url
        self._gitlab = gitlab.Gitlab(
            url,
            private_token=token,
            ssl_verify=ssl_verify,
            timeout=timeout,
            per_page=100,
            pagination="keyset",
            order_by="id",
            user_agent=user_agent,
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
        lambda self: GitlabApiCallContext(method="get_group_members", url=self.url)
    )
    def get_group_members(self, group_path: str) -> list[GitlabGroupMember]:
        """List a group's members, excluding internal group-access-token bot users."""
        group = self._gitlab.groups.get(group_path)
        return [
            GitlabGroupMember(
                id=member.id,
                username=member.username,
                name=member.name,
                access_level=member.access_level,
            )
            for member in group.members.list(iterator=True)
            if not _GROUP_BOT_USERNAME_RE.match(member.username)
        ]

    @invoke_with_hooks(
        lambda self: GitlabApiCallContext(method="get_user_by_username", url=self.url)
    )
    def get_user_by_username(self, username: str) -> GitlabUser:
        """Resolve a username to its GitLab user ID.

        Raises:
            GitlabUserNotFoundError: if no user with this username exists.
        """
        if not (users := self._gitlab.users.list(username=username)):
            raise GitlabUserNotFoundError(username)
        user = users[0]
        return GitlabUser(id=user.id, username=user.username, name=user.name)

    @invoke_with_hooks(
        lambda self: GitlabApiCallContext(method="add_group_member", url=self.url)
    )
    def add_group_member(
        self, group_path: str, user_id: int, access_level: GitlabAccessLevel
    ) -> GitlabGroupMember:
        """Add a user to a group with the given access level.

        If the user is already a member - e.g. added outside of our cached
        view of current members - updates their access level instead of
        failing.
        """
        group = self._gitlab.groups.get(group_path)
        try:
            member = group.members.create(
                {
                    "user_id": user_id,
                    "access_level": access_level.to_access_level(),
                }
            )
        except gitlab.GitlabCreateError:
            member = group.members.get(user_id)
            member.access_level = access_level.to_access_level()
            member.save()
        return GitlabGroupMember(
            id=member.id,
            username=member.username,
            name=member.name,
            access_level=member.access_level,
        )

    @invoke_with_hooks(
        lambda self: GitlabApiCallContext(method="remove_group_member", url=self.url)
    )
    def remove_group_member(self, group_path: str, member_id: int) -> None:
        """Remove a member from a group."""
        self._gitlab.groups.get(group_path).members.delete(member_id)

    @invoke_with_hooks(
        lambda self: GitlabApiCallContext(
            method="update_group_member_access", url=self.url
        )
    )
    def update_group_member_access(
        self, group_path: str, member_id: int, access_level: GitlabAccessLevel
    ) -> GitlabGroupMember:
        """Change a group member's access level."""
        group = self._gitlab.groups.get(group_path)
        member = group.members.get(member_id)
        member.access_level = access_level.to_access_level()
        member.save()
        return GitlabGroupMember(
            id=member.id,
            username=member.username,
            name=member.name,
            access_level=member.access_level,
        )

    def close(self) -> None:
        """Close the underlying HTTP session and release connections."""
        self._gitlab.session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
