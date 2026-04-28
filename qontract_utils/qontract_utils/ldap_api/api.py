"""LDAP API client with hook system for metrics, logging, and latency tracking."""

import contextvars
import time
import types
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

import structlog
from ldap3 import NONE, SAFE_SYNC, Connection, Server
from ldap3.core.exceptions import (
    LDAPCommunicationError,
    LDAPMaximumRetriesError,
    LDAPResponseTimeoutError,
    LDAPSessionTerminatedByServerError,
    LDAPSocketCloseError,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
    LDAPSocketSendError,
)
from ldap3.utils.conv import escape_filter_chars
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, RetryConfig, invoke_with_hooks, with_hooks
from qontract_utils.ldap_api.models import LdapUser
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT = 30

# Prometheus metrics
ldap_request = Counter(
    "qontract_reconcile_external_api_ldap_requests_total",
    "Total number of LDAP requests",
    ["method"],
)

ldap_request_duration = Histogram(
    "qontract_reconcile_external_api_ldap_request_duration_seconds",
    "LDAP request duration in seconds",
    ["method"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

# Local storage for latency tracking (tuple stack to support nested calls)
_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)


class LdapApiError(Exception):
    """Raised when an LDAP operation fails."""


@dataclass(frozen=True)
class LdapApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "get_users", "get_group_members")
    """

    method: str


def _metrics_hook(context: LdapApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    ldap_request.labels(context.method).inc()


def _latency_start_hook(_context: LdapApiCallContext) -> None:
    """Built-in hook to start latency measurement."""
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: LdapApiCallContext) -> None:
    """Built-in hook to record latency measurement."""
    stack = _latency_tracker.get()
    if not stack:
        return
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    ldap_request_duration.labels(context.method).observe(duration)


def _request_log_hook(context: LdapApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug("LDAP request", method=context.method)


# Retry only on transient LDAP errors (network/connection issues).
# Logical errors (noSuchObject, invalidCredentials, etc.) are NOT retried.
_LDAP_TRANSIENT_ERRORS = (
    LDAPCommunicationError,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
    LDAPSocketSendError,
    LDAPSocketCloseError,
    LDAPSessionTerminatedByServerError,
    LDAPResponseTimeoutError,
    LDAPMaximumRetriesError,
)

_LDAP_RETRY_CONFIG = RetryConfig(
    on=_LDAP_TRANSIENT_ERRORS,
    attempts=3,
    timeout=5.0,
    wait_initial=0.5,
    wait_max=5.0,
    wait_jitter=1.0,
)


@with_hooks(
    hooks=Hooks(
        pre_hooks=[_metrics_hook, _request_log_hook, _latency_start_hook],
        post_hooks=[_latency_end_hook],
    )
)
class LdapApi:
    """Stateless LDAP client using ldap3 with authenticated bind.

    Layer 1 (Pure Communication) per ADR-014.
    Uses hook system (ADR-006) for metrics, logging, latency.

    Supports both anonymous and authenticated (FreeIPA) binds.
    Use as a context manager to manage connection lifecycle.

    Args:
        server_url: LDAP server URL (e.g., "ldap://ldap.example.com")
        base_dn: Base DN for searches (e.g., "dc=example,dc=com")
        bind_dn: Service account DN for authenticated bind (None for anonymous)
        bind_password: Service account password (None for anonymous)
        start_tls: Enable STARTTLS before binding
        timeout: Connection timeout in seconds
        hooks: Optional custom hooks merged with built-in hooks (ADR-006)
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        server_url: str,
        base_dn: str,
        bind_dn: str | None = None,
        bind_password: str | None = None,
        *,
        start_tls: bool = False,
        timeout: int = _DEFAULT_TIMEOUT,
        hooks: Hooks | None = None,  # noqa: ARG002 - Handled by @with_hooks decorator
    ) -> None:
        self.base_dn = base_dn
        self._start_tls = start_tls
        self._connection = Connection(
            server=Server(server_url, get_info=NONE),
            user=bind_dn,
            password=bind_password,
            client_strategy=SAFE_SYNC,
            receive_timeout=timeout,
            raise_exceptions=True,
        )

    def __enter__(self) -> Self:
        if self._start_tls:
            self._connection.start_tls()
        self._connection.bind()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self._connection.unbind()

    @invoke_with_hooks(
        lambda: LdapApiCallContext(method="get_users"),
        retry_config=_LDAP_RETRY_CONFIG,
    )
    def get_users(self, usernames: Iterable[str]) -> list[LdapUser]:
        """Check which usernames exist in LDAP.

        Args:
            usernames: Usernames to check

        Returns:
            List of LdapUser models for usernames that exist in LDAP

        Raises:
            LdapApiError: If the LDAP search fails
        """
        if not usernames:
            return []
        user_filter = "".join(f"(uid={escape_filter_chars(u)})" for u in usernames)
        _, status, results, _ = self._connection.search(
            self.base_dn, f"(&(objectclass=person)(|{user_filter}))", attributes=["uid"]
        )

        # status["result"] is 0 on success, non-zero on failure (e.g., server down, timeout, etc.)
        # and should exists according to RFC 4511 search result format. If missing, treat as unknown error.
        if (error_code := status.get("result", 99999)) != 0:
            error_desc = status.get("description", "unknown error")
            raise LdapApiError(f"LDAP search failed (error {error_code}: {error_desc})")

        return [LdapUser(username=r["attributes"]["uid"][0]) for r in results]
