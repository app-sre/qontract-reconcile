"""Quay API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless API client with support for metrics and
rate limiting via hooks (ADR-006).
"""

import contextvars
import time
from dataclasses import dataclass
from typing import Self

import httpx2
import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API
from qontract_utils.quay_api.models import QuayRepo

logger = structlog.get_logger(__name__)

quay_request = Counter(
    # Following naming convention (qontract_reconcile_external_api_<component>_requests_total)
    # to automatically include this metric in dashboards
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
# Quay paginates via next_page token; cap page follows to avoid infinite loops
_MAX_PAGE_FOLLOWS = 15


@dataclass(frozen=True)
class QuayApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "repository.list")
        verb: HTTP verb (e.g., "GET")
        org: Quay organization name
    """

    method: str
    verb: str
    org: str


def _metrics_hook(context: QuayApiCallContext) -> None:
    quay_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: QuayApiCallContext) -> None:
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: QuayApiCallContext) -> None:
    stack = _latency_tracker.get()
    if not stack:
        return
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    quay_request_duration.labels(context.method, context.verb).observe(duration)


def _request_log_hook(context: QuayApiCallContext) -> None:
    logger.debug(
        "API request", method=context.method, verb=context.verb, org=context.org
    )


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
    """Stateless Quay API client with hook system.

    Layer 1 (Pure Communication) client following ADR-014. Scoped to a single
    Quay organization. Provides methods to manage repositories within that org.

    Hook System (ADR-006):
    - Always includes built-in hooks (metrics, logging, latency)
    - Supports additional custom hooks via hooks parameter
    - Hooks receive QuayApiCallContext with method, verb, org

    Example:
        >>> api = QuayApi(org="my-org", token="...", base_url="https://quay.io")
        >>> repos = api.list_images()
        >>> for repo in repos:
        ...     print(repo.name, repo.is_public)
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        org: str,
        token: str,
        base_url: str = "https://quay.io",
        timeout: int = TIMEOUT,
        hooks: Hooks | None = None,  # ruff: ignore[unused-method-argument] - Handled by @with_hooks
    ) -> None:
        """Initialize Quay API client.

        Args:
            org: Quay organization name (used as namespace for all operations)
            token: Quay API token (Bearer token)
            base_url: Quay instance base URL (default: https://quay.io)
            timeout: Request timeout in seconds (default: 60)
            hooks: Optional custom hooks merged with built-in hooks
        """
        self.org = org
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        self._client = httpx2.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="repository.list", verb="GET", org=self.org
        )
    )
    def list_images(self) -> list[QuayRepo]:
        """List all repositories in the organization.

        Follows Quay's cursor-based pagination transparently.

        Returns:
            List of QuayRepo with name, is_public, description

        Raises:
            httpx2.HTTPStatusError: on non-2xx responses
            ValueError: if pagination exceeds _MAX_PAGE_FOLLOWS
        """
        repos: list[QuayRepo] = []
        params: dict[str, object] = {"namespace": self.org}
        follows = 0

        while True:
            response = self._client.get("/api/v1/repository", params=params)
            response.raise_for_status()
            body = response.json()
            repos.extend(
                QuayRepo(
                    name=r["name"],
                    is_public=r["is_public"],
                    description=r.get("description") or "",
                )
                for r in body.get("repositories", [])
            )

            next_page = body.get("next_page")
            if not next_page:
                break

            follows += 1
            if follows > _MAX_PAGE_FOLLOWS:
                raise ValueError(
                    f"Quay list_images exceeded {_MAX_PAGE_FOLLOWS} page follows for org '{self.org}'"
                )
            params = {"namespace": self.org, "next_page": next_page}

        return repos

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="repository.create", verb="POST", org=self.org
        )
    )
    def repo_create(self, repo_name: str, description: str, *, public: bool) -> None:
        """Create a repository in the organization.

        Args:
            repo_name: Name of the repository to create
            description: Repository description
            public: If True, repository is publicly visible

        Raises:
            httpx2.HTTPStatusError: on non-2xx responses
        """
        response = self._client.post(
            "/api/v1/repository",
            json={
                "repo_kind": "image",
                "namespace": self.org,
                "visibility": "public" if public else "private",
                "repository": repo_name,
                "description": description,
            },
        )
        response.raise_for_status()

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="repository.delete", verb="DELETE", org=self.org
        )
    )
    def repo_delete(self, repo_name: str) -> None:
        """Delete a repository from the organization.

        Args:
            repo_name: Name of the repository to delete

        Raises:
            httpx2.HTTPStatusError: on non-2xx responses
        """
        response = self._client.delete(f"/api/v1/repository/{self.org}/{repo_name}")
        response.raise_for_status()

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="repository.update_description", verb="PUT", org=self.org
        )
    )
    def repo_update_description(self, repo_name: str, description: str) -> None:
        """Update a repository's description.

        Args:
            repo_name: Name of the repository
            description: New description

        Raises:
            httpx2.HTTPStatusError: on non-2xx responses
        """
        response = self._client.put(
            f"/api/v1/repository/{self.org}/{repo_name}",
            json={"description": description},
        )
        response.raise_for_status()

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="repository.make_public", verb="POST", org=self.org
        )
    )
    def repo_make_public(self, repo_name: str) -> None:
        """Make a repository publicly visible.

        Args:
            repo_name: Name of the repository

        Raises:
            httpx2.HTTPStatusError: on non-2xx responses
        """
        self._repo_change_visibility(repo_name, "public")

    @invoke_with_hooks(
        lambda self: QuayApiCallContext(
            method="repository.make_private", verb="POST", org=self.org
        )
    )
    def repo_make_private(self, repo_name: str) -> None:
        """Make a repository private.

        Args:
            repo_name: Name of the repository

        Raises:
            httpx2.HTTPStatusError: on non-2xx responses
        """
        self._repo_change_visibility(repo_name, "private")

    def _repo_change_visibility(self, repo_name: str, visibility: str) -> None:
        response = self._client.post(
            f"/api/v1/repository/{self.org}/{repo_name}/changevisibility",
            json={"visibility": visibility},
        )
        response.raise_for_status()

    def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
