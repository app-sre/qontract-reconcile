"""Internal Groups API client with hook system (Layer 1)."""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from typing import Any, Self

import httpx2
import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3
_HTTP_NOT_FOUND = 404

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

_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)


class NotFoundError(Exception):
    """Raised when a group does not exist."""


@dataclass(frozen=True)
class InternalGroupsApiCallContext:
    """Context passed to Internal Groups API hooks."""

    method: str
    verb: str


def _metrics_hook(context: InternalGroupsApiCallContext) -> None:
    internal_groups_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: InternalGroupsApiCallContext) -> None:
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: InternalGroupsApiCallContext) -> None:
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
    logger.debug("API request", method=context.method, verb=context.verb)


def _fetch_access_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    timeout: float,
) -> str:
    response = httpx2.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


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
class InternalGroupsApi:
    """Stateless Internal Groups API client using httpx2 with OAuth2 client credentials.

    Layer 1 client following ADR-014. Fetches a client-credentials bearer token once
    at construction (same pattern as OcmApi). HTTPTransport handles transient failures;
    auth errors are not retried in-process.
    """

    _hooks: Hooks

    def __init__(
        self,
        api_url: str,
        issuer_url: str,
        client_id: str,
        client_secret: str,
        hooks: Hooks | None = None,
        timeout: float = REQUEST_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        _ = hooks
        self.api_url = api_url.rstrip("/")
        token_url = f"{issuer_url.rstrip('/')}/protocol/openid-connect/token"
        access_token = _fetch_access_token(token_url, client_id, client_secret, timeout)
        self._client = httpx2.Client(
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
            timeout=timeout,
            transport=httpx2.HTTPTransport(retries=max_retries),
        )

    @staticmethod
    def _check_response(resp: httpx2.Response) -> None:
        if resp.status_code == _HTTP_NOT_FOUND:
            raise NotFoundError(resp.text)
        resp.raise_for_status()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        url: str,
        json: dict[Any, Any] | None = None,
    ) -> httpx2.Response:
        return self._client.request(method=method, url=url, json=json)

    @invoke_with_hooks(
        lambda self, name: InternalGroupsApiCallContext(method="group", verb="GET")
    )
    def group(self, name: str) -> dict[str, Any]:
        resp = self._request("GET", f"{self.api_url}/v1/groups/{name}")
        self._check_response(resp)
        return resp.json()

    @invoke_with_hooks(
        lambda self, name: InternalGroupsApiCallContext(
            method="delete_group", verb="DELETE"
        )
    )
    def delete_group(self, name: str) -> None:
        resp = self._request("DELETE", f"{self.api_url}/v1/groups/{name}")
        self._check_response(resp)

    @invoke_with_hooks(
        lambda self, data: InternalGroupsApiCallContext(
            method="create_group", verb="POST"
        )
    )
    def create_group(self, data: dict[str, Any]) -> dict[str, Any]:
        resp = self._request("POST", f"{self.api_url}/v1/groups/", json=data)
        self._check_response(resp)
        return resp.json()

    @invoke_with_hooks(
        lambda self, name, data: InternalGroupsApiCallContext(
            method="update_group", verb="PATCH"
        )
    )
    def update_group(self, name: str, data: dict[str, Any]) -> dict[str, Any]:
        resp = self._request(
            "PATCH",
            f"{self.api_url}/v1/groups/{name}",
            json=data,
        )
        self._check_response(resp)
        return resp.json()
