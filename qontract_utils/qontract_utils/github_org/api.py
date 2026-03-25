"""GitHub Organization API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless API client for GitHub organization operations
with support for metrics and rate limiting via hooks (ADR-006).

Note: PyGithub does not support listing pending org invitations, so that
endpoint is implemented directly using requests.
"""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from typing import Any

import requests
import structlog
from github import Github
from github.NamedUser import NamedUser
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

# Prometheus metrics (following qontract_reconcile_external_api_<component>_requests_total convention)
github_org_request = Counter(
    "qontract_reconcile_external_api_github_org_requests_total",
    "Total number of GitHub Organization API requests",
    ["method", "verb"],
)

github_org_request_duration = Histogram(
    "qontract_reconcile_external_api_github_org_request_duration_seconds",
    "GitHub Organization API request duration in seconds",
    ["method", "verb"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

# Local storage for latency tracking (tuple stack to support nested calls)
_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)


@dataclass(frozen=True)
class GithubOrgApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "org.get_admin_members")
        verb: HTTP verb (e.g., "GET", "PUT")
        org: GitHub organization name
    """

    method: str
    verb: str
    org: str


def _metrics_hook(context: GithubOrgApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    github_org_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: GithubOrgApiCallContext) -> None:
    """Built-in hook to start latency measurement."""
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: GithubOrgApiCallContext) -> None:
    """Built-in hook to record latency measurement."""
    stack = _latency_tracker.get()
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    github_org_request_duration.labels(context.method, context.verb).observe(duration)


def _request_log_hook(context: GithubOrgApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug(
        "GitHub Org API request",
        org=context.org,
        method=context.method,
        verb=context.verb,
    )


_DEFAULT_HOOKS = Hooks(
    pre_hooks=[_metrics_hook, _request_log_hook, _latency_start_hook],
    post_hooks=[_latency_end_hook],
)


@with_hooks(hooks=_DEFAULT_HOOKS)
class GithubOrgApi:
    """Layer 1: Pure API client for GitHub organization member operations.

    Provides stateless access to GitHub org membership APIs:
    - Listing current admin (owner) members
    - Listing pending invitations (not supported by PyGithub, uses requests)
    - Adding a member as org admin

    All methods are synchronous for use in Celery workers.
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        hooks: Hooks | None = None,  # noqa: ARG002 - handled by @with_hooks
    ) -> None:
        """Initialize GithubOrgApi.

        Args:
            token: GitHub API token
            base_url: GitHub API base URL (override for GHE)
            hooks: Optional custom hooks merged with built-in hooks
        """
        self._token = token
        self._base_url = base_url
        self._gh = Github(token, base_url=base_url)

    def _paginated_get(self, path: str) -> list[dict[str, Any]]:
        """Perform a paginated GET against the GitHub REST API.

        Args:
            path: API path (e.g., "/orgs/my-org/invitations")

        Returns:
            Combined list of all items across all pages
        """
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github.v3+json",
        }
        items: list[dict[str, Any]] = []

        while url:
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            page = response.json()
            if isinstance(page, list):
                items.extend(page)
            # Follow pagination links
            url = response.links.get("next", {}).get("url", "")

        return items

    @invoke_with_hooks(
        lambda self, org_name: GithubOrgApiCallContext(  # noqa: ARG005
            method="org.get_admin_members", verb="GET", org=org_name
        )
    )
    def get_admin_members(self, org_name: str) -> list[str]:
        """Fetch current admin (owner) members of a GitHub organization.

        Returns lowercase login names of all members with the 'admin' role.

        Args:
            org_name: GitHub organization name

        Returns:
            Sorted list of lowercase GitHub usernames with admin role
        """
        org = self._gh.get_organization(org_name)
        return sorted(m.login.lower() for m in org.get_members(role="admin"))

    @invoke_with_hooks(
        lambda self, org_name: GithubOrgApiCallContext(  # noqa: ARG005
            method="org.get_pending_invitations", verb="GET", org=org_name
        )
    )
    def get_pending_invitations(self, org_name: str) -> list[str]:
        """Fetch pending organization invitations.

        PyGithub does not support this endpoint, so it is implemented
        directly using the GitHub REST API.

        Args:
            org_name: GitHub organization name

        Returns:
            Sorted list of lowercase GitHub usernames with pending invitations
        """
        invitations = self._paginated_get(f"/orgs/{org_name}/invitations")
        return sorted(
            login for inv in invitations if (login := inv.get("login", "").lower())
        )

    @invoke_with_hooks(
        lambda self, org_name, username: GithubOrgApiCallContext(  # noqa: ARG005
            method="org.add_member_as_admin", verb="PUT", org=org_name
        )
    )
    def add_member_as_admin(self, org_name: str, username: str) -> None:
        """Add a user to a GitHub organization with admin (owner) role.

        Args:
            org_name: GitHub organization name
            username: GitHub username to add as admin
        """
        org = self._gh.get_organization(org_name)
        user = self._gh.get_user(username)
        if not isinstance(user, NamedUser):
            raise TypeError(
                f"Expected NamedUser for '{username}', got {type(user).__name__}"
            )
        org.add_to_members(user, "admin")
