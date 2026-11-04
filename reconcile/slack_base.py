from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from qontract_api_client import schemas as qontract_api_schemas
from qontract_api_client.sync_client import (
    slack_chat_post_message,
    slack_chat_post_message_task_status,
)

from reconcile import queries
from reconcile.utils.config import get_config
from reconcile.utils.runtime.integration import setup_qontract_api_client

if TYPE_CHECKING:
    from collections.abc import Mapping

# Matches reconcile.utils.runtime.integration.poll_task_status's default: the
# qontract-api blocking-GET route itself caps at settings.api_task_max_timeout
# (300s), so this is the longest a caller can usefully wait anyway.
_CHAT_WAIT_TIMEOUT = 300


def is_gov_slack_workspace() -> bool:
    """
    Determine if a workspace is a government Slack workspace.

    :return: True if it's a gov-slack workspace, False otherwise
    """
    # Check GOV_SLACK environment variable from OpenShift YAML configuration
    # If not set, defaults to False (regular Slack)
    gov_slack_env = os.getenv("GOV_SLACK", "false")

    return gov_slack_env.lower() == "true"


class SlackApi:
    """Thin layer posting Slack messages via qontract-api."""

    def __init__(
        self,
        workspace_name: str,
        token: Mapping[str, Any],
        channel: str | None = None,
        icon_emoji: str | None = None,
        username: str | None = None,
    ) -> None:
        """
        :param workspace_name: Slack workspace name (ex. coreos)
        :param token: Vault secret reference for the Slack bot token
        (path/field/version), resolved server-side by qontract-api
        :param channel: the Slack channel to post messages to
        :param icon_emoji: emoji to use as the message icon
        :param username: bot username to display
        """
        self.workspace_name = workspace_name
        self.token = token
        self.channel = channel
        self.icon_emoji = icon_emoji
        self.username = username

    def _secret(self) -> qontract_api_schemas.Secret:
        return qontract_api_schemas.Secret(
            secret_manager_url=get_config()["vault"]["server"],
            path=self.token["path"],
            field=self.token.get("field"),
            version=self.token.get("version"),
        )

    def chat_post_message(
        self,
        text: str,
        *,
        resolve_mentions: bool = False,
        wait: bool = False,
    ) -> None:
        """
        Queue a chat message to be sent into a channel via qontract-api.

        Fire-and-forget by default: qontract-api queues the actual send on a
        background worker (see ADR-003) and this returns as soon as it's
        queued, without waiting for the message to actually be delivered.
        There's nothing useful a caller could do about a failed send anyway
        (e.g. Slack rate limits) — the task result isn't checked.

        :param text: message to send to channel
        :param resolve_mentions: if True, "@handle" tokens in `text` are
        resolved server-side to real Slack mentions (see
        SlackWorkspaceClient._resolve_mentions). Leave False (the default) for
        free text that should be posted literally — only set True when the
        caller intentionally constructs a handle to ping.
        :param wait: if True, block until the message is actually delivered
        (or fails) instead of returning as soon as it's queued, and raise if
        delivery failed. Use this when the caller needs to know delivery
        succeeded before acting on it (e.g. recording state so a failed
        notification gets retried on the next run) — plain notifications can
        stay fire-and-forget.
        :raises ValueError: when Slack channel wasn't provided
        :raises qontract_api_client.exceptions.HTTPStatusError: if unsuccessful
        response from qontract-api, or (wait=True) if the message didn't
        finish sending within the timeout
        :raises RuntimeError: (wait=True only) if the message failed to send
        """
        if not self.channel:
            raise ValueError(
                "Slack channel name must be provided when posting messages."
            )

        setup_qontract_api_client()
        response = slack_chat_post_message(
            data=qontract_api_schemas.ChatRequest(
                workspace_name=self.workspace_name,
                channel=self.channel,
                text=text,
                icon_emoji=self.icon_emoji,
                username=self.username,
                secret=self._secret(),
                resolve_mentions=resolve_mentions,
            )
        )
        if not wait:
            return

        result = slack_chat_post_message_task_status(
            task_id=response.id, timeout=_CHAT_WAIT_TIMEOUT
        )
        if result.status == qontract_api_schemas.TaskStatus.FAILED:
            raise RuntimeError(
                f"Slack message delivery failed: {'; '.join(result.errors)}"
            )


def slackapi_from_queries(
    integration_name: str, channel: str | None = None
) -> SlackApi:
    slack_workspace = {"workspace": queries.get_slack_workspace()}
    return slackapi_from_slack_workspace(slack_workspace, integration_name, channel)


def slackapi_from_slack_workspace(
    slack_workspace: Mapping[str, Any],
    integration_name: str,
    channel: str | None = None,
) -> SlackApi:
    if "workspace" not in slack_workspace:
        raise ValueError('Slack workspace not containing keyword "workspace"')
    workspace_name = slack_workspace["workspace"]["name"]

    if "integrations" not in slack_workspace["workspace"]:
        raise ValueError('Slack workspace not containing any "integrations"')
    [slack_integration_config] = [
        i
        for i in slack_workspace["workspace"]["integrations"]
        if i["name"] == integration_name
    ]

    token = slack_integration_config["token"]
    icon_emoji = (
        slack_workspace.get("icon_emoji") or slack_integration_config["icon_emoji"]
    )

    username = slack_workspace.get("username") or slack_integration_config["username"]

    if channel is None:
        channel = slack_workspace.get("channel") or slack_integration_config["channel"]

    return SlackApi(
        workspace_name,
        token=token,
        channel=channel,
        icon_emoji=icon_emoji,
        username=username,
    )
