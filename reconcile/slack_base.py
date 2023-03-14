from collections.abc import Mapping
from typing import (
    Any,
    Optional,
)

from reconcile import queries
from reconcile.utils.secret_reader import (
    SecretReader,
    SecretReaderBase,
)
from reconcile.utils.slack_api import (
    HasClientConfig,
    SlackApi,
    SlackApiConfig,
)


def slackapi_from_queries(
    integration_name: str, init_usergroups: bool = True
) -> SlackApi:
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    slack_workspace = {"workspace": queries.get_slack_workspace()}
    return slackapi_from_slack_workspace(
        slack_workspace, secret_reader, integration_name, init_usergroups
    )


def slackapi_from_slack_workspace(
    slack_workspace: Mapping[str, Any],
    secret_reader: SecretReaderBase,
    integration_name: str,
    init_usergroups: bool = True,
    channel: Optional[str] = None,
) -> SlackApi:
    if "workspace" not in slack_workspace:
        raise ValueError('Slack workspace not containing keyword "workspace"')
    workspace_name = slack_workspace["workspace"]["name"]
    client_config = slack_workspace["workspace"].get("api_client")

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

    if client_config:
        api_config = SlackApiConfig.from_dict(client_config)
    else:
        api_config = SlackApiConfig()

    api = SlackApi(
        workspace_name,
        token=secret_reader.read(token),
        channel=channel,
        api_config=api_config,
        init_usergroups=init_usergroups,
        icon_emoji=icon_emoji,
        username=username,
    )

    return api


def slackapi_from_permissions(
    permissions: Mapping[str, Any],
    secret_reader: SecretReader,
    init_usergroups: bool = True,
) -> SlackApi:
    if "workspace" not in permissions:
        raise ValueError('Slack workspace not containing keyword "workspace"')
    workspace_name = permissions["workspace"]["name"]
    client_config = permissions["workspace"].get("api_client")

    token = permissions["workspace"]["token"]

    if client_config:
        api_config = SlackApiConfig.from_dict(client_config)
    else:
        api_config = SlackApiConfig()

    api = SlackApi(
        workspace_name,
        token=secret_reader.read(token),
        init_usergroups=init_usergroups,
        api_config=api_config,
    )

    return api


def get_slackapi(
    workspace_name: str,
    token: str,
    client_config: Optional[HasClientConfig] = None,
    init_usergroups: bool = True,
    channel: Optional[str] = None,
) -> SlackApi:
    """Initiate a SlackApi instance."""
    if client_config:
        api_config = SlackApiConfig.from_client_config(client_config)
    else:
        api_config = SlackApiConfig()

    api = SlackApi(
        workspace_name,
        token=token,
        channel=channel,
        init_usergroups=init_usergroups,
        api_config=api_config,
    )
    return api
