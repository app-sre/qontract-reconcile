import sys
import shutil
import logging

from reconcile import queries

from reconcile.utils.defer import defer
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.terrascript_client import TerrascriptClient as Terrascript

QONTRACT_INTEGRATION = "aws-iam-keys"


def filter_accounts(accounts, account_name):
    accounts = [a for a in accounts if a.get("deleteKeys")]
    if account_name:
        accounts = [a for a in accounts if a["name"] == account_name]
    return accounts


def get_keys_to_delete(accounts):
    return {
        account["name"]: account["deleteKeys"]
        for account in accounts
        if account["deleteKeys"] not in (None, [])
    }


def init_tf_working_dirs(accounts, thread_pool_size, settings):
    # copied here to avoid circular dependency
    QONTRACT_INTEGRATION = "terraform_resources"
    QONTRACT_TF_PREFIX = "qrtf"
    # if the terraform-resources integration is disabled
    # for an account, it means that Terrascript will not
    # initiate that account's config and will not create
    # a working directory for it. this means that we are
    # not able to recycle access keys belonging to users
    # created by terraform-resources, but it is disabled
    # tl;dr - we are good. how cool is this alignment...
    ts = Terrascript(
        QONTRACT_INTEGRATION,
        QONTRACT_TF_PREFIX,
        thread_pool_size,
        accounts,
        settings=settings,
    )
    return ts.dump()


def cleanup(working_dirs):
    for wd in working_dirs.values():
        shutil.rmtree(wd)


@defer
def run(
    dry_run,
    thread_pool_size=10,
    disable_service_account_keys=False,
    account_name=None,
    defer=None,
):
    accounts = filter_accounts(queries.get_aws_accounts(), account_name)
    if not accounts:
        logging.debug("nothing to do here")
        # using return because terraform-resources
        # may be the calling entity, and has more to do
        return

    settings = queries.get_app_interface_settings()
    aws = AWSApi(thread_pool_size, accounts, settings=settings)
    keys_to_delete = get_keys_to_delete(accounts)
    working_dirs = init_tf_working_dirs(accounts, thread_pool_size, settings)
    defer(lambda: cleanup(working_dirs))
    error = aws.delete_keys(
        dry_run, keys_to_delete, working_dirs, disable_service_account_keys
    )
    if error:
        sys.exit(1)
