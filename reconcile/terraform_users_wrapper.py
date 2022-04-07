import sys
import logging

from sretoolbox.utils import threaded
from typing import Iterable, Optional

import reconcile.terraform_users as tfu

from reconcile import queries
from reconcile.utils.sharding import is_in_shard_round_robin
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terrascript_client import TerrascriptClient as Terrascript
from reconcile.status import ExitCodes

QONTRACT_INTEGRATION = "terraform-users-wrapper"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def get_accounts_names() -> Iterable[str]:
    accounts = queries.get_aws_accounts()
    settings = queries.get_app_interface_settings()
    # using Terrascript to filter out disabled accounts
    ts = Terrascript(
        tfu.QONTRACT_INTEGRATION,
        tfu.QONTRACT_INTEGRATION_VERSION,
        1,
        accounts,
        settings=settings,
    )
    return ts.uids.keys()


def tfu_run_wrapper(
    account_name: str,
    dry_run: bool,
    internal_thread_pool_size: int,
    print_to_file: Optional[str] = None,
    enable_deletion: bool = False,
    io_dir: str = "throughput/",
    send_mails: bool = True,
) -> int:
    exit_code = 0
    try:
        tfu.run(
            account_name=account_name,
            dry_run=dry_run,
            print_to_file=print_to_file,
            enable_deletion=enable_deletion,
            io_dir=io_dir,
            thread_pool_size=internal_thread_pool_size,
            send_mails=send_mails,
        )
    except SystemExit as e:
        exit_code = e.code
    return exit_code


def run(
    dry_run: bool,
    print_to_file: Optional[str] = None,
    enable_deletion: bool = False,
    io_dir: str = "throughput/",
    thread_pool_size: int = 10,
    send_mails: bool = True,
) -> None:

    account_names = [
        name
        for index, name in enumerate(sorted(get_accounts_names()))
        if is_in_shard_round_robin(name, index)
    ]

    if not account_names:
        logging.warning("No accounts in shards")
        return

    exit_codes = threaded.run(
        tfu_run_wrapper,
        account_names,
        thread_pool_size,
        dry_run=dry_run,
        print_to_file=print_to_file,
        enable_deletion=enable_deletion,
        io_dir=io_dir,
        internal_thread_pool_size=thread_pool_size,
        send_mails=send_mails,
    )

    if any(exit_codes):
        sys.exit(ExitCodes.ERROR)
