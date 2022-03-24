import logging

from reconcile.utils.smtp_client import SmtpClient
from reconcile import queries

from reconcile.slack_base import slackapi_from_queries
from reconcile.utils.state import State

QONTRACT_INTEGRATION = "sentry-helper"


def guess_user(user_name, users):
    guesses = [
        u
        for u in users
        if user_name.lower() == u["name"].lower()
        or user_name.lower() == u["org_username"]
        or user_name.lower() == u["github_username"].lower()
    ]
    return guesses


def get_sentry_users_from_mails(mails):
    user_names = set()
    for mail in mails:
        msg = mail["msg"]
        user_line = [ln for ln in msg.split("\n") if "is requesting access to" in ln]
        if not user_line:
            continue
        user_line = user_line[0]
        user_name = user_line.split("is requesting access to")[0].strip()
        user_names.add(user_name)

    return user_names


def run(dry_run):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    users = queries.get_users()
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )
    smtp_client = SmtpClient(settings=settings)
    mails = smtp_client.get_mails(
        criteria='SUBJECT "Sentry Access Request"', folder="[Gmail]/Sent Mail"
    )
    user_names = get_sentry_users_from_mails(mails)
    if not dry_run:
        slack = slackapi_from_queries(QONTRACT_INTEGRATION, init_usergroups=False)
    for user_name in user_names:
        guesses = guess_user(user_name, users)
        if not guesses:
            logging.debug(f"no users guessed for {user_name}")
            continue
        slack_username = guesses[0].get("slack_username") or guesses[0]["org_username"]
        if state.exists(slack_username):
            continue
        logging.info(["help_user", slack_username])
        if not dry_run:
            state.add(slack_username)
            slack.chat_post_message(
                f"yo <@{slack_username}>! it appears that you have "
                + "requested access to a project in Sentry. "
                + "access is managed automatically via app-interface. "
                "checkout https://url.corp.redhat.com/sentry-help"
            )
