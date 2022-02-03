from reconcile import queries

from reconcile.utils.slack_api import SlackApi, SlackApiConfig


def init_slack(slack_info, integration, init_usergroups=True):
    settings = queries.get_app_interface_settings()
    workspace_name = slack_info['workspace']['name']
    slack_integrations = slack_info['workspace']['integrations']
    client_config = slack_info['workspace'].get('api_client')
    slack_config = \
        [i for i in slack_integrations if i['name'] == integration]
    [slack_config] = slack_config

    token = slack_config['token']
    default_channel = slack_config['channel']
    icon_emoji = slack_config['icon_emoji']
    username = slack_config['username']
    channel = slack_info.get('channel') or default_channel

    slack_api_kwargs = {
        'settings': settings,
        'init_usergroups': init_usergroups,
        'channel': channel,
        'icon_emoji': icon_emoji,
        'username': username
    }

    if client_config:
        slack_api_kwargs['api_config'] = \
            SlackApiConfig.from_dict(client_config)

    slack = SlackApi(workspace_name, token, **slack_api_kwargs)

    return slack


def init_slack_workspace(integration, init_usergroups=True):
    workspace = queries.get_slack_workspace()
    return init_slack({'workspace': workspace}, integration,
                      init_usergroups=init_usergroups)
