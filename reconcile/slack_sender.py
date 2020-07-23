import sys
import logging

import reconcile.queries as queries
from utils.slack_api import SlackApi

from utils.state import State

QONTRACT_INTEGRATION = 'slack-sender'


def collect_to(to):
    """Collect audience to send notification to from to object

    Arguments:
        to {dict} -- AppInterfaceNotification_v1 object

    Raises:
        AttributeError: Unknown alias

    Returns:
        set -- Audience to send notification to
    """
    audience = set()

    users = to.get('users')
    if users:
        for user in users:
            audience.add(user['org_username'])

    channels = to.get('channels')
    if channels:
        for channel in channels:
            audience.add(channel)

    return audience


def run(dry_run=False):
    slackapi = SlackApi(username="app-sre-bot", icon_emoji=":eyes:")
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION,
        accounts=accounts,
        settings=settings
    )
    notifications = queries.get_app_interface_notifications()

    # validate no 2 notifications have the same name
    notification_names = set([n['name'] for n in notifications])
    if len(notifications) != len(notification_names):
        logging.error('notification names must be unique.')
        sys.exit(1)

    notifications_to_send = [n for n in notifications
                             if not state.exists(n['name'])]

    for notification in notifications_to_send:
        logging.info(['send_notification', notification['name'],
                      notification['subject']])

        if not dry_run:
            names = collect_to(notification['to'])
            # if user, get user_id; if channel, keep the original (channel
            # name)
            users = slackapi.get_user_list_by_names(names)
            user_ids = list(users.keys())
            user_names = list(users.values())
            channel_names = [c for c in names if c not in user_names]
            ids = user_ids + channel_names
            subject = notification['subject']
            body = notification['body']
            for id in ids:
                slackapi.chat_post_message_to_channel(channel=id, text=subject
                                                      + '\n' + body)
            state.add(notification['name'])
