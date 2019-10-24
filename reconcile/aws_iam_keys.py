import shutil

import reconcile.queries as queries

from utils.defer import defer
from utils.aws_api import AWSApi
from reconcile.terraform_resources import init_working_dirs


def get_keys_to_delete(accounts):
    return {account['name']: account['deleteKeys']
            for account in accounts
            if account['deleteKeys'] not in (None, [])}


def cleanup(working_dirs):
    for wd in working_dirs.values():
        shutil.rmtree(wd)


@defer
def run(dry_run=False, thread_pool_size=10, enable_deletion=False,
        defer=None):
    accounts = queries.get_aws_accounts()
    aws = AWSApi(thread_pool_size, accounts)
    keys_to_delete = get_keys_to_delete(accounts)
    # no use for terrascript for us here, and an
    # error in init_working_dirs is very unlikely
    _, working_dirs, _ = init_working_dirs(accounts, thread_pool_size)
    defer(lambda: cleanup(working_dirs))
    aws.delete_keys(dry_run, keys_to_delete, working_dirs)
