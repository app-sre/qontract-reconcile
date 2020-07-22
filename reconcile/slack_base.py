import reconcile.queries as queries

from utils.slack_api import SlackApi


def init_slack(slack_info, integration):
    settings = queries.get_app_interface_settings()
    slack_integrations = slack_info['workspace']['integrations']
    slack_config = \
        [i for i in slack_integrations if i['name'] == integration]
    [slack_config] = slack_config

    token = slack_config['token']
    default_channel = slack_config['channel']
    icon_emoji = slack_config['icon_emoji']
    username = slack_config['username']
    channel = slack_info.get('channel') or default_channel

    slack = SlackApi(token,
                     settings=settings,
                     init_usergroups=False,
                     channel=channel,
                     icon_emoji=icon_emoji,
                     username=username)

    return slack
