import logging

import utils.smtp_client as smtp_client
import reconcile.queries as queries

from reconcile.slack_base import init_slack_workspace
from utils.state import State

QONTRACT_INTEGRATION = 'sentry-helper'


def guess_user(user_name, users):
    guesses = [
        u for u in users
        if user_name.lower() == u['name'].lower()
        or user_name.lower() == u['org_username']
        or user_name.lower() == u['github_username'].lower()
    ]
    return guesses


def run(dry_run):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    users = queries.get_users()
    state = State(
        integration=QONTRACT_INTEGRATION,
        accounts=accounts,
        settings=settings
    )

    user_names = smtp_client.get_sentry_users_from_mails(settings=settings)
    if not dry_run:
        slack = init_slack_workspace(QONTRACT_INTEGRATION)
    for user_name in user_names:
        guesses = guess_user(user_name, users)
        if not guesses:
            continue
        slack_username = \
            guesses[0].get('slack_username') or guesses[0]['org_username']
        if state.exists(slack_username):
            continue
        logging.info(['help_user', slack_username])
        if not dry_run:
            state.add(slack_username)
            slack.chat_post_message(
                f'yo <@{slack_username}>! ' +
                'checkout https://url.corp.redhat.com/sentry-help')
