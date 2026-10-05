"""Internal Groups API client with hook system (Layer 1)."""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from typing import Any, Self

import requests
import structlog
from oauthlib.oauth2 import BackendApplicationClient, TokenExpiredError
from prometheus_client import Counter, Histogram
from requests import Response
from requests_oauthlib import OAuth2Session

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

REQUEST_TIMEOUT = 30
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
    """Stateless Internal Groups API client."""

    _hooks: Hooks

    def __init__(
        self,
        api_url: str,
        issuer_url: str,
        client_id: str,
        client_secret: str,
        hooks: Hooks | None = None,  # ruff: ignore[unused-method-argument] — handled by @with_hooks
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.issuer_url = issuer_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        client = BackendApplicationClient(client_id=self.client_id)
        self._client = OAuth2Session(self.client_id, client=client)

    def _fetch_token(self) -> dict[str, Any]:
        self._client.token = {}
        return self._client.fetch_token(
            token_url=f"{self.issuer_url}/protocol/openid-connect/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
        )

    @staticmethod
    def _check_response(resp: requests.Response) -> None:
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == _HTTP_NOT_FOUND:
                raise NotFoundError(e.response.text) from e
            raise

    def __enter__(self) -> Self:
        if not self._client.token:
            self._client.token = self._fetch_token()
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
        timeout: int = REQUEST_TIMEOUT,
    ) -> Response:
        last_error: TokenExpiredError | None = None
        for _ in range(2):
            try:
                return self._client.request(
                    method=method,
                    url=url,
                    json=json,
                    headers={"Content-Type": "application/json"},
                    timeout=timeout,
                )
            except TokenExpiredError as err:
                self._client.token = self._fetch_token()
                last_error = err
        if last_error is not None:
            raise last_error
        raise RuntimeError("unreachable")

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
