"""Keycloak API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless API client with support for metrics and
logging via hooks (ADR-006), on top of the wire-format models in _raw_client.py.
"""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from typing import Self

import httpx2
import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.keycloak_api._raw_client import (
    RawClientRegistrationRequest,
    RawKeycloakClient,
)
from qontract_utils.keycloak_api.models import KeycloakSsoClient
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

TIMEOUT = 30.0
MAX_RETRIES = 3

DEFAULT_CLIENT_SCOPES = ["web-origins", "acr", "profile", "roles", "email"]

# Prometheus metrics
keycloak_request = Counter(
    "qontract_reconcile_external_api_keycloak_requests_total",
    "Total number of Keycloak API requests",
    ["method", "verb"],
)

keycloak_request_duration = Histogram(
    "qontract_reconcile_external_api_keycloak_request_duration_seconds",
    "Keycloak API request duration in seconds",
    ["method", "verb"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

# Local storage for latency tracking (tuple stack to support nested calls)
_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)


@dataclass(frozen=True)
class KeycloakApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "clients.register")
        verb: HTTP verb (e.g., "POST")
        url: Keycloak realm base URL (identifies which realm was called)
    """

    method: str
    verb: str
    url: str


def _metrics_hook(context: KeycloakApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    keycloak_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: KeycloakApiCallContext) -> None:
    """Built-in hook to start latency measurement."""
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: KeycloakApiCallContext) -> None:
    """Built-in hook to record latency measurement."""
    stack = _latency_tracker.get()
    if not stack:
        return
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    keycloak_request_duration.labels(context.method, context.verb).observe(duration)


def _request_log_hook(context: KeycloakApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug(
        "API request", method=context.method, verb=context.verb, url=context.url
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
class KeycloakApi:
    """Stateless Keycloak API client with hook system.

    Layer 1 (Pure Communication) client following ADR-014. Covers exactly the Keycloak
    operations needed by reconcile/rhidp/sso_client: registering and deleting dynamically
    registered SSO clients via Keycloak's native client registration endpoint.

    Each instance owns its own httpx2.Client - use as a context manager (or call
    close()) to release its underlying HTTP connection when done.

    Hook System (ADR-006):
    - Always includes built-in hooks (metrics, logging, latency)
    - Supports additional custom hooks via hooks parameter
    - Hooks receive KeycloakApiCallContext with method, verb, url
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        url: str,
        initial_access_token: str,
        hooks: Hooks | None = None,
        timeout: float = TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        """Initialize the Keycloak API client.

        Args:
            url: Keycloak realm base URL (e.g., "https://sso.redhat.com/auth/realms/x")
            initial_access_token: static per-realm bearer token used to register clients
            timeout: API request timeout in seconds (default: 30)
            max_retries: number of transport-level retries for failed requests (default: 3)
            hooks: Optional custom hooks to merge with built-in hooks. Not read here -
                @with_hooks intercepts and merges it into self._hooks before this body runs.
        """
        _ = hooks
        self.url = url
        self._client = httpx2.Client(
            base_url=url,
            headers={"Authorization": f"Bearer {initial_access_token}"},
            timeout=timeout,
            transport=httpx2.HTTPTransport(retries=max_retries),
        )
        self._raw = RawKeycloakClient(self._client)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @invoke_with_hooks(
        lambda self: KeycloakApiCallContext(
            method="clients.register", verb="POST", url=self.url
        )
    )
    def register_client(
        self,
        client_name: str,
        redirect_uris: list[str],
        group_filter_regex: str | None = None,
    ) -> KeycloakSsoClient:
        """Register a new SSO client via Keycloak's native registration endpoint."""
        scopes = [*DEFAULT_CLIENT_SCOPES]
        attributes: dict[str, str] | None = None
        if group_filter_regex:
            scopes.append("regex-filtered-groups")
            attributes = {"group-filter-regex": group_filter_regex}

        raw = self._raw.register_client(
            RawClientRegistrationRequest(
                client_id=client_name,
                redirect_uris=list(redirect_uris),
                default_client_scopes=scopes,
                attributes=attributes,
            )
        )
        return KeycloakSsoClient(
            client_id=raw.client_id,
            client_secret=raw.secret,
            redirect_uris=raw.redirect_uris,
            registration_access_token=raw.registration_access_token,
            attributes=raw.attributes,
        )

    @invoke_with_hooks(
        lambda self: KeycloakApiCallContext(
            method="clients.delete", verb="DELETE", url=self.url
        )
    )
    def delete_client(self, client_id: str, registration_access_token: str) -> None:
        """Delete a registered SSO client.

        Uses the per-client registration_access_token returned at registration time,
        not the realm's initial_access_token used for registration.
        """
        self._raw.delete_client(
            client_id=client_id, registration_access_token=registration_access_token
        )
