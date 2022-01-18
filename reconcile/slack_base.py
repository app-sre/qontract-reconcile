from typing import Mapping, Any, Optional

from reconcile import queries

from reconcile.utils.slack_api import SlackApi, SlackApiConfig


def slackapi_from_queries(integration_name: str) -> SlackApi:
    app_interface_settings = queries.get_app_interface_settings()
    slack_workspace = {'workspace': queries.get_slack_workspace()}
    return slackapi_from_dict(slack_workspace, app_interface_settings,
                              integration_name)


def slackapi_from_dict(slack_workspace: Mapping[str, Any],
                       app_interface_settings: Mapping[str, Any],
                       integration_name: str,
                       channel: Optional[str] = None) -> SlackApi:
    if 'workspace' not in slack_workspace:
        raise ValueError(
            'Slack workspace not containing keyword "workspace"')
    workspace_name = slack_workspace['workspace']['name']
    client_config = slack_workspace['workspace'].get('api_client')

    [slack_integration_config] = \
        [i for i in slack_workspace['workspace']['integrations'] if
         i['name'] == integration_name]

    token = slack_integration_config['token']
    icon_emoji = slack_workspace.get('icon_emoji') or \
        slack_integration_config['icon_emoji']

    username = slack_workspace.get('username') or \
        slack_integration_config['username']

    if channel is None:
        channel = slack_workspace.get('channel') or \
            slack_integration_config['channel']

    if client_config:
        api_config = SlackApiConfig.from_dict(client_config)
    else:
        api_config = SlackApiConfig()

    api = SlackApi(workspace_name, token,
                   secret_reader_settings=app_interface_settings,
                   channel=channel, icon_emoji=icon_emoji, username=username,
                   api_config=api_config)

    return api
