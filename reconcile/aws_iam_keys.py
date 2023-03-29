import logging
import shutil
import sys
from typing import Any

from reconcile import queries
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
from reconcile.utils.state import (
    State,
    init_state,
)
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript

QONTRACT_INTEGRATION = "aws-iam-keys"


def filter_accounts(accounts, account_name):
    accounts = [a for a in accounts if a.get("deleteKeys")]
    if account_name:
        accounts = [a for a in accounts if a["name"] == account_name]
    return accounts


def get_keys_to_delete(accounts) -> dict[str, list[str]]:
    return {
        account["name"]: account["deleteKeys"]
        for account in accounts
        if account["deleteKeys"] not in (None, [])
    }


def should_run(state: State, keys_to_delete: dict[str, list[str]]) -> bool:
    for account_name, keys in keys_to_delete.items():
        if state.get(account_name, []) != keys:
            return True
    return False


def update_state(state: State, keys_to_update: dict[str, list[str]]):
    for account_name, keys in keys_to_update.items():
        if state.get(account_name, []) != keys:
            state.add(account_name, keys, force=True)


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
    accounts = filter_accounts(
        queries.get_aws_accounts(terraform_state=True), account_name
    )
    if not accounts:
        logging.debug("nothing to do here")
        # using return because terraform-resources
        # may be the calling entity, and has more to do
        return

    settings = queries.get_app_interface_settings()
    state = init_state(integration=QONTRACT_INTEGRATION)
    defer(state.cleanup)
    keys_to_delete = get_keys_to_delete(accounts)
    if not should_run(state, keys_to_delete):
        logging.debug("nothing to do here")
        # using return because terraform-resources
        # may be the calling entity, and has more to do
        return

    working_dirs = init_tf_working_dirs(accounts, thread_pool_size, settings)
    defer(lambda: cleanup(working_dirs))
    with AWSApi(thread_pool_size, accounts, settings=settings) as aws:
        error, service_account_recycle_complete = aws.delete_keys(
            dry_run, keys_to_delete, working_dirs, disable_service_account_keys
        )
    if error:
        sys.exit(1)

    if (
        not dry_run
        and not disable_service_account_keys
        and service_account_recycle_complete
    ):
        update_state(state, keys_to_delete)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"keys": get_keys_to_delete(queries.get_aws_accounts(terraform_state=True))}
