import sys

import reconcile.queries as queries
import reconcile.terraform_resources as tfr
import reconcile.utils.threaded as threaded

from reconcile.utils.semver_helper import make_semver
from reconcile.status import ExitCodes

QONTRACT_INTEGRATION = 'terraform-resources-wrapper'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def tfr_run_wrapper(account_name,
                    dry_run,
                    print_only,
                    enable_deletion,
                    io_dir,
                    internal_thread_pool_size,
                    internal,
                    use_jump_host,
                    light,
                    vault_output_path):
    exit_code = 0
    try:
        tfr.run(dry_run=dry_run,
                print_only=print_only,
                enable_deletion=enable_deletion,
                io_dir=io_dir,
                thread_pool_size=internal_thread_pool_size,
                internal=internal,
                use_jump_host=use_jump_host,
                light=light,
                vault_output_path=vault_output_path,
                account_name=account_name)
    except SystemExit as e:
        exit_code = e.code
    return exit_code


def run(dry_run, print_only=False,
        enable_deletion=False, io_dir='throughput/',
        thread_pool_size=10, internal=None, use_jump_host=True,
        light=False, vault_output_path=''):
    account_names = [a['name'] for a in queries.get_aws_accounts()]
    if len(account_names) == 0:
        return

    exit_codes = threaded.run(
        tfr_run_wrapper, account_names, thread_pool_size,
        dry_run=dry_run,
        print_only=print_only,
        enable_deletion=enable_deletion,
        io_dir=io_dir,
        internal_thread_pool_size=thread_pool_size,
        internal=internal,
        use_jump_host=use_jump_host,
        light=light,
        vault_output_path=vault_output_path,
    )

    if any(exit_codes):
        sys.exit(ExitCodes.ERROR)
