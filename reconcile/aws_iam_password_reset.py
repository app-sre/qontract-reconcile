import logging

from reconcile import queries

from reconcile.utils.aws_api import AWSApi
from reconcile.utils.state import State

QONTRACT_INTEGRATION = "aws-iam-password-reset"


def run(dry_run):
    accounts = queries.get_aws_accounts(reset_passwords=True)
    settings = queries.get_app_interface_settings()
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )

    for a in accounts:
        aws_api = None
        account_name = a["name"]
        reset_passwords = a.get("resetPasswords")
        if not reset_passwords:
            continue
        for r in reset_passwords:
            user_name = r["user"]["org_username"]
            request_id = r["requestId"]
            state_key = f"{account_name}/{user_name}/{request_id}"
            if state.exists(state_key):
                continue

            logging.info(["reset_password", account_name, user_name])
            if dry_run:
                continue

            if aws_api is None:
                aws_api = AWSApi(1, [a], settings=settings)

            aws_api.reset_password(account_name, user_name)
            aws_api.reset_mfa(account_name, user_name)
            state.add(state_key)
