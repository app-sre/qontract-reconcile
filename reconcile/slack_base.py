from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from qontract_api_client import schemas as qontract_api_schemas
from qontract_api_client.sync_client import (
    slack_chat_post_message,
    slack_conversations_history,
)

from reconcile import queries
from reconcile.utils.config import get_config
from reconcile.utils.runtime.integration import setup_qontract_api_client

if TYPE_CHECKING:
    from collections.abc import Mapping


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
    """Thin layer posting Slack messages and reading conversation history via qontract-api."""

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
        :param channel: the Slack channel to post messages to or read
        conversation history from
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

    def chat_post_message(self, text: str) -> None:
        """
        Send a chat message into a channel via qontract-api.

        :param text: message to send to channel
        :raises ValueError: when Slack channel wasn't provided
        :raises qontract_api_client.exceptions.HTTPStatusError: if unsuccessful
        response from qontract-api
        """
        if not self.channel:
            raise ValueError(
                "Slack channel name must be provided when posting messages."
            )

        setup_qontract_api_client()
        slack_chat_post_message(
            data=qontract_api_schemas.ChatRequest(
                workspace_name=self.workspace_name,
                channel=self.channel,
                text=text,
                icon_emoji=self.icon_emoji,
                username=self.username,
                secret=self._secret(),
            )
        )

    def get_flat_conversation_history(
        self, from_timestamp: int, to_timestamp: int | None
    ) -> list[qontract_api_schemas.SlackMessageResponse]:
        """Get all messages in a channel between from_timestamp and to_timestamp
        via qontract-api, ignoring threads."""
        if not self.channel:
            raise ValueError("Expecting a channel to be set")

        setup_qontract_api_client()
        secret = self._secret()
        response = slack_conversations_history(
            secret_manager_url=secret.secret_manager_url,
            path=secret.path,
            field=secret.field,
            version=secret.version,
            workspace_name=self.workspace_name,
            channel=self.channel,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        return response.messages


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
