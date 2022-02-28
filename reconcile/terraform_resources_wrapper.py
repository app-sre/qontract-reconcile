import sys
import logging

from sretoolbox.utils import threaded

import reconcile.terraform_resources as tfr

from reconcile import queries
from reconcile.utils.sharding import is_in_shard_round_robin
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terrascript_client import TerrascriptClient as Terrascript
from reconcile.status import ExitCodes

QONTRACT_INTEGRATION = "terraform-resources-wrapper"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def get_accounts_names():
    accounts = queries.get_aws_accounts()
    settings = queries.get_app_interface_settings()
    # using Terrascript to filter out disabled accounts
    ts = Terrascript(
        tfr.QONTRACT_INTEGRATION,
        tfr.QONTRACT_INTEGRATION_VERSION,
        1,
        accounts,
        settings=settings,
    )
    return ts.uids.keys()


def tfr_run_wrapper(
    account_name,
    dry_run,
    print_to_file,
    enable_deletion,
    io_dir,
    internal_thread_pool_size,
    internal,
    use_jump_host,
    light,
    vault_output_path,
    extra_labels,
):
    exit_code = 0
    try:
        tfr.run(
            dry_run=dry_run,
            print_to_file=print_to_file,
            enable_deletion=enable_deletion,
            io_dir=io_dir,
            thread_pool_size=internal_thread_pool_size,
            internal=internal,
            use_jump_host=use_jump_host,
            light=light,
            vault_output_path=vault_output_path,
            account_name=account_name,
            extra_labels=extra_labels,
        )
    except SystemExit as e:
        exit_code = e.code
    return exit_code


def run(
    dry_run,
    print_to_file=None,
    enable_deletion=False,
    io_dir="throughput/",
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    light=False,
    vault_output_path="",
    extra_labels=None,
):
    account_names = [
        name
        for index, name in enumerate(sorted(get_accounts_names()))
        if is_in_shard_round_robin(name, index)
    ]

    if not account_names:
        logging.warning("No accounts in shards")
        return

    exit_codes = threaded.run(
        tfr_run_wrapper,
        account_names,
        thread_pool_size,
        dry_run=dry_run,
        print_to_file=print_to_file,
        enable_deletion=enable_deletion,
        io_dir=io_dir,
        internal_thread_pool_size=thread_pool_size,
        internal=internal,
        use_jump_host=use_jump_host,
        light=light,
        vault_output_path=vault_output_path,
        extra_labels=extra_labels,
    )

    if any(exit_codes):
        sys.exit(ExitCodes.ERROR)
