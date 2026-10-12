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
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any

import requests
import structlog
from github import Github
from github.GithubException import GithubException, RateLimitExceededException
from github.NamedUser import NamedUser
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, RetryConfig, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API
from qontract_utils.user_agent import DEFAULT_USER_AGENT

logger = structlog.get_logger(__name__)

# GitHub resets its primary rate limit window hourly. Used as a conservative
# fallback when a rate-limit response carries neither a Retry-After nor an
# X-RateLimit-Reset header.
_DEFAULT_RATE_LIMIT_FALLBACK_SECONDS = 3600


class GithubRateLimitExceededError(Exception):
    """Raised when GitHub's primary or secondary API rate limit is exhausted.

    Retrying before `reset_at` is futile - the caller should back off instead.
    """

    def __init__(self, reset_at: datetime, message: str | None = None) -> None:
        self.reset_at = reset_at
        super().__init__(
            message
            or f"GitHub API rate limit exceeded; resets at {reset_at.isoformat()}"
        )


def _reset_at_from_headers(headers: Mapping[str, str]) -> datetime:
    """Derive the rate-limit reset time from response/exception headers.

    Prefers `Retry-After` (used for GitHub's secondary rate limit, seconds
    from now) over `X-RateLimit-Reset` (used for the primary rate limit, an
    absolute epoch timestamp). Falls back to a conservative default when
    neither header is present or a value fails to parse - `Retry-After` may
    also carry an HTTP-date per RFC 9110, which `int()` cannot parse.
    """
    if retry_after := headers.get("retry-after"):
        with suppress(ValueError, OverflowError):
            return datetime.now(UTC) + timedelta(seconds=int(retry_after))
    if reset := headers.get("x-ratelimit-reset"):
        with suppress(ValueError, OSError, OverflowError):
            return datetime.fromtimestamp(int(reset), tz=UTC)
    return datetime.now(UTC) + timedelta(seconds=_DEFAULT_RATE_LIMIT_FALLBACK_SECONDS)


def _is_rate_limit_response(status_code: int, headers: Mapping[str, str]) -> bool:
    """Match GitHub's primary and secondary rate-limit response shapes.

    Primary: 403 with `X-RateLimit-Remaining: 0`. Secondary (abuse detection,
    concurrent-request limits): 403 or 429, often with `Retry-After` but NOT
    necessarily zeroing the primary quota's `X-RateLimit-Remaining` (it's a
    separate bucket) - see
    https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
    """
    if status_code == HTTPStatus.TOO_MANY_REQUESTS:
        return True
    return status_code == HTTPStatus.FORBIDDEN and (
        headers.get("x-ratelimit-remaining") == "0"
        or headers.get("retry-after") is not None
    )


def _rate_limit_reset_at(exc: BaseException) -> datetime | None:
    """Return the rate-limit reset time if `exc` is a GitHub rate limit error.

    Returns None for any other exception. Shared by the error hook (which
    converts the exception) and the retry predicate (which must never retry
    it), so the two can never disagree on what counts as a rate limit.
    """
    if isinstance(exc, RateLimitExceededException):
        return _reset_at_from_headers(exc.headers or {})
    if isinstance(exc, GithubException) and _is_rate_limit_response(
        exc.status, exc.headers or {}
    ):
        return _reset_at_from_headers(exc.headers or {})
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        response = exc.response
        if _is_rate_limit_response(response.status_code, response.headers):
            return _reset_at_from_headers(response.headers)
    return None


# Server-side statuses worth a quick retry (distinct from client errors like
# 401/404/422, which won't succeed on retry, and from 403/429 rate limits,
# which are handled separately and must never be retried).
_RETRYABLE_HTTP_STATUSES = frozenset(
    {
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)


def _should_retry(exc: Exception) -> bool:
    """Retry transient network/server errors; never retry rate limits.

    Retrying a rate-limited request before GitHub's reset window is
    guaranteed to fail and only burns more of the shared quota, so those
    fail fast via `_rate_limit_error_hook` instead of being retried here.
    """
    if _rate_limit_reset_at(exc) is not None:
        return False
    if isinstance(exc, requests.ConnectionError | requests.Timeout):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in _RETRYABLE_HTTP_STATUSES
    return isinstance(exc, GithubException) and exc.status in _RETRYABLE_HTTP_STATUSES


_RETRY_CONFIG = RetryConfig(
    on=_should_retry,
    attempts=3,
    timeout=5.0,
    wait_initial=0.5,
    wait_max=5.0,
    wait_jitter=1.0,
)


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


def _rate_limit_error_hook(_context: GithubOrgApiCallContext, exc: Exception) -> None:
    """Convert GitHub rate-limit errors into GithubRateLimitExceededError.

    Runs as an error hook, receiving the exception that triggered it, so all
    three API methods share one detection path instead of each catching
    PyGithub/requests exceptions individually. Shares detection logic with
    `_should_retry` via `_rate_limit_reset_at` so the two can never disagree
    on what counts as a rate limit. Raising here replaces the original
    exception for the caller.
    """
    if (reset_at := _rate_limit_reset_at(exc)) is not None:
        raise GithubRateLimitExceededError(reset_at) from exc


_DEFAULT_HOOKS = Hooks(
    pre_hooks=[_metrics_hook, _request_log_hook, _latency_start_hook],
    post_hooks=[_latency_end_hook],
    error_hooks=[_rate_limit_error_hook],
    retry_config=_RETRY_CONFIG,
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
        hooks: Hooks | None = None,  # ruff: ignore[unused-method-argument] - handled by @with_hooks
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        """Initialize GithubOrgApi.

        Args:
            token: GitHub API token
            base_url: GitHub API base URL (override for GHE)
            hooks: Optional custom hooks merged with built-in hooks
            user_agent: User-Agent header sent with every request. Defaults to
                identifying qontract-utils itself; callers embedded in a larger
                service should pass their own app name/version instead.
        """
        self._token = token
        self._base_url = base_url
        self._user_agent = user_agent
        self._gh = Github(token, base_url=base_url, user_agent=user_agent)

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
            "User-Agent": self._user_agent,
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
        lambda self, org_name: GithubOrgApiCallContext(  # ruff: ignore[unused-lambda-argument]
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
        lambda self, org_name: GithubOrgApiCallContext(  # ruff: ignore[unused-lambda-argument]
            method="org.get_members", verb="GET", org=org_name
        )
    )
    def get_members(self, org_name: str) -> list[str]:
        """Fetch all members of a GitHub organization (any role).

        Unlike `get_admin_members`, this returns every organization member
        regardless of role and preserves the login casing exactly as GitHub
        reports it - callers that need case-insensitive comparison must
        lowercase on their side.

        Args:
            org_name: GitHub organization name

        Returns:
            Sorted list of GitHub usernames (original case) of all org members
        """
        org = self._gh.get_organization(org_name)
        return sorted(m.login for m in org.get_members())

    @invoke_with_hooks(
        lambda self, org_name: GithubOrgApiCallContext(  # ruff: ignore[unused-lambda-argument]
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
        lambda self, org_name, username: GithubOrgApiCallContext(  # ruff: ignore[unused-lambda-argument]
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
