"""LDAP API client with hook system for metrics, logging, and latency tracking."""

import contextvars
import time
import types
from collections import defaultdict
from collections.abc import Collection, Iterable
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
from ldap3.utils.dn import parse_dn
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, RetryConfig, invoke_with_hooks, with_hooks
from qontract_utils.ldap_api.models import LdapGroup, LdapUser
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT = 30
_UNKNOWN_LDAP_ERROR = 99999

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


def _get_cn_from_dn(dn: str) -> str:
    """Extract CN value from a DN string."""
    rdn = parse_dn(dn)[0]
    if rdn[0].lower() != "cn":
        raise LdapApiError(
            f"Expected CN as first RDN component, got {rdn[0]!r} in {dn!r}"
        )
    return rdn[1]


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
        start_tls: bool = True,
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

    @staticmethod
    def _check_ldap_response(status: dict) -> None:
        """Check LDAP response status and raise LdapApiError on failure."""
        if (error_code := status.get("result", _UNKNOWN_LDAP_ERROR)) != 0:
            error_desc = status.get("description", "unknown error")
            raise LdapApiError(
                f"LDAP operation failed (error {error_code}: {error_desc})"
            )

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
        self._check_ldap_response(status)

        return [LdapUser(username=r["attributes"]["uid"][0]) for r in results]

    @invoke_with_hooks(
        lambda: LdapApiCallContext(method="get_group_members"),
        retry_config=_LDAP_RETRY_CONFIG,
    )
    def get_group_members(self, groups_dns: Collection[str]) -> list[LdapGroup]:
        """Get members of the specified LDAP groups.

        Attention: groups_dns must be full DNs (e.g., "cn=group1,ou=groups,dc=example,dc=com") as returned by the LDAP "memberOf" attribute.
        """
        if not groups_dns:
            return []

        group_filter = f"(|{''.join([f'(memberOf={escape_filter_chars(dn)})' for dn in sorted(groups_dns)])})"

        _, status, users, _ = self._connection.search(
            self.base_dn,
            group_filter,
            attributes=["uid", "memberOf"],
        )

        self._check_ldap_response(status)

        groups_and_members: dict[str, set[str]] = defaultdict(set[str])
        for u in users:
            uid = u["attributes"]["uid"][0]
            for group in set(u["attributes"]["memberOf"]).intersection(groups_dns):
                groups_and_members[group].add(uid)

        return [
            LdapGroup(
                cn=_get_cn_from_dn(dn),
                dn=dn,
                members=frozenset(LdapUser(username=uid) for uid in members),
            )
            for dn, members in groups_and_members.items()
        ]
