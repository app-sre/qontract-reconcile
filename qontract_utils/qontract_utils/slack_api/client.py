from __future__ import annotations

import http
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from slack_sdk import WebClient
from slack_sdk.http_retry import (
    HttpRequest,
    HttpResponse,
    RateLimitErrorRetryHandler,
    RetryHandler,
    RetryState,
)

from qontract_utils.hooks import invoke_with_hooks
from qontract_utils.metrics import slack_request
from qontract_utils.slack_api.models import SlackChannel, SlackUser, SlackUsergroup

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)


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
    logger.debug(
        f"Slack API call: method={context.method}, verb={context.verb}, workspace={context.workspace}"
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
        return (
            response is not None
            and response.status_code >= http.HTTPStatus.INTERNAL_SERVER_ERROR
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
        pre_hooks: Sequence[Callable[[SlackApiCallContext], None]] | None = None,
    ) -> None:
        """Initialize SlackApi wrapper.

        Args:
            workspace_name: Slack workspace name (ex. coreos)
            token: Slack API token
            timeout: API timeout in seconds (default: 30)
            max_retries: Max retries for failed requests (default: 5)
            method_configs: Method-specific configs, e.g., {"users.list": {"limit": 1000}}
            pre_hooks: List of hooks called before every API call.
                Hooks receive SlackApiCallContext with method, verb, and workspace info.
                Metrics hook (_metrics_hook) is automatically included.
        """
        self.workspace_name = workspace_name
        self.timeout = timeout
        self.max_retries = max_retries
        self._method_configs = method_configs or {}

        # Build hooks list: always include metrics hook, then user hooks
        self._pre_hooks: list[Callable[[SlackApiCallContext], None]] = [_metrics_hook]
        if pre_hooks:
            self._pre_hooks.extend(pre_hooks)

        self._sc = WebClient(
            token=token,
            timeout=self.timeout,
            # Determine the appropriate Slack API base URL based on GOV_SLACK environment variable
            base_url=slack_api_url,
        )
        # Add retry handlers in addition to the defaults provided by the Slack client
        self._sc.retry_handlers.append(
            RateLimitErrorRetryHandler(max_retry_count=self.max_retries)
        )
        self._sc.retry_handlers.append(
            ServerErrorRetryHandler(max_retry_count=self.max_retries)
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
            with invoke_with_hooks(
                SlackApiCallContext(
                    method="users.list",
                    verb="GET",
                    workspace=self.workspace_name,
                ),
                pre_hooks=self._pre_hooks,
            ):
                result = self._sc.api_call(
                    "users.list", http_verb="GET", params=additional_kwargs
                )

            users.extend(SlackUser(**user_data) for user_data in result["members"])

            cursor = (result.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break

            additional_kwargs["cursor"] = cursor

        return users

    def usergroups_list(self, *, include_users: bool = True) -> list[SlackUsergroup]:
        """Fetch all usergroups from Slack API.

        Args:
            include_users: Include user IDs in usergroup data

        Returns:
            List of SlackUsergroup objects with typed Pydantic models
        """
        with invoke_with_hooks(
            SlackApiCallContext(
                method="usergroups.list",
                verb="GET",
                workspace=self.workspace_name,
            ),
            pre_hooks=self._pre_hooks,
        ):
            result = self._sc.usergroups_list(
                include_users=include_users, include_disabled=True
            )
        return [SlackUsergroup(**ug) for ug in result["usergroups"]]

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
        with invoke_with_hooks(
            SlackApiCallContext(
                method="usergroups.create",
                verb="POST",
                workspace=self.workspace_name,
            ),
            pre_hooks=self._pre_hooks,
        ):
            response = self._sc.usergroups_create(name=name or handle, handle=handle)
        return SlackUsergroup(**response["usergroup"])

    def usergroup_enable(self, *, usergroup_id: str) -> SlackUsergroup:
        """Enable a usergroup.

        Args:
            usergroup_id: Encoded usergroup ID

        Returns:
            Updated SlackUsergroup object
        """
        with invoke_with_hooks(
            SlackApiCallContext(
                method="usergroups.enable",
                verb="POST",
                workspace=self.workspace_name,
            ),
            pre_hooks=self._pre_hooks,
        ):
            response = self._sc.usergroups_enable(usergroup=usergroup_id)
        return SlackUsergroup(**response["usergroup"])

    def usergroup_disable(self, *, usergroup_id: str) -> SlackUsergroup:
        """Disable a usergroup.

        Args:
            usergroup_id: Encoded usergroup ID

        Returns:
            Updated SlackUsergroup object
        """
        with invoke_with_hooks(
            SlackApiCallContext(
                method="usergroups.disable",
                verb="POST",
                workspace=self.workspace_name,
            ),
            pre_hooks=self._pre_hooks,
        ):
            response = self._sc.usergroups_disable(usergroup=usergroup_id)
        return SlackUsergroup(**response["usergroup"])

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
        with invoke_with_hooks(
            SlackApiCallContext(
                method="usergroups.update",
                verb="POST",
                workspace=self.workspace_name,
            ),
            pre_hooks=self._pre_hooks,
        ):
            response = self._sc.usergroups_update(
                usergroup=usergroup_id,
                name=name,
                description=description,
                channels=channel_ids,
            )
        return SlackUsergroup(**response["usergroup"])

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
        with invoke_with_hooks(
            SlackApiCallContext(
                method="usergroups.users.update",
                verb="POST",
                workspace=self.workspace_name,
            ),
            pre_hooks=self._pre_hooks,
        ):
            response = self._sc.usergroups_users_update(
                usergroup=usergroup_id, users=user_ids
            )
        return SlackUsergroup(**response["usergroup"])

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
            with invoke_with_hooks(
                SlackApiCallContext(
                    method="conversations.list",
                    verb="GET",
                    workspace=self.workspace_name,
                ),
                pre_hooks=self._pre_hooks,
            ):
                result = self._sc.api_call(
                    "conversations.list", http_verb="GET", params=additional_kwargs
                )

            channels.extend(
                SlackChannel(**channel_data) for channel_data in result["channels"]
            )

            cursor = (result.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break

            additional_kwargs["cursor"] = cursor

        return channels
