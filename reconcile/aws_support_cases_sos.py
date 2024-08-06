import itertools
import logging

from reconcile import (
    mr_client_gateway,
    queries,
)
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
from reconcile.utils.mr import CreateDeleteAwsAccessKey

QONTRACT_INTEGRATION = "aws-support-cases-sos"


def filter_accounts(accounts):
    return [a for a in accounts if a.get("premiumSupport")]


def get_deleted_keys(accounts):
    return {
        account["name"]: account["deleteKeys"]
        for account in accounts
        if account["deleteKeys"]
    }


def get_keys_to_delete(aws_support_cases):
    search_pattern = "We have become aware that the AWS Access Key "
    keys = []
    # ref:
    # https://boto3.amazonaws.com/v1/documentation/api/latest/
    # reference/services/support.html#Support.Client.describe_cases
    for account, cases in aws_support_cases.items():
        for case in cases:
            comms = case["recentCommunications"]["communications"]
            for comm in comms:
                body = comm["body"]
                split = body.split(search_pattern, 1)
                if len(split) == 2:  # sentence is found, get the key
                    key = split[1].split(" ")[0]
                    keys.append({"account": account, "key": key})
    return keys


@defer
def act(dry_run, gitlab_project_id, accounts, keys_to_delete, defer=None):
    if not dry_run and keys_to_delete:
        mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)
        defer(mr_cli.cleanup)

    for k in keys_to_delete:
        account = k["account"]
        key = k["key"]
        logging.info(["delete_aws_access_key", account, key])
        if not dry_run:
            path = "data" + next(a["path"] for a in accounts if a["name"] == account)

            mr = CreateDeleteAwsAccessKey(account, path, key)
            mr.submit(cli=mr_cli)


def run(dry_run, gitlab_project_id=None, thread_pool_size=10, enable_deletion=False):
    accounts = filter_accounts(queries.get_aws_accounts())
    settings = queries.get_app_interface_settings()
    deleted_keys = get_deleted_keys(accounts)
    with AWSApi(thread_pool_size, accounts, settings=settings) as aws:
        existing_keys = aws.get_users_keys()
        aws_support_cases = aws.get_support_cases()
    keys_to_delete_from_cases = get_keys_to_delete(aws_support_cases)
    keys_to_delete = []
    for ktd in keys_to_delete_from_cases:
        ktd_account = ktd["account"]
        ktd_key = ktd["key"]
        account_deleted_keys = deleted_keys.get(ktd_account)
        if account_deleted_keys and ktd_key in account_deleted_keys:
            continue
        account_existing_keys = existing_keys.get(ktd_account)
        if account_existing_keys:
            keys_only = itertools.chain.from_iterable(account_existing_keys.values())
            if ktd_key not in keys_only:
                continue
        keys_to_delete.append(ktd)

    act(dry_run, gitlab_project_id, accounts, keys_to_delete)
