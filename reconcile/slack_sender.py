import sys
import logging

import reconcile.queries as queries
from reconcile.slack_base import init_slack
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
    workspaces = queries.get_slack_workspaces()

    desired_workspace_name = 'coreos'
    workspace = None
    for ws in workspaces:
        if ws['name'] == desired_workspace_name:
            workspace = ws
    if workspace is None:
        logging.error(f'Could not find workspace {desired_workspace_name} '
                      f'with a \'slack-notification\' defined')
        sys.exit(1)

    slack_info = {
        'workspace': workspace,
        'channel': 'test-jfc-violet'
    }

    slackapi = init_slack(slack_info, QONTRACT_INTEGRATION)
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
            channel_name = notification.get("channel")
            if channel_name:
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
