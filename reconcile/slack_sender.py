import sys
import logging
import time

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
            recipients = collect_to(notification['to'])
            slack_ids = slackapi.get_user_list_by_names(recipients)
            channel_name = notification["name"]
            if notification['create_channel']:
                channel_info = slackapi.create_channel(channel_name)
                channel_id = channel_info["channel"]["id"]
                slackapi.invite_users_to_channel(channel=channel_id,
                                                 users=slack_ids)
                slackapi.chat_post_message_to_channel(channel=channel_id,
                                                      text=notification[
                                                           "description"])
            else:
                for slack_id in slack_ids:
                    slackapi.chat_post_message_to_channel(channel=slack_id,
                                                          text=notification[
                                                               "description"])
