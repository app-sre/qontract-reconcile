from typing import Mapping, Any, Optional

from reconcile import queries

from reconcile.utils.slack_api import SlackApi, SlackApiConfig


def slackapi_from_queries(
    integration_name: str, init_usergroups: Optional[bool] = True
) -> SlackApi:
    app_interface_settings = queries.get_app_interface_settings()
    slack_workspace = {"workspace": queries.get_slack_workspace()}
    return slackapi_from_slack_workspace(
        slack_workspace, app_interface_settings, integration_name, init_usergroups
    )


def slackapi_from_slack_workspace(
    slack_workspace: Mapping[str, Any],
    app_interface_settings: Mapping[str, Any],
    integration_name: str,
    init_usergroups: Optional[bool] = True,
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
        token,
        app_interface_settings=app_interface_settings,
        channel=channel,
        api_config=api_config,
        init_usergroups=init_usergroups,
        icon_emoji=icon_emoji,
        username=username,
    )

    return api


def slackapi_from_permissions(
    permissions: Mapping[str, Any],
    app_interface_settings: Mapping[str, Any],
    init_usergroups: Optional[bool] = True,
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
        token,
        app_interface_settings=app_interface_settings,
        init_usergroups=init_usergroups,
        api_config=api_config,
    )

    return api
