from __future__ import annotations

import contextvars
import http
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from prometheus_client import Counter, Histogram
from slack_sdk import WebClient
from slack_sdk.http_retry import (
    ConnectionErrorRetryHandler,
    HttpRequest,
    HttpResponse,
    RetryHandler,
    RetryState,
)
from slack_sdk.http_retry import (
    RateLimitErrorRetryHandler as SlackSDKRateLimitErrorRetryHandler,
)

from qontract_utils.hooks import DEFAULT_RETRY_CONFIG, RetryConfig, invoke_with_hooks
from qontract_utils.slack_api.models import SlackChannel, SlackUser, SlackUsergroup

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)

# Following naming convention (qontract_reconcile_external_api_<component>_requests_total) to
# automatically include this metric in dashboards
slack_request = Counter(
    name="qontract_reconcile_external_api_slack_requests_total",
    documentation="Number of calls made to Slack API",
    labelnames=["resource", "verb"],
)

slack_request_duration = Histogram(
    "qontract_reconcile_external_api_slack_request_duration_seconds",
    "Slack API request duration in seconds",
    ["resource", "verb"],
)

# Local storage for latency tracking
_latency_tracker = contextvars.ContextVar("latency_tracker", default=0.0)


@dataclass(frozen=True)
class SlackApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: Slack API method name (e.g., "chat.postMessage", "users.list")
        verb: HTTP verb (e.g., "GET", "POST")
        workspace: Slack workspace name
    """

    method: str
    verb: str
    workspace: str


def _metrics_hook(context: SlackApiCallContext) -> None:
    """Built-in hook for Prometheus metrics tracking.

    Automatically increments the slack_request counter with method and verb labels.
    """
    slack_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: SlackApiCallContext) -> None:
    """Built-in hook to start latency measurement.

    Stores the start time in local storage.
    """
    _latency_tracker.set(time.perf_counter())


def _latency_end_hook(context: SlackApiCallContext) -> None:
    """Built-in hook to record latency measurement.

    Calculates duration from start time and records to Prometheus histogram.
    """
    duration = time.perf_counter() - _latency_tracker.get()
    slack_request_duration.labels(context.method, context.verb).observe(duration)
    _latency_tracker.set(0.0)


def _request_log_hook(context: SlackApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug(
        "API request",
        workspace=context.workspace,
        method=context.method,
        verb=context.verb,
    )


class UserNotFoundError(Exception):
    pass


class UsergroupNotFoundError(Exception):
    pass


class ServerErrorRetryHandler(RetryHandler):
    """Retry handler for 5xx errors."""

    def _can_retry(  # noqa: PLR6301 - Required instance method for RetryHandler protocol
        self,
        *,
        state: RetryState,  # noqa: ARG002 - Required parameter for RetryHandler protocol
        request: HttpRequest,  # noqa: ARG002 - Required parameter for RetryHandler protocol
        response: HttpResponse | None = None,
        error: Exception | None = None,  # noqa: ARG002 - Required parameter for RetryHandler protocol
    ) -> bool:
        # retry on all 5xx server errors (slack_sdk ServerErrorRetryHandler only retries on 500 and 503, 504)
        return (
            response is not None
            and response.status_code >= http.HTTPStatus.INTERNAL_SERVER_ERROR
        )


class RateLimitErrorRetryHandler(SlackSDKRateLimitErrorRetryHandler):
    def prepare_for_next_attempt(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: HttpResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        logger.warning(f"Rate limit hit for request {request.url}.")
        super().prepare_for_next_attempt(
            state=state, request=request, response=response, error=error
        )


class SlackApi:
    """Wrapper around Slack API calls"""

    def __init__(
        self,
        slack_api_url: str,
        workspace_name: str,
        token: str,
        timeout: int,
        max_retries: int,
        method_configs: dict[str, dict[str, Any]] | None = None,
        pre_hooks: Iterable[Callable[[SlackApiCallContext], None]] | None = None,
        post_hooks: Iterable[Callable[[SlackApiCallContext], None]] | None = None,
        error_hooks: Iterable[Callable[[SlackApiCallContext], None]] | None = None,
        retry_hooks: Iterable[Callable[[SlackApiCallContext, int], None]] | None = None,
        retry_config: RetryConfig | None = DEFAULT_RETRY_CONFIG,
    ) -> None:
        """Initialize SlackApi wrapper.

        Args:
            workspace_name: Slack workspace name (ex. coreos)
            token: Slack API token
            timeout: API timeout in seconds
            max_retries: Max retries for failed requests
            method_configs: Method-specific configs, e.g., {"users.list": {"limit": 1000}}
            pre_hooks: List of hooks called before every API call.
                Hooks receive SlackApiCallContext with method, verb, and workspace info.
                Metrics hook (_metrics_hook) is automatically included.
        """
        self.workspace_name = workspace_name
        self._method_configs = method_configs or {}

        # Build hooks list: always include built-in hooks
        self._pre_hooks: list[Callable[[SlackApiCallContext], None]] = [
            _metrics_hook,
            _latency_start_hook,
            _request_log_hook,
        ]
        if pre_hooks:
            self._pre_hooks.extend(pre_hooks)
        self._post_hooks: list[Callable[[SlackApiCallContext], None]] = [
            _latency_end_hook
        ]
        if post_hooks:
            self._post_hooks.extend(post_hooks)
        self._error_hooks: list[Callable[[SlackApiCallContext], None]] = []
        if error_hooks:
            self._error_hooks.extend(error_hooks)
        self._retry_hooks: list[Callable[[SlackApiCallContext, int], None]] = []
        if retry_hooks:
            self._retry_hooks.extend(retry_hooks)
        self._retry_config = retry_config

        self._sc = WebClient(
            token=token,
            timeout=timeout,
            base_url=slack_api_url,
            retry_handlers=[
                ConnectionErrorRetryHandler(max_retry_count=max_retries),
                RateLimitErrorRetryHandler(max_retry_count=max_retries),
                ServerErrorRetryHandler(max_retry_count=max_retries),
            ],
        )

    @invoke_with_hooks(
        lambda self: SlackApiCallContext(
            method="users.list", verb="GET", workspace=self.workspace_name
        )
    )
    def users_list(self) -> list[SlackUser]:
        """Fetch all users from Slack API.

        Returns:
            List of SlackUser objects with typed Pydantic models
        """
        users: list[SlackUser] = []
        cursor = ""
        additional_kwargs: dict[str, str | int] = {"cursor": cursor}

        method_config = self._method_configs.get("users.list")
        if method_config:
            additional_kwargs.update(method_config)

        while True:
            result = self._sc.api_call("users.list", params=additional_kwargs)

            users.extend(SlackUser(**user_data) for user_data in result["members"])

            cursor = (result.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break

            additional_kwargs["cursor"] = cursor

        return users

    @invoke_with_hooks(
        lambda self: SlackApiCallContext(
            method="usergroups.list", verb="GET", workspace=self.workspace_name
        )
    )
    def usergroups_list(self, *, include_users: bool = True) -> list[SlackUsergroup]:
        """Fetch all usergroups from Slack API.

        Args:
            include_users: Include user IDs in usergroup data

        Returns:
            List of SlackUsergroup objects with typed Pydantic models
        """
        result = self._sc.usergroups_list(
            include_users=include_users, include_disabled=True
        )
        return [SlackUsergroup(**ug) for ug in result["usergroups"]]

    @invoke_with_hooks(
        lambda self: SlackApiCallContext(
            method="usergroups.create", verb="POST", workspace=self.workspace_name
        )
    )
    def usergroup_create(
        self, *, handle: str, name: str | None = None
    ) -> SlackUsergroup:
        """Create a new usergroup.

        Args:
            handle: Usergroup handle (e.g., "oncall-team")
            name: Usergroup display name (defaults to handle)

        Returns:
            Created SlackUsergroup object
        """
        response = self._sc.usergroups_create(name=name or handle, handle=handle)
        return SlackUsergroup(**response["usergroup"])

    @invoke_with_hooks(
        lambda self: SlackApiCallContext(
            method="usergroups.enable", verb="POST", workspace=self.workspace_name
        )
    )
    def usergroup_enable(self, *, usergroup_id: str) -> SlackUsergroup:
        """Enable a usergroup.

        Args:
            usergroup_id: Encoded usergroup ID

        Returns:
            Updated SlackUsergroup object
        """
        response = self._sc.usergroups_enable(usergroup=usergroup_id)
        return SlackUsergroup(**response["usergroup"])

    @invoke_with_hooks(
        lambda self: SlackApiCallContext(
            method="usergroups.disable", verb="POST", workspace=self.workspace_name
        )
    )
    def usergroup_disable(self, *, usergroup_id: str) -> SlackUsergroup:
        """Disable a usergroup.

        Args:
            usergroup_id: Encoded usergroup ID

        Returns:
            Updated SlackUsergroup object
        """
        response = self._sc.usergroups_disable(usergroup=usergroup_id)
        return SlackUsergroup(**response["usergroup"])

    @invoke_with_hooks(
        lambda self: SlackApiCallContext(
            method="usergroups.update", verb="POST", workspace=self.workspace_name
        )
    )
    def usergroup_update(
        self,
        *,
        usergroup_id: str,
        name: str | None = None,
        description: str | None = None,
        channel_ids: list[str] | None = None,
    ) -> SlackUsergroup:
        """Update an existing usergroup.

        Args:
            usergroup_id: Encoded usergroup ID
            name: Usergroup display name
            description: Short description of the usergroup
            channel_ids: List of encoded channel IDs that the usergroup uses by default

        Returns:
            Updated SlackUsergroup object
        """
        response = self._sc.usergroups_update(
            usergroup=usergroup_id,
            name=name,
            description=description,
            channels=channel_ids,
        )
        return SlackUsergroup(**response["usergroup"])

    @invoke_with_hooks(
        lambda self: SlackApiCallContext(
            method="usergroups.users.update",
            verb="POST",
            workspace=self.workspace_name,
        )
    )
    def usergroup_users_update(
        self,
        *,
        usergroup_id: str,
        user_ids: list[str],
    ) -> SlackUsergroup:
        """Update the list of users for a usergroup.

        Args:
            usergroup_id: Encoded usergroup ID
            user_ids: List of encoded user IDs representing the entire list of users for the usergroup

        Returns:
            Updated SlackUsergroup object
        """
        response = self._sc.usergroups_users_update(
            usergroup=usergroup_id, users=user_ids
        )
        return SlackUsergroup(**response["usergroup"])

    @invoke_with_hooks(
        lambda self: SlackApiCallContext(
            method="conversations.list", verb="GET", workspace=self.workspace_name
        )
    )
    def conversations_list(self) -> list[SlackChannel]:
        """Fetch all conversations (channels) from Slack API.

        Returns:
            List of SlackChannel objects with typed Pydantic models
        """
        channels: list[SlackChannel] = []
        cursor = ""
        additional_kwargs: dict[str, str | int] = {"cursor": cursor}

        method_config = self._method_configs.get("conversations.list")
        if method_config:
            additional_kwargs.update(method_config)

        while True:
            result = self._sc.api_call("conversations.list", params=additional_kwargs)

            channels.extend(
                SlackChannel(**channel_data) for channel_data in result["channels"]
            )

            cursor = (result.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break

            additional_kwargs["cursor"] = cursor

        return channels
