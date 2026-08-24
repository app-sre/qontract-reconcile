"""Quay API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless API client for Quay robot-account operations
with support for metrics via hooks (ADR-006).
"""

import contextlib
import contextvars
import time
from dataclasses import dataclass
from typing import Any, Self

import httpx2
import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API
from qontract_utils.quay_api.models import RobotAccount, RobotAccountPermission
from qontract_utils.user_agent import DEFAULT_USER_AGENT

logger = structlog.get_logger(__name__)

# Prometheus metrics (following qontract_reconcile_external_api_<component>_requests_total)
quay_request = Counter(
    "qontract_reconcile_external_api_quay_requests_total",
    "Total number of Quay API requests",
    ["method", "verb"],
)

quay_request_duration = Histogram(
    "qontract_reconcile_external_api_quay_request_duration_seconds",
    "Quay API request duration in seconds",
    ["method", "verb"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)

TIMEOUT = 60


@dataclass(frozen=True)
class QuayApiCallContext:
    """Context information passed to API call hooks."""

    method: str
    verb: str
    organization: str


def _metrics_hook(context: QuayApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    quay_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: QuayApiCallContext) -> None:
    """Built-in hook to start latency measurement."""
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: QuayApiCallContext) -> None:
    """Built-in hook to record latency measurement."""
    stack = _latency_tracker.get()
    if not stack:
        return
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    quay_request_duration.labels(context.method, context.verb).observe(duration)


def _request_log_hook(context: QuayApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug(
        "Quay API request",
        organization=context.organization,
        method=context.method,
        verb=context.verb,
    )


def _normalize_host(base_url: str) -> str:
    """Normalize a Quay host to a scheme+host URL without trailing slash."""
    if base_url.startswith(("http://", "https://")):
        return base_url.rstrip("/")
    return f"https://{base_url.rstrip('/')}"


def _error_message(error: httpx2.HTTPStatusError) -> str:
    """Extract Quay error message from an HTTP error response, if present."""
    with contextlib.suppress(ValueError, KeyError, AttributeError, TypeError):
        message = error.response.json().get("message", "")
        if isinstance(message, str):
            return message
    return ""


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
class QuayApi:
    """Stateless Quay API client for robot-account operations.

    Layer 1 (Pure Communication) client following ADR-014. One instance is
    bound to a single organization. Robot names are short names (without the
    ``org+`` prefix); the prefix is applied internally.

    All methods are synchronous for use in Celery workers.
    """

    _hooks: Hooks

    def __init__(
        self,
        token: str,
        organization: str,
        base_url: str = "quay.io",
        timeout: int = TIMEOUT,
        max_retries: int = 3,
        hooks: Hooks | None = None,  # ruff: ignore[unused-method-argument] - handled by @with_hooks
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        """Initialize Quay API client.

        Args:
            token: Quay OAuth/automation token (Bearer)
            organization: Quay organization name
            base_url: Hostname (e.g. ``quay.io``) or full URL
            timeout: HTTP timeout in seconds
            max_retries: Number of retries for failed requests
            hooks: Optional custom hooks merged with built-in hooks
            user_agent: User-Agent header sent with every request
        """
        self.host = _normalize_host(base_url)
        self.organization = organization
        self._client = httpx2.Client(
            base_url=self.host,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": user_agent,
                "Content-Type": "application/json",
            },
            timeout=timeout,
            transport=httpx2.HTTPTransport(retries=max_retries),
        )

    def _robot_user(self, robot_name: str) -> str:
        """Return the fully-qualified Quay robot username (``org+name``)."""
        return f"{self.organization}+{robot_name}"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET request returning JSON."""
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def _put(self, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """PUT request. Empty/204 responses return an empty dict."""
        kwargs: dict[str, Any] = {}
        if data is not None:
            kwargs["json"] = data
        response = self._client.put(path, **kwargs)
        response.raise_for_status()
        if response.status_code == httpx2.codes.NO_CONTENT or not response.content:
            return {}
        return response.json()

    def _delete(self, path: str) -> None:
        """DELETE request."""
        response = self._client.delete(path)
        response.raise_for_status()

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="robots.list", verb="GET", organization=self.organization
        )
    )
    def list_robot_accounts(self) -> list[RobotAccount]:
        """List robot accounts in the organization.

        Names are normalized to short names (the ``org+`` prefix is stripped).
        """
        body = self._get(
            f"/api/v1/organization/{self.organization}/robots",
            params={"permissions": "true"},
        )
        prefix = f"{self.organization}+"
        return [
            RobotAccount(
                name=robot["name"].removeprefix(prefix),
                description=robot.get("description"),
                teams=[t["name"] for t in robot.get("teams") or []],
                repositories=robot.get("repositories") or [],
            )
            for robot in body["robots"]
        ]

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="robots.create", verb="PUT", organization=self.organization
        )
    )
    def create_robot_account(self, name: str, description: str) -> None:
        """Create a robot account. The returned token is discarded."""
        self._put(
            f"/api/v1/organization/{self.organization}/robots/{name}",
            data={"description": description},
        )

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="robots.delete", verb="DELETE", organization=self.organization
        )
    )
    def delete_robot_account(self, name: str) -> None:
        """Delete a robot account."""
        self._delete(f"/api/v1/organization/{self.organization}/robots/{name}")

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="robots.permissions", verb="GET", organization=self.organization
        )
    )
    def get_robot_account_permissions(self, name: str) -> list[RobotAccountPermission]:
        """List repository permissions for a robot account."""
        body = self._get(
            f"/api/v1/organization/{self.organization}/robots/{name}/permissions"
        )
        return [
            RobotAccountPermission.model_validate(perm) for perm in body["permissions"]
        ]

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="team.members.add", verb="PUT", organization=self.organization
        )
    )
    def add_user_to_team(self, user: str, team: str) -> None:
        """Add a user (or fully-qualified robot ``org+name``) to a team."""
        self._put(
            f"/api/v1/organization/{self.organization}/team/{team}/members/{user}"
        )

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="team.robots.remove", verb="DELETE", organization=self.organization
        )
    )
    def remove_robot_from_team(self, robot_name: str, team: str) -> None:
        """Remove a robot from a team without dropping org membership.

        Idempotent when the robot is not a team member.
        """
        robot_user = self._robot_user(robot_name)
        path = (
            f"/api/v1/organization/{self.organization}/team/{team}/members/{robot_user}"
        )
        try:
            self._delete(path)
        except httpx2.HTTPStatusError as error:
            expected = f"User {robot_user} does not belong to team {team}"
            if _error_message(error) != expected:
                raise

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="repo.robots.permissions.set",
            verb="PUT",
            organization=self.organization,
        )
    )
    def set_repo_robot_account_permissions(
        self, repo_name: str, robot_name: str, role: str
    ) -> None:
        """Set a robot's role on a repository."""
        self._put(
            f"/api/v1/repository/{self.organization}/{repo_name}"
            f"/permissions/user/{self._robot_user(robot_name)}",
            data={"role": role},
        )

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="repo.robots.permissions.delete",
            verb="DELETE",
            organization=self.organization,
        )
    )
    def delete_repo_robot_account_permissions(
        self, repo_name: str, robot_name: str
    ) -> None:
        """Remove a robot's permission on a repository."""
        self._delete(
            f"/api/v1/repository/{self.organization}/{repo_name}"
            f"/permissions/user/{self._robot_user(robot_name)}"
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
