"""Internal Groups API client with OAuth2 client-credentials token management."""

import contextvars
import time
from dataclasses import dataclass

import requests
import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, RetryConfig, invoke_with_hooks, with_hooks
from qontract_utils.internal_groups_api.models import Group, GroupMember
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT = 30
_TOKEN_BUFFER_SECONDS = 30  # Refresh token this many seconds before expiry
_HTTP_UNAUTHORIZED = 401

# Prometheus metrics
internal_groups_request = Counter(
    "qontract_reconcile_external_api_internal_groups_requests_total",
    "Total number of Internal Groups API requests",
    ["method", "verb"],
)

internal_groups_request_duration = Histogram(
    "qontract_reconcile_external_api_internal_groups_request_duration_seconds",
    "Internal Groups API request duration in seconds",
    ["method", "verb"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

# Local storage for latency tracking (tuple stack to support nested calls)
_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)


class TokenExpiredError(Exception):
    """Raised when the server returns 401, indicating an expired or invalid token."""


@dataclass(frozen=True)
class InternalGroupsApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "groups.members")
        verb: HTTP verb (e.g., "GET")
        id: Resource identifier (group name)
        client: Client instance used by retry hooks to refresh the OAuth2 token
    """

    method: str
    verb: str
    id: str
    client: "InternalGroupsApi"


def _metrics_hook(context: InternalGroupsApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    internal_groups_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: InternalGroupsApiCallContext) -> None:
    """Built-in hook to start latency measurement."""
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: InternalGroupsApiCallContext) -> None:
    """Built-in hook to record latency measurement."""
    stack = _latency_tracker.get()
    if not stack:
        return
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    internal_groups_request_duration.labels(context.method, context.verb).observe(
        duration
    )


def _request_log_hook(context: InternalGroupsApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug("API request", method=context.method, verb=context.verb, id=context.id)


def _token_refresh_retry_hook(
    context: InternalGroupsApiCallContext, _attempt_num: int
) -> None:
    """Retry hook: invalidate cached token so the next attempt acquires a fresh one."""
    context.client.invalidate_token()


# Retry once immediately after token refresh — no backoff needed for auth retry.
_TOKEN_REFRESH_RETRY_CONFIG = RetryConfig(
    on=TokenExpiredError,
    attempts=2,
    wait_initial=0.0,
    wait_max=0.0,
    wait_jitter=0.0,
)


@with_hooks(
    hooks=Hooks(
        pre_hooks=[_metrics_hook, _request_log_hook, _latency_start_hook],
        post_hooks=[_latency_end_hook],
        retry_hooks=[_token_refresh_retry_hook],
    )
)
class InternalGroupsApi:
    """Stateless HTTP client for the internal groups proxy API.

    Handles OAuth2 client-credentials token acquisition and renewal.
    Tokens are cached in-memory (per instance) and refreshed before expiry.

    This is Layer 1 (Pure Communication) following ADR-014.
    Uses the hook system (ADR-006) for metrics, logging, latency, and retry.

    Args:
        base_url: Base URL of the internal groups API (e.g., "https://groups.example.com")
        token_url: OAuth2 token endpoint URL
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret (resolved value)
        timeout: HTTP request timeout in seconds
        hooks: Additional hooks merged with built-in hooks (ADR-006)
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        timeout: int = _DEFAULT_TIMEOUT,
        hooks: Hooks | None = None,  # noqa: ARG002 - Handled by @with_hooks decorator
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _acquire_token(self) -> str:
        """Acquire a new OAuth2 access token using client-credentials flow."""
        logger.debug("Acquiring OAuth2 token", token_url=self.token_url)
        response = requests.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        self._token = data["access_token"]
        expires_in = data.get("expires_in", 300)
        self._token_expires_at = time.monotonic() + expires_in - _TOKEN_BUFFER_SECONDS
        return self._token

    def _get_token(self) -> str:
        """Return a valid access token, refreshing if expired."""
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        return self._acquire_token()

    def invalidate_token(self) -> None:
        """Invalidate the cached token, forcing re-acquisition on the next request."""
        self._token = None
        self._token_expires_at = 0.0

    def _get(self, path: str) -> dict:
        """Execute an authenticated GET request.

        Raises:
            TokenExpiredError: If the server returns 401 (token invalid or expired)
            requests.HTTPError: For any other non-2xx response
        """
        token = self._get_token()
        response = requests.get(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout,
        )
        if response.status_code == _HTTP_UNAUTHORIZED:
            raise TokenExpiredError
        response.raise_for_status()
        return response.json()

    @invoke_with_hooks(
        lambda self, group_name: InternalGroupsApiCallContext(
            method="groups.members", verb="GET", id=group_name, client=self
        ),
        retry_config=_TOKEN_REFRESH_RETRY_CONFIG,
    )
    def get_group_members(self, group_name: str) -> Group:
        """Fetch members of an LDAP group.

        Args:
            group_name: LDAP group name

        Returns:
            Group with its members

        Raises:
            TokenExpiredError: If the server returns 401 and the token-refresh retry fails
            requests.HTTPError: If the API returns a non-2xx status (other than 401)
        """
        data = self._get(f"/groups/{group_name}/members")
        members = [GroupMember(id=m["id"]) for m in data.get("members", [])]
        return Group(name=group_name, members=members)
